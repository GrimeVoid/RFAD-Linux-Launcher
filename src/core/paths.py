"""
Модуль разрешения путей сборки RFAD.
Исключает хардкод и динамически определяет пути к компонентам Wine, Proton, MO2 и игре.
Автоматически обнаруживает установленные версии GE-Proton в Heroic и Steam.
"""

from __future__ import annotations
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class GamePaths:
    """Умный резолвер путей внутри каталога сборки RFAD."""

    def __init__(self, root: Optional[str | Path] = None) -> None:
        if not root or not str(root).strip():
            from src.config import _get_default_game_dir
            root = _get_default_game_dir()
        self.root = Path(root).expanduser().resolve()

    @property
    def is_valid_root(self) -> bool:
        """Проверяет, существует ли директория игры."""
        return self.root.is_dir()

    @property
    def mo2_exe(self) -> Path:
        """Путь к исполняемому файлу Mod Organizer 2."""
        return self.root / "MO2" / "ModOrganizer.exe"

    @property
    def bethini_exe(self) -> Optional[Path]:
        """Путь к исполняемому файлу BethINI.exe (BethINI Standalone или tools/BethINI)."""
        candidates = [
            self.root / "BethINI Standalone" / "BethINI.exe",
            self.root / "tools" / "BethINI" / "BethINI.exe",
            self.root / "BethINI" / "BethINI.exe",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return None

    @property
    def mods_dir(self) -> Path:
        """Путь к каталогу модов Mod Organizer 2."""
        return self.root / "MO2" / "mods"

    @property
    def skyrim_exe(self) -> Path:
        """Путь к исполняемому файлу SkyrimSE.exe."""
        return self.root / "SkyrimSE.exe"

    @property
    def skse_exe(self) -> Path:
        """Путь к skse64_loader.exe."""
        return self.root / "skse64_loader.exe"

    @property
    def is_game_installed(self) -> bool:
        """
        Проверяет, установлена ли игра по целевому пути.
        Требуется существование директории root и ключевых исполняемых файлов:
        - SkyrimSE.exe
        - MO2/ModOrganizer.exe
        """
        return self.is_valid_root and self.skyrim_exe.is_file() and self.mo2_exe.is_file()

    def auto_link_proton(self) -> Optional[Path]:
        """
        Если в RFAD/wine/proton нет Proton, ищет установленный GE-Proton
        в Heroic или Steam и создает аккуратный симлинк.
        """
        if not self.is_valid_root:
            return None

        target_proton = self.root / "wine" / "proton"
        if (target_proton / "files" / "bin" / "wine").is_file():
            return target_proton

        proton_search_dirs = [
            Path.home() / ".config" / "heroic" / "tools" / "proton",
            Path.home() / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic" / "tools" / "proton",
            Path.home() / ".local" / "share" / "Steam" / "compatibilitytools.d",
        ]
        for search_dir in proton_search_dirs:
            if search_dir.is_dir():
                for p in sorted(search_dir.iterdir(), reverse=True):
                    if (p / "files" / "bin" / "wine").is_file():
                        try:
                            target_proton.parent.mkdir(parents=True, exist_ok=True)
                            if target_proton.is_symlink():
                                target_proton.unlink()
                            if not target_proton.exists():
                                target_proton.symlink_to(p)
                                logger.info("Создан симлинк на Proton: %s -> %s", target_proton, p)
                                return target_proton
                        except Exception as e:
                            logger.warning("Не удалось создать симлинк на Proton: %s", e)
                        return p

        return None

    @property
    def wine_bin(self) -> Optional[Path]:
        """
        Ищет бинарник wine/wine64 в комплекте сборки (GE-Proton),
        в Heroic/Steam или в системном PATH (Nix).
        """
        # Сначала пробуем авто-линковку Proton из Heroic/Steam
        self.auto_link_proton()

        candidates: List[Path] = [
            self.root / "wine" / "proton" / "files" / "bin" / "wine",
            self.root / "wine" / "proton" / "files" / "bin" / "wine64",
            self.root / "wine" / "files" / "bin" / "wine",
            self.root / "wine" / "files" / "bin" / "wine64",
            self.root / "wine" / "bin" / "wine",
            self.root / "wine" / "bin" / "wine64",
        ]

        # Поиск в Heroic и Steam Proton
        proton_search_dirs = [
            Path.home() / ".config" / "heroic" / "tools" / "proton",
            Path.home() / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic" / "tools" / "proton",
            Path.home() / ".local" / "share" / "Steam" / "compatibilitytools.d",
        ]
        for s_dir in proton_search_dirs:
            if s_dir.is_dir():
                for p in sorted(s_dir.iterdir(), reverse=True):
                    candidates.append(p / "files" / "bin" / "wine")

        for cand in candidates:
            if cand.is_file():
                return cand

        # Резервный системный Wine (из Nix или дистрибутива)
        sys_wine = shutil.which("wine")
        if sys_wine:
            return Path(sys_wine)

        return None

    @property
    def proton_files_dir(self) -> Optional[Path]:
        """
        Каталог файлов Proton (содержит bin, lib, lib64).
        Ищется динамически среди стандартных вариантов раскладки.
        """
        candidates = [
            self.root / "wine" / "proton" / "files",
            self.root / "wine" / "files",
            self.root / "wine",
        ]

        # Heroic и Steam Proton
        proton_search_dirs = [
            Path.home() / ".config" / "heroic" / "tools" / "proton",
            Path.home() / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic" / "tools" / "proton",
            Path.home() / ".local" / "share" / "Steam" / "compatibilitytools.d",
        ]
        for s_dir in proton_search_dirs:
            if s_dir.is_dir():
                for p in sorted(s_dir.iterdir(), reverse=True):
                    candidates.append(p / "files")

        for p in candidates:
            if p.is_dir() and (p / "bin").is_dir():
                return p
        return None

    @property
    def wine_prefix(self) -> Optional[Path]:
        """
        Динамически определяет путь к WINEPREFIX.
        Устраняет расхождения между wine/prefix/pfx, wine/prefix и wine/pfx.
        """
        candidates = [
            self.root / "wine" / "prefix" / "pfx",
            self.root / "wine" / "prefix",
            self.root / "wine" / "pfx",
            self.root / "prefix" / "pfx",
            self.root / "prefix",
        ]

        # 1. Приоритет: каталог, в котором уже присутствует инициализированный drive_c
        for cand in candidates:
            if (cand / "drive_c").is_dir():
                return cand

        # 2. Второй приоритет: любой существующий каталог префикса
        for cand in candidates:
            if cand.is_dir():
                return cand

        # 3. Дефолт по умолчанию для чистой сборки RFAD GE-Proton
        return self.root / "wine" / "prefix" / "pfx"

    @property
    def local_version_file(self) -> Path:
        """Путь к файлу version.txt внутри мода патча."""
        return self.root / "MO2" / "mods" / "RFAD_PATCH" / "version.txt"

    def get_local_version(self) -> str:
        """Возвращает текущую установленную версию патча RFAD."""
        vf = self.local_version_file
        if not vf.is_file():
            return "0.0"
        try:
            content = vf.read_text(encoding="utf-8-sig", errors="ignore").strip()
            return content if content else "0.0"
        except Exception as e:
            logger.warning("Не удалось прочитать локальную версию: %s", e)
            return "0.0"

    def check_readiness(self) -> Tuple[bool, str]:
        """
        Комплексно проверяет готовность сборки к запуску.
        Возвращает кортеж (is_ready, message).
        """
        if not self.is_valid_root:
            return False, f"Каталог игры не найден: {self.root}"

        if not self.skyrim_exe.is_file():
            return False, f"SkyrimSE.exe не найден по пути: {self.skyrim_exe}"

        if not self.mo2_exe.is_file():
            return False, f"ModOrganizer.exe не найден по пути: {self.mo2_exe}"

        if not self.wine_bin:
            return False, "Бинарник Wine не найден ни в комплекте сборки, ни в системе."

        pfx = self.wine_prefix
        if not pfx or not (pfx / "drive_c").is_dir():
            return False, "Префикс Wine ещё не настроен (требуется инициализация окружения)."

        return True, "Сборка готова к запуску"
