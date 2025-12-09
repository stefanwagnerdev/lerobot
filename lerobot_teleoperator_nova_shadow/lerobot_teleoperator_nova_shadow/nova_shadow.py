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

"""
Nova Shadow Teleoperator - Records the robot's current state as actions.

This teleoperator is designed for recording datasets when the robot is being
controlled externally (e.g., via teaching pendant, jogging, or another system).
It reads the current joint positions from Nova and returns them as "actions",
allowing you to record demonstrations without a physical leader arm.
"""

import asyncio
import logging
import threading
from typing import Any

from lerobot.teleoperators.teleoperator import Teleoperator
from wandelbots_api_client.v2 import ApiClient, Configuration
from wandelbots_api_client.v2.api import MotionGroupApi

from .config_nova_shadow import ROBOT_JOINTS, NovaShadowConfig

logger = logging.getLogger(__name__)


class NovaShadow(Teleoperator):
    """
    A teleoperator that shadows the robot's current state.

    This is useful for recording datasets when the robot is being controlled
    by an external system (teaching pendant, jogging, etc.). It reads the
    current joint positions and returns them as "actions" for recording.

    The robot controlled by this teleoperator should be the same robot
    that is being recorded - this creates a "shadow" effect where the
    recorded actions match what the robot is actually doing.
    """

    config_class = NovaShadowConfig
    name = "nova_shadow"

    def __init__(self, config: NovaShadowConfig):
        super().__init__(config)
        self.config = config

        # Determine number of joints based on controller
        self.num_joints = ROBOT_JOINTS.get(config.controller_name.lower(), 6)

        # API client
        self._api_client: ApiClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        # Current state (updated by state stream)
        self._current_joints: list[float] = [0.0] * self.num_joints
        self._state_lock = threading.Lock()
        self._connected = False

        # State streaming task
        self._state_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def action_features(self) -> dict:
        """Return the action feature specification matching the robot joints."""
        return {f"joint_{i+1}.pos": float for i in range(self.num_joints)}

    @property
    def feedback_features(self) -> dict:
        """No feedback features for shadow teleoperator."""
        return {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        """Shadow teleoperator doesn't need calibration."""
        return True

    def calibrate(self) -> None:
        """No calibration needed for shadow teleoperator."""
        pass

    def configure(self) -> None:
        """No configuration needed for shadow teleoperator."""
        pass

    def connect(self, calibrate: bool = True) -> None:
        """Connect to Nova and start streaming state."""
        if self._connected:
            return

        logger.info(f"Connecting Nova Shadow Teleoperator to {self.config.nova_api}")

        # Create API client - append /api/v2 like the robot class does
        api_host = f"{self.config.nova_api}/api/v2"
        if not api_host.startswith("http"):
            api_host = "http://" + api_host
        configuration = Configuration(host=api_host)
        self._api_client = ApiClient(configuration)

        # Start async event loop in background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Start state streaming
        future = asyncio.run_coroutine_threadsafe(self._start_streaming(), self._loop)
        future.result(timeout=10.0)  # Wait for initial state

        self._connected = True
        logger.info("Nova Shadow Teleoperator connected")

    def disconnect(self) -> None:
        """Disconnect from Nova."""
        if not self._connected:
            return

        logger.info("Disconnecting Nova Shadow Teleoperator")

        # Stop state streaming
        if self._loop and self._stop_event:
            asyncio.run_coroutine_threadsafe(self._stop_streaming(), self._loop).result(timeout=5.0)

        # Stop event loop
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            self._thread.join(timeout=5.0)

        if self._api_client:
            # Close synchronously to avoid coroutine warning
            pass

        self._connected = False
        logger.info("Nova Shadow Teleoperator disconnected")

    def get_action(self) -> dict[str, Any]:
        """Return the current robot joint positions as actions."""
        if not self._connected:
            raise RuntimeError("Teleoperator not connected")

        with self._state_lock:
            joints = self._current_joints.copy()

        return {f"joint_{i+1}.pos": joints[i] for i in range(self.num_joints)}

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        """No-op for shadow teleoperator (no feedback to send)."""
        pass

    def _run_loop(self) -> None:
        """Run the asyncio event loop in background thread."""
        if self._loop:
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

    async def _start_streaming(self) -> None:
        """Start the state streaming task."""
        self._stop_event = asyncio.Event()
        self._state_task = asyncio.create_task(self._state_stream())

        # Wait for initial state
        await asyncio.sleep(0.5)

    async def _stop_streaming(self) -> None:
        """Stop the state streaming task."""
        if self._stop_event:
            self._stop_event.set()
        if self._state_task:
            self._state_task.cancel()
            try:
                await self._state_task
            except asyncio.CancelledError:
                pass

    async def _state_stream(self) -> None:
        """Stream robot state from Nova."""
        if self._api_client is None or self._stop_event is None:
            return

        state_api = MotionGroupApi(self._api_client)
        # Format: {motion_group_index}@{controller_name}
        motion_group = f"{self.config.motion_group}@{self.config.controller_name}"

        while not self._stop_event.is_set():
            try:
                async for motion_state in state_api.stream_motion_group_state(
                    cell="cell",
                    motion_group=motion_group,
                    controller=self.config.controller_name,
                    response_rate=100,  # 100ms = 10Hz
                ):
                    if self._stop_event.is_set():
                        break

                    # Extract joint positions - the API returns them directly
                    if hasattr(motion_state, "joint_position"):
                        with self._state_lock:
                            self._current_joints = list(motion_state.joint_position)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.warning(f"State stream error: {e}, reconnecting...")
                    await asyncio.sleep(1.0)
