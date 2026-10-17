"""在 WebAssembly 沙箱里运行模型写的 Python（PIL）画图代码。

- Python 跑在 Pyodide 里（编译成 WebAssembly 的 CPython，带 Pillow），代码看到的是内存里的文件系统，碰不到本机文件。
- 光靠 WASM 不够：Pyodide 能通过 JS 接口调用宿主运行时。所以 Pyodide 跑在 Deno 里，Deno 默认没有任何权限，
  这里只给读 Pyodide 目录的权限：代码读写不了本机文件、不能联网、不能执行命令、读不到环境变量。
  （Node 的权限模式不行：Pyodide 在它下面加载不起来，而且 Node 文档说明它的权限模式防不了恶意代码。）
- 每次运行一个新进程，超时直接杀掉。

Pyodide 和 Pillow 第一次用时下载到 .cache/pyodide/<版本>/（约 8 MB），按固定的哈希校验。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYODIDE_VERSION = "314.0.7"
# Pyodide 本体：npm 包，校验值是 npm registry 给出的 integrity（sha512）
_TARBALL_URL = f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE_VERSION}.tgz"
_TARBALL_SHA512 = "0YvXxEhfEdpLfb/XkM2BFAeMROq0iMUX2bzzH9pOttyMcWkwq+HbE5uyuGD82LN7y2q+SNvi/6V5JEsOlD2R1A=="
# Pillow 不在 npm 包里，从 Pyodide 的 CDN 下载；sha256 和 pyodide-lock.json 里记录的一致
_PILLOW_FILE = "pillow-12.2.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl"
_PILLOW_SHA256 = "e29838b7a756e4ee0f27a9cfa9a387ee0dfa2e9dd44be2dd595130b9f9d93ac3"
_PILLOW_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/{_PILLOW_FILE}"
_REQUIRED = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json", _PILLOW_FILE)

CACHE_DIR = PROJECT_ROOT / ".cache" / "pyodide" / PYODIDE_VERSION
RUNNER = Path(__file__).with_name("pil_sandbox_runner.mjs")
MARK = "@@RESULT@@"
MAX_SIDE = 4096
DEFAULT_TIMEOUT = 30.0
INSTALL_HINT = "需要安装 Deno 才能运行画图代码（代码在 Deno + WebAssembly 沙箱里运行）。macOS：brew install deno；其他系统见 https://deno.com"

_setup_lock = threading.Lock()
_slots = threading.BoundedSemaphore(4)  # 同时运行的沙箱进程数


class SandboxUnavailable(RuntimeError):
    """运行环境的问题（没装 Deno、下载失败、沙箱没起来），不是代码本身的错。"""


@dataclass
class RunResult:
    ok: bool
    png: bytes | None = None
    size: tuple[int, int] | None = None
    error: str | None = None
    stdout: str = ""


def find_deno() -> str | None:
    found = shutil.which("deno")
    if found:
        return found
    # 从图形界面或 IDE 启动时 PATH 里可能没有这些目录
    for candidate in (Path.home() / ".deno" / "bin" / "deno", Path("/opt/homebrew/bin/deno"), Path("/usr/local/bin/deno")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _ready(directory: Path) -> bool:
    return all((directory / name).is_file() for name in _REQUIRED)


def _fetch(client: httpx.Client, url: str) -> bytes:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.content


def _extract(tarball: bytes, dest: Path) -> None:
    """只取 npm 包 package/ 下一层的普通文件（Pyodide 的文件都在这一层），不会写到 dest 外面。"""
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("package/")
            if not member.isfile() or name == member.name or "/" in name or name in ("", ".", ".."):
                continue
            source = tar.extractfile(member)
            if source is not None:
                (dest / name).write_bytes(source.read())


def ensure_pyodide() -> Path:
    """确保 Pyodide 和 Pillow 已经下载好，返回所在目录。"""
    if _ready(CACHE_DIR):
        return CACHE_DIR
    with _setup_lock:
        if _ready(CACHE_DIR):
            return CACHE_DIR
        logger.info(f"下载 Pyodide {PYODIDE_VERSION} 到 {CACHE_DIR}")
        CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{PYODIDE_VERSION}-", dir=CACHE_DIR.parent))
        try:
            with httpx.Client(timeout=httpx.Timeout(120, connect=20), follow_redirects=True) as client:
                tarball = _fetch(client, _TARBALL_URL)
                if base64.b64encode(hashlib.sha512(tarball).digest()).decode() != _TARBALL_SHA512:
                    raise SandboxUnavailable("下载的 Pyodide 校验值不对，已丢弃")
                _extract(tarball, staging)
                wheel = _fetch(client, _PILLOW_URL)
                if hashlib.sha256(wheel).hexdigest() != _PILLOW_SHA256:
                    raise SandboxUnavailable("下载的 Pillow（Pyodide 版）校验值不对，已丢弃")
                (staging / _PILLOW_FILE).write_bytes(wheel)
            if not _ready(staging):
                raise SandboxUnavailable("Pyodide 安装包里缺少文件")
            if CACHE_DIR.exists():  # 上次没下载完整
                shutil.rmtree(CACHE_DIR)
            staging.rename(CACHE_DIR)
        except httpx.HTTPError as exc:
            raise SandboxUnavailable(f"下载 Pyodide 失败（只需要下载一次，约 8 MB）：{exc}") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    return CACHE_DIR


def _command(deno: str, index: Path) -> list[str]:
    if "," in str(index) or "," in str(RUNNER):
        raise SandboxUnavailable(f"项目路径里有逗号，Deno 的权限参数没法表示：{PROJECT_ROOT}")
    return [
        deno, "run", "--quiet", "--no-prompt", "--no-config", "--no-lock", "--no-npm", "--no-remote",
        f"--allow-read={index},{RUNNER}",
        "--deny-write", "--deny-net", "--deny-run", "--deny-env", "--deny-ffi", "--deny-sys",
        str(RUNNER), str(index),
    ]


def run(code: str, width: int = 900, height: int = 1600, *, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """运行一段画图代码。代码里有现成的 img（白底 RGB 画布）和 draw，结束时 img 就是结果。

    代码本身的错误（语法错误、异常、超时）放在 RunResult.error 里；环境问题抛 SandboxUnavailable。
    """
    if not (16 <= width <= MAX_SIDE and 16 <= height <= MAX_SIDE):
        return RunResult(ok=False, error=f"画布宽高要在 16 到 {MAX_SIDE} 之间")
    deno = find_deno()
    if not deno:
        raise SandboxUnavailable(INSTALL_HINT)
    index = ensure_pyodide()
    request = json.dumps({"code": code, "width": width, "height": height})
    env = {"PATH": os.environ.get("PATH", ""), "NO_COLOR": "1", "DENO_NO_UPDATE_CHECK": "1"}
    t0 = time.time()
    with _slots:
        try:
            proc = subprocess.run(
                _command(deno, index), input=request, capture_output=True, text=True,
                timeout=timeout, env=env, cwd=str(RUNNER.parent),
            )
        except subprocess.TimeoutExpired:
            return RunResult(ok=False, error=f"代码运行超过 {timeout:g} 秒，已被中止（检查有没有死循环）")
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith(MARK)), None)
    if line is None:
        detail = (proc.stderr or proc.stdout).strip()[-500:]
        raise SandboxUnavailable(f"画图沙箱没有正常运行（退出码 {proc.returncode}）：{detail}")
    data = json.loads(line[len(MARK):])
    stdout = (data.get("stdout") or "")[-4000:]
    if data.get("internal"):
        raise SandboxUnavailable(f"画图沙箱出错：{str(data.get('error'))[-500:]}")
    logger.info(f"PIL 沙箱运行 {time.time() - t0:.1f}s ok={data.get('ok')}")
    if not data.get("ok"):
        return RunResult(ok=False, error=data.get("error") or "运行失败", stdout=stdout)
    w, h = data.get("size") or (width, height)
    if max(w, h) > MAX_SIDE:
        return RunResult(ok=False, error=f"画出的图太大（{w}×{h}），宽高不能超过 {MAX_SIDE}", stdout=stdout)
    return RunResult(ok=True, png=base64.b64decode(data["png"]), size=(w, h), stdout=stdout)


if __name__ == "__main__":
    # 手动检查环境：uv run python -m src.tools.pil_sandbox
    started = time.time()
    demo = run("draw.ellipse([100, 100, W - 100, W - 100], outline='black', width=6)\nprint('ok', W, H)")
    print(f"{time.time() - started:.1f}s", {"ok": demo.ok, "size": demo.size, "error": demo.error, "stdout": demo.stdout})
