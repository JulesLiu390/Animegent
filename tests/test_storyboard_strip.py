"""测试：用 generate_comic_strip 的方式生成分镜条，然后切割成 16:9 帧。

生成一个 4 格无台词分镜条（纯画面，无气泡无边框），然后均分裁成 4 张 16:9 帧。
使用「设置」中配置的图片生成模型。

运行: uv run python tests/test_storyboard_strip.py
"""

from pathlib import Path

from PIL import Image

from src.providers import image as image_provider

PROJECT = Path("projects/jojo test")
CHARACTERS = [
    PROJECT / "output/stylized/jojo_nobita.png",
    PROJECT / "output/stylized/jojo_shizuka_v4_correct.png",
]
OUTPUT_DIR = Path("tests/test_storyboard_strip_output")


def generate_storyboard_strip() -> Path:
    """生成 4 格无台词分镜条。"""
    labels = [f"Image {i + 1}: Character reference" for i in range(len(CHARACTERS))]

    prompt = (
        f"{chr(10).join(labels)}\n\n"
        "Generate a vertical storyboard strip with EXACTLY 4 panels stacked vertically.\n\n"
        "Storyboard for an anime scene — two characters confront each other on a street at sunset:\n"
        "Panel 1: Wide establishing shot — a Japanese street at sunset, character 1 walks toward camera from far away.\n"
        "Panel 2: Medium shot — character 2 stands with arms crossed, smirking, viewed from a low angle.\n"
        "Panel 3: Close-up — character 1 adjusts his glasses, intense expression, dramatic lighting.\n"
        "Panel 4: Wide shot — both characters face each other in the middle of the street, tension.\n\n"
        "STRICT RULES:\n"
        "1. EXACTLY 4 panels, stacked vertically, 9:16 aspect ratio total.\n"
        "2. NO dialogue bubbles, NO text, NO sound effects, NO speech — PURE VISUALS ONLY.\n"
        "3. NO borders, NO margins, NO white edges, NO gaps between panels.\n"
        "   Each panel's artwork must extend to the VERY EDGE of the image, filling 100% of the area.\n"
        "   Panels touch each other directly — the bottom edge of panel 1 is the top edge of panel 2.\n"
        "4. Each panel must have a DIFFERENT camera angle and composition.\n"
        "5. Characters MUST match the reference images exactly.\n"
        "6. Anime/animation art style, cinematic, high quality.\n"
        "7. This is a storyboard/keyframe sheet — focus on clear staging, lighting, and composition.\n"
    )

    result = image_provider.generate(prompt, CHARACTERS, aspect_ratio="9:16")
    return image_provider.save(result, OUTPUT_DIR / "storyboard_strip.png")


def split_to_frames(strip_path: Path, num_panels: int = 4) -> list[Path]:
    """均分切割 + 左右裁到 16:9。"""
    img = Image.open(strip_path)
    w, h = img.size
    panel_h = h // num_panels

    results = []
    for i in range(num_panels):
        top = i * panel_h
        bottom = top + panel_h

        # 左右居中裁到 16:9
        target_w = int(panel_h * 16 / 9)
        if target_w > w:
            target_w = w
        left = (w - target_w) // 2
        right = left + target_w

        panel = img.crop((left, top, right, bottom))
        out_path = OUTPUT_DIR / f"clip_{i + 1}.png"
        panel.save(out_path)
        results.append(out_path)

    return results


def refine_frame(
    frame_path: Path,
    output_path: Path,
) -> Path:
    """放大分镜帧分辨率，只传原图 + 放大指令，不传任何额外素材。"""
    result = image_provider.generate(
        "Upscale this image to higher resolution. Keep everything exactly the same. Do not add, remove, or change anything.",
        [frame_path],
        aspect_ratio="16:9",
    )
    image_provider.save(result, output_path)

    # 裁到精确 16:9
    img = Image.open(output_path)
    w, h = img.size
    target_ratio = 16 / 9
    current_ratio = w / h
    if abs(current_ratio - target_ratio) > 0.01:
        if current_ratio > target_ratio:
            # 太宽，裁左右
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            # 太高，裁上下
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        img.save(output_path)

    return output_path


# 每个 clip 的细化 prompt（描述角色外观 + 画面细节）
REFINE_PROMPTS = [
    (
        "Panel 1 — Wide establishing shot.\n"
        "Character 1 (muscular man in yellow polo shirt, blue shorts, round glasses, JOJO style) "
        "walks toward camera from far away on a Japanese street at sunset. "
        "Dramatic long shadows, warm orange lighting."
    ),
    (
        "Panel 2 — Low angle medium shot.\n"
        "Character 2 (girl in pink dress with twin tails, JOJO style, confident smirk) "
        "stands with arms crossed, viewed from below. "
        "She looks powerful and intimidating against the sunset sky."
    ),
    (
        "Panel 3 — Extreme close-up.\n"
        "Character 1 (muscular man, yellow polo shirt, round glasses) adjusts his glasses with one hand. "
        "Intense determined expression, light reflecting off the glasses. "
        "Dramatic shadows on his face."
    ),
    (
        "Panel 4 — Wide shot, both characters.\n"
        "Character 1 (yellow polo shirt, round glasses, muscular) on the left, "
        "Character 2 (pink dress, twin tails) on the right. "
        "They face each other in the middle of the street. Tension. Sunset behind them."
    ),
]


if __name__ == "__main__":
    for cp in CHARACTERS:
        if not cp.exists():
            print(f"跳过: {cp} 不存在")
            exit(0)

    print("1. 生成分镜条（4格，无台词无边框）...")
    strip = generate_storyboard_strip()
    img = Image.open(strip)
    print(f"   → {strip} ({img.size[0]}x{img.size[1]})")

    print("2. 切割成 16:9 帧...")
    frames = split_to_frames(strip)
    for f in frames:
        fi = Image.open(f)
        ratio = fi.size[0] / fi.size[1]
        print(f"   → {f.name}: {fi.size[0]}x{fi.size[1]} (ratio={ratio:.2f})")

    print("3. 放大每帧...")
    for i, frame in enumerate(frames):
        out = OUTPUT_DIR / f"clip_{i + 1}_refined.png"
        result = refine_frame(frame, out)
        ri = Image.open(result)
        print(f"   → {result.name}: {ri.size[0]}x{ri.size[1]}")

    print(f"---\n输出: {OUTPUT_DIR}/")
