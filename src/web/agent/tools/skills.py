"""技能：读取 skills/ 里的做法说明。技能目录在系统提示词里，正文和参考资料用这里的工具按需读取（只读）。"""

from __future__ import annotations

from .. import skills as library
from .base import Tool, ToolContext, obj, register, string


def skill_load(args: dict, ctx: ToolContext) -> dict:
    try:
        skill = library.get(args.get("skill_id", ""), ctx.project_dir, ctx.mode)
        content = library.wrap(skill, "SKILL.md", skill.body(), library.MAX_SKILL_CHARS)
        resources = skill.resources()
    except (library.SkillError, OSError) as exc:
        return {"error": str(exc)}
    result: dict = {"skill_id": skill.id, "name": skill.name, "source": skill.source, "content": content}
    if resources:
        result["resources"] = resources
    return result


def skill_read_resource(args: dict, ctx: ToolContext) -> dict:
    path = str(args.get("path") or "").strip()
    try:
        skill = library.get(args.get("skill_id", ""), ctx.project_dir, ctx.mode)
        content = library.wrap(skill, path, skill.resource(path), library.MAX_RESOURCE_CHARS)
    except (library.SkillError, OSError) as exc:
        return {"error": str(exc)}
    return {"skill_id": skill.id, "path": path, "content": content}


register(
    Tool(
        name="skill_load",
        description=(
            "读取一个技能的完整说明（SKILL.md）。系统提示词的「可用技能」里列出了技能 id 和什么时候用；"
            "要做技能描述里写的事情时先读，再照着做。技能只是说明，不会带来新的工具或权限。"
        ),
        parameters=obj({"skill_id": string("技能 id，见系统提示词里的「可用技能」")}, ["skill_id"]),
        run=skill_load,
        kind="read",
    ),
    Tool(
        name="skill_read_resource",
        description="读取技能目录里的参考文件（skill_load 返回的 resources 里列出的文件，例如模板、清单）。只读。",
        parameters=obj(
            {
                "skill_id": string("技能 id"),
                "path": string("技能目录里的相对路径，例如 template.md"),
            },
            ["skill_id", "path"],
        ),
        run=skill_read_resource,
        kind="read",
    ),
)
