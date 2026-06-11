# RoboCasa Server 接口文档

## 架构概览

服务端通过 3 个 ZMQ socket 与客户端通信：

| Socket | 类型 | 默认端口 | 方向 | 用途 |
|--------|------|----------|------|------|
| `pub`  | PUB  | 5555     | 服务端→客户端 | 推送机器人状态、相机图像 |
| `ctrl` | PULL | 5556     | 客户端→服务端 | 接收控制指令 |
| `svc`  | REP  | 5557     | 请求-应答 | 服务调用（重置、IK 求解等） |

所有消息使用 **msgpack** 编码。

---

## 一、状态推送 (PUB socket `tcp://host:5555`)

服务端每步仿真（默认 20Hz）发布一次。客户端需订阅对应 topic 前缀才能收到数据。

### 1.1 机械臂状态 `/robot/arm/state`

| 字段 | 类型 | 维度 | 说明 |
|------|------|------|------|
| `joint_pos` | `float[]` | 7 | 关节角度 (rad) |
| `joint_vel` | `float[]` | 7 | 关节角速度 (rad/s) |
| `eef_pos` | `float[]` | 3 | 末端位置 (x, y, z)，世界坐标系 |
| `eef_quat` | `float[]` | 4 | 末端姿态四元数 (w, x, y, z) |

### 1.2 夹爪状态 `/robot/gripper/state`

| 字段 | 类型 | 维度 | 说明 |
|------|------|------|------|
| `gripper_qpos` | `float[]` | 2 | 左右指关节位置 (m) |

### 1.3 移动底座状态 `/robot/base/state`

| 字段 | 类型 | 维度 | 说明 |
|------|------|------|------|
| `base_pos` | `float[]` | 3 | 底座位姿 (x, y, yaw) |
| `base_vel` | `float[]` | 3 | 底座速度 (vx, vy, omega) |

### 1.4 升降躯干状态 `/robot/torso/state`

| 字段 | 类型 | 说明 |
|------|------|------|
| `torso_height` | `float` | 躯干高度 (m) |

---

## 二、相机推送 (PUB socket)

### 2.1 相机列表

| 相机名 | 视角 |
|--------|------|
| `robot0_agentview_center` | 居中俯视 |
| `robot0_agentview_left` | 左侧俯视 |
| `robot0_agentview_right` | 右侧俯视 |
| `robot0_frontview` | 正前方 |
| `robot0_eye_in_hand` | 末端腕部 |

### 2.2 RGB 图像 `/cameras/{cam_name}/rgb`

三帧 multipart 消息：

| 帧 | 内容 | 编码 |
|----|------|------|
| 1 | topic 字符串（如 `/cameras/robot0_agentview_center/rgb`） | UTF-8 |
| 2 | 元信息 `{"shape": [H, W, 3], "dtype": "uint8"}` | msgpack |
| 3 | 原始像素字节 (H×W×3) | raw bytes |

图像已翻转为上下方向正确（MuJoCo 默认渲染为上下颠倒）。

### 2.3 深度图 `/cameras/{cam_name}/depth`

格式同上，dtype 为 `float32`，shape 为 `[H, W]`，单位米。

### 2.4 相机内参 `/cameras/{cam_name}/info`

每 5 秒重发一次，确保后连接客户端能收到。

| 字段 | 类型 | 说明 |
|------|------|------|
| `intrinsics` | `float[3][3]` | 3×3 内参矩阵 `[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]` |
| `cam_pos` | `float[3]` | 相机世界坐标 |
| `cam_quat` | `float[4]` | 相机朝向四元数 (w, x, y, z) |
| `fovy` | `float` | 垂直视场角 (度) |
| `width` | `int` | 图像宽度 (px) |
| `height` | `int` | 图像高度 (px) |

---

## 三、控制指令 (PULL socket `tcp://host:5556`)

两帧 multipart 消息：`[topic_bytes, msgpack(payload)]`

采用 **hold-last-value** 策略：指令持续生效直到发送新值或 env reset。

### 3.1 机械臂末端增量位姿 `/robot/arm/delta_ee_pose`

相对当前末端坐标系的增量运动。

| 索引 | 含义 | 范围 |
|------|------|------|
| 0 | dx 前后 | [-1, 1] → 映射到 [-0.05m, 0.05m] / step |
| 1 | dy 左右 | 同上 |
| 2 | dz 上下 | 同上 |
| 3 | droll | [-1, 1] → 映射到 [-0.5rad, 0.5rad] / step |
| 4 | dpitch | 同上 |
| 5 | dyaw | 同上 |

> **重要**：每条指令只发送一个增量。如需连续运动，保持相同 delta 值（hold-last-value 机制会每步重复应用）。

### 3.2 夹爪 `/robot/gripper/command`

| 值 | 含义 |
|----|------|
| `[-1.0]` | 完全张开 |
| `[1.0]` | 完全闭合 |

支持连续值，中间值对应中间开度。

### 3.3 移动底座 `/robot/base/command`

| 索引 | 含义 | 范围 |
|------|------|------|
| 0 | vx 前后速度 | [-1, 1] |
| 1 | vy 左右速度 | [-1, 1] |
| 2 | omega 旋转角速度 | [-1, 1] |

> 当底座速度非零时，机械臂自动切换为"世界系跟踪模式"（随底座运动补偿）。

### 3.4 升降躯干 `/robot/torso/command`

| 值 | 含义 |
|----|------|
| `[h]` | 目标高度，范围 [-1, 1] 映射到实际关节范围 |

---

## 四、服务调用 (REP socket `tcp://host:5557`)

请求格式：`[topic_bytes, msgpack(params)]`
响应格式：`[status_bytes, msgpack(response)]`
- 成功：`status = b"ok"`，`response` 含 `"status": "ok"`
- 失败：`status = b"err"`，`response` 含 `"status": "error"` 和 `"message"`

### 4.1 场景重置 `/env/reset`

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `layout_id` | `int` | （可选）厨房布局 ID |
| `style_id` | `int` | （可选）风格 ID |

> 不传参数时仅重置当前场景到初始状态，不换布局。

**响应**：`{"status": "ok"}`

> 重置后所有控制指令缓冲区归零。

### 4.2 IK 求解 `/robot/arm/solve_ik`

**请求参数**：

| 参数 | 类型 | 维度 | 说明 |
|------|------|------|------|
| `target_pos` | `float[]` | 3 | 目标末端位置 (x, y, z)，世界系 |
| `target_quat` | `float[]` | 4 | 目标末端姿态四元数 (w, x, y, z) |

**成功响应**：

```json
{
  "status": "ok",
  "joint_angles": [j0, j1, j2, j3, j4, j5, j6]
}
```

**失败响应**：`{"status": "unreachable", "message": "..."}`

---

## 五、接口使用示例

以下所有示例基于 `RoboCasaClient`。先完成连接：

```python
from robocasa.server.client import RoboCasaClient
import time, numpy as np

client = RoboCasaClient(host="localhost")
client.connect()
```

### 5.1 连接与断开

```python
# 连接服务端
client.connect()
print("已连接")

# 断开连接
client.close()
print("已断开")
```

### 5.2 读取状态（非阻塞轮询）

```python
import time

deadline = time.monotonic() + 3.0
while time.monotonic() < deadline:
    client.recv_state()          # 非阻塞，收完当前缓冲区内所有消息
    if client.arm_state:         # 收到数据后退出
        break
    time.sleep(0.05)

# 机械臂状态
arm = client.arm_state
print("关节角度:", arm["joint_pos"])         # [j0, j1, j2, j3, j4, j5, j6] (rad)
print("关节速度:", arm["joint_vel"])          # [v0, v1, v2, v3, v4, v5, v6] (rad/s)
print("末端位置:", arm["eef_pos"])           # [x, y, z] (m)
print("末端姿态:", arm["eef_quat"])          # [w, x, y, z] 四元数

# 夹爪状态
print("夹爪位置:", client.gripper_state["gripper_qpos"])  # [left, right] (m)

# 底座状态
base = client.base_state
print("底座位姿:", base["base_pos"])         # [x, y, yaw]
print("底座速度:", base["base_vel"])         # [vx, vy, omega]

# 躯干状态
print("躯干高度:", client.torso_state["torso_height"])    # float (m)
```

### 5.3 机械臂末端运动

delta 值作用于**当前末端坐标系**（非世界系），hold-last-value 模式下每仿真步重复执行。

```python
STEP = 0.02            # 每次步进幅度，值越大移动越快
DURATION = 20          # 持续步数（20 × 0.05s = 1 秒）

directions = {
    "前":  [ STEP, 0, 0, 0, 0, 0],
    "后":  [-STEP, 0, 0, 0, 0, 0],
    "左":  [0, -STEP, 0, 0, 0, 0],
    "右":  [0,  STEP, 0, 0, 0, 0],
    "上":  [0, 0,  STEP, 0, 0, 0],
    "下":  [0, 0, -STEP, 0, 0, 0],
}

# 演示：依次上下左右前后各移动 1 秒
for name, delta in directions.items():
    client.recv_state()
    before = client.arm_state.get("eef_pos", [0,0,0])

    for _ in range(DURATION):
        client.send_delta_ee_pose(delta)
        time.sleep(0.05)            # 匹配服务端控制频率 20Hz

    time.sleep(0.1)                 # 等待仿真推进
    client.recv_state()
    after = client.arm_state.get("eef_pos", [0,0,0])
    print(f"{name}: {before} → {after}")

# ⚠️ 必须显式归零，否则机械臂按最后一条 delta 一直运动
client.send_delta_ee_pose([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
```

### 5.4 夹爪开合

```python
import time

# 完全张开
client.send_gripper(-1.0)
time.sleep(0.5)
client.recv_state()
print("张开:", client.gripper_state["gripper_qpos"])

# 半开
client.send_gripper(0.0)
time.sleep(0.5)
client.recv_state()
print("半开:", client.gripper_state["gripper_qpos"])

# 完全闭合
client.send_gripper(1.0)
time.sleep(0.5)
client.recv_state()
print("闭合:", client.gripper_state["gripper_qpos"])

# 抓取示例：张开 → 下降到物体高度 → 闭合 → 抬起
client.send_gripper(-1.0)
time.sleep(0.3)
for _ in range(40):
    client.send_delta_ee_pose([0, 0, -0.02, 0, 0, 0])
    time.sleep(0.05)
client.send_gripper(1.0)
time.sleep(0.3)
for _ in range(40):
    client.send_delta_ee_pose([0, 0, 0.02, 0, 0, 0])
    time.sleep(0.05)
client.send_delta_ee_pose([0, 0, 0, 0, 0, 0])
```

### 5.5 底座移动

底座运动时机械臂自动切换为世界系跟踪模式，随底座一起移动。

```python
import time

# 前进
for _ in range(40):
    client.send_base([0.3, 0.0, 0.0])
    time.sleep(0.05)

# 原地逆时针旋转
for _ in range(40):
    client.send_base([0.0, 0.0, 0.3])
    time.sleep(0.05)

# ⚠️ 必须显式归零
client.send_base([0.0, 0.0, 0.0])
```

### 5.6 躯干升降

```python
# 升到最高
client.send_torso(1.0)
time.sleep(1.0)
client.recv_state()
print("躯干高度:", client.torso_state["torso_height"])

# 降到最低
client.send_torso(-1.0)
time.sleep(1.0)
client.recv_state()
print("躯干高度:", client.torso_state["torso_height"])
```

### 5.7 读取相机图像

```python
import numpy as np

# 等待相机图像到达
deadline = time.monotonic() + 5.0
while time.monotonic() < deadline:
    client.recv_state()
    if client.camera_rgb("agentview_center") is not None:
        break
    time.sleep(0.05)

# RGB 图像
rgb = client.camera_rgb("agentview_center")
print(f"RGB: shape={rgb.shape}, dtype={rgb.dtype}, range=[{rgb.min()}, {rgb.max()}]")
# RGB: shape=(256, 256, 3), dtype=uint8, range=[0, 255]

# 深度图
depth = client.camera_depth("agentview_center")
print(f"Depth: shape={depth.shape}, dtype={depth.dtype}")
# Depth: shape=(256, 256), dtype=float32

# 相机内参
info = client.camera_info("agentview_center")
if info:
    K = np.array(info["intrinsics"])          # 3×3 内参矩阵
    print(f"焦距 fx={K[0,0]:.0f} px")
    print(f"光心 ({K[0,2]:.0f}, {K[1,2]:.0f})")
    print(f"视场角 fovy={info['fovy']:.1f}°")
    print(f"分辨率 {info['width']}×{info['height']}")

# 点云计算（内参 + 深度图 → 相机系 3D 坐标）
fx, fy = K[0, 0], K[1, 1]
cx, cy = K[0, 2], K[1, 2]
v, u = np.mgrid[0:depth.shape[0], 0:depth.shape[1]]
z = depth
x = (u - cx) * z / fx
y = (v - cy) * z / fy
points_camera = np.stack([x, y, z], axis=-1)  # (H, W, 3)

# 显示图像（需要 opencv-python）
try:
    import cv2
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.imshow("agentview_center", bgr)
    cv2.waitKey(1)
except ImportError:
    print("安装 opencv-python 后可显示图像窗口")
```

### 5.8 IK 逆运动学求解

将世界坐标系下的目标末端位姿转为关节角度。

```python
# 基于当前末端位置，向右偏移 5cm 作为目标
client.recv_state()
arm = client.arm_state
target_pos = np.array(arm["eef_pos"]) + np.array([0.05, 0.0, 0.0])
target_quat = arm["eef_quat"]    # 保持当前姿态

result = client.solve_ik(target_pos=target_pos, target_quat=target_quat)
print(result)
# {'status': 'ok', 'joint_angles': [0.12, -0.45, 1.23, -2.10, 0.56, 0.34, 0.78]}

if result["status"] == "ok":
    print("目标关节角度:", [f"{j:.3f}" for j in result["joint_angles"]])

# 不可达目标会返回失败
result = client.solve_ik(
    target_pos=[100.0, 0.0, 0.0],          # 太远，不可达
    target_quat=[1.0, 0.0, 0.0, 0.0],
)
print(result)
# {'status': 'unreachable', 'message': '...'}
```

### 5.9 场景重置

```python
# 重置当前场景（不换布局）：回到初始状态
result = client.reset()
print(result)   # {'status': 'ok'}

# 切换到指定布局和风格
result = client.reset(layout_id=11, style_id=14)
print(result)   # {'status': 'ok'}

# 不传参 = 不换布局，仅重置物体和机器人到初始位姿
result = client.reset(layout_id=None, style_id=None)
print(result)   # {'status': 'ok'}
```

### 5.10 完整交互循环示例

```python
# 用键盘实时控制机械臂
import sys, select, termios, tty

def get_key():
    """读取单个按键（非阻塞）"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if select.select([sys.stdin], [], [], 0.01)[0]:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

step = 0.03
print("键盘控制: w/s 前后  a/d 左右  q/e 上下  i/k 夹爪开/合  x 停止  Esc 退出")

try:
    while True:
        client.recv_state()
        key = get_key()

        if key == '\x1b':    # Esc
            break
        elif key == 'w':
            client.send_delta_ee_pose([ step, 0, 0, 0, 0, 0])
        elif key == 's':
            client.send_delta_ee_pose([-step, 0, 0, 0, 0, 0])
        elif key == 'a':
            client.send_delta_ee_pose([0, -step, 0, 0, 0, 0])
        elif key == 'd':
            client.send_delta_ee_pose([0,  step, 0, 0, 0, 0])
        elif key == 'q':
            client.send_delta_ee_pose([0, 0,  step, 0, 0, 0])
        elif key == 'e':
            client.send_delta_ee_pose([0, 0, -step, 0, 0, 0])
        elif key == 'i':
            client.send_gripper(-1.0)       # 张开
        elif key == 'k':
            client.send_gripper(1.0)        # 闭合
        elif key == 'x':
            client.send_delta_ee_pose([0, 0, 0, 0, 0, 0])
            client.send_base([0, 0, 0])

        time.sleep(0.02)
finally:
    # 停止所有运动
    client.send_delta_ee_pose([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    client.send_base([0.0, 0.0, 0.0])
    client.close()
```

---

## 六、命令行启动

```bash
python -m robocasa.server \
    --task DefrostByCategory \
    --layout 11 \
    --style 14 \
    --pub-port 5555 \
    --ctrl-port 5556 \
    --srv-port 5557 \
    --cam-width 256 \
    --cam-height 256 \
    --control-freq 20 \
    --no-viewer        # 无头模式（不启动渲染窗口）
```
