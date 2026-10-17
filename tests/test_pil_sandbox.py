"""PIL 沙箱：真的用 Deno + Pyodide 运行（没装 Deno、或者第一次用时下载不了 Pyodide 就跳过）。"""

import io
import json

import pytest
from PIL import Image

from src.tools import pil_sandbox


@pytest.fixture(scope="module")
def sandbox():
    if not pil_sandbox.find_deno():
        pytest.skip("没有安装 Deno")
    try:
        pil_sandbox.ensure_pyodide()
    except pil_sandbox.SandboxUnavailable as exc:
        pytest.skip(str(exc))
    return pil_sandbox


def test_command_only_allows_reading_pyodide():
    cmd = pil_sandbox._command("deno", pil_sandbox.CACHE_DIR)
    assert [a for a in cmd if a.startswith("--allow")] == [f"--allow-read={pil_sandbox.CACHE_DIR},{pil_sandbox.RUNNER}"]
    for flag in ("--no-prompt", "--deny-net", "--deny-write", "--deny-run", "--deny-env", "--deny-ffi", "--deny-sys"):
        assert flag in cmd


def test_draws_on_the_prepared_canvas(sandbox):
    result = sandbox.run("draw.rectangle([10, 10, W - 10, H // 2], outline='black', width=6)\nprint('done', W, H)", 300, 400)
    assert result.ok, result.error
    assert result.size == (300, 400) and result.stdout == "done 300 400"
    img = Image.open(io.BytesIO(result.png))
    assert img.size == (300, 400)
    assert img.getpixel((12, 100)) == (0, 0, 0) and img.getpixel((150, 300)) == (255, 255, 255)


def test_code_can_replace_img_and_use_fonts(sandbox):
    code = "img = Image.new('RGB', (64, 32), 'black')\nImageDraw.Draw(img).text((2, 2), '12', font=ImageFont.load_default(size=20), fill='white')"
    result = sandbox.run(code, 100, 100)
    assert result.ok, result.error
    assert result.size == (64, 32)


def test_code_errors_come_back_with_line_numbers(sandbox):
    result = sandbox.run("x = 1\ny = undefined_name", 100, 100)
    assert not result.ok and "line 2" in result.error and "NameError" in result.error
    syntax = sandbox.run("draw.line([(0, 0), (1, 1)]", 100, 100)
    assert not syntax.ok and "SyntaxError" in syntax.error
    assert "不是 PIL Image" in sandbox.run("img = 42", 100, 100).error


def test_code_cannot_touch_the_host(sandbox, tmp_path):
    """Python 的 open() 只看得到 WASM 里的文件系统；通过 Pyodide 的 JS 接口调宿主也会被 Deno 拦住。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    target = tmp_path / "written.txt"
    probes = {
        "js-read": f"Deno.readTextFileSync({json.dumps(str(secret))})",
        "js-write": f"Deno.writeTextFileSync({json.dumps(str(target))}, 'x')",
        "js-run": "new Deno.Command('id').outputSync()",
        "js-env": "Deno.env.get('HOME')",
        "node-fs": f"process.getBuiltinModule('node:fs').readFileSync({json.dumps(str(secret))}, 'utf8')",
    }
    code = (
        "from pyodide.code import run_js\n"
        "got = []\n"
        f"try:\n    open({str(secret)!r}).read()\n    got.append('python-read')\nexcept OSError:\n    pass\n"
        f"for label, src in {probes!r}.items():\n"
        "    try:\n        run_js(src)\n        got.append(label)\n    except Exception:\n        pass\n"
        "print(','.join(got) or 'blocked')\n"
    )
    result = sandbox.run(code, 100, 100)
    assert result.ok, result.error
    assert result.stdout == "blocked"
    assert not target.exists()


def test_endless_code_is_stopped(sandbox):
    result = sandbox.run("while True:\n    pass", 100, 100, timeout=5)
    assert not result.ok and "超过 5 秒" in result.error


def test_canvas_size_is_limited():
    assert not pil_sandbox.run("pass", 10, 100).ok
    assert not pil_sandbox.run("pass", 100, pil_sandbox.MAX_SIDE + 1).ok
