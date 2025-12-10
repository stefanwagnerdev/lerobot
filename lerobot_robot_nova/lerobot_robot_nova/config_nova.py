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

"""Configuration class for Nova robot integration."""

import os
from dataclasses import dataclass, field

from lerobot.cameras.configs import CameraConfig
from lerobot.robots.config import RobotConfig


@RobotConfig.register_subclass("nova")
@dataclass
class NovaRobotConfig(RobotConfig):
    """Configuration for a Wandelbots Nova robot.

    Nova is a robot platform that supports multiple robot types through a unified API.
    Configure your robot on the Nova instance first, then reference it by controller name.

    Args:
        nova_api: URL of the Nova API. Defaults to NOVA_API environment variable.
        controller_name: Name of the controller configured on the Nova instance.
        motion_group: Index of the motion group on the controller (default: 0).
        enable_jogging: Whether to enable jogging control for sending actions.
            Set to False for recording with teaching pendant (observation-only mode).
            Set to True for policy evaluation (robot actively executes actions).
        cameras: Dictionary of camera configurations keyed by camera name.
    """

    # Nova API URL - defaults to environment variable
    nova_api: str = field(default_factory=lambda: os.environ.get("NOVA_API", "http://localhost:80"))

    # Controller name as configured on the Nova instance
    controller_name: str = "ur10e"

    # Motion group index (most robots use 0, Fanuc uses 1)
    motion_group: int = 0

    # Enable jogging control for sending actions (set False for teaching pendant recording)
    enable_jogging: bool = False

    # Optional cameras
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
