"""分镜模式（目前休眠，见 src/web/features.py）：分镜脚本 → 四格首帧 → 视频片段 → 合并成片。"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageFilter

from src.providers import image as image_provider

from .base import Tool, ToolContext, array, integer, obj, register, string

logger = logging.getLogger(__name__)

STORYBOARD = frozenset({"storyboard"})


def generate_storyboard_strip(args: dict, ctx: ToolContext) -> dict:
    char_paths = args.get("character_paths") or []
    panel_descs = args.get("panel_descriptions") or []
    strip_index = int(args.get("strip_index", 1))
    out_dir = Path(args.get("output_dir") or "output/storyboards/frames")
    out_dir.mkdir(parents=True, exist_ok=True)
    num_panels = len(panel_descs)
    if num_panels == 0:
        return {"error": "panel_descriptions 不能为空"}
    for cp in char_paths:
        if not Path(cp).exists():
            return {"error": f"角色图不存在: {cp}"}

    labels = "\n".join(f"Image {i + 1}: Character reference" for i in range(len(char_paths)))
    panel_text = "\n".join(f"Panel {i + 1}: {desc}" for i, desc in enumerate(panel_descs))
    prompt = (
        f"{labels}\n\n"
        f"Generate a vertical storyboard strip with EXACTLY {num_panels} panels stacked vertically.\n\n"
        f"{panel_text}\n\n"
        f"STRICT RULES:\n"
        f"1. EXACTLY {num_panels} panels, stacked vertically, 9:16 aspect ratio total.\n"
        f"2. NO dialogue bubbles, NO text, NO sound effects — PURE VISUALS ONLY.\n"
        f"3. NO borders, NO margins, NO white edges, NO gaps between panels.\n"
        f"   Panels touch each other directly, artwork fills 100% of the area.\n"
        f"4. Each panel MUST have a DIFFERENT camera angle and composition.\n"
        f"5. Characters MUST match the reference images exactly.\n"
        f"6. Anime/animation art style, cinematic, high quality.\n"
    )

    # 1. 生成整条
    image = image_provider.generate(prompt, char_paths, aspect_ratio="9:16")
    strip_path = image_provider.save(image, out_dir.parent / "strips" / f"strip_{strip_index}.png")

    # 2. 均分切成每格一帧
    img = PILImage.open(strip_path)
    w, h = img.size
    panel_h = h // num_panels
    raw_frames: list[Path] = []
    for i in range(num_panels):
        top = i * panel_h
        target_w = min(int(panel_h * 16 / 9), w)
        left = (w - target_w) // 2
        frame_path = out_dir / f"clip_{(strip_index - 1) * 4 + i + 1}_raw.png"
        img.crop((left, top, left + target_w, top + panel_h)).save(frame_path)
        raw_frames.append(frame_path)

    # 3. 本地放大（LANCZOS + 锐化）并裁到精确的 16:9
    target_h = 768
    output_frames: list[str] = []
    for raw in raw_frames:
        frame = PILImage.open(raw)
        fw, fh = frame.size
        new_w = int(fw * target_h / fh)
        frame = frame.resize((new_w, target_h), PILImage.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        target_w = int(target_h * 16 / 9)
        if new_w >= target_w:
            left = (new_w - target_w) // 2
            frame = frame.crop((left, 0, left + target_w, target_h))
        final_path = raw.parent / raw.name.replace("_raw.png", ".png")
        frame.save(final_path, quality=95)
        output_frames.append(str(final_path))
        raw.unlink(missing_ok=True)

    return {"strip_path": str(strip_path), "frames": output_frames, "count": len(output_frames), "strip_index": strip_index}


def generate_video_clip(args: dict, ctx: ToolContext) -> dict:
    from src.providers.video import generate_video

    clip_index = int(args.get("clip_index", 1))
    project_dir = ctx.project_dir
    video_dir = project_dir / "output" / "videos" if project_dir else Path("output/videos")
    video_dir.mkdir(parents=True, exist_ok=True)

    # 自动读取 clip_N.md 作为 prompt，首帧用 frames/clip_N.png
    prompt = ""
    first_frame = ""
    if project_dir:
        clip_md = project_dir / "output" / "storyboards" / "clip_scripts" / f"clip_{clip_index}.md"
        if not clip_md.exists():
            return {"error": f"clip 脚本不存在: clip_{clip_index}.md"}
        prompt = clip_md.read_text(encoding="utf-8").strip()
        logger.info(f"Video prompt from clip_{clip_index}.md: {prompt[:100]}")
        first_frame = str(project_dir / "output" / "storyboards" / "frames" / f"clip_{clip_index}.png")
        if not Path(first_frame).exists():
            return {"error": f"首帧不存在: clip_{clip_index}.png"}

    video_path = generate_video(
        prompt=prompt,
        images=[first_frame] if first_frame else None,
        aspect_ratio=args.get("aspect_ratio", "16:9"),
        output_dir=video_dir,
    )
    renamed = video_dir / f"clip_{clip_index}{video_path.suffix}"
    if renamed.exists() and renamed != video_path:
        renamed.unlink()
    video_path.rename(renamed)
    return {"output_path": str(renamed), "first_frame": first_frame, "clip_index": clip_index}


def merge_video_clips(args: dict, ctx: ToolContext) -> dict:
    clip_paths = args.get("clip_paths") or []
    output_path = Path(args.get("output_path", ""))
    if not clip_paths:
        return {"error": "clip_paths 不能为空"}
    for cp in clip_paths:
        if not Path(cp).exists():
            return {"error": f"视频文件不存在: {cp}"}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg concat demuxer
    list_file = output_path.parent / f"_concat_{output_path.stem}.txt"
    list_file.write_text(
        "".join("file '{}'\n".format(str(Path(cp).resolve()).replace("'", "'\\''")) for cp in clip_paths)
    )
    try:
        concat = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
        result = subprocess.run([*concat, "-c", "copy", str(output_path)], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:  # 直接拼接失败时重新编码
            result = subprocess.run([*concat, "-c:v", "libx264", "-c:a", "aac", str(output_path)], capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"error": f"ffmpeg 合并失败: {result.stderr[:500]}"}
        # 第一帧作为封面
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(output_path), "-frames:v", "1", "-q:v", "2", str(output_path.with_suffix(".png"))],
            capture_output=True, timeout=30,
        )
    except FileNotFoundError:
        return {"error": "ffmpeg 未安装，请先安装 ffmpeg"}
    finally:
        list_file.unlink(missing_ok=True)
    return {"output_path": str(output_path), "clip_count": len(clip_paths)}


def write_storyboard(args: dict, ctx: ToolContext) -> dict:
    p = Path(args["file_path"])
    try:
        json.loads(args["content"])
    except json.JSONDecodeError as e:
        return {"error": f"JSON 格式错误: {e}"}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"], encoding="utf-8")
    return {"message": "分镜脚本写入成功", "file_path": str(p)}


def read_storyboard(args: dict, ctx: ToolContext) -> dict:
    p = Path(args["file_path"])
    if not p.exists():
        return {"error": f"文件不存在: {args['file_path']}"}
    try:
        return {"file_path": str(p), "content": json.loads(p.read_text(encoding="utf-8"))}
    except json.JSONDecodeError as e:
        return {"error": f"JSON 解析失败: {e}"}


register(
    Tool(
        name="generate_storyboard_strip",
        description=(
            "【Step 2】生成 4 格分镜条漫并自动切割为 4 张 16:9 首帧。\n"
            "传入角色素材图 + 每格的画面描述（4 个），内部自动：\n"
            "1. 生成 9:16 四格无台词条漫（角色参考图保证一致性）\n"
            "2. 均分切割成 4 张帧\n"
            "3. 逐帧放大分辨率\n"
            "4. 裁切到精确 16:9\n"
            "输出 4 张首帧到指定目录。"
        ),
        parameters=obj(
            {
                "character_paths": array(string("角色图片路径"), "角色素材图片路径列表（stylized 目录下）"),
                "panel_descriptions": array(string("画面描述"), "4 个格子的画面描述（每格对应一个 clip 的首帧画面）"),
                "strip_index": integer("条漫编号（第几条，从1开始）"),
                "output_dir": string("输出目录路径（如 output/storyboards/frames）"),
            },
            ["character_paths", "panel_descriptions", "strip_index", "output_dir"],
        ),
        run=generate_storyboard_strip,
        kind="generate",
        modes=STORYBOARD,
    ),
    Tool(
        name="generate_video_clip",
        description=(
            "【Step 4】基于 clip_index 生成 6 秒 16:9 视频。\n"
            "自动从 clip_scripts/clip_N.md 读取完整视频脚本作为 prompt，\n"
            "自动从 storyboards/frames/clip_N.png 读取首帧。\n"
            "只需传 clip_index 即可。"
        ),
        parameters=obj({"clip_index": integer("片段编号（从1开始）")}, ["clip_index"]),
        run=generate_video_clip,
        kind="generate",
        modes=STORYBOARD,
        role="video",
    ),
    Tool(
        name="merge_video_clips",
        description="【Step 5】将多个视频 clip 按顺序合并为一个完整视频。单独的 clip 文件保留不删除。",
        parameters=obj(
            {
                "clip_paths": array(string("视频路径"), "视频 clip 文件路径列表，按播放顺序排列"),
                "output_path": string("合并后的输出视频路径"),
            },
            ["clip_paths", "output_path"],
        ),
        run=merge_video_clips,
        kind="write",
        modes=STORYBOARD,
    ),
    Tool(
        name="write_storyboard",
        description="写入分镜脚本 JSON 文件到 output/storyboards/ 目录。内容为标准分镜 JSON 格式（含 clips/shots 结构）。",
        parameters=obj(
            {"file_path": string("JSON 文件路径（如 output/storyboards/xxx.json）"), "content": string("完整的 JSON 字符串")},
            ["file_path", "content"],
        ),
        run=write_storyboard,
        kind="write",
        modes=STORYBOARD,
    ),
    Tool(
        name="read_storyboard",
        description="读取分镜脚本 JSON 文件。",
        parameters=obj({"file_path": string("JSON 文件路径")}, ["file_path"]),
        run=read_storyboard,
        kind="read",
        modes=STORYBOARD,
    ),
)
