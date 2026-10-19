"""条漫模式：按分镜草稿（或剧本）和角色参考图生成一条竖向条漫。"""

from __future__ import annotations

from pathlib import Path

from src.providers import image as image_provider

from . import drafts
from .base import Tool, ToolContext, array, integer, obj, register, resolve_path, string


def _from_draft(args: dict, ctx: ToolContext) -> dict:
    """分镜草稿 → 画面指令、总剧本的画面总则和服装表、版式草图（参数没传 layout_path 时用草稿记录的）。"""
    path = Path(args["draft_path"])
    if not path.is_file():
        return {"error": f"分镜草稿不存在: {args['draft_path']}"}
    draft = path.read_text(encoding="utf-8")
    directions = drafts.section(draft, drafts.DIRECTIONS)
    if not directions:
        return {"error": "分镜草稿里没有「画面指令」一节"}
    meta = drafts.draft_meta(draft)
    rules = ""
    costumes = drafts.Costumes()
    script = Path(resolve_path(meta["script"], ctx.project_dir)) if meta.get("script") else None
    if script and script.is_file():
        script_text = script.read_text(encoding="utf-8")
        rules = drafts.section(script_text, drafts.VISUAL_RULES) or ""
        costumes = drafts.costumes(script_text)
    # 总剧本还没有画面总则时退而附上项目的风格设定，画风总要交代给生图模型
    source = "the visual rules of the master script" if rules else "the project's style guide"
    rules = rules or drafts.style_text(ctx.project_dir, ctx.lang)
    layout = args.get("layout_path") or ""
    if not layout and meta.get("layout") and Path(resolve_path(meta["layout"], ctx.project_dir)).is_file():
        layout = resolve_path(meta["layout"], ctx.project_dir)
    return {"directions": directions, "rules": rules, "rules_source": source, "layout": layout, "panels": drafts.panel_count(directions),
            "costumes": costumes, "index": drafts.draft_index(draft, path) or int(args.get("strip_index", 0) or 0) or None}


def generate_comic_strip(args: dict, ctx: ToolContext) -> dict:
    char_paths = args["character_paths"]
    char_names = args.get("character_names") or []
    strip_index = int(args.get("strip_index", 1))
    draft: dict | None = None
    if args.get("draft_path"):
        draft = _from_draft(args, ctx)
        if draft.get("error"):
            return draft
    elif not args.get("script"):
        return {"error": "要传 draft_path（分镜草稿），或者传 script（这一条的剧本）"}

    # 服装表：每张角色图旁边写上这个人这一时期穿什么，这一条的换装另列
    worn, changes = draft["costumes"].for_strip(draft["index"], char_names) if draft else ({}, [])
    references: list[str] = []
    char_labels = []
    for i, cp in enumerate(char_paths):
        if not Path(cp).exists():
            return {"error": f"角色图不存在: {cp}"}
        references.append(cp)
        name_label = char_names[i] if i < len(char_names) else chr(ord("A") + i)
        clothes = f", wearing: {worn[name_label]}" if name_label in worn else ""
        char_labels.append(f"Image {i + 1}: Character {name_label}{clothes}")

    scene_label = ""
    if args.get("scene_path"):
        if not Path(args["scene_path"]).exists():
            return {"error": f"场景图不存在: {args['scene_path']}"}
        references.append(args["scene_path"])
        scene_label = f"Image {len(references)}: Scene/Background\n"

    # 版式草图（draw_with_pil / draft_strip 画的）放在最后一张参考图：按草图的格子形状和位置画
    layout_path = draft["layout"] if draft else args.get("layout_path") or ""
    layout_label = layout_rules = ""
    if layout_path:
        if not Path(layout_path).exists():
            return {"error": f"版式草图不存在: {layout_path}"}
        references.append(layout_path)
        n = len(references)
        layout_label = f"Image {n}: PANEL LAYOUT SKETCH (a blank page showing only the panel borders)\n"
        layout_rules = (
            f"PANEL LAYOUT: follow Image {n} exactly.\n"
            f"- Keep every panel's shape, size and position the same as in Image {n} (slanted borders, trapezoids, "
            f"circles, rounded corners, borderless areas) and keep the white gutters between panels.\n"
            f"- The gray numbers show the reading order: panel k shows beat k of the script. Do NOT draw the numbers.\n"
            f"- Gray dashed outlines with a number mark panels without a border (frameless, or bleeding to the page edge): "
            f"draw them without a frame; do not draw the dashed lines.\n"
            f"- A smaller panel drawn on top of a larger panel is an inset panel: draw it over the larger panel, "
            f"separated by a thin white margin.\n"
            f"- A gray dashed outline with a capital letter (A, B…) marks a character or object drawn WITHOUT a frame on top of "
            f"the panels, as the directions describe for that letter: it crosses the panel borders and gutters, and the borders "
            f"stop where it covers them. Do not draw the letter or the outline.\n\n"
        )

    newline = "\n"
    language = "English" if ctx.lang == "en" else "Chinese"
    labels = f"{newline.join(char_labels)}\n{scene_label}{layout_label}\n"
    borders = "Black panel borders exactly where the layout sketch has them" if layout_rules else "Black panel borders separating each panel"
    if draft:
        count = draft["panels"]
        panels = f"following the panel layout in Image {len(references)}" if layout_rules else f"with {count or '4-6'} panels"
        rules = (f"ART STYLE AND GLOBAL RULES (from {draft['rules_source']}, the same for every strip):\n{draft['rules']}\n\n"
                 if draft["rules"] else "")
        if worn:
            costume_rule = (
                "1. The characters in the reference images must look exactly like their references (face, hair, body) and wear "
                "the clothes written next to their image, in every panel"
                + (", except where a costume change below says otherwise" if changes else "")
                + ". Keep each garment's color the same from panel to panel: light may tint it, but its own color stays recognizable.\n"
            )
        else:
            costume_rule = (
                "1. The characters in the reference images must look exactly like their references (face, hair, body, clothes) "
                "unless a panel direction says otherwise.\n"
            )
        change_block = ("COSTUME CHANGES IN THIS STRIP (only these):\n" + "".join(f"- {c}\n" for c in changes) + "\n") if changes else ""
        prompt = (
            f"{labels}"
            f"Draw strip #{strip_index} of a vertical comic (条漫) as one image, {panels}.\n\n"
            f"{rules}"
            f"PANEL DIRECTIONS (panel k is the panel numbered k in the layout; draw what each panel describes: "
            f"who is in it, camera, composition, acting, background and light, and the exact text):\n\n"
            f"{draft['directions']}\n\n"
            f"CHARACTERS:\n"
            f"{costume_rule}"
            f"2. Each panel shows only the people its direction lists. Do not add reference characters to panels that don't list them.\n"
            f"3. Background people (passers-by, other children, crowds) appear only where the directions ask for them, "
            f"and must look clearly different from every reference character: different clothes, hairstyle and colors.\n\n"
            f"{change_block}"
            f"{layout_rules}"
            f"TEXT:\n"
            f"- Letter the dialogue, narration and sound effects exactly as written in the directions, in {language}, "
            f"using the balloon or box type and the position the directions give.\n"
            f"- Use one lettering style and size across the whole strip, and keep text away from the page edges.\n"
            f"- Do not add any other text: no captions, titles, panel numbers or labels.\n\n"
            f"FORMAT:\n"
            f"- Vertical layout, 9:16 aspect ratio\n"
            f"- {borders}\n\n"
            f"Output a single vertical comic strip image."
        )
    else:
        panels = f"following the panel layout in Image {len(references)}" if layout_rules else "with 4-6 panels"
        prompt = (
            f"{labels}"
            f"Generate a vertical comic strip (条漫) {panels}.\n"
            f"This is strip #{strip_index}. Script for this strip:\n\n"
            f"{args['script']}\n\n"
            f"STRICT RULES:\n"
            f"1. The named characters are the ones shown above; do not invent other main characters. "
            f"Background people (passers-by, crowds) only where the script asks for them, and they must look clearly "
            f"different from every reference character (different clothes, hairstyle and colors).\n"
            f"2. Each character's appearance MUST match their reference image exactly.\n"
            f"3. Every named character in the script should appear in at least 2 panels.\n\n"
            f"{layout_rules}"
            f"FORMAT:\n"
            f"- Vertical layout, 9:16 aspect ratio\n"
            f"- {borders}\n"
            f"- Manga/comic art style\n"
            f"- Dialogue bubbles in {language}\n"
            f"- Vary camera angles across panels (wide, medium, close-up)\n\n"
            f"Output a single vertical comic strip image."
        )

    image = image_provider.generate(prompt, references, aspect_ratio="9:16")
    out = image_provider.save(image, args["output_path"])
    result: dict = {"output_path": str(out), "strip_index": strip_index, "characters": char_paths}
    if args.get("draft_path"):
        result["draft_path"] = args["draft_path"]
    if image.text:
        result["text"] = image.text
    return result


register(
    Tool(
        name="generate_comic_strip",
        description=(
            "生成一条竖向条漫（4-6格）。每次调用生成一条，可多次调用生成多条。"
            "必须传入角色素材图片路径（stylized目录下）。有分镜草稿时传 draft_path：按草稿的「画面指令」画，"
            "并自动附上总剧本的「画面总则」和「服装表」里这些人的衣服；没有草稿时传 script（这一条的剧本）。"
            "传 layout_path（版式草图）时按草图的格子形状和位置画；传了 draft_path 没传 layout_path 时用草稿记录的版式草图。"
            "输出一张 9:16 竖向条漫图片，包含分格、对话气泡和黑色分格边框。"
        ),
        parameters=obj(
            {
                "character_paths": array(string("角色图片路径"), "角色图片路径列表（必须是 stylized 目录下的角色图）"),
                "character_names": array(string("角色名"), "角色名称列表，与 character_paths 一一对应，如 ['Jules', 'Peize']；和分镜草稿里的称呼一致"),
                "draft_path": string("这一条的分镜草稿路径（draft_strip 写的，output/scripts/strips/strip_N.md）"),
                "script": string("没有分镜草稿时：本条条漫的剧本（4-6格的分格描述、对话、镜头）"),
                "strip_index": integer("条漫编号，从1开始"),
                "output_path": string("输出路径"),
                "scene_path": string("场景/背景参考图路径（可选）"),
                "layout_path": string("版式草图路径（可选，draft_strip / draw_with_pil 画的）"),
            },
            ["character_paths", "character_names", "strip_index", "output_path"],
        ),
        run=generate_comic_strip,
        kind="generate",
        modes=frozenset({"comic"}),
    ),
)
