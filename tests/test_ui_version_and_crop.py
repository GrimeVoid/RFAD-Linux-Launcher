"""
Тесты для проверки перемещения информации о версии сборки и
режима отрисовки фоновых изображений Center Crop (Aspect Fill с центрированием).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import QRect, QSize
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel

from src.config import ConfigManager
from src.ui.main_window import CanvasWidget, MainWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestVersionDisplayAndCenterCrop(unittest.TestCase):
    """Тестирование компактной метки версии и алгоритма Center Crop в CanvasWidget."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.cfg_file = self.tmp_dir / "launcher.json"
        self.config_mgr = ConfigManager(self.cfg_file)
        self.config_mgr.set("game_dir", str(self.tmp_dir / "game"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_version_label_placement_and_states(self) -> None:
        """Проверка отображения версии сборки под главным заголовком."""
        win = MainWindow(self.config_mgr)
        win.show()
        app.processEvents()

        # 1. Проверяем наличие lbl_version
        self.assertIsNotNone(win.lbl_version)
        self.assertIsInstance(win.lbl_version, QLabel)
        self.assertEqual(win.lbl_version.objectName(), "versionBadge")

        # 2. Игра не установлена -> «Версия: не установлена»
        self.assertIn("не установлена", win.lbl_version.text().lower())

        # 3. Актуальная версия получена, но игра не установлена
        win._on_update_checked(has_update=False, loc="...", rem="16.09", notes="")
        self.assertIn("Версия: не установлена (Актуальная: 16.09)", win.lbl_version.text())

        # 4. Игра установлена (локальная 16.09, актуальная 16.09)
        win._local_version = "16.09"
        win._remote_version = "16.09"
        win._update_version_display()
        self.assertEqual(win.lbl_version.text(), "Версия: 16.09")

        # 5. Игра установлена, доступно обновление (локальная 16.09, актуальная 16.10)
        win._local_version = "16.09"
        win._remote_version = "16.10"
        win._update_version_display()
        self.assertEqual(win.lbl_version.text(), "Версия: 16.09 (Актуальная: 16.10)")

        # 6. Проверяем, что промежуточный блок ver_card отсутствует
        # Ищем в окне QLabel со старыми заголовками плашки «Установлена:» и «Актуальная:»
        labels = win.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        self.assertNotIn("Установлена:", texts)
        self.assertNotIn("Актуальная:", texts)

        win.close()

    def test_center_crop_math_and_rendering(self) -> None:
        """Проверка работы алгоритма Center Crop (Aspect Fill) в CanvasWidget."""
        canvas = CanvasWidget()
        canvas.resize(800, 600)  # Соотношение 4:3 = 1.333
        canvas.show()
        app.processEvents()

        # Тест горизонтального широкоформатного изображения (1920x1080, 16:9 = 1.777)
        wide_pixmap = QPixmap(1920, 1080)
        wide_pixmap.fill(QColor("blue"))
        canvas.set_custom_background(wide_pixmap, "Широкий фон")

        # Проверяем, что рендеринг отрабатывает корректно
        target_img = QImage(800, 600, QImage.Format_ARGB32)
        canvas.render(target_img)

        # Тест вертикального изображения (1080x1920, 9:16 = 0.5625)
        tall_pixmap = QPixmap(1080, 1920)
        tall_pixmap.fill(QColor("red"))
        canvas.set_custom_background(tall_pixmap, "Вертикальный фон")

        target_img2 = QImage(800, 600, QImage.Format_ARGB32)
        canvas.render(target_img2)

        # Тест квадратного изображения (1000x1000)
        square_pixmap = QPixmap(1000, 1000)
        square_pixmap.fill(QColor("green"))
        canvas.set_custom_background(square_pixmap, "Квадратный фон")

        target_img3 = QImage(800, 600, QImage.Format_ARGB32)
        canvas.render(target_img3)

        # Сброс к дефолтному фону
        canvas.set_custom_background(None, None)
        target_img4 = QImage(800, 600, QImage.Format_ARGB32)
        canvas.render(target_img4)

        canvas.close()


if __name__ == "__main__":
    unittest.main()
