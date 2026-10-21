#!/usr/bin/env bash
# Запуск лаунчера RFAD в изолированном Nix-окружении
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec nix-shell "$SCRIPT_DIR/shell.nix" --run "$SCRIPT_DIR/run.sh"
