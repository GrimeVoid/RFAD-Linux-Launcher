"""
Unit-тесты для подсистемы динамических фонов лаунчера RFAD SE.
Проверяют сканирование модов, конвертацию DDS, дисковое кэширование в PNG,
работу CanvasWidget и интеграцию в главное окно.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap

# Создаем приложение QApplication для поддержки QPixmap в headless-тестах
app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

from src.config import ConfigManager
from src.core.backgrounds import BackgroundInfo, BackgroundManager, MENU_THEME_NAMES
from src.core.paths import GamePaths
from src.ui.main_window import CanvasWidget, MainWindow


class TestBackgroundManager(unittest.TestCase):
    """Тестирование поиска, кэширования и загрузки фонов."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.cache_dir = self.tmp_dir / "cache"
        self.game_dir = self.tmp_dir / "game"
        self.mods_dir = self.game_dir / "MO2" / "mods"
        self.paths = GamePaths(self.game_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_background_info_display_name(self) -> None:
        """Проверка форматирования отображаемого имени BackgroundInfo."""
        info_mm = BackgroundInfo(
            path=Path("/test/mm.dds"),
            title="Чёрный Предел (Blackreach)",
            category="main_menu",
        )
        self.assertEqual(info_mm.display_name, "Главное меню: Чёрный Предел (Blackreach)")

        info_ls = BackgroundInfo(
            path=Path("/test/ls.dds"),
            title="Dagoth Ur",
            category="load_screen",
        )
        self.assertEqual(info_ls.display_name, "Экран загрузки: Dagoth Ur")

    def test_scan_real_rfad_mods_if_available(self) -> None:
        """Проверка сканирования реальных модов сборки RFAD (если они доступны на машине)."""
        real_paths = GamePaths(Path.home() / "Archive" / "_Games_" / "RFAD")
        if real_paths.mods_dir.is_dir():
            bm = BackgroundManager(real_paths, cache_dir=self.cache_dir)
            bgs = bm.get_available_backgrounds()
            self.assertGreater(len(bgs), 50, "Ожидалось обнаружить более 50 обоев и экранов загрузки")

            # Проверяем наличие категорий
            categories = {b.category for b in bgs}
            self.assertIn("main_menu", categories)
            self.assertIn("load_screen", categories)

            # Проверяем выбор случайного фона
            res = bm.get_random_background()
            self.assertIsNotNone(res)
            info, pix = res
            self.assertFalse(pix.isNull())
            self.assertGreater(pix.width(), 500)

            # Проверяем, что создался файл кэша
            cached_files = list(self.cache_dir.glob("*.png"))
            self.assertGreater(len(cached_files), 0, "Конвертированное изображение должно быть сохранено в кэш")

    def test_mock_mods_scanning(self) -> None:
        """Тест сканирования фиктивной структуры модов."""
        # 1. Создаем структуру мода меню
        mm_theme = self.mods_dir / "[RfaD] Main Menu" / "mainmenuwallpapers" / "Blackreach" / "DATA" / "textures" / "interface" / "objects"
        mm_theme.mkdir(parents=True, exist_ok=True)

        # Создаем валидную тестовую картинку PNG и сохраняем
        img = Image.new("RGBA", (128, 128), color=(100, 150, 200, 255))
        img.save(mm_theme / "MAINMENUWALLPAPER.png")
        # Создаем служебный файл, который должен быть проигнорирован
        img.save(mm_theme / "vis.png")

        # 2. Создаем структуру загрузочных экранов
        ls_folder = self.mods_dir / "RfaD - Load Screens" / "textures"
        ls_folder.mkdir(parents=True, exist_ok=True)
        img.save(ls_folder / "LG-cardart-Miraak.png")

        bm = BackgroundManager(self.paths, cache_dir=self.cache_dir)
        bgs = bm.get_available_backgrounds()

        self.assertEqual(len(bgs), 2)
        names = [b.title for b in bgs]
        self.assertIn(MENU_THEME_NAMES["blackreach"], names)
        self.assertIn("Miraak", names)

    def test_get_next_background_cycles_differently(self) -> None:
        """Проверка того, что get_next_background возвращает другой фон при наличии нескольких."""
        folder = self.mods_dir / "RfaD - Load Screens" / "textures"
        folder.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGBA", (64, 64), color="red")
        img.save(folder / "LG-cardart-Card1.png")
        img.save(folder / "LG-cardart-Card2.png")

        bm = BackgroundManager(self.paths, cache_dir=self.cache_dir)
        first_info, _ = bm.get_random_background()
        next_res = bm.get_next_background(current_path=first_info.path)
        self.assertIsNotNone(next_res)
        next_info, _ = next_res
        self.assertNotEqual(next_info.path, first_info.path)

    def test_convert_dds_letterbox_and_resize(self) -> None:
        """Проверка логики crop для текстур с letterboxing и resize для полноразмерных текстур."""
        bm = BackgroundManager(self.paths, cache_dir=self.cache_dir)

        # 1. Текстура с letterboxing (черные поля сверху и снизу, полезный арт 16:9 в центре)
        # Размер 1000x1000. В центре полоса Y от 218 до 780 (высота 562, соотношение 1000/562 ~ 1.779)
        letterbox_img = Image.new("RGBA", (1000, 1000), (0, 0, 0, 255))
        for y in range(219, 781):
            for x in range(1000):
                letterbox_img.putpixel((x, y), (200, 100, 50, 255))
        lb_path = self.tmp_dir / "test_lb.dds"
        # Сохраняем как DDS (или через прямой вызов _convert_dds_to_pixmap, PIL умеет DDS)
        letterbox_img.save(lb_path, format="DDS")

        pix_lb = bm._convert_dds_to_pixmap(lb_path)
        self.assertIsNotNone(pix_lb)
        self.assertEqual(pix_lb.width(), 1000)
        self.assertEqual(pix_lb.height(), 562)

        # 2. Полноразмерная квадратная текстура (загрузочный экран без полей)
        full_img = Image.new("RGBA", (1000, 1000), (200, 100, 50, 255))
        full_path = self.tmp_dir / "test_full.dds"
        full_img.save(full_path, format="DDS")

        pix_full = bm._convert_dds_to_pixmap(full_path)
        self.assertIsNotNone(pix_full)
        self.assertEqual(pix_full.width(), 1000)
        self.assertEqual(pix_full.height(), 562)  # round(1000 * 9 / 16) = 562


class TestCanvasWidgetAndUI(unittest.TestCase):
    """Тестирование CanvasWidget и интеграции динамических фонов в MainWindow."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.cfg_file = self.tmp_dir / "launcher.json"
        self.config_mgr = ConfigManager(self.cfg_file)
        self.config_mgr.set("game_dir", str(Path.home() / "Archive" / "_Games_" / "RFAD"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_canvas_widget_set_custom_background(self) -> None:
        """Проверка работы set_custom_background в CanvasWidget."""
        canvas = CanvasWidget()
        self.assertIsNone(canvas.custom_bg_pixmap)

        pix = QPixmap(100, 100)
        pix.fill()
        canvas.set_custom_background(pix, "Тестовый фон")

        self.assertIsNotNone(canvas.custom_bg_pixmap)
        self.assertEqual(canvas.custom_bg_title, "Тестовый фон")

        # Сброс
        canvas.set_custom_background(None, None)
        self.assertIsNone(canvas.custom_bg_pixmap)

    def test_main_window_background_actions(self) -> None:
        """Проверка методов _load_initial_background, _cycle_background и _reset_background_to_default."""
        win = MainWindow(self.config_mgr)

        # 1. Проверяем, что при старте установился случайный фон (если моды доступны)
        if win.bg_mgr.get_available_backgrounds():
            self.assertIsNotNone(win.canvas.custom_bg_pixmap)
            self.assertIsNotNone(win.current_bg_info)

            # 2. Переключение на следующий фон
            prev_path = win.current_bg_info.path
            win._cycle_background()
            self.assertIsNotNone(win.current_bg_info)
            self.assertTrue(self.config_mgr.get("random_background"))

            # 3. Сброс к дефолтному фону
            win._reset_background_to_default()
            self.assertIsNone(win.canvas.custom_bg_pixmap)
            self.assertIsNone(win.current_bg_info)
            self.assertFalse(self.config_mgr.get("random_background"))

            # 4. Повторное переключение возвращает динамический фон
            win._cycle_background()
            self.assertIsNotNone(win.canvas.custom_bg_pixmap)
            self.assertTrue(self.config_mgr.get("random_background"))

        win.close()


if __name__ == "__main__":
    unittest.main()
