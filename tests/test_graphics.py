"""
Тесты для модуля управления графическими пресетами GraphicsManager.
Проверяют изоляцию и восстановление файлов ENBSeries и ReShade.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from src.core.graphics import GraphicsManager
from src.core.paths import GamePaths


class TestGraphicsManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.game_root = Path(self.temp_dir.name)
        self.paths = GamePaths(str(self.game_root))
        self.gfx = GraphicsManager(self.paths)

        # Создаем файлы ENB
        (self.game_root / "d3d11.dll").write_text("ENB_DLL", encoding="utf-8")
        (self.game_root / "enblocal.ini").write_text("[ENB]", encoding="utf-8")
        (self.game_root / "enbseries.ini").write_text("[GLOBAL]", encoding="utf-8")
        (self.game_root / "enbseries").mkdir()
        (self.game_root / "enbseries" / "enbeffect.fx").write_text("// shader", encoding="utf-8")
        (self.game_root / "enbcache").mkdir()

        # Создаем файлы ReShade
        (self.game_root / "dxgi.dll").write_text("RESHADE_DLL", encoding="utf-8")
        (self.game_root / "ReShade.ini").write_text("[GENERAL]", encoding="utf-8")
        (self.game_root / "reshade-shaders").mkdir()
        (self.game_root / "reshade-shaders" / "test.fx").write_text("// fx", encoding="utf-8")
        (self.game_root / "Farsh_preset.ini").write_text("[PRESET]", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_apply_reshade_preset_isolates_enb(self):
        """При выборе ReShade в корне должен остаться только ReShade, ENB изолируется."""
        self.gfx.apply_graphic_preset("ReShade")

        # ENB файлы должны исчезнуть из корня
        self.assertFalse((self.game_root / "d3d11.dll").exists())
        self.assertFalse((self.game_root / "enblocal.ini").exists())
        self.assertFalse((self.game_root / "enbseries.ini").exists())
        self.assertFalse((self.game_root / "enbseries").exists())
        self.assertFalse((self.game_root / "enbcache").exists())

        # ENB файлы должны быть сохранены в .graphics_backup/enb/
        enb_bak = self.game_root / ".graphics_backup" / "enb"
        self.assertTrue((enb_bak / "d3d11.dll").is_file())
        self.assertTrue((enb_bak / "enblocal.ini").is_file())
        self.assertTrue((enb_bak / "enbseries.ini").is_file())
        self.assertTrue((enb_bak / "enbseries" / "enbeffect.fx").is_file())

        # ReShade файлы должны остаться в корне
        self.assertTrue((self.game_root / "dxgi.dll").is_file())
        self.assertTrue((self.game_root / "ReShade.ini").is_file())
        self.assertTrue((self.game_root / "reshade-shaders" / "test.fx").is_file())

    def test_apply_enb_preset_isolates_reshade(self):
        """При переключении на ENB должны восстановиться файлы ENB, а ReShade изолируется."""
        # Сначала включаем ReShade
        self.gfx.apply_graphic_preset("ReShade")
        self.assertFalse((self.game_root / "d3d11.dll").exists())

        # Теперь переключаем на ENB
        self.gfx.apply_graphic_preset("ENB")

        # ENB файлы вернулись в корень
        self.assertTrue((self.game_root / "d3d11.dll").is_file())
        self.assertTrue((self.game_root / "enblocal.ini").is_file())
        self.assertTrue((self.game_root / "enbseries" / "enbeffect.fx").is_file())

        # ReShade файлы перемещены в бэкап
        self.assertFalse((self.game_root / "dxgi.dll").exists())
        self.assertFalse((self.game_root / "ReShade.ini").exists())
        self.assertFalse((self.game_root / "reshade-shaders").exists())

        reshade_bak = self.game_root / ".graphics_backup" / "reshade"
        self.assertTrue((reshade_bak / "dxgi.dll").is_file())
        self.assertTrue((reshade_bak / "ReShade.ini").is_file())
        self.assertTrue((reshade_bak / "reshade-shaders" / "test.fx").is_file())

    def test_apply_none_preset_isolates_both(self):
        """При выборе 'None' изолируются и ENB, и ReShade."""
        self.gfx.apply_graphic_preset("None")

        self.assertFalse((self.game_root / "d3d11.dll").exists())
        self.assertFalse((self.game_root / "dxgi.dll").exists())
        self.assertFalse((self.game_root / "enbseries").exists())
        self.assertFalse((self.game_root / "reshade-shaders").exists())

        # Оба пресета в бэкапе
        self.assertTrue((self.game_root / ".graphics_backup" / "enb" / "d3d11.dll").is_file())
        self.assertTrue((self.game_root / ".graphics_backup" / "reshade" / "dxgi.dll").is_file())

    def test_recovery_from_disabled_files(self):
        """Корректная обработка файлов с расширением .disabled."""
        # Переименовываем d3d11.dll в d3d11.dll.disabled
        (self.game_root / "d3d11.dll").rename(self.game_root / "d3d11.dll.disabled")
        self.gfx.disable_enb()

        # Файл должен попасть в бэкап как d3d11.dll
        enb_bak = self.game_root / ".graphics_backup" / "enb"
        self.assertTrue((enb_bak / "d3d11.dll").is_file())
        self.assertFalse((self.game_root / "d3d11.dll.disabled").exists())


if __name__ == "__main__":
    unittest.main()
