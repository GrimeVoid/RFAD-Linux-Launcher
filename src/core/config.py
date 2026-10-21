"""
Модуль конфигурации лаунчера RFAD (core реэкспорт).
Предоставляет доступ к классам конфигурации через src.core.config.
"""

from __future__ import annotations
from src.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    LEGACY_CONFIG_FILE,
    ConfigManager,
)

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    "LEGACY_CONFIG_FILE",
    "ConfigManager",
]
