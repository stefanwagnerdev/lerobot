#!/usr/bin/env python

# Copyright 2024 Wandelbots GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Nova robot implementation for LeRobot.

This module implements the Robot interface for Wandelbots Nova platform.
It uses the Nova Jogging API for streaming joint commands and the
Motion Group API for state streaming.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from typing import Any

import wandelbots_api_client.v2 as wb_api
from wandelbots_api_client.v2.models import (
    InitializeJoggingRequest,
    JointVelocityRequest,
)
from websockets.exceptions import ConnectionClosedError

from lerobot.cameras.camera import Camera
from lerobot.cameras.utils import make_cameras_from_configs
from lerobot.robots.robot import Robot

from .config_nova import NovaRobotConfig

logger = logging.getLogger(__name__)


class NovaRobot(Robot):
    """Robot implementation for Wandelbots Nova platform.

    Nova is a robot platform that supports multiple robot types through a unified API.
    This implementation uses the Jogging API for sending joint velocity commands
    and the Motion Group State stream for reading current joint positions.

    The robot must be configured on the Nova instance first, then referenced
    by controller name in the config.

    Attributes:
        config_class: The configuration class for this robot.
        name: The name identifier for this robot type.
    """

    config_class = NovaRobotConfig
    name = "nova"

    def __init__(self, config: NovaRobotConfig):
        super().__init__(config)
        self.config: NovaRobotConfig = config

        # Nova API client and state
        self._api_client: wb_api.ApiClient | None = None
        self._connected: bool = False

        # Motion group identifier (format: "0@controller_name")
        self._motion_group_id: str = f"{config.motion_group}@{config.controller_name}"
        self._controller: str = config.controller_name
        self._cell: str = "cell"
        #todo: get tcp name from config
        self._tcp: str = "flange"

        # Joint state (updated by state stream)
        self._current_joints: list[float] | None = None
        self._num_joints: int | None = None

        # Target joints for jogging control
        self._target_joints: list[float] | None = None

        # Jogging control parameters
        self._max_velocity_rad_s: float = 0.5
        self._tolerance_rad: float = 0.01
        self._p_gain: float = 2.0

        # Async event loop and tasks (run in background thread)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._state_stream_task: asyncio.Task | None = None
        self._jogging_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

        # Flag to track if jogging is active (only for policy evaluation)
        self._jogging_active: bool = False

        # Cameras
        self.cameras: dict[str, Camera] = make_cameras_from_configs(config.cameras)

    # -------------------------------------------------------------------------
    # Feature definitions (callable before connect)
    # -------------------------------------------------------------------------

    @property
    def _motors_ft(self) -> dict[str, type]:
        """Motor features - joint positions."""
        # Default to 6 joints (common for UR, KUKA, etc.)
        # Will be updated after connect based on actual robot
        num_joints = self._num_joints or 6
        return {f"joint_{i+1}.pos": float for i in range(num_joints)}

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        """Camera features - image shapes."""
        return {
            cam_name: (cam.height, cam.width, 3)
            for cam_name, cam in self.cameras.items()
        }

    @property
    def observation_features(self) -> dict:
        """Returns the observation features (joints + cameras)."""
        return {**self._motors_ft, **self._cameras_ft}

    @property
    def action_features(self) -> dict:
        """Returns the action features (joint positions to command)."""
        return self._motors_ft

    # -------------------------------------------------------------------------
    # Connection management
    # -------------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Returns True if connected to Nova and all cameras."""
        cameras_connected = all(cam.is_connected for cam in self.cameras.values())
        nova_connected = self._connected and self._current_joints is not None
        return nova_connected and cameras_connected

    def connect(self, calibrate: bool = True) -> None:
        """Connect to the Nova robot and start streaming.

        Args:
            calibrate: Ignored for Nova (calibration handled by Nova platform).
        """
        if self.is_connected:
            logger.warning("Already connected to Nova robot")
            return

        logger.info(f"Connecting to Nova at {self.config.nova_api}...")

        # Initialize API client
        api_host = f"{self.config.nova_api}/api/v2"
        if not api_host.startswith("http"):
            api_host = "http://" + api_host
        self._api_client = wb_api.ApiClient(wb_api.Configuration(host=api_host))

        # Start background event loop for async operations
        self._start_async_loop()

        # Wait for initial state to be received
        timeout = 10.0
        elapsed = 0.0
        while self._current_joints is None and elapsed < timeout:
            import time
            time.sleep(0.1)
            elapsed += 0.1

        if self._current_joints is None:
            raise ConnectionError(
                f"Failed to receive initial state from Nova within {timeout}s. "
                + f"Check that controller '{self.config.controller_name}' exists and is active."
            )

        self._num_joints = len(self._current_joints)
        self._connected = True
        logger.info(
            f"Connected to Nova robot with {self._num_joints} joints. "
            + f"Motion group: {self._motion_group_id}"
        )

        # Connect cameras
        for cam_name, cam in self.cameras.items():
            logger.info(f"Connecting camera: {cam_name}")
            cam.connect()

        # Configure robot (no-op for Nova, but part of interface)
        self.configure()

    def disconnect(self) -> None:
        """Disconnect from the Nova robot and stop streaming."""
        if not self._connected:
            return

        logger.info("Disconnecting from Nova robot...")

        # Close API client (async) before stopping the loop
        if self._api_client and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._api_client.close(), self._loop
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error closing API client: {e}")

        # Stop async loop and tasks
        self._stop_async_loop()

        # Disconnect cameras
        for cam in self.cameras.values():
            cam.disconnect()

        self._api_client = None
        self._connected = False
        self._current_joints = None
        self._target_joints = None
        logger.info("Disconnected from Nova robot")

    # -------------------------------------------------------------------------
    # Calibration (handled by Nova platform)
    # -------------------------------------------------------------------------

    @property
    def is_calibrated(self) -> bool:
        """Nova handles calibration internally."""
        return True

    def calibrate(self) -> None:
        """No calibration needed - Nova handles this internally."""
        pass

    def configure(self) -> None:
        """Configure the robot. No additional configuration needed for Nova."""
        pass

    # -------------------------------------------------------------------------
    # Observation and Action
    # -------------------------------------------------------------------------

    def get_observation(self) -> dict[str, Any]:
        """Get current observation (joint positions + camera images).

        Returns:
            Dictionary with joint positions and camera images.
        """
        if not self.is_connected:
            raise ConnectionError("Nova robot is not connected")

        # Build observation dict with joint positions
        current_joints = self._current_joints
        if current_joints is None:
            raise ConnectionError("Nova robot is not connected")

        obs = {}
        for i, joint_pos in enumerate(current_joints):
            obs[f"joint_{i+1}.pos"] = joint_pos

        # Add camera images
        for cam_name, cam in self.cameras.items():
            obs[cam_name] = cam.async_read()

        return obs

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Send action (target joint positions) to the robot.

        Behavior depends on config.enable_jogging:
        
        - enable_jogging=False (default): Observation-only mode for recording.
          Actions are acknowledged but the robot is NOT moved. This allows
          manual control via teaching pendant during data collection.
          
        - enable_jogging=True: Active control mode for policy evaluation.
          On first call, this starts the jogging control loop which takes
          exclusive control of the robot and moves it towards target positions.

        Args:
            action: Dictionary with joint position targets (e.g., {"joint_1.pos": 0.5, ...})

        Returns:
            The action that was sent.
        """
        if not self.is_connected:
            raise ConnectionError("Nova robot is not connected")

        # Extract target joint positions from action dict
        num_joints = self._num_joints or 6
        target = []
        for i in range(num_joints):
            key = f"joint_{i+1}.pos"
            if key not in action:
                raise ValueError(f"Missing joint position: {key}")
            target.append(float(action[key]))

        # Only start jogging if enabled (for policy evaluation)
        if self.config.enable_jogging:
            # Start jogging on first send_action call (lazy initialization)
            if not self._jogging_active:
                self._start_jogging()

            # Update target for jogging control loop
            self._target_joints = target
        else:
            # Observation-only mode: acknowledge action but don't move robot
            # This allows manual control via teaching pendant during recording
            pass

        return action


    def _start_jogging(self) -> None:
        """Start the jogging control loop (lazy initialization).
        
        This is called on the first send_action() call, not on connect().
        This allows the robot to be controlled manually via teaching pendant
        during recording, while still enabling programmatic control during
        policy evaluation.
        """
        if self._jogging_active:
            return
        
        if self._loop is None:
            raise RuntimeError("Async loop not running - robot not connected")
        
        logger.info("Starting Nova jogging control (robot will be under programmatic control)")
        
        # Schedule jogging task in the async loop
        def start_jogging():
            self._jogging_task = asyncio.create_task(self._jogging_control())
        
        self._loop.call_soon_threadsafe(start_jogging)
        self._jogging_active = True

    # -------------------------------------------------------------------------
    # Async background loop for Nova streams
    # -------------------------------------------------------------------------

    def _start_async_loop(self) -> None:
        """Start the background async event loop."""
        self._loop = asyncio.new_event_loop()
        self._stop_event = asyncio.Event()

        def run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_streams())

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    def _stop_async_loop(self) -> None:
        """Stop the background async event loop."""
        if self._loop is None:
            return

        # Signal stop
        if self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

        # Cancel tasks
        if self._state_stream_task:
            self._loop.call_soon_threadsafe(self._state_stream_task.cancel)
        if self._jogging_task:
            self._loop.call_soon_threadsafe(self._jogging_task.cancel)

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._loop = None
        self._thread = None

    async def _run_streams(self) -> None:
        """Run the state stream only.
        
        Jogging is NOT started here - it's started lazily in send_action()
        to allow manual control via teaching pendant during recording.
        """
        self._state_stream_task = asyncio.create_task(self._state_stream())

        # Wait for stop signal
        await self._stop_event.wait()

        # Cancel state stream task
        self._state_stream_task.cancel()

        try:
            await self._state_stream_task
        except asyncio.CancelledError:
            pass

    async def _state_stream(self) -> None:
        """Stream motion group state from Nova."""
        try:
            state_api = wb_api.MotionGroupApi(self._api_client)
            logger.debug("Starting Nova state stream...")

            async for motion_state in state_api.stream_motion_group_state(
                cell=self._cell,
                motion_group=self._motion_group_id,
                controller=self._controller,
                response_rate=100,  # 100ms = 10Hz
            ):
                self._current_joints = list(motion_state.joint_position)

        except asyncio.CancelledError:
            logger.debug("State stream cancelled")
        except ConnectionClosedError as e:
            logger.warning(f"State stream websocket closed: {e}")
        except Exception as e:
            logger.error(f"State stream error: {e}")
            logger.error(traceback.format_exc())

    async def _jogging_control(self) -> None:
        """Run the jogging control loop using P-control."""

        def _build_request(velocity: list[float] | None = None) -> JointVelocityRequest:
            """Build a JointVelocityRequest."""
            if velocity is None:
                velocity = [0.0] * (self._num_joints or 6)
            return JointVelocityRequest(velocity=velocity)

        async def _client_request_generator(response_stream):
            """Client request generator for jogging control."""
            # Start Jogging by sending InitializeJogging once
            yield InitializeJoggingRequest(
                motion_group=self._motion_group_id, tcp=self._tcp
            )
            logger.debug("Sent InitializeJoggingRequest")

            # Consume responses and send velocity commands
            async for _ in response_stream:
                if self._target_joints is None or self._current_joints is None:
                    # No target or no state: remain idle
                    yield _build_request()
                    continue

                # Compute velocity using P-control
                velocities = self._p_control(
                    current=self._current_joints,
                    target=self._target_joints,
                )
                yield _build_request(velocity=velocities)

        try:
            jogging_api = wb_api.JoggingApi(self._api_client)
            logger.debug("Starting Nova jogging control...")

            await jogging_api.execute_jogging(
                cell=self._cell,
                controller=self._controller,
                client_request_generator=_client_request_generator,
            )
        except asyncio.CancelledError:
            logger.debug("Jogging control cancelled")
        except ConnectionClosedError as e:
            logger.warning(f"Jogging websocket closed, check if motion group or tcp exists: {e}")
        except Exception as e:
            logger.error(f"Jogging control error: {e}")
            logger.error(traceback.format_exc())

    def _p_control(
        self,
        current: list[float],
        target: list[float],
    ) -> list[float]:
        """Simple P-control to compute joint velocities towards target.

        Args:
            current: Current joint positions (radians).
            target: Target joint positions (radians).

        Returns:
            Joint velocities (rad/s) to move towards target.
        """
        if len(current) != len(target):
            raise ValueError("Current and target must have same length")

        # Check if all joints are within tolerance
        if all(
            abs(c - t) <= self._tolerance_rad for c, t in zip(current, target)
        ):
            return [0.0] * len(current)

        # Compute velocities with P-control and clamping
        velocities = []
        for c, t in zip(current, target):
            error = t - c
            velocity = error * self._p_gain
            # Clamp to max velocity
            velocity = max(-self._max_velocity_rad_s, min(self._max_velocity_rad_s, velocity))
            velocities.append(velocity)

        return velocities
