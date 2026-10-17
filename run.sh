#!/usr/bin/env bash
# Animegent 一键启动：检查/安装依赖 → 同时启动后端和前端 → 打开浏览器。按 Ctrl+C 一起停止。
#
# 用法：
#   ./run.sh
# 可选环境变量：
#   FRONTEND_PORT=5173   前端端口
#   BACKEND_PORT=8000    后端端口（前端通过开发服务器代理访问后端，端口随意）
#   NO_BROWSER=1         启动后不自动打开浏览器
#   ANIMEGENT_STORYBOARD=1  打开休眠中的分镜 / 视频模式（默认关闭，见 src/web/features.py）
#
# 首次使用：打开页面后点右上角「⚙ API 设置」，添加服务商并分配模型。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT/web/frontend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PID=""
FRONTEND_PID=""
CLEANED=""

fail() {
  echo "❌ $*" >&2
  exit 1
}

# ---------- 环境检查 ----------
command -v uv >/dev/null 2>&1 || fail "没有找到 uv，请先安装：brew install uv（或参考 https://docs.astral.sh/uv/）"
command -v npm >/dev/null 2>&1 || fail "没有找到 npm，请先安装 Node.js 20+：brew install node"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || fail "需要 Node.js 20 或更高版本（当前 $(node -v)）"
# 可选：agent 画版式草图（draw_with_pil）的代码在 Deno + WebAssembly 沙箱里运行
command -v deno >/dev/null 2>&1 || [ -x "$HOME/.deno/bin/deno" ] || echo "⚠ 没有找到 Deno：agent 不能画版式草图（其他功能不受影响）。安装：brew install deno"

port_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
  fi
}

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pid="$(port_pid "$port")"
  if [ -n "$pid" ]; then
    fail "端口 $port 已被占用（PID $pid，$(ps -o comm= -p "$pid" 2>/dev/null)）。如果是之前启动的 Animegent，先停掉它：kill $pid"
  fi
done

# ---------- 依赖 ----------
echo "▶ 检查后端依赖（uv sync）…"
(cd "$ROOT" && uv sync)

if [ ! -d "$FRONTEND_DIR/node_modules" ] || [ "$FRONTEND_DIR/package-lock.json" -nt "$FRONTEND_DIR/node_modules/.package-lock.json" ]; then
  echo "▶ 安装前端依赖（npm install）…"
  (cd "$FRONTEND_DIR" && npm install --no-audit --no-fund)
fi

# ---------- 停止 ----------
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  [ -n "$CLEANED" ] && return
  CLEANED=1
  echo
  echo "▶ 正在停止 Animegent…"
  [ -n "$FRONTEND_PID" ] && kill_tree "$FRONTEND_PID"
  [ -n "$BACKEND_PID" ] && kill_tree "$BACKEND_PID"
  wait 2>/dev/null || true
  echo "已停止。"
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap cleanup EXIT

# ---------- 启动 ----------
echo "▶ 启动后端 http://localhost:$BACKEND_PORT"
(cd "$ROOT" && exec uv run uvicorn src.web.api:app --reload --port "$BACKEND_PORT") &
BACKEND_PID=$!

echo "▶ 启动前端 http://localhost:$FRONTEND_PORT"
(cd "$FRONTEND_DIR" && ANIMEGENT_BACKEND="http://127.0.0.1:$BACKEND_PORT" exec ./node_modules/.bin/vite --port "$FRONTEND_PORT" --strictPort --clearScreen false) &
FRONTEND_PID=$!

wait_for() {
  local url="$1" pid="$2" name="$3" i
  for i in $(seq 1 120); do
    curl -sf -o /dev/null "$url" && return 0
    kill -0 "$pid" 2>/dev/null || fail "$name 启动失败，请查看上面的日志"
    sleep 1
  done
  fail "等待$name启动超时（$url）"
}
wait_for "http://localhost:$BACKEND_PORT/api/projects" "$BACKEND_PID" "后端"
wait_for "http://localhost:$FRONTEND_PORT" "$FRONTEND_PID" "前端"

URL="http://localhost:$FRONTEND_PORT"
echo
echo "✅ Animegent 已启动：$URL"
echo "   首次使用：点右上角「⚙ API 设置」添加服务商并分配模型"
echo "   按 Ctrl+C 停止"
echo

if [ "${NO_BROWSER:-}" != "1" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi

# 任意一个服务退出，就把另一个也停掉
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
fail "有服务意外退出，正在停止其余服务"
