#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
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
RealSense camera implementation via REST API with WebRTC streaming.

This camera connects to a RealSense REST API service that provides WebRTC
video streaming from Intel RealSense cameras.
"""

import asyncio
import logging
import threading
from typing import Any

import cv2
import requests
from numpy.typing import NDArray

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription  # type: ignore
    from av import VideoFrame  # type: ignore
    import av  # type: ignore

    # Suppress swscaler warnings about colorspace conversion (yuv420p -> bgr24)
    # This is normal for WebRTC video streams and just uses software conversion
    av.logging.set_level(av.logging.ERROR)

    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False  # type: ignore

from lerobot.cameras.camera import Camera
from lerobot.cameras.configs import ColorMode
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from .config_realsense_webrtc import RealsenseWebrtcCameraConfig

logger = logging.getLogger(__name__)


class FrameReceiver:
    """Receives video frames from WebRTC track and stores the latest frame."""

    def __init__(self):
        self.frame: NDArray[Any] | None = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()

    async def receive_frames(self, track):
        """Continuously receive frames from the WebRTC track."""
        while True:
            try:
                frame: VideoFrame = await track.recv()
                # Convert to numpy array (BGR format from av)
                img = frame.to_ndarray(format="bgr24")
                with self.frame_lock:
                    self.frame = img
                self.frame_event.set()
            except Exception as e:
                logger.debug(f"Frame receive stopped: {e}")
                break


class RealsenseWebrtcCamera(Camera):
    """
    RealSense camera accessed via REST API with WebRTC streaming.

    This camera connects to a RealSense REST API service that provides WebRTC
    video streaming. It supports Intel RealSense D405, D415, D435, etc.

    The camera uses WebRTC for efficient, low-latency video streaming over the
    network, making it suitable for remote camera setups.

    Example:
        ```python
        from lerobot_camera_realsense_webrtc import (
            RealsenseWebrtcCamera,
            RealsenseWebrtcCameraConfig
        )

        config = RealsenseWebrtcCameraConfig(
            api_url="http://172.31.11.129:8000",
            device_id="315122271048",  # D405 on flange
            stream_type="color",
            fps=30,
            width=640,
            height=480
        )
        camera = RealsenseWebrtcCamera(config)
        camera.connect()

        frame = camera.read()
        print(frame.shape)  # e.g., (480, 640, 3)

        camera.disconnect()
        ```
    """

    def __init__(self, config: RealsenseWebrtcCameraConfig):
        super().__init__(config)
        self.config = config
        self._is_connected = False
        self._pc: RTCPeerConnection | None = None
        self._frame_receiver: FrameReceiver | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._color_mode = ColorMode.RGB  # Default output mode
        self._session_id: str | None = None  # WebRTC session ID

    @property
    def is_connected(self) -> bool:
        """Check if the camera is currently connected."""
        return self._is_connected

    @staticmethod
    def find_cameras() -> list[dict[str, Any]]:
        """
        Detect available RealSense cameras via the REST API.

        This requires the REALSENSE_API environment variable or api_url config
        to be set. Returns a list of dictionaries with device information.

        Returns:
            List of dicts with 'serial_number', 'name', and other device info.
        """
        import os

        api_url = os.environ.get("REALSENSE_API", "http://localhost:8000")

        try:
            response = requests.get(f"{api_url}/api/devices/", timeout=5)
            response.raise_for_status()
            devices = response.json()
            return [
                {
                    "serial_number": d.get("serial_number", "unknown"),
                    "name": d.get("name", "unknown"),
                    "connected": d.get("connected", False),
                }
                for d in devices
            ]
        except Exception as e:
            logger.error(f"Failed to query RealSense REST API at {api_url}: {e}")
            return []

    def _run_event_loop(self):
        """Run the asyncio event loop in a background thread."""
        asyncio.set_event_loop(self._event_loop)
        self._event_loop.run_forever()

    def _start_stream(self) -> None:
        """Start the RealSense stream via REST API before WebRTC connection."""
        api_url = self.config.api_url.rstrip("/")

        # Stop any existing stream first to ensure we start fresh with the requested resolution
        self._stop_stream()

        # Get sensor info to find the correct sensor_id
        sensors_url = f"{api_url}/api/devices/{self.config.device_id}/sensors/"
        response = requests.get(sensors_url, timeout=10)
        response.raise_for_status()
        sensors = response.json()

        # Find sensor that supports the requested stream type
        sensor_id = None
        for sensor in sensors:
            for profile in sensor.get("supported_stream_profiles", []):
                if profile.get("stream_type") == self.config.stream_type:
                    sensor_id = sensor.get("sensor_id")
                    break
            if sensor_id:
                break

        if not sensor_id:
            raise RuntimeError(
                f"No sensor found supporting stream type '{self.config.stream_type}'"
            )

        # Configure stream
        width = self.config.width or 640
        height = self.config.height or 480
        fps = self.config.fps or 30

        # Determine format based on stream type
        format_map = {
            "color": "rgb8",
            "depth": "z16",
            "infrared-1": "y8",
            "infrared-2": "y8",
        }
        fmt = format_map.get(self.config.stream_type, "rgb8")

        start_url = f"{api_url}/api/devices/{self.config.device_id}/stream/start"
        payload = {
            "configs": [
                {
                    "stream_type": self.config.stream_type,
                    "format": fmt,
                    "resolution": {"width": width, "height": height},
                    "framerate": fps,
                    "sensor_id": sensor_id,
                }
            ]
        }

        logger.info(f"Starting RealSense stream: {payload}")
        response = requests.post(start_url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("RealSense stream started successfully")

    def _stop_stream(self) -> None:
        """Stop the RealSense stream via REST API."""
        try:
            api_url = self.config.api_url.rstrip("/")
            stop_url = f"{api_url}/api/devices/{self.config.device_id}/stream/stop"
            requests.post(stop_url, timeout=10)
            logger.info("RealSense stream stopped")
        except Exception as e:
            logger.debug(f"Error stopping stream: {e}")

    async def _establish_webrtc_connection(self) -> None:
        """Establish WebRTC connection to the RealSense REST API.

        The flow is:
        1. Client requests an offer from server: POST /api/webrtc/offer {device_id, stream_types}
        2. Server returns SDP offer + session_id
        3. Client creates answer and sends it: POST /api/webrtc/answer {session_id, sdp, type}
        """
        if not AIORTC_AVAILABLE:
            raise RuntimeError(
                "aiortc is required for WebRTC camera support. "
                "Install it with: pip install aiortc"
            )

        self._pc = RTCPeerConnection()
        self._frame_receiver = FrameReceiver()

        @self._pc.on("track")
        async def on_track(track):
            logger.info(f"Received {track.kind} track")
            if track.kind == "video":
                asyncio.create_task(self._frame_receiver.receive_frames(track))

        # Step 1: Request offer from server
        api_url = self.config.api_url.rstrip("/")
        offer_url = f"{api_url}/api/webrtc/offer"

        payload = {
            "device_id": self.config.device_id,
            "stream_types": [self.config.stream_type],
        }

        logger.info(f"Requesting WebRTC offer from {offer_url}")
        response = requests.post(offer_url, json=payload, timeout=30)
        response.raise_for_status()

        offer_data = response.json()
        self._session_id = offer_data.get("session_id")
        logger.info(f"Received offer, session_id: {self._session_id}")

        # Step 2: Set remote description (server's offer)
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        await self._pc.setRemoteDescription(offer)

        # Step 3: Create answer
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)

        # Step 4: Send answer to server
        answer_url = f"{api_url}/api/webrtc/answer"
        answer_payload = {
            "session_id": self._session_id,
            "sdp": self._pc.localDescription.sdp,
            "type": self._pc.localDescription.type,
        }

        logger.info(f"Sending WebRTC answer to {answer_url}")
        response = requests.post(answer_url, json=answer_payload, timeout=30)
        response.raise_for_status()

        logger.info("WebRTC connection established")

    def connect(self, warmup: bool = True) -> None:
        """
        Establish connection to the RealSense camera via WebRTC.

        Args:
            warmup: If True, waits for the first frame before returning.

        Raises:
            DeviceAlreadyConnectedError: If the camera is already connected.
            RuntimeError: If the connection fails.
        """
        if self._is_connected:
            raise DeviceAlreadyConnectedError(
                f"RealsenseWebrtcCamera({self.config.device_id}) is already connected."
            )

        logger.info(
            f"Connecting to RealSense camera {self.config.device_id} "
            f"via {self.config.api_url}"
        )

        # Step 1: Start the RealSense stream via REST API
        self._start_stream()

        # Create event loop in background thread
        self._event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._loop_thread.start()

        # Run WebRTC connection setup
        future = asyncio.run_coroutine_threadsafe(
            self._establish_webrtc_connection(), self._event_loop
        )

        try:
            future.result(timeout=self.config.ice_timeout_s + 10)
        except Exception as e:
            self.disconnect()
            raise RuntimeError(f"Failed to establish WebRTC connection: {e}") from e

        self._is_connected = True

        if warmup:
            # Wait for first frame
            logger.info("Warming up camera, waiting for first frame...")
            if not self._frame_receiver.frame_event.wait(timeout=10.0):
                self.disconnect()
                raise RuntimeError("Timeout waiting for first frame from camera")
            logger.info("Camera warmup complete")

    def read(self, color_mode: ColorMode | None = None) -> NDArray[Any]:
        """
        Capture and return a single frame from the camera.

        Args:
            color_mode: Desired color mode (RGB or BGR). Defaults to RGB.

        Returns:
            np.ndarray: Captured frame as a numpy array with shape (H, W, 3).

        Raises:
            DeviceNotConnectedError: If the camera is not connected.
            RuntimeError: If no frame is available.
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                f"RealsenseWebrtcCamera({self.config.device_id}) is not connected."
            )

        with self._frame_receiver.frame_lock:
            if self._frame_receiver.frame is None:
                raise RuntimeError("No frame available from camera")
            frame = self._frame_receiver.frame.copy()

        # Handle color mode conversion (frame comes in BGR from aiortc)
        mode = color_mode if color_mode is not None else self._color_mode
        if mode == ColorMode.RGB:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        return frame

    def async_read(self, timeout_ms: float = 1000.0) -> NDArray[Any]:
        """
        Asynchronously capture and return a single frame.

        Waits for a new frame or returns the latest available frame.

        Args:
            timeout_ms: Maximum time to wait for a frame in milliseconds.

        Returns:
            np.ndarray: Captured frame as a numpy array.

        Raises:
            DeviceNotConnectedError: If the camera is not connected.
            RuntimeError: If no frame is received within the timeout.
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                f"RealsenseWebrtcCamera({self.config.device_id}) is not connected."
            )

        # Wait for new frame
        self._frame_receiver.frame_event.clear()
        if not self._frame_receiver.frame_event.wait(timeout=timeout_ms / 1000.0):
            # Return existing frame if available
            with self._frame_receiver.frame_lock:
                if self._frame_receiver.frame is not None:
                    frame = self._frame_receiver.frame.copy()
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            raise RuntimeError(f"Timeout ({timeout_ms}ms) waiting for frame")

        return self.read()

    def disconnect(self) -> None:
        """Disconnect from the camera and release resources."""
        if self._pc is not None:
            # Close peer connection
            if self._event_loop is not None:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._pc.close(), self._event_loop
                    )
                    future.result(timeout=5.0)
                except Exception as e:
                    logger.debug(f"Error closing peer connection: {e}")

            self._pc = None

        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=2.0)
            self._event_loop = None
            self._loop_thread = None

        self._frame_receiver = None
        self._is_connected = False

        # Stop the RealSense stream
        self._stop_stream()

        logger.info(f"Disconnected from RealSense camera {self.config.device_id}")


__all__ = ["RealsenseWebrtcCamera"]
