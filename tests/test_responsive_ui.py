"""
Тесты адаптивности пользовательского интерфейса (Responsive UI) под тайловые композиторы (Niri/Wayland).
Проверяют отсутствие наложения и конфликтов геометрии кнопок при динамическом изменении размеров окна.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Включаем offscreen-режим для тестов Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from src.config import ConfigManager
from src.ui.main_window import ActionButtonsWidget, MainWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestResponsiveUI(unittest.TestCase):
    """Набор тестов адаптивности и масштабирования интерфейса лаунчера."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = ConfigManager(Path(self.temp_dir.name) / "launcher.json")
        self.window = MainWindow(self.config)
        self.window.show()

    def tearDown(self) -> None:
        self.window.close()
        self.temp_dir.cleanup()

    def test_window_minimum_size_for_niri(self) -> None:
        """Проверка, что окно лаунчера имеет строгий минимальный размер 960x580 для Niri."""
        min_size = self.window.minimumSize()
        self.assertGreaterEqual(min_size.width(), 960, "Минимальная ширина окна должна быть не менее 960px")
        self.assertGreaterEqual(min_size.height(), 580, "Минимальная высота окна должна быть не менее 580px")

    def test_no_button_overlaps_on_window_resizing(self) -> None:
        """
        Проверка отсутствия физического перекрытия между кнопками центральной панели (btn_play, btn_gear)
        и кнопками левой панели (btn_mo2, btn_bethini, btn_fix) при различных размерах окна.
        """
        resolutions = [
            (1920, 1080),  # Полноэкранный Full HD
            (1440, 900),   # Ноутбуки и 16:10
            (1280, 720),   # HD
            (1120, 680),   # Стандартный размер лаунчера
            (1020, 640),   # Ранее проблемный размер, где происходил наезд
            (960, 580),    # Ровно половина 1080p экрана в Niri
            (800, 500),    # Экстремально узкий запрос (окно удерживает свой minimumSize)
        ]

        for w, h in resolutions:
            with self.subTest(width=w, height=h):
                self.window.resize(w, h)
                app.processEvents()

                actual_w = self.window.width()
                actual_h = self.window.height()

                self.assertGreaterEqual(actual_w, 960)
                self.assertGreaterEqual(actual_h, 580)

                g_play = self.window.btn_play.geometry()
                g_gear = self.window.btn_gear.geometry()

                # 1. Центральная панель: btn_play и btn_gear не перекрываются
                self.assertFalse(
                    g_play.intersects(g_gear),
                    f"Кнопки btn_play и btn_gear перекрываются при размере {actual_w}x{actual_h}: "
                    f"play={g_play}, gear={g_gear}",
                )

                # 2. Левая панель: геометрия кнопок navBtn
                g_mo2 = self.window.btn_mo2.geometry()
                g_bethini = self.window.btn_bethini.geometry()
                g_fix = self.window.btn_fix.geometry()

                self.assertFalse(
                    g_mo2.intersects(g_bethini),
                    f"Кнопки btn_mo2 и btn_bethini перекрываются при размере {actual_w}x{actual_h}",
                )
                self.assertFalse(
                    g_bethini.intersects(g_fix),
                    f"Кнопки btn_bethini и btn_fix перекрываются при размере {actual_w}x{actual_h}",
                )
                self.assertFalse(
                    g_mo2.intersects(g_fix),
                    f"Кнопки btn_mo2 и btn_fix перекрываются при размере {actual_w}x{actual_h}",
                )

    def test_button_layout_hierarchy(self) -> None:
        """
        Проверка правильного иерархического порядка кнопок:
        1. Mod Organizer 2 перенесен в левую колонку.
        2. BethINI размещен строго под Mod Organizer 2.
        3. Фикс утилит размещен самым нижним в левой колонке.
        4. В центре строки действий находятся только Играть/Установить и шестеренка настроек.
        """
        app.processEvents()

        # Вертикальные координаты в левой панели
        y_mo2 = self.window.btn_mo2.y()
        y_bethini = self.window.btn_bethini.y()
        y_fix = self.window.btn_fix.y()

        self.assertLess(
            y_mo2, y_bethini,
            "Кнопка BethINI должна быть строго под кнопкой Mod Organizer 2"
        )
        self.assertLess(
            y_bethini, y_fix,
            "Кнопка «Фикс утилит» должна быть самым нижним элементом в левой колонке"
        )

        # Текст кнопок
        self.assertIn("Mod Organizer 2", self.window.btn_mo2.text())
        self.assertIn("BethINI", self.window.btn_bethini.text())
        self.assertIn("Фикс утилит", self.window.btn_fix.text())

        # Центральная строка действий
        self.assertIs(self.window.action_bar.btn_play, self.window.btn_play)
        self.assertIs(self.window.action_bar.btn_gear, self.window.btn_gear)
        self.assertIsNone(self.window.action_bar.btn_extra)

    def test_action_buttons_widget_compact_fallback(self) -> None:
        """
        Проверка прямого адаптивного перестроения ActionButtonsWidget в компактный режим
        при экстремально узкой ширине центральной колонки (< 410px).
        """
        from PyQt5.QtWidgets import QPushButton
        b1 = QPushButton("ИГРАТЬ")
        b2 = QPushButton("MO2")
        b3 = QPushButton("GEAR")
        b1.setMinimumWidth(160)
        b2.setMinimumWidth(160)
        b3.setFixedSize(50, 50)
        standalone_bar = ActionButtonsWidget(b1, b2, b3)
        standalone_bar.show()

        # 1. При ширине >= 410px: обычный однострочный режим
        standalone_bar.resize(460, 64)
        app.processEvents()
        self.assertFalse(standalone_bar._compact_mode)
        self.assertFalse(b1.geometry().intersects(b2.geometry()))
        self.assertFalse(b2.geometry().intersects(b3.geometry()))

        # 2. При ширине < 410px: автоматическое переключение в компактный двухстрочный режим
        standalone_bar.resize(380, 130)
        app.processEvents()
        self.assertTrue(standalone_bar._compact_mode)
        self.assertFalse(b1.geometry().intersects(b2.geometry()))
        self.assertFalse(b2.geometry().intersects(b3.geometry()))
        self.assertFalse(b1.geometry().intersects(b3.geometry()))

        # 3. Экстремально узкий контейнер 260px
        standalone_bar.resize(260, 130)
        app.processEvents()
        self.assertTrue(standalone_bar._compact_mode)
        self.assertFalse(b1.geometry().intersects(b2.geometry()))
        self.assertFalse(b2.geometry().intersects(b3.geometry()))
        self.assertFalse(b1.geometry().intersects(b3.geometry()))
        standalone_bar.close()


if __name__ == "__main__":
    unittest.main()
