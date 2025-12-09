import asyncio
import os
import random
import traceback

import dotenv
import loguru
import wandelbots_api_client.v2 as wb_api
from wandelbots_api_client.v2.models import (
    InitializeJoggingRequest,
    JointVelocityRequest,
    MotionGroupState,
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
_max_ang_velocity_rad_s = 0.25  # Maximum angular velocity in rad/s
_tolerance_rad = 0.05  # tolerance in rad (when to consider joint target reached)

# Global state
api_client: wb_api.ApiClient = None
last_motion_state: list[float] = None
current_target: list[float] = None
tasks: list[asyncio.Task] = []


def _parse_motion_state(
    motion_state: MotionGroupState,
) -> list[float]:
    """Extract joint state from MotionGroupState."""
    return motion_state.joint_position


def _p_control(
    current: list[float],
    target: list[float],
    tolerance: float,
    max_velocity: float,
    gain: float = 2.0,
) -> list[float]:
    """
    Simple proportional control towards target with velocity clamping.
    """
    if len(current) != len(target):
        raise ValueError("Current and target must have same length")

    if all(abs(c - t) <= tolerance for c, t in zip(current, target)):
        return [0.0] * len(current)

    velocities = []
    for c, t in zip(current, target):
        error = t - c
        velocity = error * gain
        velocity = max(-max_velocity, min(max_velocity, velocity))
        velocities.append(velocity)

    return velocities


async def _start_jogging_control(tolerance: float, max_velocity: float):
    """
    Start the jogging control loop.
    """

    def _req(
        velocity: list[float] = None,
    ) -> JointVelocityRequest:
        """Build a JointVelocityRequest. Idle if no velocity provided."""
        if velocity is None:
            velocity = [0.0] * 6
        return JointVelocityRequest(velocity=velocity)

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

            # Get velocity commands
            velocities = _p_control(
                current=last_motion_state,
                target=current_target,
                tolerance=tolerance,
                max_velocity=max_velocity,
            )
            yield _req(velocity=velocities)

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
            tolerance=_tolerance_rad,
            max_velocity=_max_ang_velocity_rad_s,
        )
    )
    tasks.extend([state_streaming_task, jogging_task])


async def _spawn_random_target():
    """Spawn random joint targets for the joints to follow every n seconds."""
    try:
        # NOTE: You might want to adjust the range of random joint targets
        initial_joints = [0, -3.14 / 2, 3.14 / 2, 0, 0, 0]
        while True:
            global current_target
            current_target = [
                initial_joints[i] + random.uniform(-1.0, 1.0) for i in range(6)
            ]
            logger.info(f"New target set: {current_target}")
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
