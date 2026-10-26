#!/bin/bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
task_python="$task_root/.conda/SenoMiner_AI/bin/python"
if [[ ! -x "$task_python" ]]; then
  echo '找不到 SenoMiner_AI 虚拟环境，请按照 README.md 恢复环境。'
  exit 1
fi
echo '正在启动单篇论文演示页；请以程序随后显示的网址和端口为准。'
echo '使用结束后，在这个窗口按 Control+C 关闭服务。'
exec "$task_python" "$task_root/run_senolytics.py" --open-browser --no-auto-install "$@"
