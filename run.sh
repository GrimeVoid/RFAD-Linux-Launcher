#!/bin/bash
# Скрипт запуска RFAD Linux Launcher на Python
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR"

# Гарантированный запуск в Wayland-сессиях (с автоматическим fallback на xcb/XWayland)
if [ -z "$QT_QPA_PLATFORM" ]; then
    export QT_QPA_PLATFORM="wayland;xcb"
fi

python3 "$SCRIPT_DIR/src/main.py" "$@"
