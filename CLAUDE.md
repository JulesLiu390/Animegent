# AniDaily

AI-powered vertical comic strip (条漫) generator: real photos → anime characters → manga panels.

## Quick Start

```bash
# Everything (deps + backend :8000 + frontend :5173, Ctrl+C stops both)
./run.sh

# Backend
uv run uvicorn src.web.api:app --reload --port 8000

# Frontend (Vite proxies /api and /files to the backend; set ANIMEGENT_BACKEND to change the target)
cd web/frontend && npm run dev
```

## Architecture

- **Backend**: FastAPI + LLM function calling, streamed over SSE. The agent is structured as Session (conversation) → Turn (one user input, until control returns to the user) → Step (one model text segment or one tool call). One turn runs per conversation at a time (`Session.run_lock`), stopped via `/api/chat/stop` or client disconnect (`Session.cancel_event`). The tool calls of one model reply run in parallel (up to 8 threads), so drafts, reviews and generations requested together happen at once
- **Frontend**: React + TypeScript + Vite + Tailwind CSS v3; Markdown via react-markdown + remark-gfm + remark-cjk-friendly
- **AI Models**: configured in the UI (⚙ API 设置) per role — chat / vision / image / video — and stored in `settings.json`
- **Providers** (`src/providers/`): LLM via OpenAI-compatible / Gemini / Anthropic adapters; images via Gemini `generateContent` or OpenAI Images; video via unified `/v1/video/create`, OpenAI Sora or Veo; multiple keys per provider rotate round-robin. Each provider has `max_concurrency` (default 3, editable in the settings dialog): per role (chat / vision / image / video) at most that many requests run at once, the rest wait in `settings.request_slot()`; background jobs also queue per role in `JobManager` up to `settings.concurrency(role)`
- **Face Detection**: InsightFace (buffalo_l, local CPU)

## Project Structure

```
src/
  web/
    api.py          # FastAPI routes, SSE chat endpoint
    agent/          # session.py (turn loop: model rounds, tool steps, approvals, stop), tools/ (tool registry),
                    # jobs.py (background generation jobs), prompts.py (system prompt + skill catalog),
                    # skills.py (skill discovery / parsing), strip_guide.py (prompts of the draft / review sub-calls)
    db.py           # SQLite: conversations, turns, steps, model history (history_entries), jobs
    legacy.py       # Converts the old frontend-saved ui_messages into read-only legacy turns
    features.py     # Feature flags (storyboard / video mode is dormant by default)
  providers/        # settings.json + key rotation, LLM adapters (llm.py), image.py, video.py
  tools/            # Core tool implementations (face detection, stylization, image gen, PIL sandbox, strip_image: panels / grid / changes / composite, strip_text: re-lettering caption boxes)
  mcp_tools/        # MCP tool definitions (parallel interface for external clients)
  mcp_server.py     # MCP server entry point (CLI: anidaily-mcp)
web/frontend/src/
  components/       # React components (ChatPanel, ChatTurns, ToolCallCard, ApprovalDock, Composer, AssetSidebar, …)
  lib/              # Pure helpers: turns (apply turn / step / job events), media (path → URL), tools, storage
  hooks.ts          # Contexts + hooks (language, toast, lightbox, useNow)
  api.ts            # SSE parser, API client
projects/{name}/    # Per-project asset storage
  input/            # Uploaded photos
  output/           # Generated assets (stylized/, faces/, scenes/, panels/, layouts/, scripts/strips/ = strip drafts)
  scripts/          # Markdown comic scripts
  style.md          # Project style guide
```

## Key Conventions

- All asset directories use `assets.json` for metadata: `{filename: {name, description}}`
- Paths in the agent/frontend are relative to `projects/{name}/`; `tools/base.resolve_paths()` converts them to absolute
- Tools are registered in `src/web/agent/tools/` with a kind: `read` (allowed in Ask mode), `write`, `generate` (image / video models: run as background jobs and return a `job_id` at once; the model calls `check_jobs` to wait for results — all of them, or with `until: "any"` until one whose result it hasn't received yet finishes, so a group can be generated together and reviewed strip by strip as images arrive; in Confirm mode they need the user's approval first), `interactive` (`select_faces` / `select_characters`: the user's choice in the card becomes the tool result)
- Comic workflow follows Japanese manga production: master script (`output/scripts/<work>.md`, one `## 第N条｜标题` section per strip plus 企画 / 角色表 / 服装表 / 场景表 / 画面总则 / 节奏表) → strip draft (ネーム) → generation → check. `draft_strip` (kind `write`, `tools/drafts.py`) makes its own chat-model calls (`stream_chat` without tools): draft → run the layout code → editor's check with the sketch attached → revised draft; it writes `output/scripts/strips/strip_N.md` (header lines `> 总剧本：…` / `> 版式草图：…`; the last section `## 画面指令` is the only part the image model gets) and returns just a summary + the sketch. The craft guide, template and checklist are the `strip-draft` skill, plus `panel-layout` (コマ割り devices and what each conveys, layout structures A–J, reading-order conventions) and `layout-sketch` (how to draw them, including inset panels and lettered dashed outlines for figures that cross panel borders); the review uses `strip-review`. `strip_guide.py` only assembles them with the strip's material. `generate_comic_strip(draft_path=…)` sends 画面指令 + the master script's 画面总则 + the sketch, and writes each character's 服装表 line next to its reference image plus this strip's planned changes (`### 换装`, `- 第14条第5—6格｜角色：衣服`; `drafts.costumes()` parses it); `review_comic_strip` (kind `read`, vision role) checks the generated strip against the draft and returns pass / minor / redo with problems; given `character_paths` / `character_names` it also gets the character images and their 服装表 lines to check faces and clothes. Drafts don't change a main character's clothes unless 换装 lists it
- Reader-first: drafts follow the 交代 rules in `strip-draft` (establishing shots, first appearances, text–image pairing, flashback entries) and the master script carries a 读者须知 per strip. `read_through` (kind `read`, `tools/read_through.py`, the `read-through` skill) reads a group of drafts (chat role) or generated strips (vision role, drafts appended after the images) in order, retells the story and returns cross-strip issues with `target` 总剧本 / 草稿 / 成图 / 不用改. At most 12 strips per call; longer works are read in groups overlapping by one strip, and a later group passes the previous group's retelling as `previously`, so what earlier strips established isn't reported as missing. `review_comic_strip` cold-reads first and can take `previous_strip_path`; it also gets this strip's and the previous strip's master-script sections
- Check → fix → check (the `strip-fix` skill): `review_comic_strip` sends the strip plus a copy with the coordinate grid (6 columns A–F × 10 rows, `src/tools/strip_image.py`) and returns problems with `panel`, `area` (grid cells like `C4:D6`), `action` (修图 / 重画这一格 / 整条重画 / 不用改) and `fix`. `fix_comic_strip` (kind `generate`, `tools/fix.py`) takes `fixes` (panel and/or area, optional `text`, `current` (what it shows now), `instruction`) and optional `layout_path`, `reference_panels` (crops of this strip), `references` (path + label) and `marks` (default true; false skips the marks image and describes positions in words, for color / object changes). It sends the original, a marks image (grid + numbered red boxes) and the references, each labelled in the prompt. The image model redraws the whole strip, so with `keep_outside` (default) it pastes back only the boxed areas plus the change connected to them (`strip_image.Changes`: diff on a downscaled copy, thin redrawn lines filtered out, growth capped at 4× the box), limited to the box's panel(s) and not feathered against the panel border; a layout fix, a whole-image fix or a changed aspect ratio keeps the whole result. The model's raw output is saved as `fixes/<stem>_fixN_raw.png` (`raw_path`); a box that barely changed, or a panel outside the boxes with a solid change, produces a warning (usually a mis-placed area). Panels are found from white gutters (`find_panels`); output goes to `<stem>_fixN.png` (the name is reserved when the fix starts, so fixes of one strip running at once get their own files and are all counted as rounds), working images to `fixes/`. Wrong text goes to `fix_comic_text` (kind `write`, `tools/text_fix.py`, `src/tools/strip_text.py`): it finds the white caption / balloon at `area` (outline + several separate strokes inside; an area that only partly covers a box finds it, several boxes in the area need `nth`, a nearby box whose text length differs a lot is refused), erases it and re-letters `text` with a CJK font (size, line pitch, alignment and — when the length is unchanged — the original line breaks are matched from the old text; `ANIMEGENT_CJK_FONT` overrides the font), writes `<stem>_textN.png`, calls no model and doesn't count as a fix round. Against over-patching: at most `MAX_FIXES` (4) places per call and `MAX_ROUNDS` (2) fix files per strip unless `confirm_extra_round`; review problems without an explicit action default to 不用改
- Skills (same format as PetGPT's): `skills/<id>/SKILL.md` built in, `projects/<name>/skills/<id>/SKILL.md` overrides per project (an invalid project copy falls back to the built-in one). Frontmatter: `name`, `description` (what + when to read), optional `version`, `scopes` (`comic` / `storyboard`; empty = all modes); ids are lowercase letters, digits and single hyphens. The system prompt lists only the catalog for the current mode (`skills.catalog`); `skill_load` / `skill_read_resource` (kind `read`, `ToolContext.mode` decides which skills are visible) return the body / a resource file wrapped with a source + boundary note. Resource paths must stay inside the skill folder (no absolute paths, `..`, backslashes or symlinks; UTF-8 text, size-limited). Long how-to text belongs in a skill, not in `prompts.py`; the storyboard workflow is the `storyboard-video` skill. `/api/assets` lists skills as the `skills` category (built-in ones `readonly`)
- Panel layout sketches: `draw_with_pil` (kind `write`) runs model-written Python + PIL code through `src/tools/pil_sandbox.py`: Pyodide (CPython + Pillow compiled to WebAssembly) inside Deno, which only gets read access to the Pyodide directory (`.cache/pyodide/<version>/`, downloaded and hash-checked on first use). WASM alone is not a sandbox (Pyodide can call the host through its JS FFI); the Deno permissions are what block files, network, commands and env. Node's permission model is not used: Pyodide doesn't load under it. The sketch goes to `output/layouts/strip_N.png` (code in the matching `.py`), and `generate_comic_strip(layout_path=…)` passes it as the last reference image
- Tools with `model_sees_output=True` get their result image (`output_path`) attached after the tool results in the next model request only (parts marked `observation`); it is not written to the model history, so it isn't resent every round
- Interaction modes: `ask` / `confirm` (default) / `auto`. Turn statuses: running, awaiting_approval, awaiting_input, completed, failed, cancelled. A waiting turn continues via `POST /api/turns/{id}/resume`; sending a new message instead settles the pending calls as not handled
- SSE events: `conversation`, `turn` (status changes), `step` (created / updated), `delta` (streamed text of a message step), `job` (background job progress), `done`, `error`. After a stream ends the frontend polls `/api/conversations/{id}/jobs` while jobs are still running
- The backend is the single source of truth: the frontend renders `GET /api/conversations/{id}/turns` and never saves messages itself. Retry / edit (`/api/turns/{id}/retry`) and delete (`DELETE /api/turns/{id}`) drop that turn and everything after it, including the model history it produced
- Old conversations (from the `ui_messages` era) are migrated once into read-only `legacy` turns; their model history stays as context with `turn_id` NULL
- Model replies may reference files by relative path (`output/panels/strip_1.png`); the frontend resolves them against the current project (`lib/media.ts`)
- Language: supports zh (default) and en via `LanguageContext`
- Agent history uses provider-neutral message dicts (format documented at the top of `src/providers/llm.py`); never call a vendor SDK directly from tools — go through `src/providers`

## Environment

API providers and model assignments live in `settings.json` (project root, git-ignored, never served by `/files`), edited from the frontend settings dialog or `/api/settings/*`.
If `settings.json` is missing, legacy `.env` values (`API_KEYS` comma-separated, `BASE_URL`) are imported once as a Gemini-format provider.

Feature flags live in `src/web/features.py` and are sent to the frontend as `features` in every `/api/settings` response. The storyboard / video mode is **dormant** by default (`ANIMEGENT_STORYBOARD=1` enables it). While it is off, `normalize_mode()` always returns `"comic"`, so the model never gets the storyboard or video tools or prompts. The frontend hides the 条漫/分镜 switch, the video model picker and the video role in settings, and new projects skip the storyboard and video folders. The storyboard code, its tests and any existing files stay in place.

## Testing

```bash
uv run pytest tests/
```
