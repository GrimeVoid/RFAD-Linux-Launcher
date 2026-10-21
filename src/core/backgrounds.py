"""
Модуль динамических фоновых изображений лаунчера RFAD SE.
Обнаруживает фоны главного меню и загрузочные экраны из модов MO2
([RfaD] Main Menu, RFAD_PATCH, RfaD - Load Screens),
выполняет быстрое кэширование DDS-текстур в PNG и предоставляет случайные фоны.
"""

from __future__ import annotations
import hashlib
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None
from PyQt5.QtGui import QImage, QPixmap

from src.core.paths import GamePaths

logger = logging.getLogger(__name__)

# Словарь человекочитаемых названий тем главного меню
MENU_THEME_NAMES = {
    "blackreach": "Чёрный Предел (Blackreach)",
    "darkbrotherhood": "Тёмное Братство (Dark Brotherhood)",
    "flyingdragon": "Парящий Дракон (Flying Dragon)",
    "forestfantasy": "Лесная Фантазия (Forest Fantasy)",
    "snowriver": "Снежная Река (Snow River)",
    "windycreek": "Ветреный Ручей (Windy Creek)",
    "b": "Атака Дракона (Dragon Attack)",
    "bright_1": "Яркий Рассвет I (Bright 1)",
    "bright_2": "Яркий Рассвет II (Bright 2)",
    "c": "Тема C",
    "d": "Тема D",
    "v": "Тема V",
}

# Исключаемые служебные текстуры эффектов (частицы, дымка)
EXCLUDED_TEXTURE_NAMES = {
    "vim.dds",
    "vis.dds",
    "vsstr.dds",
    "vvis.dds",
    "visc.dds",
}


@dataclass
class BackgroundInfo:
    """Метаданные доступного фонового изображения."""
    path: Path
    title: str
    category: str  # 'main_menu', 'load_screen', 'custom'

    @property
    def display_name(self) -> str:
        cat_ru = {
            "main_menu": "Главное меню",
            "load_screen": "Экран загрузки",
            "custom": "Пользовательский арт",
        }.get(self.category, self.category)
        return f"{cat_ru}: {self.title}"


class BackgroundManager:
    """Управление коллекцией обоев, загрузочных экранов и их кэшированием."""

    def __init__(self, paths: GamePaths, cache_dir: Optional[Path] = None) -> None:
        self.paths = paths
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "rfad-launcher" / "backgrounds")
        self._cached_list: Optional[List[BackgroundInfo]] = None

    def invalidate_cache(self) -> None:
        """Сбрасывает кэшированный список найденных обоев."""
        self._cached_list = None

    def get_available_backgrounds(self, refresh: bool = False) -> List[BackgroundInfo]:
        """
        Сканирует моды и пользовательские каталоги на наличие фоновых изображений.
        Возвращает список доступных BackgroundInfo.
        """
        if self._cached_list is not None and not refresh:
            return self._cached_list

        backgrounds: List[BackgroundInfo] = []
        mods_dir = self.paths.mods_dir

        if mods_dir.is_dir():
            # 1. Поиск обоев главного меню в mainmenuwallpapers
            backgrounds.extend(self._scan_main_menu_wallpapers(mods_dir))

            # 2. Поиск загрузочных экранов в RfaD - Load Screens и аналогичных модах
            backgrounds.extend(self._scan_load_screens(mods_dir))

        # 3. Пользовательские фоны из ~/.config/rfad-launcher/wallpapers
        user_wallpapers_dir = Path.home() / ".config" / "rfad-launcher" / "wallpapers"
        if user_wallpapers_dir.is_dir():
            backgrounds.extend(self._scan_custom_wallpapers(user_wallpapers_dir))

        self._cached_list = backgrounds
        logger.info("Обнаружено доступных фонов RFAD: %d", len(backgrounds))
        return self._cached_list

    def _scan_main_menu_wallpapers(self, mods_dir: Path) -> List[BackgroundInfo]:
        """Поиск обоев главного меню в папках mainmenuwallpapers."""
        results: List[BackgroundInfo] = []
        for mod_folder in mods_dir.iterdir():
            if not mod_folder.is_dir():
                continue
            mm_dir = mod_folder / "mainmenuwallpapers"
            if not mm_dir.is_dir():
                continue

            for theme_dir in mm_dir.iterdir():
                if not theme_dir.is_dir():
                    continue
                theme_key = theme_dir.name.lower()
                theme_title = MENU_THEME_NAMES.get(theme_key, theme_dir.name)

                # Ищем текстуры внутри папки темы
                for f in theme_dir.glob("**/*"):
                    if not f.is_file():
                        continue
                    fname_lower = f.name.lower()
                    if fname_lower in EXCLUDED_TEXTURE_NAMES:
                        continue
                    if f.suffix.lower() in (".dds", ".png", ".jpg", ".jpeg"):
                        if "wallpaper" in fname_lower or "dragonattack" in fname_lower:
                            results.append(
                                BackgroundInfo(
                                    path=f,
                                    title=theme_title,
                                    category="main_menu",
                                )
                            )
                            break  # Одной главной текстуры на тему достаточно
        return results

    def _scan_load_screens(self, mods_dir: Path) -> List[BackgroundInfo]:
        """Поиск загрузочных экранов из мода RfaD - Load Screens."""
        results: List[BackgroundInfo] = []
        for mod_folder in mods_dir.iterdir():
            if not mod_folder.is_dir():
                continue
            folder_name_lower = mod_folder.name.lower()
            if "load" not in folder_name_lower and "screen" not in folder_name_lower:
                continue

            for f in mod_folder.glob("**/*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in (".dds", ".png", ".jpg", ".jpeg"):
                    continue
                fname_lower = f.name.lower()
                # Фильтруем файлы с артами карт TES Legends и квестовыми экранами
                if fname_lower.startswith(("lg-cardart-", "lg-quest-", "on-", "lg-")):
                    stem = f.stem
                    # Очищаем префиксы для красивого отображения
                    clean_title = re.sub(r"^(LG-cardart-|LG-quest-|ON-|lg-|LG-)", "", stem, flags=re.IGNORECASE)
                    clean_title = clean_title.replace("_", " ").strip()
                    results.append(
                        BackgroundInfo(
                            path=f,
                            title=clean_title,
                            category="load_screen",
                        )
                    )
        return results

    def _scan_custom_wallpapers(self, folder: Path) -> List[BackgroundInfo]:
        """Поиск картинок в каталоге пользователя."""
        results: List[BackgroundInfo] = []
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".dds"):
                clean_title = f.stem.replace("_", " ").strip()
                results.append(
                    BackgroundInfo(
                        path=f,
                        title=clean_title,
                        category="custom",
                    )
                )
        return results

    def clear_cache(self) -> None:
        """Удаляет все кэшированные PNG файлы фонов."""
        if self.cache_dir.is_dir():
            for f in self.cache_dir.glob("*.png"):
                try:
                    f.unlink()
                except OSError as e:
                    logger.warning("Не удалось удалить файл кэша %s: %s", f, e)

    def load_pixmap(self, bg_info: BackgroundInfo) -> Optional[QPixmap]:
        """
        Загружает изображение в QPixmap.
        Для DDS производит прозрачную конвертацию и дисковое кэширование в PNG.
        """
        path = bg_info.path
        if not path.is_file():
            logger.warning("Файл фона не найден: %s", path)
            return None

        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            pix = QPixmap(str(path))
            if not pix.isNull():
                return pix

        if path.suffix.lower() == ".dds":
            return self._convert_dds_to_pixmap(path)

        return None

    def _convert_dds_to_pixmap(self, dds_path: Path) -> Optional[QPixmap]:
        """
        Конвертирует DDS в QPixmap с надежным дисковым кэшированием в ~/.cache.
        Текстуры меню и загрузочных экранов Skyrim, сохраненные в квадратных степенях
        двойки (2048x2048, 4096x4096), восстанавливаются в исходное соотношение сторон 16:9.
        """
        if Image is None:
            logger.warning("Библиотека Pillow не установлена. Пропуск конвертации DDS %s", dds_path)
            return None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            stat = dds_path.stat()
            key = f"{dds_path.resolve()}_{stat.st_mtime}_{stat.st_size}_16x9"
            cache_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            cache_file = self.cache_dir / f"bg_{cache_hash}.png"

            # 1. Быстрая загрузка из кэша
            if cache_file.is_file():
                pix = QPixmap(str(cache_file))
                if not pix.isNull():
                    return pix

            # 2. Конвертация через Pillow с восстановлением правильных пропорций 16:9
            with Image.open(dds_path) as im:
                rgba = im.convert("RGBA")
                w, h = rgba.size

                # В Skyrim движок требует размеры степеней двойки (POT: 2048x2048, 4096x4096).
                # В темах меню (mainmenuwallpapers) широкоформатный арт 16:9 обычно центрируют с черными полосами (letterboxing).
                # А в экранах загрузки (Load Screens) широкоформатный арт часто сплющивают во весь квадрат без полей.
                if h > 0 and 0.85 <= (w / h) <= 1.15:
                    rgb = rgba.convert("RGB")
                    bbox = rgb.getbbox()
                    cropped = False
                    if bbox:
                        bw = bbox[2] - bbox[0]
                        bh = bbox[3] - bbox[1]
                        if bh > 0:
                            bbox_aspect = bw / bh
                            has_vertical_bars = (bbox[1] > 50 or bbox[3] < h - 50)
                            if has_vertical_bars and 1.5 <= bbox_aspect <= 2.0:
                                # Текстура содержит черные полосы сверху/снизу (letterboxing) и уже имеет соотношение 16:9.
                                # Обрезаем черные полосы для получения чистого широкоформатного изображения без сплющивания.
                                rgba = rgba.crop(bbox)
                                cropped = True

                    if not cropped:
                        # Текстура заполнена целиком (как загрузочные экраны) - восстанавливаем 16:9 пропорции растяжением/сжатием
                        target_w = w
                        target_h = int(round(w * 9.0 / 16.0))
                        rgba = rgba.resize((target_w, target_h), Image.Resampling.LANCZOS)

                try:
                    rgba.save(cache_file, format="PNG", optimize=False)
                    pix = QPixmap(str(cache_file))
                    if not pix.isNull():
                        return pix
                except Exception as save_err:
                    logger.warning("Не удалось записать в кэш обоев %s: %s", cache_file, save_err)

                # Резервная конвертация напрямую в память
                data = rgba.tobytes("raw", "RGBA")
                qimg = QImage(data, rgba.size[0], rgba.size[1], QImage.Format_RGBA8888)
                pix = QPixmap.fromImage(qimg)
                if not pix.isNull():
                    return pix
        except Exception as e:
            logger.error("Ошибка при чтении текстуры DDS %s: %s", dds_path, e)

        return None

    def get_random_background(self) -> Optional[Tuple[BackgroundInfo, QPixmap]]:
        """
        Выбирает случайный фон из доступных и возвращает (BackgroundInfo, QPixmap).
        Если список пуст или файлы недоступны, возвращает None.
        """
        backgrounds = self.get_available_backgrounds()
        if not backgrounds:
            return None

        # Пробуем до 3 случайных попыток на случай поврежденного файла
        shuffled = random.sample(backgrounds, min(len(backgrounds), 5))
        for bg in shuffled:
            pix = self.load_pixmap(bg)
            if pix and not pix.isNull():
                return bg, pix

        return None

    def get_next_background(
        self, current_path: Optional[Path] = None
    ) -> Optional[Tuple[BackgroundInfo, QPixmap]]:
        """
        Выбирает следующий случайный фон, отличный от текущего.
        """
        backgrounds = self.get_available_backgrounds()
        if not backgrounds:
            return None

        candidates = [b for b in backgrounds if b.path != current_path]
        if not candidates:
            candidates = backgrounds

        shuffled = random.sample(candidates, min(len(candidates), 5))
        for bg in shuffled:
            pix = self.load_pixmap(bg)
            if pix and not pix.isNull():
                return bg, pix

        return None
