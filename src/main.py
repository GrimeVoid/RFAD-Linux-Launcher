"""
Точка входа в лаунчер RFAD SE на Python (PyQt5).
"""

from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

# Гарантируем бесшовный запуск под Wayland / XWayland
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

from PyQt5.QtWidgets import QApplication

from src.config import ConfigManager, CONFIG_DIR
from src.ui.main_window import MainWindow
from src.ui.styles import apply_rfad_theme

LOG_FILE = CONFIG_DIR / "launcher.log"


def setup_logging() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        ],
    )


def main() -> int:
    setup_logging()
    logger = logging.getLogger("rfad_launcher")
    logger.info("=== Запуск RFAD Linux Launcher 2.0 (Native Python) ===")

    app = QApplication(sys.argv)
    app.setApplicationName("RFAD Launcher")
    app.setOrganizationName("RFAD")

    # Применяем официальную цветовую палитру RFAD (Obsidian & Gold)
    apply_rfad_theme(app)

    config_mgr = ConfigManager()
    window = MainWindow(config_mgr)
    window.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
