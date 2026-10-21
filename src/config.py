"""
Модуль конфигурации лаунчера RFAD.
Сохраняет и загружает настройки в формате JSON из ~/.config/rfad-launcher/launcher.json.
Обеспечивает обратную совместимость с существующим launcher.conf.
"""

from __future__ import annotations
import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "rfad-launcher"
CONFIG_FILE = CONFIG_DIR / "launcher.json"
LEGACY_CONFIG_FILE = CONFIG_DIR / "launcher.conf"


def _get_default_game_dir() -> str:
    """Возвращает стандартный путь к каталогу игры без привязки к имени пользователя."""
    archive_candidate = Path.home() / "Archive" / "_Games_" / "RFAD"
    if archive_candidate.exists():
        return str(archive_candidate)
    return str(Path.home() / "Games" / "RFAD")


DEFAULT_CONFIG: Dict[str, Any] = {
    "game_dir": _get_default_game_dir(),
    "fps_limit": 60,
    "mangohud": False,
    "gamemode": True,
    "gamescope": False,
    "fsr": False,
    "fsr_level": 95,
    "hdr": False,
    "shader_cache": True,
    "steam_drm": False,
    "graphic_mod": "ReShade",  # None, ReShade, ENB, CommunityShader
    "wine_dll_overrides": (
        "concrt140=n;xaudio2_7=n,b;d3d11=n,b;dxgi=n,b;d3dx9_42=n,b;"
        "d3dcompiler_47=n,b;dinput8=n,b;mscoree=n;d3d12=n,b;d3d12core=n,b;"
        "uiautomationcore=b,n"
    ),
    "close_on_launch": False,
    "random_background": True,
    "optimizations": {
        "nvidia_prime": True,
        "dxvk_async": True,
        "gamemode": True,
        "persistent_shader_cache": True,
        "cachyos_ntsync": True,
    },
}


class ConfigManager:
    """Менеджер конфигурации с безопасным чтением и записью."""

    def __init__(self, config_path: Path = CONFIG_FILE) -> None:
        self.config_path = config_path
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Попытка загрузить современный JSON
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        # Гарантируем наличие секции optimizations и ее полей
                        opts = copy.deepcopy(DEFAULT_CONFIG["optimizations"])
                        if isinstance(loaded.get("optimizations"), dict):
                            opts.update(loaded["optimizations"])
                        elif "gamemode" in loaded:
                            opts["gamemode"] = bool(loaded["gamemode"])
                        loaded["optimizations"] = opts
                        loaded["gamemode"] = bool(opts["gamemode"])

                        self.data.update(loaded)
                        logger.info("Конфигурация успешно загружена из JSON: %s", self.config_path)
                        return
            except Exception as e:
                logger.warning("Ошибка чтения JSON конфигурации, пробуем восстановить: %s", e)

        # 2. Обратная совместимость с legacy launcher.conf
        if LEGACY_CONFIG_FILE.exists():
            try:
                self._import_legacy_conf(LEGACY_CONFIG_FILE)
                self.save()
                logger.info("Импортирована legacy-конфигурация из %s", LEGACY_CONFIG_FILE)
                return
            except Exception as e:
                logger.warning("Ошибка разбора legacy конфигурации: %s", e)

        # 3. Сохраняем значения по умолчанию
        self.save()

    def _import_legacy_conf(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = [p.strip() for p in line.split(":", 1)]
                val_lower = val.lower()

                if key == "gameDir":
                    self.data["game_dir"] = val
                elif key == "MangoHud":
                    self.data["mangohud"] = val_lower == "true"
                elif key == "FSR":
                    self.data["fsr"] = val_lower == "true"
                elif key == "FsrLvl":
                    try:
                        self.data["fsr_level"] = int(val)
                    except ValueError:
                        pass
                elif key == "ShaderCache":
                    self.data["shader_cache"] = val_lower == "true"
                elif key == "HDR":
                    self.data["hdr"] = val_lower == "true"
                elif key == "SteamFix":
                    self.data["steam_drm"] = val_lower == "true"
                elif key == "FpsLimit":
                    try:
                        self.data["fps_limit"] = int(val)
                    except ValueError:
                        pass
                elif key == "WineDllOverrides":
                    self.data["wine_dll_overrides"] = val
                elif key == "GrafikMod":
                    if val in ("None", "Нету", ""):
                        self.data["graphic_mod"] = "None"
                    else:
                        self.data["graphic_mod"] = val

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def get_optimization(self, name: str, default: bool = True) -> bool:
        """Получение флага оптимизации оборудования."""
        opts = self.data.get("optimizations")
        if isinstance(opts, dict) and name in opts:
            return bool(opts[name])
        return bool(self.data.get(name, default))

    def set_optimization(self, name: str, value: bool) -> None:
        """Установка флага оптимизации оборудования."""
        if "optimizations" not in self.data or not isinstance(self.data["optimizations"], dict):
            self.data["optimizations"] = copy.deepcopy(DEFAULT_CONFIG["optimizations"])
        self.data["optimizations"][name] = bool(value)
        if name == "gamemode":
            self.data["gamemode"] = bool(value)
        self.save()

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error("Не удалось сохранить конфигурацию: %s", e)
