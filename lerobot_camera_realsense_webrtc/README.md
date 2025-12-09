# LeRobot Camera Plugin: RealSense WebRTC

LeRobot camera plugin for Intel RealSense cameras accessed via a WebRTC-enabled REST API.

## Overview

This plugin allows LeRobot to capture images from Intel RealSense cameras (D405, D415, D435, etc.) through a network REST API that provides WebRTC video streaming. This is useful for:

- Remote camera setups where cameras are not directly connected to the robot control computer
- Centralized camera management with multiple devices
- Low-latency video streaming over network

## Installation

```bash
cd lerobot_camera_realsense_webrtc
pip install -e .
```

## Configuration

Set the RealSense REST API URL in your environment:

```bash
export REALSENSE_API=http://172.31.11.129:8000
```

## Usage

### With LeRobot Recording (CLI)

Record a dataset with camera images using the command line:

```bash
export NOVA_API=http://172.31.10.79
export REALSENSE_API=http://172.31.11.129:8000

lerobot-record \
    --robot.type=nova \
    --robot.controller_name=ur10e \
    --robot.cameras='{"cam_flange": {"type": "realsense_webrtc", "device_id": "315122271048", "fps": 30, "width": 640, "height": 480}}' \
    --teleop.type=nova_shadow \
    --teleop.controller_name=ur10e \
    --dataset.repo_id=your_username/nova_ur10e_dataset \
    --dataset.num_episodes=10 \
    --dataset.single_task="Pick and place task" \
    --dataset.push_to_hub=false
```

### Multiple Cameras

Add multiple cameras by extending the cameras dictionary:

```bash
--robot.cameras='{
    "cam_flange": {"type": "realsense_webrtc", "device_id": "315122271048", "fps": 30, "width": 640, "height": 480},
    "cam_left": {"type": "realsense_webrtc", "device_id": "319522063360", "fps": 30, "width": 640, "height": 480},
    "cam_right": {"type": "realsense_webrtc", "device_id": "314522065367", "fps": 30, "width": 640, "height": 480}
}'
```

### Standalone Usage (Python API)

```python
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

# Read a frame
frame = camera.read()  # Returns numpy array (H, W, 3) in RGB
print(f"Frame shape: {frame.shape}")  # (480, 640, 3)

camera.disconnect()
```

## Available Devices

With the provided REST API:

| Serial Number | Model | Description             |
| ------------- | ----- | ----------------------- |
| 315122271048  | D405  | Mounted on robot flange |
| 319522063360  | D415  | External camera 1       |
| 314522065367  | D415  | External camera 2       |

## Requirements

- RealSense REST API service running with WebRTC support
- `aiortc` library for WebRTC communication
- `aiohttp` for async HTTP requests
- `av` (PyAV) for video frame decoding
- Network connectivity to the API server

## Troubleshooting

### "No accelerated colorspace conversion found" warnings

These warnings from FFmpeg are harmless and indicate that software-based YUV to BGR conversion is being used. They are suppressed by default in this plugin.

### Connection timeouts

If the WebRTC connection times out:

1. Check that the RealSense API service is running
2. Verify network connectivity to the API server
3. Ensure the device_id matches an available camera
4. The default ICE timeout is 10 seconds - increase `ice_timeout_s` if needed

## License

Apache-2.0
