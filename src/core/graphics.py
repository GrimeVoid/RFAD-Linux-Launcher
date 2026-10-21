"""
Модуль управления графическими пресетами и изоляции графических инжекторов RFAD SE.
Обеспечивает физическую изоляцию файлов ENBSeries и ReShade:
- При выборе ReShade: активен ТОЛЬКО ReShade, все файлы ENB (d3d11.dll, enbseries, ini)
  изолируются в .graphics_backup/enb/ и не вызывают компиляцию шейдеров в Wine/DXVK.
- При выборе ENB: активен ENB, файлы ReShade изолируются в .graphics_backup/reshade/.
- При выборе Оригинальной/Чистой графики (None): изолируются и ENB, и ReShade.
- При выборе Community Shaders: изолируются инжекторы и активируется мод в MO2.
"""

from __future__ import annotations
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from src.core.paths import GamePaths

logger = logging.getLogger(__name__)

ENB_ITEMS = [
    "d3d11.dll",
    "d3dcompiler_46e.dll",
    "enblocal.ini",
    "enbseries.ini",
    "enbseries",
    "enbcache",
]

RESHADE_ITEMS = [
    "dxgi.dll",
    "ReShade.ini",
    "ReShadeGUI.ini",
    "ReShade.log",
    "reshade-shaders",
    "Farsh_preset.ini",
    "5_1_au_preset.ini",
]

PRESET_RESHADE = "ReShade"
PRESET_ENB = "ENB"
PRESET_COMMUNITY_SHADERS = "CommunityShader"
PRESET_NONE = "None"


class GraphicsManager:
    """Менеджер переключения и изоляции графических модов RFAD SE."""

    def __init__(self, paths: GamePaths) -> None:
        self.paths = paths

    @property
    def root(self) -> Path:
        return self.paths.root

    @property
    def backup_dir(self) -> Path:
        return self.root / ".graphics_backup"

    @property
    def enb_backup_dir(self) -> Path:
        return self.backup_dir / "enb"

    @property
    def reshade_backup_dir(self) -> Path:
        return self.backup_dir / "reshade"

    def disable_enb(self) -> List[str]:
        """
        Изолирует файлы ENBSeries из корня игры в каталог .graphics_backup/enb/.
        Возвращает список перемещенных файлов.
        """
        if not self.root.is_dir():
            return []

        moved: List[str] = []
        self.enb_backup_dir.mkdir(parents=True, exist_ok=True)

        for name in ENB_ITEMS:
            src = self.root / name
            src_disabled = self.root / f"{name}.disabled"

            # 1. Если активный файл/папка лежит в корне
            if src.exists() or src.is_symlink():
                dest = self.enb_backup_dir / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    shutil.move(str(src), str(dest))
                    moved.append(name)
                    logger.info("ENB файл изолирован: %s -> .graphics_backup/enb/", name)
                except Exception as e:
                    logger.warning("Не удалось переместить ENB компонент %s в бэкап: %s", name, e)

            # 2. Если файл был переименован с суффиксом .disabled
            elif src_disabled.exists() or src_disabled.is_symlink():
                dest = self.enb_backup_dir / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    shutil.move(str(src_disabled), str(dest))
                    moved.append(name)
                    logger.info("ENB .disabled файл перемещен в бэкап: %s", name)
                except Exception as e:
                    logger.warning("Не удалось переместить %s в бэкап: %s", src_disabled.name, e)

        return moved

    def enable_enb(self) -> List[str]:
        """
        Восстанавливает файлы ENBSeries из .graphics_backup/enb/ в корень игры.
        Возвращает список восстановленных файлов.
        """
        if not self.root.is_dir():
            return []

        restored: List[str] = []

        # 1. Восстановление из .graphics_backup/enb/
        if self.enb_backup_dir.is_dir():
            for name in ENB_ITEMS:
                src = self.enb_backup_dir / name
                if src.exists() or src.is_symlink():
                    dest = self.root / name
                    try:
                        if dest.exists() or dest.is_symlink():
                            if dest.is_dir() and not dest.is_symlink():
                                shutil.rmtree(dest, ignore_errors=True)
                            else:
                                dest.unlink(missing_ok=True)
                        shutil.move(str(src), str(dest))
                        restored.append(name)
                        logger.info("ENB файл восстановлен в корень: %s", name)
                    except Exception as e:
                        logger.warning("Не удалось восстановить ENB компонент %s: %s", name, e)

        # 2. Восстановление из .disabled в корне игры (если есть)
        for name in ENB_ITEMS:
            src_disabled = self.root / f"{name}.disabled"
            if src_disabled.exists() or src_disabled.is_symlink():
                dest = self.root / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    src_disabled.rename(dest)
                    restored.append(name)
                    logger.info("ENB файл переименован обратно: %s", name)
                except Exception as e:
                    logger.warning("Не удалось переименовать %s: %s", src_disabled.name, e)

        return restored

    def disable_reshade(self) -> List[str]:
        """
        Изолирует файлы ReShade из корня игры в каталог .graphics_backup/reshade/.
        Возвращает список перемещенных файлов.
        """
        if not self.root.is_dir():
            return []

        moved: List[str] = []
        self.reshade_backup_dir.mkdir(parents=True, exist_ok=True)

        for name in RESHADE_ITEMS:
            src = self.root / name
            src_disabled = self.root / f"{name}.disabled"

            # 1. Если активный файл/папка лежит в корне
            if src.exists() or src.is_symlink():
                dest = self.reshade_backup_dir / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    shutil.move(str(src), str(dest))
                    moved.append(name)
                    logger.info("ReShade файл изолирован: %s -> .graphics_backup/reshade/", name)
                except Exception as e:
                    logger.warning("Не удалось переместить ReShade компонент %s в бэкап: %s", name, e)

            # 2. Если файл был переименован с суффиксом .disabled
            elif src_disabled.exists() or src_disabled.is_symlink():
                dest = self.reshade_backup_dir / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    shutil.move(str(src_disabled), str(dest))
                    moved.append(name)
                    logger.info("ReShade .disabled файл перемещен в бэкап: %s", name)
                except Exception as e:
                    logger.warning("Не удалось переместить %s в бэкап: %s", src_disabled.name, e)

        return moved

    def enable_reshade(self) -> List[str]:
        """
        Восстанавливает файлы ReShade из .graphics_backup/reshade/ в корень игры.
        Возвращает список восстановленных файлов.
        """
        if not self.root.is_dir():
            return []

        restored: List[str] = []

        # 1. Восстановление из .graphics_backup/reshade/
        if self.reshade_backup_dir.is_dir():
            for name in RESHADE_ITEMS:
                src = self.reshade_backup_dir / name
                if src.exists() or src.is_symlink():
                    dest = self.root / name
                    try:
                        if dest.exists() or dest.is_symlink():
                            if dest.is_dir() and not dest.is_symlink():
                                shutil.rmtree(dest, ignore_errors=True)
                            else:
                                dest.unlink(missing_ok=True)
                        shutil.move(str(src), str(dest))
                        restored.append(name)
                        logger.info("ReShade файл восстановлен в корень: %s", name)
                    except Exception as e:
                        logger.warning("Не удалось восстановить ReShade компонент %s: %s", name, e)

        # 2. Восстановление из .disabled в корне игры (если есть)
        for name in RESHADE_ITEMS:
            src_disabled = self.root / f"{name}.disabled"
            if src_disabled.exists() or src_disabled.is_symlink():
                dest = self.root / name
                try:
                    if dest.exists() or dest.is_symlink():
                        if dest.is_dir() and not dest.is_symlink():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    src_disabled.rename(dest)
                    restored.append(name)
                    logger.info("ReShade файл переименован обратно: %s", name)
                except Exception as e:
                    logger.warning("Не удалось переименовать %s: %s", src_disabled.name, e)

        return restored

    def set_community_shaders_enabled(self, enabled: bool) -> None:
        """Включает или выключает Community Shaders в modlist.txt MO2."""
        profiles_dir = self.root / "MO2" / "profiles"
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

    def apply_graphic_preset(self, preset: str) -> None:
        """
        Применяет выбранный графический пресет:
        - 'ReShade': активен только ReShade, ENB изолирован в .graphics_backup/enb/
        - 'ENB': активен только ENB, ReShade изолирован в .graphics_backup/reshade/
        - 'CommunityShader': активен только Community Shaders, ENB и ReShade изолированы
        - 'None' / 'Vanilla' / 'Оригинальная (Без модов)': отключены и ENB, и ReShade
        """
        norm = (preset or "").strip()

        if norm in ("ReShade", "reshade"):
            self.enable_reshade()
            self.disable_enb()
            self.set_community_shaders_enabled(False)
            logger.info("[Графика] Активирован только ReShade. Файлы ENB изолированы.")

        elif norm in ("ENB", "enb"):
            self.enable_enb()
            self.disable_reshade()
            self.set_community_shaders_enabled(False)
            logger.info("[Графика] Активирован ENB. Файлы ReShade изолированы.")

        elif norm in ("CommunityShader", "Community Shaders"):
            self.disable_enb()
            self.disable_reshade()
            self.set_community_shaders_enabled(True)
            logger.info("[Графика] Активирован Community Shaders. ENB и ReShade изолированы.")

        else:  # None / Vanilla / Оригинальная (Без модов)
            self.disable_enb()
            self.disable_reshade()
            self.set_community_shaders_enabled(False)
            logger.info("[Графика] Ванильный режим. Все графические инжекторы изолированы.")

    def get_status(self) -> dict:
        """Возвращает информацию о текущем состоянии графических файлов в корне игры."""
        return {
            "has_enb_active": (self.root / "d3d11.dll").is_file(),
            "has_reshade_active": (self.root / "dxgi.dll").is_file(),
            "has_enb_backup": self.enb_backup_dir.is_dir() and any(self.enb_backup_dir.iterdir()),
            "has_reshade_backup": self.reshade_backup_dir.is_dir() and any(self.reshade_backup_dir.iterdir()),
        }
