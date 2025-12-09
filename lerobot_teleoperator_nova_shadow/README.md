# Nova Shadow Teleoperator for LeRobot

A teleoperator plugin for [LeRobot](https://github.com/huggingface/lerobot) that enables dataset recording when a robot is controlled externally (e.g., via teaching pendant, jogging, or another system).

## Overview

The Nova Shadow Teleoperator "shadows" the robot's current state - it reads the robot's joint positions from Nova and returns them as "actions". This allows you to record demonstrations without a physical leader arm, simply by moving the robot with external controls.

## Installation

```bash
pip install -e ./lerobot_teleoperator_nova_shadow
```

## Usage

Use with `lerobot-record` to record datasets while manually controlling the robot:

```bash
export NOVA_API=http://your-nova-instance

lerobot-record \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --teleop.type=nova_shadow \
    --teleop.controller_name=ur10e \
    --dataset.repo_id=${HF_USER}/my_dataset \
    --dataset.single_task="Pick up the red cube" \
    --dataset.num_episodes=50
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `nova_api` | `$NOVA_API` or `http://localhost:80` | Nova API URL |
| `controller_name` | `ur10e` | Name of the robot controller in Nova |
| `motion_group` | `0` | Motion group index |

## How It Works

1. Connects to Nova's state streaming API
2. Continuously reads the robot's current joint positions
3. Returns these positions as "actions" when `get_action()` is called
4. The recorded dataset will have matching observations and actions (since the "action" is what the robot is currently doing)

This is perfect for:
- Recording demonstrations via teaching pendant
- Recording while using Nova's jogging interface
- Any scenario where the robot is controlled externally

## License

Apache-2.0
