"""系统提示词：创作模式（条漫 / 分镜）的介绍和工作流 + 技能目录 + 交互规则 + 项目上下文（目录、风格设定、已有素材、后台任务）。

详细的做法（总剧本、分镜草稿、版式草图、检查成图、分镜视频）写在 skills/ 里，这里只放技能目录，模型按需用 skill_load 读。
"""

from __future__ import annotations

from pathlib import Path

from . import skills
from .tools import Tool
from .tools.assets import load_assets_json

_COMIC_INTRO = (
    "你是 AniDaily 动画条漫生成助手（条漫模式）。你可以：\n"
    "1. 检测图片中的人脸并风格化为动画角色\n"
    "2. 编辑已有素材或凭空生成新素材\n"
    "3. 生成竖向条漫（4-6格）：先写总剧本，再给每条写分镜草稿（日漫的ネーム：版式、镜头、构图、动作神态、文字位置），"
    "按草稿生成，生成后对照草稿检查，有问题就局部修图\n"
    "4. 读写剧本 md 文件\n\n"
)

_COMIC_WORKFLOW = (
    "- **生成条漫的工作流**（总剧本 → 分镜草稿 → 生成 → 检查）：\n"
    "  1. 先用 list_files 查看 output/stylized/ 目录，了解已有角色。\n"
    "  2. 调用 select_characters，根据用户描述预选最匹配的角色（preselected 里填 path+label），用户会在界面上确认。\n"
    "  3. 用户确认角色后，先用 skill_load 读 master-script 技能，再按它写总剧本（write_script 到 output/scripts/作品名.md）。"
    "服装表要写清每个人穿什么、具体颜色，主要角色之间的颜色拉开，换衣服的地方单独列出。"
    "写节奏表时再读 panel-layout 技能，给每一条分一个版式结构（A–J），相邻几条不重复，特殊结构留给章节开头和情绪高点。"
    "要改总剧本的结构时也先读这两个技能。\n"
    "  4. 把总剧本的要点展示给用户（一句话梗概，每条一行），询问：要生成几条？默认1条。\n"
    "  5. 用户确认后，对要生成的每一条调用 draft_strip 写分镜草稿。"
    "它会单独起草、画版式草图、对照清单检查修改，只把摘要和草图交回来，草稿内容不用你再写一遍。"
    "同一次回复里的几个 draft_strip 会同时写（同时调用模型的数量有上限，多的自动排队），所以这样安排顺序："
    "作品开头、人物和说法第一次出现的那几条，一条一条按顺序写（后一条要看到前一条的草稿）；"
    "其余的分两批：第一批隔一条取一条（例如 8、10、12……）在一次回复里一起写，"
    "第二批在下一次回复里一起写剩下的（9、11、13……），这时每条的前后两条都已经写好，衔接接得上。"
    "一组草稿写完、生成之前，调用 read_through（drafts 按阅读顺序传）以第一次看的读者身份连读一遍，"
    "按 read-through 技能处理：根在总剧本的先改总剧本，根在草稿的带上问题作为 notes 重写那几条（这几条在一次回复里一起重写）；"
    "相邻几条的版式不要一样，摘要要和总剧本对得上。\n"
    "  6. 一组的 generate_comic_strip 在一次回复里一起发起（各条互不依赖；后台同时生成的数量有上限，多的排队）："
    "传用户确认的角色路径和名字，draft_path 和 layout_path 用 draft_strip 返回的路径，不用再传 script。"
    "然后用 check_jobs（until: \"any\"）等：有一条生成好了就先检查这一条，其余的继续在后台生成。\n"
    "  7. 每条生成好后，先用 skill_load 读 strip-fix 技能，按它做「逐条检查 → 克制地修图 → 整组连读」：review_comic_strip 检查"
    "（上一条已经有成图时传 previous_strip_path，检查衔接；character_paths 和 character_names 传生成时用的，检查长相和衣服），"
    "字错了先用 fix_comic_text 按原文重新排字；只修会让读者读错、连续性断掉、情绪落空或者字错的地方，"
    "修完和修之前比，变差了就退回。好了几条时，这几条的 review_comic_strip 可以一起调用（previous_strip_path 要等上一条也有成图）；"
    "不同条的修图可以一起发起，同一条的修图要等上一次修完、检查过再发。一组都好了以后调用 read_through（strips 按顺序传，同时传 drafts）连读一遍。"
    "最后把最终版、改了什么、哪些问题故意没修展示给用户。\n"
    "  8. 用户指出某一条哪里不对时：局部的问题按 strip-fix 技能用 fix_comic_strip 直接修（字错了用 fix_comic_text）；要大改就先改分镜草稿"
    "（draft_strip 带上 notes；用户也可能已经在素材栏里自己改了草稿），再重新生成。"
    "要你自己动手改分镜草稿时先读 strip-draft 技能；只改一句台词这类小地方，可以直接用 update_script 改草稿「画面指令」里的那一句。"
    "要用 draw_with_pil 手动画或改版式草图时，先读 layout-sketch 技能。\n"
    "  9. 绝对不要用 generate_asset 生成条漫，generate_asset 不支持角色参考图。\n\n"
)

_STORYBOARD_INTRO = (
    "你是 AniDaily 动画分镜生成助手（分镜模式）。你可以：\n"
    "1. 检测图片中的人脸并风格化为动画角色\n"
    "2. 编辑已有素材或凭空生成新素材\n"
    "3. 为每个分镜 clip 合成首帧关键画（角色+场景合成，16:9 横屏）\n"
    "4. 读写剧情脚本（md）和分镜脚本（JSON）\n\n"
)

_STORYBOARD_WORKFLOW = (
    "- **分镜视频工作流**：完整的步骤、分镜脚本 JSON 的格式和规则都在 storyboard-video 技能里。"
    "收到做分镜、做视频的请求时，先用 skill_load 读它，再按里面的步骤执行。\n\n"
)


def _common_rules(tools: list[Tool]) -> str:
    generate = "、".join(t.name for t in tools if t.kind == "generate") or "生成类工具"
    return (
        "交互规则：\n"
        "- 需要好几步才能完成的请求：先用一两句话说明打算怎么做，然后直接调用工具开始，不要在文字里问「可以开始吗」。"
        "需要用户批准的操作，系统会在界面上请用户批准。\n"
        f"- **生成类工具在后台执行**：{generate} 调用后立即返回 job_id，图片在后台生成。"
        "互不依赖的生成可以在同一次回复里一起发起（例如一次发起 4 条条漫）。"
        "需要用到生成结果之前（向用户展示图片、用新生成的角色画条漫等），先调用 check_jobs 等待并拿到结果，不要假设已经生成好。\n"
        "- 工具结果说明用户没有批准某次调用时，不要原样重试：按用户的说明调整，或者问用户想怎么改。\n"
        "- 当用户发送图片时，不要自动执行任何工具。先确认用户的意图，然后再执行对应操作。\n"
        "- 只有当用户明确要求执行某个操作时，才调用对应工具。\n"
        "- 当用户给角色或素材起名、备注、改名时，立即调用 rename_asset。\n"
        "- 人脸检测完成后，**必须先向用户展示检测结果**，然后询问用户要风格化哪些人。"
        "**绝对不要在检测后自动调用 stylize_character**，必须等用户确认。\n"
        "- 当用户要求风格化角色时，**必须先调用 select_faces** 让用户在界面上勾选。"
        "select_faces / select_characters 的工具结果就是用户在界面上做的选择。\n"
        "- **update_script 失败时**：必须先用 read_script 重新读取文件内容，再用正确的 old_text 重试 update_script。\n"
        "- 工具返回的文件路径必须在后续操作中直接使用，不要猜测路径。\n"
        "- 如果不确定文件位置，先使用 list_files 工具查看。\n"
        "- **风格设定**：项目根目录的 style.md 记录画风、语言、排版等偏好，内容已经附在下方「漫画风格设定」里，"
        "生成角色、条漫或素材时直接遵守，**不需要再用 read_script 读取 style.md**；"
        "用户要求修改风格时，用 write_script / update_script 更新 style.md。\n"
        "- 回复里展示生成的图片或文件时用 Markdown，路径直接用工具返回的路径或相对项目目录的路径，"
        "例如 ![第1条](output/panels/strip_1.png)、[剧本](output/scripts/story.md)。\n"
    )


def _interaction_rules(interaction: str, tools: list[Tool]) -> str:
    if interaction == "ask":
        readers = "、".join(t.name for t in tools if t.kind == "read")
        return (
            "\n**当前交互模式：讨论**\n"
            "- 只回复文字，与用户讨论、积累上下文。\n"
            f"- 只能使用 {readers} 这些读取类工具查看现有内容。\n"
            "- 不能调用生成类、编辑类、写入类工具。\n"
            "- 帮用户完善想法，等用户切换到其他模式后再执行。\n\n"
        )
    if interaction == "auto":
        return "\n**当前交互模式：自动执行**\n- 工具调用会直接执行，不需要用户批准。\n\n"
    return (
        "\n**当前交互模式：生成前确认**\n"
        "- 生成类工具执行前，系统会请用户在界面上批准；你照常调用即可，不用先在文字里征求同意。\n\n"
    )


def _asset_summary(project_dir: Path, mode: str) -> str:
    """项目各分类已有的素材（含 assets.json 里的名称和描述）。"""
    out = project_dir / "output"
    categories = {
        "原始图片": project_dir / "input",
        "风格化角色": out / "stylized",
        "人脸": out / "faces",
        "场景": out / "scenes" / "stylized",
        "去人场景": out / "scenes" / "no_people",
        "条漫": out / "panels",
        "版式草图": out / "layouts",
    }
    if mode == "storyboard":
        categories["视频片段"] = out / "videos"
        categories["分镜脚本"] = out / "storyboards"
    categories["剧本"] = out / "scripts"
    if mode != "storyboard":
        categories["分镜草稿"] = out / "scripts" / "strips"
    lines: list[str] = []
    for label, dir_path in categories.items():
        if not dir_path.exists():
            continue
        files = sorted(f for f in dir_path.iterdir() if f.is_file() and f.name != "assets.json")
        if not files:
            continue
        meta = load_assets_json(dir_path)
        if meta:
            lines.append(f"  [{label}] ({len(files)} 个):")
            for f in files:
                info = meta.get(f.name)
                lines.append(f"    - {f.name}: {info.get('name', '')} ({info.get('description', '')})" if info else f"    - {f.name}")
        else:
            lines.append(f"  [{label}] ({len(files)} 个): {', '.join(f.name for f in files[:5])}")
            if len(files) > 5:
                lines.append(f"    ... 等共 {len(files)} 个文件")
    return "\n".join(lines)


def _project_context(project_dir: Path | None, mode: str, lang: str) -> str:
    if not project_dir:
        return "所有文件路径基于项目根目录。输出文件默认放在 output/ 下。\n"
    out = project_dir / "output"
    context = (
        f"当前项目目录: {project_dir}\n"
        f"用户上传的原始图片在 {project_dir / 'input'}/ 下。\n"
        f"输出文件必须放在对应子目录下：\n"
        f"  - 风格化角色: {out / 'stylized'}/\n"
        f"  - 人脸裁剪: {out / 'faces'}/\n"
        f"  - 场景: {out / 'scenes' / 'stylized'}/\n"
        f"  - 去人场景: {out / 'scenes' / 'no_people'}/\n"
        f"  - 条漫: {out / 'panels'}/\n"
        f"  - 版式草图（PNG + 画图代码 .py）: {out / 'layouts'}/\n"
    )
    if mode == "storyboard":
        context += (
            f"  - 视频片段: {out / 'videos'}/\n"
            f"  - 分镜条漫(整条): {out / 'storyboards' / 'strips'}/\n"
            f"  - 分镜脚本(JSON): {out / 'storyboards'}/\n"
            f"  - 视频脚本(MD): {out / 'storyboards' / 'clip_scripts'}/\n"
        )
    context += f"  - 剧本(MD): {out / 'scripts'}/\n"
    if mode != "storyboard":
        context += f"  - 分镜草稿(MD): {out / 'scripts' / 'strips'}/\n"
    context += "\n"

    # 风格设定直接附上，不用模型再去读
    style_path = project_dir / ("style_en.md" if lang == "en" else "style.md")
    if not style_path.exists():
        style_path = project_dir / "style.md"
    if style_path.exists():
        label = (
            f"Comic style guide ({style_path.name}, user-editable, must follow when generating):"
            if lang == "en" else f"漫画风格设定（{style_path.name}，用户可编辑，生成内容时必须遵守）："
        )
        context += f"{label}\n{style_path.read_text(encoding='utf-8').strip()}\n\n"

    summary = _asset_summary(project_dir, mode)
    if summary:
        context += f"当前项目已有素材：\n{summary}\n"
    return context


def _jobs_context(unfinished_jobs: list[dict]) -> str:
    if not unfinished_jobs:
        return ""
    lines = [f"  - {j['id']}（{j['tool']}，{'生成中' if j['status'] == 'running' else '排队中'}）" for j in unfinished_jobs]
    return "\n后台还没完成的生成任务（需要结果时用 check_jobs 查询或等待）：\n" + "\n".join(lines) + "\n"


def build_system_prompt(*, mode: str, interaction: str, lang: str, project_dir: Path | None,
                        tools: list[Tool], unfinished_jobs: list[dict]) -> str:
    intro, workflow = (_STORYBOARD_INTRO, _STORYBOARD_WORKFLOW) if mode == "storyboard" else (_COMIC_INTRO, _COMIC_WORKFLOW)
    return (
        intro
        + _common_rules(tools)
        + workflow
        + skills.catalog(skills.available(project_dir, mode))
        + _project_context(project_dir, mode, lang)
        + _jobs_context(unfinished_jobs)
        + ("Reply in English." if lang == "en" else "回复使用中文。")
        + _interaction_rules(interaction, tools)
    )
