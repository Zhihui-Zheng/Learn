#!/usr/bin/env python
"""
Test client for RoboCasa ZMQ simulation server.

Prints robot state and controls the robot.
Run AFTER starting the server:

     python -m robocasa.server --task DefrostByCategory --layout 11 --style 14 --seed 42

Usage:
    python test_client.py [--host HOST] [--mode simple|interactive]

Dependencies: pyzmq msgpack numpy (opencv-python optional)
"""

from robocasa.server.client import RoboCasaClient
import time
import cv2

client = RoboCasaClient(host="localhost")
client.connect()

# 读取初始位置
client.recv_state()
before = client.base_state["base_pos"]
print(f"移动前: x={before[0]:.3f}  y={before[1]:.3f}  yaw={before[2]:.3f}")

# 底盘向左平移，持续 2 秒（40 步 × 0.05s = 2s）
for _ in range(40):
    client.send_base([0.0, 0.3, 0])
    time.sleep(0.05)

# 必须显式归零
client.send_base([0.0, 0.0, 0.0])
time.sleep(0.2)

# 读取移动后位置
client.recv_state()
after = client.base_state["base_pos"]
print(f"移动后: x={after[0]:.3f}  y={after[1]:.3f}  yaw={after[2]:.3f}")
print(f"位移:   dx={after[0]-before[0]:.3f}  dy={after[1]-before[1]:.3f}  dyaw={after[2]-before[2]:.3f}")

client.close()
