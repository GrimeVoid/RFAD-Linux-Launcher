"""
Модульные тесты для проверки профиля аппаратной оптимизации лаунчера RFAD
(Гибридная графика NVIDIA Prime Offload, многопоточность CPU, Linux Gaming Kernel & Proton).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import DEFAULT_CONFIG, ConfigManager
from src.core.paths import GamePaths
from src.core.runner import GameRunner


class TestHardwareOptimizations(unittest.TestCase):
    """Тестирование профиля оптимизации оборудования и формирования переменных окружения."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Создаем фиктивную структуру сборки RFAD
        self.rfad_root = self.temp_path / "RFAD"
        self.rfad_root.mkdir(parents=True)
        (self.rfad_root / "Data").mkdir()
        (self.rfad_root / "MO2").mkdir()
        (self.rfad_root / "MO2" / "ModOrganizer.exe").touch()

        # Фиктивный префикс Proton/Wine
        self.pfx = self.rfad_root / "prefix"
        self.pfx.mkdir(parents=True)
        (self.pfx / "drive_c").mkdir(parents=True)

        self.paths = GamePaths(self.rfad_root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_config_has_optimizations(self) -> None:
        """Проверка наличия секции optimizations по умолчанию."""
        self.assertIn("optimizations", DEFAULT_CONFIG)
        opts = DEFAULT_CONFIG["optimizations"]
        self.assertTrue(opts["nvidia_prime"])
        self.assertTrue(opts["dxvk_async"])
        self.assertTrue(opts["gamemode"])
        self.assertTrue(opts["persistent_shader_cache"])
        self.assertTrue(opts["cachyos_ntsync"])

    def test_config_manager_migration(self) -> None:
        """Проверка автоматической инициализации optimizations при загрузке старого JSON."""
        old_json_file = self.temp_path / "old_launcher.json"
        old_data = {
            "game_dir": str(self.rfad_root),
            "fps_limit": 60,
            "shader_cache": True,
        }
        with open(old_json_file, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        cfg_mgr = ConfigManager(old_json_file)
        self.assertIn("optimizations", cfg_mgr.data)
        self.assertTrue(cfg_mgr.get_optimization("nvidia_prime"))
        self.assertTrue(cfg_mgr.get_optimization("cachyos_ntsync"))

        # Проверка изменения флага через set_optimization
        cfg_mgr.set_optimization("nvidia_prime", False)
        self.assertFalse(cfg_mgr.get_optimization("nvidia_prime"))

    def test_runner_environment_with_optimizations_enabled(self) -> None:
        """Проверка генерации переменных окружения при включенных аппаратных оптимизациях."""
        config = {
            "fps_limit": 60,
            "shader_cache": True,
            "optimizations": {
                "nvidia_prime": True,
                "dxvk_async": True,
                "gamemode": True,
                "persistent_shader_cache": True,
                "cachyos_ntsync": True,
            },
        }

        runner = GameRunner(self.paths, config)
        env = runner.build_environment()

        # 1. NVIDIA Prime Offload
        self.assertEqual(env.get("__NV_PRIME_RENDER_OFFLOAD"), "1")
        self.assertEqual(env.get("__GLX_VENDOR_LIBRARY_NAME"), "nvidia")
        self.assertEqual(env.get("VKD3D_CONFIG"), "dxr11,dxr")

        # 2. DXVK Async
        self.assertEqual(env.get("DXVK_ASYNC"), "1")
        self.assertEqual(env.get("DXVK_GPLASYNCCACHE"), "1")
        self.assertIn("dxvk.enableAsync = true", env.get("DXVK_CONFIG", ""))
        self.assertIn("dxvk.numCompilerThreads = 4", env.get("DXVK_CONFIG", ""))
        self.assertIn("dxvk.useRawSsbo = True", env.get("DXVK_CONFIG", ""))
        self.assertIn("dxgi.maxFrameLatency = 1", env.get("DXVK_CONFIG", ""))

        # 3. NVIDIA Persistent Shader Cache (10 GB)
        self.assertEqual(env.get("__GL_SHADER_DISK_CACHE"), "1")
        self.assertEqual(env.get("__GL_SHADER_DISK_CACHE_SIZE"), "10737418240")
        self.assertEqual(env.get("__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"), "1")
        self.assertTrue(env.get("__GL_SHADER_DISK_CACHE_PATH", "").endswith("GLCache"))
        self.assertEqual(env.get("DXVK_STATE_CACHE"), "1")

        # 4. CachyOS NTSync / FSync
        self.assertEqual(env.get("WINE_FSYNC"), "1")
        self.assertEqual(env.get("WINE_NT_SYNC"), "1")
        self.assertEqual(env.get("PROTON_NO_ESYNC"), "1")
        self.assertEqual(env.get("PROTON_ENABLE_NVAPI"), "1")

    def test_runner_environment_with_optimizations_disabled(self) -> None:
        """Проверка отключения оптимизаций при установке флагов в False."""
        config = {
            "fps_limit": 60,
            "shader_cache": False,
            "optimizations": {
                "nvidia_prime": False,
                "dxvk_async": False,
                "gamemode": False,
                "persistent_shader_cache": False,
                "cachyos_ntsync": False,
            },
        }

        runner = GameRunner(self.paths, config)
        env = runner.build_environment()

        # NVIDIA Prime отключен
        self.assertNotIn("__NV_PRIME_RENDER_OFFLOAD", env)
        self.assertNotIn("__GLX_VENDOR_LIBRARY_NAME", env)

        # DXVK Async выключен
        self.assertEqual(env.get("DXVK_ASYNC"), "0")
        self.assertEqual(env.get("DXVK_GPLASYNCCACHE"), "0")
        self.assertNotIn("DXVK_CONFIG", env)

        # Кэш шейдеров выключен
        self.assertEqual(env.get("__GL_SHADER_DISK_CACHE"), "0")
        self.assertEqual(env.get("DXVK_STATE_CACHE"), "0")

        # NTSync/FSync не форсируются
        self.assertNotIn("WINE_FSYNC", env)
        self.assertNotIn("WINE_NT_SYNC", env)

    def test_gamemode_prefix(self) -> None:
        """Проверка добавления gamemoderun в цепочку запуска."""
        config_enabled = {
            "gamemode": True,
            "optimizations": {"gamemode": True},
        }
        config_disabled = {
            "gamemode": False,
            "optimizations": {"gamemode": False},
        }

        runner_on = GameRunner(self.paths, config_enabled)
        runner_off = GameRunner(self.paths, config_disabled)

        with patch("shutil.which", return_value="/usr/bin/gamemoderun"):
            self.assertIn("gamemoderun", runner_on.build_command_prefix())
            self.assertNotIn("gamemoderun", runner_off.build_command_prefix())

    def test_settings_dialog_ui(self) -> None:
        """Проверка инициализации и сохранения настроек через SettingsDialog."""
        from PyQt5.QtWidgets import QApplication
        from src.ui.settings_dialog import SettingsDialog

        _ = QApplication.instance() or QApplication([])

        cfg_file = self.temp_path / "test_dialog_launcher.json"
        cfg_mgr = ConfigManager(cfg_file)

        dlg = SettingsDialog(None, cfg_mgr, self.paths)
        # Проверяем, что чекбоксы инициализированы значениями из конфига
        self.assertTrue(dlg.chk_nvidia_prime.isChecked())
        self.assertTrue(dlg.chk_dxvk_async.isChecked())
        self.assertTrue(dlg.chk_persistent_shader_cache.isChecked())
        self.assertTrue(dlg.chk_cachyos_ntsync.isChecked())
        self.assertTrue(dlg.chk_gamemode.isChecked())

        # Меняем значение и сохраняем
        dlg.chk_nvidia_prime.setChecked(False)
        dlg._save()

        # Проверяем, что в конфиге сохранилось новое значение
        self.assertFalse(cfg_mgr.get_optimization("nvidia_prime"))
        self.assertTrue(cfg_mgr.get_optimization("dxvk_async"))
        dlg.close()


if __name__ == "__main__":
    unittest.main()

