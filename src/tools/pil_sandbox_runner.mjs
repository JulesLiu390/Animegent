// 在 Pyodide（WebAssembly 版 CPython + Pillow）里运行一段 PIL 画图代码。由 pil_sandbox.py 用 Deno 启动，
// 只有读 Pyodide 目录的权限。请求从 stdin 读：{"code": str, "width": int, "height": int}；
// 结果以 @@RESULT@@ 开头的一行 JSON 写到 stdout：{"ok": true, "png": base64, "size": [w, h], "stdout": str}
// 或 {"ok": false, "error": str, "stdout": str}。
import { join } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const MARK = "@@RESULT@@";
const indexDir = process.argv[2];

// 模型的代码在 <code> 里执行；预先准备好画布 img（白底 RGB）和 draw，结束时把 img 存成 PNG
const HARNESS = `
import base64, io, math, sys, traceback
from PIL import Image, ImageDraw, ImageFont

def _run(code, width, height):
    img = Image.new("RGB", (width, height), "white")
    ns = {"__name__": "__main__", "Image": Image, "ImageDraw": ImageDraw, "ImageFont": ImageFont,
          "math": math, "W": width, "H": height, "img": img, "draw": ImageDraw.Draw(img)}
    try:
        exec(compile(code, "<code>", "exec"), ns)
    except BaseException:
        etype, value, tb = sys.exc_info()
        frames = [f for f in traceback.extract_tb(tb) if f.filename == "<code>"]
        lines = traceback.format_list(frames) + traceback.format_exception_only(etype, value)
        return {"ok": False, "error": "".join(lines).strip()}
    out = ns.get("img")
    if not isinstance(out, Image.Image):
        return {"ok": False, "error": "代码结束时 img 不是 PIL Image（最后要画在 img 上，或者把 img 赋值成画好的图）"}
    if max(out.size) > 4096:
        return {"ok": False, "error": f"画出的图太大（{out.size[0]}×{out.size[1]}），宽高不能超过 4096"}
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "PNG")
    return {"ok": True, "png": base64.b64encode(buf.getvalue()).decode(), "size": list(out.size)}
`;

function emit(result) {
  process.stdout.write(MARK + JSON.stringify(result) + "\n");
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

const printed = [];
try {
  const request = JSON.parse(await readStdin());
  const { loadPyodide } = await import(pathToFileURL(join(indexDir, "pyodide.mjs")).href);
  const pyodide = await loadPyodide({
    indexURL: indexDir.endsWith("/") ? indexDir : indexDir + "/",
    stdout: (line) => printed.push(line),
    stderr: (line) => printed.push(line),
  });
  await pyodide.loadPackage("pillow", { messageCallback: () => {}, errorCallback: (line) => printed.push(line) });
  pyodide.runPython(HARNESS);
  const proxy = pyodide.globals.get("_run")(request.code, request.width, request.height);
  const result = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  emit({ ...result, stdout: printed.join("\n") });
} catch (err) {
  emit({ ok: false, internal: true, error: String(err && err.stack ? err.stack : err), stdout: printed.join("\n") });
}
