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

"""Configuration for RealSense cameras accessed via REST API with WebRTC."""

import os
from dataclasses import dataclass, field

from lerobot.cameras.configs import CameraConfig


@CameraConfig.register_subclass("realsense_webrtc")
@dataclass
class RealsenseWebrtcCameraConfig(CameraConfig):
    """Configuration for RealSense cameras accessed via WebRTC REST API.

    This camera connects to a RealSense REST API service that provides WebRTC
    streaming. It supports color and depth streams from RealSense devices.

    Attributes:
        api_url: Base URL of the RealSense REST API (e.g., http://172.31.11.129:8000)
                 Can be overridden with REALSENSE_API environment variable.
        device_id: Serial number of the RealSense device (e.g., "315122271048")
        stream_type: Type of stream to capture ("color" or "depth"). Defaults to "color".
        fps: Desired frames per second.
        width: Frame width in pixels.
        height: Frame height in pixels.
        ice_timeout_s: Timeout in seconds for ICE connection establishment.

    Example:
        ```python
        config = RealsenseWebrtcCameraConfig(
            api_url="http://172.31.11.129:8000",
            device_id="315122271048",  # D405 on flange
            stream_type="color",
            fps=30,
            width=640,
            height=480
        )
        ```
    """

    api_url: str = field(default_factory=lambda: os.environ.get("REALSENSE_API", "http://localhost:8000"))
    device_id: str = ""  # RealSense serial number
    stream_type: str = "color"  # "color" or "depth"
    ice_timeout_s: float = 10.0


__all__ = ["RealsenseWebrtcCameraConfig"]
