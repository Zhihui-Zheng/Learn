# RoboCasa 安装说明

> **环境名称**: `robocasa` (conda 环境)
> **Python 版本**: 3.11
> **适用系统**: Ubuntu 20.04+ / macOS
> **最后更新**: 2026-05-31

---

## 1. 创建并激活 Conda 环境

```bash
conda create -c conda-forge -n robocasa python=3.11 -y
conda activate robocasa
```

---

## 2. 安装 robosuite 依赖（必须使用 master 分支）

```bash
cd ~
git clone https://github.com/ARISE-Initiative/robosuite
cd robosuite
pip install -e .
```

> **⚠️ 注意**：必须从 GitHub master 分支安装 robosuite，**不要**通过 PyPI (`pip install robosuite`) 安装，否则会出现兼容性问题。

---

## 3. 安装 RoboCasa

```bash
cd ~
git clone https://github.com/robocasa/robocasa
cd robocasa
pip install -e .
```

### 可选：设置代码格式化

```bash
pip install pre-commit
pre-commit install
```

### 可选：修复 numba/numpy 兼容性问题

如果在运行过程中遇到 numba 或 numpy 相关错误，执行：

```bash
conda install -c numba numba=0.56.4 -y
```

---

## 4. 下载资源文件

> **⚠️ 注意**：下载的资源文件约 **10GB**，请确保网络畅通且磁盘空间充足。

```bash
# 设置系统宏变量
python -m robocasa.scripts.setup_macros

# 下载厨房场景资源（约 10GB）
python -m robocasa.scripts.download_kitchen_assets
```

---

## 5. 验证安装

### 5.1 探索厨房场景

```bash
python -m robocasa.demos.demo_kitchen_scenes
```

### 5.2 查看任务演示

```bash
python -m robocasa.demos.demo_tasks
```

### 5.3 查看物体库

```bash
python -m robocasa.demos.demo_objects
```

### 5.4 测试遥操作

```bash
python -m robocasa.demos.demo_teleop
```

---

## 6. 快速测试代码

```python
import gymnasium as gym
import robocasa
from robocasa.utils.env_utils import run_random_rollouts

env = gym.make(
    "robocasa/PickPlaceCounterToCabinet",
    split="pretrain",
    seed=0
)

run_random_rollouts(
    env, num_rollouts=3, num_steps=100, video_path="/tmp/test.mp4"
)
```

---

## 7. 常见问题

### Q1: X Server / DISPLAY 错误

**错误信息**：
```
ImportError: this platform is not supported: ('failed to acquire X connection...')
```

**解决方法**（无头服务器）：
```bash
xvfb-run python -m robocasa.demos.demo_kitchen_scenes
```

### Q2: macOS 用户

在 macOS 上运行 demo 脚本时，需要在 `python` 前加 `mj` 前缀：
```bash
mjpython -m robocasa.demos.demo_tasks
```

### Q3: SpaceMouse 遥控器

如果使用 SpaceMouse，可能需要修改 `robocasa/macros_private.py` 中的 `SPACEMOUSE_PRODUCT_ID` 变量以匹配你的设备型号。

---

## 8. 主要依赖列表

| 依赖 | 版本 |
|------|------|
| Python | 3.11 |
| numpy | 2.2.5 |
| numba | 0.61.2 |
| scipy | 1.15.3 |
| mujoco | 3.3.1 |
| pygame | latest |
| opencv-python | latest |
| gymnasium | latest |
| tianshou | 0.4.10 |
| lerobot | 0.3.3 |

---

## 参考资料

- [RoboCasa 官方文档](https://robocasa.ai/docs/introduction/overview.html)
- [RoboCasa GitHub](https://github.com/robocasa/robocasa)
- [robosuite GitHub](https://github.com/ARISE-Initiative/robosuite)
