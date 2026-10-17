"""用 Python + PIL 写代码画图，主要用来画条漫的版式草图。

代码在 WebAssembly 沙箱里运行（src/tools/pil_sandbox.py）。画好的图附在下一次请求里给模型看，
模型看了不满意就改代码重画；代码存在图片旁边的同名 .py 里，之后也能读出来接着改。
"""

from __future__ import annotations

from pathlib import Path

from src.tools import pil_sandbox

from .base import Tool, ToolContext, integer, obj, register, string

DEFAULT_SIZE = (900, 1600)  # 9:16，和条漫同比例


def draw_with_pil(args: dict, ctx: ToolContext) -> dict:
    out = Path(args["output_path"]).with_suffix(".png")
    if ctx.project_dir and not out.resolve().is_relative_to(ctx.project_dir.resolve()):
        return {"error": f"output_path 要在项目目录里: {args['output_path']}"}
    width = int(args.get("width") or DEFAULT_SIZE[0])
    height = int(args.get("height") or DEFAULT_SIZE[1])
    try:
        result = pil_sandbox.run(args["code"], width, height)
    except pil_sandbox.SandboxUnavailable as exc:
        return {"error": str(exc)}
    if not result.ok:
        failed = {"error": f"代码运行出错：\n{result.error}"}
        if result.stdout:
            failed["stdout"] = result.stdout
        return failed

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.png or b"")
    code_path = out.with_suffix(".py")
    code_path.write_text(args["code"], encoding="utf-8")
    done = {
        "output_path": str(out),
        "code_path": str(code_path),
        "size": list(result.size or (width, height)),
        "message": "画好了，图片附在后面。看一下有没有要改的；要改就改代码，用同一个 output_path 再调用一次。",
    }
    if result.stdout:
        done["stdout"] = result.stdout
    return done


register(
    Tool(
        name="draw_with_pil",
        description=(
            "用 Python + PIL 写代码画图，主要用来画条漫的版式草图（每一格的形状和位置）。"
            "代码在隔离的 WebAssembly 沙箱里运行：不能读写文件、不能联网，只能画图。"
            "已经准备好的变量：img（白底 RGB 画布，W×H）、draw（img 上的 ImageDraw）、W、H、Image、ImageDraw、ImageFont、math；"
            "字体用 ImageFont.load_default(size=N)（只有英文字母和数字）。代码结束时的 img 就是结果。"
            "PNG 存到 output_path，代码存到同名 .py；画好的图会附在工具结果后面给你看，"
            "不满意就改代码，用同一个 output_path 重新调用。"
        ),
        parameters=obj(
            {
                "code": string("Python 代码，在 img / draw 上作画"),
                "output_path": string("输出 PNG 路径。版式草图放 output/layouts/，如 output/layouts/strip_1.png"),
                "width": integer(f"画布宽度，默认 {DEFAULT_SIZE[0]}"),
                "height": integer(f"画布高度，默认 {DEFAULT_SIZE[1]}（9:16，和条漫同比例）"),
            },
            ["code", "output_path"],
        ),
        run=draw_with_pil,
        kind="write",
        model_sees_output=True,
    ),
)
