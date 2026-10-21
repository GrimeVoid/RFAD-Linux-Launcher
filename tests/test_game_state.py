"""
Тесты проверки состояния установки игры и переключения UI в RFAD Launcher.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

# Устанавливаем оффлайн/offscreen платформу для PyQt5 тестов
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtWidgets import QApplication

from src.config import ConfigManager
from src.core.paths import GamePaths
from src.core.installer import find_default_installer
from src.ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestGameStateAndUI(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.game_root = Path(self.temp_dir.name) / "RFAD"
        self.config_file = Path(self.temp_dir.name) / "launcher.json"

        # Создаем временный конфигурационный файл
        self.config = ConfigManager(self.config_file)
        self.config.set("game_dir", str(self.game_root))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_installer_auto_discovery(self):
        """Проверка автопоиска инсталлятора в изолированном домашнем каталоге."""
        fake_home = Path(self.temp_dir.name) / "fake_home"
        dl_dir = fake_home / "Downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        fake_exe = dl_dir / "RfaD SE 6.2.exe"
        fake_exe.touch()

        with patch("src.core.installer.Path.home", return_value=fake_home):
            inst = find_default_installer()
            self.assertIsNotNone(inst)
            self.assertTrue(inst.is_file())
            self.assertEqual(inst.resolve(), fake_exe.resolve())
            self.assertTrue("rfad" in inst.name.lower())

    def test_paths_is_game_installed(self):
        """Проверка детекции установки в GamePaths."""
        paths = GamePaths(self.game_root)
        # 1. Папка не существует
        self.assertFalse(paths.is_game_installed)

        # 2. Папка создана, но файлов нет
        self.game_root.mkdir(parents=True, exist_ok=True)
        self.assertFalse(paths.is_game_installed)

        # 3. Есть только SkyrimSE.exe
        (self.game_root / "SkyrimSE.exe").touch()
        self.assertFalse(paths.is_game_installed)

        # 4. Есть и SkyrimSE.exe, и MO2/ModOrganizer.exe
        mo2_dir = self.game_root / "MO2"
        mo2_dir.mkdir(parents=True, exist_ok=True)
        (mo2_dir / "ModOrganizer.exe").touch()
        self.assertTrue(paths.is_game_installed)

        # 5. Проверка резолвера BethINI.exe
        self.assertIsNone(paths.bethini_exe)
        bethini_dir = self.game_root / "BethINI Standalone"
        bethini_dir.mkdir(parents=True, exist_ok=True)
        bethini_file = bethini_dir / "BethINI.exe"
        bethini_file.touch()
        self.assertEqual(paths.bethini_exe, bethini_file)

    def test_ui_dynamic_switch_install_and_play(self):
        """Проверка динамического переключения UI лаунчера между УСТАНОВИТЬ и ИГРАТЬ."""
        window = MainWindow(self.config)

        # 1. Игра НЕ установлена
        self.assertEqual(window.btn_play.text(), "  УСТАНОВИТЬ")
        self.assertEqual(window.btn_play.objectName(), "mainInstallBtn")
        self.assertTrue(window.btn_play.isEnabled())
        self.assertFalse(window.btn_mo2.isEnabled())
        self.assertFalse(window.btn_bethini.isEnabled())
        self.assertIn("Сборка не установлена", window.status_box.text())

        # 2. Теперь симулируем установку игры (без BethINI)
        self.game_root.mkdir(parents=True, exist_ok=True)
        (self.game_root / "SkyrimSE.exe").touch()
        mo2_dir = self.game_root / "MO2"
        mo2_dir.mkdir(parents=True, exist_ok=True)
        (mo2_dir / "ModOrganizer.exe").touch()

        # Вызываем проверку состояния (как при клике по любой кнопке или после установки)
        is_installed = window._check_and_refresh_state()
        self.assertTrue(is_installed)

        # Теперь кнопка переключилась в режим ИГРАТЬ
        self.assertEqual(window.btn_play.text(), "  ИГРАТЬ")
        self.assertEqual(window.btn_play.objectName(), "mainPlayBtn")

        # 3. Симулируем появление BethINI.exe
        bethini_dir = self.game_root / "BethINI Standalone"
        bethini_dir.mkdir(parents=True, exist_ok=True)
        (bethini_dir / "BethINI.exe").touch()

        # Инициализируем префикс для ready=True
        pfx_drive_c = self.game_root / "wine" / "prefix" / "pfx" / "drive_c"
        pfx_drive_c.mkdir(parents=True, exist_ok=True)
        wine_bin = self.game_root / "wine" / "bin" / "wine"
        wine_bin.parent.mkdir(parents=True, exist_ok=True)
        wine_bin.touch()

        window._check_and_refresh_state()
        self.assertTrue(window.btn_mo2.isEnabled())
        self.assertTrue(window.btn_bethini.isEnabled())

        # 4. Симулируем удаление/перемещение SkyrimSE.exe
        (self.game_root / "SkyrimSE.exe").unlink()
        is_installed = window._check_and_refresh_state()
        self.assertFalse(is_installed)

        # Кнопка мгновенно вернулась в режим УСТАНОВИТЬ
        self.assertEqual(window.btn_play.text(), "  УСТАНОВИТЬ")
        self.assertEqual(window.btn_play.objectName(), "mainInstallBtn")
        self.assertTrue(window.btn_play.isEnabled())

        self.assertFalse(window.btn_mo2.isEnabled())
        self.assertFalse(window.btn_bethini.isEnabled())

        window.close()

    def test_setup_choice_dialog(self):
        """Проверка инициализации и констант диалога SetupChoiceDialog."""
        from src.ui.main_window import SetupChoiceDialog
        dialog = SetupChoiceDialog()
        self.assertEqual(dialog.CHOICE_INSTALL, 1)
        self.assertEqual(dialog.CHOICE_IMPORT, 2)
        dialog.close()

    @patch("src.core.paths.GamePaths.check_readiness", return_value=(True, "OK"))
    @patch("src.ui.main_window.QMessageBox.information")
    @patch("src.ui.main_window.QFileDialog.getExistingDirectory")
    def test_import_existing_build_success(self, mock_file_dialog, mock_info, mock_ready):
        """Проверка успешного импорта существующей папки с игрой."""
        imported_dir = Path(self.temp_dir.name) / "MyCustomRFAD"
        imported_dir.mkdir(parents=True, exist_ok=True)
        (imported_dir / "SkyrimSE.exe").touch()
        (imported_dir / "MO2").mkdir(parents=True, exist_ok=True)
        (imported_dir / "MO2" / "ModOrganizer.exe").touch()

        mock_file_dialog.return_value = str(imported_dir)

        window = MainWindow(self.config)
        self.assertEqual(window.btn_play.text(), "  УСТАНОВИТЬ")

        success = window._import_existing_build()
        self.assertTrue(success)

        # Конфигурация обновилась
        self.assertEqual(Path(self.config.get("game_dir")).resolve(), imported_dir.resolve())
        # Лаунчер переключился в режим ИГРАТЬ
        self.assertTrue(window.paths.is_game_installed)
        self.assertEqual(window.btn_play.text(), "  ИГРАТЬ")
        self.assertTrue(window.btn_play.isEnabled())

        self.assertTrue(window.btn_mo2.isEnabled())

        window.close()

    @patch("src.ui.main_window.QFileDialog.getExistingDirectory")
    def test_import_existing_build_cancelled(self, mock_file_dialog):
        """Проверка отмены диалога выбора папки при импорте."""
        mock_file_dialog.return_value = ""

        window = MainWindow(self.config)
        initial_game_dir = self.config.get("game_dir")

        success = window._import_existing_build()
        self.assertFalse(success)
        self.assertEqual(self.config.get("game_dir"), initial_game_dir)

        window.close()

    @patch("src.ui.main_window.QMessageBox.information")
    @patch("src.ui.main_window.QFileDialog.getExistingDirectory")
    def test_import_parent_folder_auto_detect(self, mock_file_dialog, mock_info):
        """Проверка авто-детекции подпапки RFAD при выборе родительского каталога."""
        parent_dir = Path(self.temp_dir.name) / "GamesRoot"
        rfad_sub = parent_dir / "RFAD"
        rfad_sub.mkdir(parents=True, exist_ok=True)
        (rfad_sub / "SkyrimSE.exe").touch()
        (rfad_sub / "MO2").mkdir(parents=True, exist_ok=True)
        (rfad_sub / "MO2" / "ModOrganizer.exe").touch()

        mock_file_dialog.return_value = str(parent_dir)

        window = MainWindow(self.config)
        success = window._import_existing_build()
        self.assertTrue(success)

        # Путь скорректирован на rfad_sub
        self.assertEqual(Path(self.config.get("game_dir")).resolve(), rfad_sub.resolve())
        self.assertTrue(window.paths.is_game_installed)
        self.assertEqual(window.btn_play.text(), "  ИГРАТЬ")

        window.close()


    @patch("src.ui.main_window.QMessageBox.warning")
    @patch("src.ui.main_window.QFileDialog.getExistingDirectory")
    def test_import_missing_files_warning_rejected(self, mock_file_dialog, mock_warning):
        """Проверка отклонения импорта при отсутствии файлов игры."""
        from PyQt5.QtWidgets import QMessageBox
        empty_dir = Path(self.temp_dir.name) / "EmptyFolder"
        empty_dir.mkdir(parents=True, exist_ok=True)

        mock_file_dialog.return_value = str(empty_dir)
        mock_warning.return_value = QMessageBox.No

        window = MainWindow(self.config)
        initial_dir = self.config.get("game_dir")

        success = window._import_existing_build()
        self.assertFalse(success)
        self.assertEqual(self.config.get("game_dir"), initial_dir)
        mock_warning.assert_called_once()

        window.close()

    @patch("subprocess.Popen")
    def test_game_runner_launch_bethini(self, mock_popen):
        """Проверка запуска BethINI через GameRunner."""
        from src.core.runner import GameRunner
        mock_proc = unittest.mock.MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        # Создаем файлы сборки и BethINI
        self.game_root.mkdir(parents=True, exist_ok=True)
        bethini_dir = self.game_root / "BethINI Standalone"
        bethini_dir.mkdir(parents=True, exist_ok=True)
        bethini_file = bethini_dir / "BethINI.exe"
        bethini_file.touch()

        wine_bin = self.game_root / "wine" / "bin" / "wine"
        wine_bin.parent.mkdir(parents=True, exist_ok=True)
        wine_bin.touch()

        pfx_drive_c = self.game_root / "wine" / "prefix" / "pfx" / "drive_c"
        pfx_drive_c.mkdir(parents=True, exist_ok=True)

        paths = GamePaths(self.game_root)
        runner = GameRunner(paths, {})

        proc = runner.launch_bethini()
        self.assertEqual(proc.pid, 12345)
        mock_popen.assert_called_once()
        cmd_called = mock_popen.call_args[0][0]
        self.assertIn(str(paths.wine_bin), cmd_called)
        self.assertIn(str(bethini_file), cmd_called)
        # Проверяем, что рабочая директория - каталог BethINI
        self.assertEqual(mock_popen.call_args[1]["cwd"], str(bethini_dir))


if __name__ == "__main__":
    unittest.main()



