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
LeRobot camera plugin for RealSense cameras via REST API with WebRTC streaming.

This plugin provides camera support for Intel RealSense cameras accessed through
a WebRTC-enabled REST API service. Useful for remote camera setups.

Usage:
    from lerobot_camera_realsense_webrtc import (
        RealsenseWebrtcCamera,
        RealsenseWebrtcCameraConfig
    )

    config = RealsenseWebrtcCameraConfig(
        api_url="http://172.31.11.129:8000",
        device_id="315122271048",
        stream_type="color",
        fps=30,
        width=640,
        height=480
    )
    camera = RealsenseWebrtcCamera(config)
    camera.connect()
    frame = camera.read()
    camera.disconnect()
"""

from .config_realsense_webrtc import RealsenseWebrtcCameraConfig
from .realsense_webrtc import RealsenseWebrtcCamera

__all__ = ["RealsenseWebrtcCamera", "RealsenseWebrtcCameraConfig"]
