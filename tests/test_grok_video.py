"""测试视频生成：纯 prompt 生成视频（使用「设置」中配置的视频模型，旧版默认是 Grok Video 3）。"""

from pathlib import Path

from src.providers.video import generate_video


def test_generate_video():
    output_dir = Path(__file__).parent / "test_grok_video_output"
    output_dir.mkdir(exist_ok=True)
    video = generate_video(
        prompt="A cute anime girl walking through a cherry blossom garden in spring, gentle breeze, petals falling, anime style, soft lighting",
        aspect_ratio="16:9",
        output_dir=output_dir,
    )
    assert video.exists(), "未找到生成的视频文件"
    print(f"生成的视频: {video} ({video.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    test_generate_video()
