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

"""Configuration for Nova Shadow Teleoperator."""

import os
from dataclasses import dataclass, field

from lerobot.teleoperators.config import TeleoperatorConfig


# Number of joints for different robot types
ROBOT_JOINTS = {
    "ur10e": 6,
    "ur5e": 6,
    "ur3e": 6,
    "ur10": 6,
    "ur5": 6,
    "ur3": 6,
    "ur16e": 6,
    "ur20": 6,
    "ur30": 6,
    "fanuc": 6,
    "kuka": 6,
    "yaskawa": 6,
}


@TeleoperatorConfig.register_subclass("nova_shadow")
@dataclass
class NovaShadowConfig(TeleoperatorConfig):
    """Configuration for Nova Shadow Teleoperator.

    This teleoperator reads the current robot state from Nova and returns it
    as actions, enabling dataset recording when the robot is controlled externally
    (e.g., via teaching pendant or jogging).
    """

    # Nova API URL (can also be set via NOVA_API environment variable)
    nova_api: str = field(
        default_factory=lambda: os.environ.get("NOVA_API", "http://localhost:80")
    )

    # Name of the controller/robot in Nova (e.g., "ur10e", "ur5e")
    controller_name: str = "ur10e"

    # Motion group index (usually 0 for single-arm robots)
    motion_group: int = 0
