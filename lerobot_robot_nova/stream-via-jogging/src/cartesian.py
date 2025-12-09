import asyncio
import os
import random
import traceback

import dotenv
import loguru
import numpy as np
import wandelbots_api_client.v2 as wb_api
from scipy.spatial.transform import Rotation as R
from wandelbots_api_client.v2.models import (
    InitializeJoggingRequest,
    MotionGroupState,
    TcpVelocityRequest,
)
from websockets.exceptions import ConnectionClosedError

# Logging
logger = loguru.logger

# Environment variables
dotenv.load_dotenv()
_nova_api = os.getenv("NOVA_API")
if _nova_api is None:
    raise ValueError("NOVA_API environment variable not set - see .env.template")
_motion_group = os.getenv("MOTION_GROUP")
if _motion_group is None:
    raise ValueError("MOTION_GROUP environment variable not set - see .env.template")
_controller = _motion_group.split("@")[-1]

# Globals variables
_cell = "cell"
_tcp = "Flange"
_max_pos_velocity_mm_s = 50.0  # Maximum position velocity in mm/s
_max_rot_velocity_rad_s = 0.25  # Maximum rotation velocity in rad/s
_pos_tolerance_mm = (
    1.0  # Position tolerance in mm (when to consider positional target reached)
)
_rot_tolerance_rad = (
    0.05  # Rotation tolerance in rad (when to consider angular target reached)
)

# Global state
api_client: wb_api.ApiClient = None
last_motion_state: list[float] = None
current_target: list[float] = None
tasks: list[asyncio.Task] = []


def _parse_motion_state(
    motion_state: MotionGroupState,
) -> list[float]:
    """Extract TCP position and orientation from MotionGroupState."""
    state = motion_state.tcp_pose
    return [*state.position, *state.orientation]


def _shortest_rotation(rot_from: list[float], rot_to: list[float]) -> list[float]:
    """
    Calculate the shortest rotation vector to go from rot_from to rot_to.

    Args:
        rot_from: Current rotation as [rx, ry, rz]
        rot_to:   Target rotation as [rx, ry, rz]
    Returns:
        Shortest rotation vector from rot_from to rot_to as [rx, ry, rz]
    """

    R_from = R.from_rotvec(rot_from, degrees=False)
    R_to = R.from_rotvec(rot_to, degrees=False)
    R_rel = R_to * R_from.inv()
    return R_rel.as_rotvec()


def _p_control(
    current: list[float],
    target: list[float],
    pos_tolerance: float,
    rot_tolerance: float,
    max_pos_velocity: float,
    max_rot_velocity: float,
    gain: float = 2.0,
) -> tuple[list[float], list[float]]:
    """
    Simple proportional control towards target with velocity clamping for position and rotation.

    Args:
        current: Current position and orientation values [pos_x, pos_y, pos_z, rot_x, rot_y, rot_z]
        target: Target position and orientation values [pos_x, pos_y, pos_z, rot_x, rot_y, rot_z]
        pos_tolerance: Tolerance for position (mm)
        rot_tolerance: Tolerance for rotation (rad)
        max_pos_velocity: Maximum allowed position velocity (mm/s)
        max_rot_velocity: Maximum allowed rotation velocity (rad/s)
        gain: Proportional gain factor

    Returns:
        Tuple of (position_velocities, rotation_velocities)
    """

    if len(current) != len(target):
        raise ValueError("Current and target must have same length")

    if len(current) != 6:
        raise ValueError(
            "Expected 6 values for position and orientation (x,y,z,rx,ry,rz)"
        )

    # Split into position and rotation components
    current_pos = current[:3]
    current_rot = current[3:]
    target_pos = target[:3]
    target_rot = target[3:]

    # Check if position is within tolerance and compute position velocities
    pos_within_tolerance = all(
        abs(c - t) <= pos_tolerance for c, t in zip(current_pos, target_pos)
    )
    if pos_within_tolerance:
        pos_velocities = [0.0, 0.0, 0.0]
    else:
        pos_velocities = []
        for c, t in zip(current_pos, target_pos):
            error = t - c
            velocity = error * gain
            velocity = max(-max_pos_velocity, min(max_pos_velocity, velocity))
            pos_velocities.append(velocity)

    # Check if rotation is within tolerance and compute rotation velocities
    angular_distance = np.linalg.norm(_shortest_rotation(current_rot, target_rot))
    rot_within_tolerance = angular_distance <= rot_tolerance
    if rot_within_tolerance:
        rot_velocities = [0.0, 0.0, 0.0]
    else:
        angular_error = _shortest_rotation(current_rot, target_rot)
        rot_velocities = []
        for error_component in angular_error:
            velocity = error_component * gain
            velocity = max(-max_rot_velocity, min(max_rot_velocity, velocity))
            rot_velocities.append(velocity)

    return pos_velocities, rot_velocities


async def _start_jogging_control(
    pos_tolerance_mm: float,
    rot_tolerance_rad: float,
    max_pos_velocity_mm_s: float,
    max_rot_velocity_rad_s: float,
):
    """
    Start the jogging control loop.
    """

    def _req(
        translation: list[float] = None, rotation: list[float] = None
    ) -> TcpVelocityRequest:
        """Build a TcpVelocityRequest. Default to idle if none given."""
        if translation is None:
            translation = [0.0, 0.0, 0.0]
        if rotation is None:
            rotation = [0.0, 0.0, 0.0]
        return TcpVelocityRequest(translation=translation, rotation=rotation)

    async def _client_request_generator(response_stream):
        """Client request generator for jogging control."""

        # Start Jogging by sending InitializeJogging once
        yield InitializeJoggingRequest(motion_group=_motion_group, tcp=_tcp)
        logger.info("Sent InitializeJoggingRequest")

        # Consume responses (keeps the stream alive)
        async for _ in response_stream:
            if current_target is None:
                # No target: remain idle
                yield _req()
                continue

            if last_motion_state is None:
                # No motion state yet: remain idle
                yield _req()
                continue

            # Get velocity commands for position and rotation
            pos_vel, rot_vel = _p_control(
                current=last_motion_state,
                target=current_target,
                pos_tolerance=pos_tolerance_mm,
                rot_tolerance=rot_tolerance_rad,
                max_pos_velocity=max_pos_velocity_mm_s,
                max_rot_velocity=max_rot_velocity_rad_s,
            )
            yield _req(translation=pos_vel, rotation=rot_vel)

    try:
        jogging_api = wb_api.JoggingApi(api_client)
        logger.info("Starting jogging control...")
        await jogging_api.execute_jogging(
            cell=_cell,
            controller=_controller,
            client_request_generator=_client_request_generator,
        )
    except asyncio.CancelledError:
        logger.warning("Jogging control cancelled")
        return
    except ConnectionClosedError as e:
        logger.warning(f"Jogging control websocket closed unexpectedly: {e}")
        return
    except Exception as e:
        logger.error(f"Jogging control error: {e}")
        logger.error(traceback.format_exc())
        raise


async def _start_state_stream():
    global last_motion_state
    try:
        state_api = wb_api.MotionGroupApi(api_client)
        logger.info("Starting state streaming...")
        async for motion_state in state_api.stream_motion_group_state(
            cell=_cell,
            motion_group=_motion_group,
            controller=_controller,
            response_rate=100,
        ):
            last_motion_state = _parse_motion_state(motion_state)
    except asyncio.CancelledError:
        logger.warning("State stream cancelled")
        return
    except ConnectionClosedError as e:
        logger.warning(f"State stream websocket closed unexpectedly: {e}")
        return
    except Exception as e:
        logger.error(f"State stream error: {e}")
        logger.error(traceback.format_exc())
        raise


async def _connect_services():
    """Establish APIs and start the async streaming task."""
    global api_client, tasks

    # Initialize API client
    api_host = f"{_nova_api}/api/v2"
    if not api_host.startswith("http"):
        api_host = "http://" + api_host
    api_client = wb_api.ApiClient(wb_api.Configuration(host=api_host))
    logger.info(f"Connected to Nova API at {api_host}")

    # start streams
    state_streaming_task = asyncio.create_task(_start_state_stream())
    jogging_task = asyncio.create_task(
        _start_jogging_control(
            pos_tolerance_mm=_pos_tolerance_mm,
            rot_tolerance_rad=_rot_tolerance_rad,
            max_pos_velocity_mm_s=_max_pos_velocity_mm_s,
            max_rot_velocity_rad_s=_max_rot_velocity_rad_s,
        )
    )
    tasks.extend([state_streaming_task, jogging_task])


async def _spawn_random_target():
    """Spawn random targets for the TCP to follow every n seconds."""
    try:
        while True:
            # NOTE: The bounds need to be adjusted depending on the robot used,
            # NOTE: to avoid running in joint limits and self collision during testing.
            target = [
                random.uniform(1500.0, 2000.0),
                random.uniform(-200.0, 200.0),
                random.uniform(800.0, 1200.0),
                random.uniform(-0.4, 0.4),
                random.uniform(1.4, 2.2),
                random.uniform(-0.4, 0.4),
            ]
            global current_target
            current_target = target
            logger.info(f"New target set: {target}")
            await asyncio.sleep(2.0)
    except asyncio.CancelledError:
        logger.info("Random target spawning cancelled")
        return


async def main():
    # Connect to API and start NOVA streams
    await _connect_services()

    # Start random target spawning
    _target_task = asyncio.create_task(_spawn_random_target())
    tasks.append(_target_task)

    # Keep loop running and print latest motion state
    while True:
        await asyncio.sleep(0.1)
        if last_motion_state is not None:
            print([f"{v:.2f}" for v in last_motion_state])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()
        logger.info("All tasks cancelled. Exiting.")
