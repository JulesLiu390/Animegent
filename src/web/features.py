"""功能开关：休眠的功能代码都保留，只是默认不开放，需要时用环境变量打开。"""

import os


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# 分镜模式（分镜脚本 → 首帧 → 视频片段 → 合并成片）暂时休眠：
# 关闭时 Agent 一律按条漫模式运行（模型拿不到分镜 / 视频工具），前端也不显示分镜和视频的入口。
# 打开：ANIMEGENT_STORYBOARD=1 ./run.sh
STORYBOARD = _env_flag("ANIMEGENT_STORYBOARD")


def public() -> dict:
    """告诉前端哪些功能是开放的。"""
    return {"storyboard": STORYBOARD}
