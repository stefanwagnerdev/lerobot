# lerobot_robot_nova

Wandelbots Nova robot integration for [LeRobot](https://github.com/huggingface/lerobot).

This plugin enables controlling industrial robots through the [Wandelbots Nova](https://wandelbots.com/) platform within the LeRobot ecosystem. It allows you to record datasets using the teaching pendant for jogging and train imitation learning policies.

For the general LeRobot workflow (recording, training, evaluation), see the [Imitation Learning on Real-World Robots](https://huggingface.co/docs/lerobot/il_robots) documentation.

## Installation

```bash
# Install the robot plugin
pip install -e ./lerobot_robot_nova

# Install the teleoperator plugin (required for recording)
pip install -e ./lerobot_teleoperator_nova_shadow

# Install the camera plugin (required for training policies)
pip install -e ./lerobot_camera_realsense_webrtc
```

## Configuration

```bash
# Nova API endpoint
export NOVA_API=http://172.31.10.79

# RealSense REST API endpoint (for cameras)
export REALSENSE_API=http://172.31.11.129:8000
```

## Nova-Specific Arguments

| Argument                         | Description                                       |
| -------------------------------- | ------------------------------------------------- |
| `--robot.type=nova`              | Use the Nova robot plugin                         |
| `--robot.controller_name=ur10e`  | Controller name configured in Nova                |
| `--robot.enable_jogging=true`    | Enable jogging mode for replay/inference          |
| `--teleop.type=nova_shadow`      | Shadow teleoperator (reads robot state as action) |
| `--teleop.controller_name=ur10e` | Controller name for teleoperator                  |

## Example Commands

### Teleoperate (test connectivity)

```bash
lerobot-teleoperate \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --teleop.type=nova_shadow \
    --teleop.controller_name=ur10e
```

### Record Dataset

Jog the robot using the Nova teaching pendant while recording:

```bash
lerobot-record \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --robot.cameras='{"cam_flange": {"type": "realsense_webrtc", "device_id": "315122271048", "fps": 30, "width": 640, "height": 480}}' \
    --teleop.type=nova_shadow \
    --teleop.controller_name=ur10e \
    --dataset.repo_id=${HF_USER}/nova_ur10e_dataset \
    --dataset.num_episodes=50 \
    --dataset.single_task="Pick and place task"
```

### Replay Episode

```bash
lerobot-replay \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --robot.enable_jogging=true \
    --dataset.repo_id=${HF_USER}/nova_ur10e_dataset \
    --dataset.episode=0
```

### Run Inference

```bash
lerobot-record \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --robot.enable_jogging=true \
    --robot.cameras='{"cam_flange": {"type": "realsense_webrtc", "device_id": "315122271048", "fps": 30, "width": 640, "height": 480}}' \
    --dataset.repo_id=${HF_USER}/eval_nova_ur10e \
    --dataset.num_episodes=10 \
    --policy.path=outputs/train/act_nova_ur10e/checkpoints/last/pretrained_model
```

## How It Works

The Nova integration uses a **shadow teleoperator** pattern:

1. **Recording**: The robot is jogged via the Nova teaching pendant. The `nova_shadow` teleoperator reads the current robot state as the "action", allowing you to record demonstrations without a physical leader arm.

2. **Replay/Inference**: Set `--robot.enable_jogging=true` to enable the robot to execute commands. The plugin sends joint position commands through the Nova jogging API.

## Supported Robots

Nova supports multiple industrial robot brands. Configure your robot on the Nova instance first, then reference it by controller name:

- Universal Robots (UR3, UR5, UR10, UR10e, UR16, UR20, UR30)
- KUKA robots
- Fanuc robots
- ABB robots
- Yaskawa robots
- And more...

## License

Apache-2.0
