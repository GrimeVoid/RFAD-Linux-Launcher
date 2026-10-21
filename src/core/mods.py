"""
Модуль управления модами, графическими пресетами и Steam DRM.
Позволяет безопасно переключать ENB, ReShade, Community Shaders и Steam Fix.
Обеспечивает атомарное копирование и защиту от сбоев файловой системы.
"""

from __future__ import annotations
import logging
import os
import shutil
from pathlib import Path
from typing import List
from src.core.paths import GamePaths

logger = logging.getLogger(__name__)

GRAPHIC_ROOT_FILES = [
    "dxgi.dll",
    "d3d11.dll",
    "ReShade.ini",
    "ReShadeGUI.ini",
    "reshade-shaders",
    "enbseries",
    "enbseries.ini",
    "enblocal.ini",
]


class ModManager:
    """Управление графическими модификациями и компонентами сборки."""

    def __init__(self, paths: GamePaths) -> None:
        self.paths = paths

    def clean_root_graphics(self) -> None:
        """Безопасно удаляет активные файлы графических модов из корня игры."""
        root = self.paths.root
        if not root.is_dir():
            return

        for name in GRAPHIC_ROOT_FILES:
            target = root / name
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.is_file() or target.is_symlink():
                    target.unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Не удалось удалить графический компонент '%s': %s", name, e)

        logger.info("Корень игры очищен от графических пресетов")

    def _copy_item_safe(self, src: Path, dest_dir: Path) -> None:
        """Копирует файл или каталог с заменой целевого объекта."""
        dest = dest_dir / src.name
        try:
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest, ignore_errors=True)
                else:
                    dest.unlink(missing_ok=True)

            if src.is_dir():
                shutil.copytree(src, dest, symlinks=False)
            else:
                shutil.copy2(src, dest)
        except Exception as e:
            logger.error("Ошибка копирования '%s' -> '%s': %s", src, dest, e)
            raise

    def apply_graphic_preset(self, preset: str) -> None:
        """
        Переключает графический мод через GraphicsManager (ReShade / ENB / CommunityShader / None).
        Обеспечивает изоляцию файлов в .graphics_backup/.
        """
        from src.core.graphics import GraphicsManager
        gfx = GraphicsManager(self.paths)
        gfx.apply_graphic_preset(preset)


    def _set_community_shaders_enabled(self, enabled: bool) -> None:
        """Включает или выключает Community Shaders в modlist.txt MO2."""
        profiles_dir = self.paths.root / "MO2" / "profiles"
        if not profiles_dir.is_dir():
            return

        for profile in profiles_dir.iterdir():
            if not profile.is_dir():
                continue
            modlist_file = profile / "modlist.txt"
            if not modlist_file.is_file():
                continue

            try:
                lines = modlist_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                new_lines: List[str] = []
                for line in lines:
                    trimmed = line.strip()
                    if "Community Shaders" in trimmed:
                        prefix = "+" if enabled else "-"
                        mod_name = trimmed.lstrip("+- ")
                        new_lines.append(f"{prefix}{mod_name}")
                    else:
                        new_lines.append(line)

                modlist_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logger.info("Обновлен профиль MO2 (%s): Community Shaders = %s", profile.name, enabled)
            except Exception as e:
                logger.warning("Не удалось обновить modlist в %s: %s", profile.name, e)

    def set_steam_drm(self, enable_fix: bool) -> None:
        """
        Включает (crack) или выключает (оригинал) Steam DRM Fix.
        """
        drm_dir = self.paths.root / "disabledGameFiles" / "SteamDRM"
        source_dir = (drm_dir / "on") if enable_fix else (drm_dir / "off")

        if not source_dir.is_dir():
            logger.warning("Папка Steam DRM не найдена: %s", source_dir)
            raise FileNotFoundError(f"Каталог с файлами Steam DRM не найден: {source_dir}")

        for item in source_dir.iterdir():
            self._copy_item_safe(item, self.paths.root)

        logger.info("Steam DRM режим установлен: enable_fix=%s", enable_fix)
