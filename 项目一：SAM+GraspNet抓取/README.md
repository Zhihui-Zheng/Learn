# 项目一：SAM + GraspNet 抓取

基于 RoboCasa 环境的 SAM 分割与 GraspNet 抓取演示项目。

## 项目结构

- `project1/robocasa/` — 主项目代码（RoboCasa + MyDemo）
- `assets/` — 场景与模型资源文件

## 环境配置

详见 `project1/robocasa/INSTALL_ROBOCASA.md`。

## 大文件说明

以下文件因体积过大未上传至 GitHub，需自行准备：

| 文件 | 说明 |
|------|------|
| `project1.zip` | 完整项目压缩包（约 1.3 GB） |
| `project1/robocasa/robocasa/MyDemo/sam_b.pt` | SAM 模型权重（约 358 MB） |

SAM 权重可从 [Segment Anything Model](https://github.com/facebookresearch/segment-anything) 官方渠道下载。

## 快速开始

```bash
conda activate robocasa
cd project1/robocasa
pip install -e .
jupyter notebook robocasa/MyDemo/text_to_grasp.ipynb
```
