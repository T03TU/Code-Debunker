#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$project_root/backend/.venv/bin/python"
if [[ ! -x "$python_bin" || ! -d "$project_root/frontend/node_modules" ]]; then
    echo 'Install backend and frontend dependencies first. See README.md.' >&2
    exit 1
fi
backend_pid=''
frontend_pid=''
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
    [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$project_root/backend"
backend_args=(app.main:app --host 127.0.0.1 --port 8000)
if [[ -f .env ]]; then backend_args+=(--env-file .env); fi
"$python_bin" -m uvicorn "${backend_args[@]}" &
backend_pid=$!
cd "$project_root/frontend"
# Polling also works on hosts with exhausted inotify watchers.
CHOKIDAR_USEPOLLING=1 node node_modules/vite/bin/vite.js --host 127.0.0.1 &
frontend_pid=$!
echo 'CodeDebunker: http://127.0.0.1:5173'
wait -n "$backend_pid" "$frontend_pid"
