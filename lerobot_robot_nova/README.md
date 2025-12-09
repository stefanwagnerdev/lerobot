# lerobot_robot_nova

Wandelbots Nova robot integration for [LeRobot](https://github.com/huggingface/lerobot).

This plugin enables controlling robots through the Wandelbots Nova platform within the LeRobot ecosystem.

## Installation

```bash
pip install lerobot_robot_nova
```

Or install from source:

```bash
cd lerobot_robot_nova
pip install -e .
```

## Configuration

Set the `NOVA_API` environment variable to point to your Nova instance:

```bash
export NOVA_API=http://your-nova-instance:80
```

## Usage

Once installed, the plugin is automatically discovered by LeRobot. Use it with:

```bash
# Teleoperate
lerobot-teleoperate --robot.type=nova --robot.controller_name=ur10e

# Record data
lerobot-record --robot.type=nova --robot.controller_name=ur10e --repo-id=my_dataset
```

## Supported Robots

Nova supports multiple robot types. Configure your robot on the Nova instance first, then reference it by controller name:

- Universal Robots (UR3, UR5, UR10, UR10e, UR16, UR20, UR30)
- KUKA robots
- Fanuc robots
- ABB robots
- Yaskawa robots
- And more...

## License

Apache-2.0
