"""
Модуль окна настроек лаунчера RFAD.
Содержит диалог управления путями, графикой, Wine и комплексным
профилем оптимизации оборудования (NVIDIA Prime Offload, многопоточность CPU, Linux Gaming Kernel & Proton).
"""

from __future__ import annotations
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import ConfigManager
from src.core.mods import ModManager
from src.core.paths import GamePaths

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Окно настроек игры, окружения Wine и профиля оптимизации оборудования."""

    def __init__(self, parent: QWidget, config_mgr: ConfigManager, paths: GamePaths) -> None:
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.paths = paths
        self.setWindowTitle("Настройки RFAD Launcher")
        self.resize(620, 520)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        title = QLabel("Настройки RFAD Launcher")
        title.setObjectName("sectionTitle")
        main_layout.addWidget(title)

        # Вкладки настроек
        tabs = QTabWidget()

        # === Вкладка 1: Оптимизация оборудования ===
        tab_hw = QWidget()
        hw_layout = QVBoxLayout(tab_hw)
        hw_layout.setContentsMargins(14, 14, 14, 14)
        hw_layout.setSpacing(12)

        hw_card = QFrame()
        hw_card.setObjectName("card")
        c_layout = QVBoxLayout(hw_card)
        c_layout.setSpacing(10)

        hw_header = QLabel("Оптимизация оборудования (NVIDIA Prime & CPU)")
        hw_header.setObjectName("sectionTitle")
        c_layout.addWidget(hw_header)

        hw_sub = QLabel(
            "Гибридная графика (NVIDIA Prime Offload), многопоточность CPU, "
            "Linux Gaming Kernel (NTSync/FSync) и Proton."
        )
        hw_sub.setObjectName("secondaryLabel")
        hw_sub.setWordWrap(True)
        c_layout.addWidget(hw_sub)

        # 1. NVIDIA Prime Offload
        self.chk_nvidia_prime = QCheckBox("Принудительный запуск на дискретной GPU NVIDIA (Prime Offload)")
        self.chk_nvidia_prime.setChecked(self.config_mgr.get_optimization("nvidia_prime", True))
        c_layout.addWidget(self.chk_nvidia_prime)
        lbl_prime_hint = QLabel("   __NV_PRIME_RENDER_OFFLOAD=1: Задействует дискретную видеокарту NVIDIA вместо встроенной графики (iGPU)")
        lbl_prime_hint.setObjectName("dimLabel")
        c_layout.addWidget(lbl_prime_hint)

        # 2. DXVK Async
        self.chk_dxvk_async = QCheckBox("Асинхронная компиляция шейдеров (DXVK Async против фризов)")
        self.chk_dxvk_async.setChecked(self.config_mgr.get_optimization("dxvk_async", True))
        c_layout.addWidget(self.chk_dxvk_async)
        lbl_async_hint = QLabel("   DXVK_ASYNC=1, dxvk.enableAsync, 4 потока компиляции для устранения статтеров")
        lbl_async_hint.setObjectName("dimLabel")
        c_layout.addWidget(lbl_async_hint)

        # 3. Persistent Shader Cache
        self.chk_persistent_shader_cache = QCheckBox("Кэширование шейдеров NVIDIA (10 ГБ)")
        self.chk_persistent_shader_cache.setChecked(self.config_mgr.get_optimization("persistent_shader_cache", True))
        c_layout.addWidget(self.chk_persistent_shader_cache)
        lbl_cache_hint = QLabel("   __GL_SHADER_DISK_CACHE_SIZE=10GB в ~/.cache/nvidia/GLCache без авто-очистки")
        lbl_cache_hint.setObjectName("dimLabel")
        c_layout.addWidget(lbl_cache_hint)

        # 4. FSync / NT-Sync (CachyOS)
        self.chk_cachyos_ntsync = QCheckBox("FSync / NT-Sync (CachyOS)")
        self.chk_cachyos_ntsync.setChecked(self.config_mgr.get_optimization("cachyos_ntsync", True))
        c_layout.addWidget(self.chk_cachyos_ntsync)
        lbl_sync_hint = QLabel("   WINE_FSYNC=1, WINE_NT_SYNC=1: Высокопроизводительная синхронизация потоков на ядре CachyOS")
        lbl_sync_hint.setObjectName("dimLabel")
        c_layout.addWidget(lbl_sync_hint)

        # 5. GameMode
        self.chk_gamemode = QCheckBox("GameMode (производительность CPU)")
        self.chk_gamemode.setChecked(self.config_mgr.get_optimization("gamemode", True))
        c_layout.addWidget(self.chk_gamemode)
        lbl_gm_hint = QLabel("   gamemoderun: Перевод процессора (CPU) в режим 'performance' governor и снижение задержек")
        lbl_gm_hint.setObjectName("dimLabel")
        c_layout.addWidget(lbl_gm_hint)

        hw_layout.addWidget(hw_card)
        hw_layout.addStretch()
        tabs.addTab(tab_hw, "Оптимизация оборудования")


        # === Вкладка 2: Графика и система ===
        tab_general = QWidget()
        gen_layout = QVBoxLayout(tab_general)
        gen_layout.setContentsMargins(14, 14, 14, 14)
        gen_layout.setSpacing(12)

        # Путь к сборке
        path_box = QFrame()
        path_box.setObjectName("card")
        p_layout = QVBoxLayout(path_box)
        p_layout.addWidget(QLabel("Каталог сборки игры (RFAD):"))
        p_h = QHBoxLayout()
        self.txt_game_dir = QLineEdit(str(self.paths.root))
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_dir)
        p_h.addWidget(self.txt_game_dir)
        p_h.addWidget(btn_browse)
        p_layout.addLayout(p_h)
        gen_layout.addWidget(path_box)

        # Опции оверлеев и окружения
        opts_box = QFrame()
        opts_box.setObjectName("card")
        o_layout = QVBoxLayout(opts_box)

        self.chk_mangohud = QCheckBox("Оверлей MangoHud (FPS, температуры)")
        self.chk_mangohud.setChecked(self.config_mgr.get("mangohud", False))
        o_layout.addWidget(self.chk_mangohud)

        self.chk_gamescope = QCheckBox("Запуск через Gamescope")
        self.chk_gamescope.setChecked(self.config_mgr.get("gamescope", False))
        o_layout.addWidget(self.chk_gamescope)

        self.chk_fsr = QCheckBox("Wine Fullscreen FSR")
        self.chk_fsr.setChecked(self.config_mgr.get("fsr", False))
        o_layout.addWidget(self.chk_fsr)

        self.chk_shader_cache = QCheckBox("Базовый кэш шейдеров (DXVK State Cache)")
        self.chk_shader_cache.setChecked(self.config_mgr.get("shader_cache", True))
        o_layout.addWidget(self.chk_shader_cache)

        self.chk_steam_fix = QCheckBox("Steam Fix (эмуляция Steam DRM)")
        self.chk_steam_fix.setChecked(self.config_mgr.get("steam_drm", False))
        o_layout.addWidget(self.chk_steam_fix)

        self.chk_random_bg = QCheckBox("Случайный фон при запуске (из модов меню и экранов загрузки)")
        self.chk_random_bg.setChecked(self.config_mgr.get("random_background", True))
        o_layout.addWidget(self.chk_random_bg)

        fps_h = QHBoxLayout()
        fps_h.addWidget(QLabel("Лимит FPS (DXVK_FRAME_RATE):"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(0, 360)
        self.spin_fps.setValue(self.config_mgr.get("fps_limit", 60))
        fps_h.addWidget(self.spin_fps)
        fps_h.addStretch()
        o_layout.addLayout(fps_h)

        gen_layout.addWidget(opts_box)
        gen_layout.addStretch()
        tabs.addTab(tab_general, "Графика и пути")


        main_layout.addWidget(tabs)

        # Кнопка сохранения
        btn_save = QPushButton("Сохранить настройки")
        btn_save.setObjectName("accentAction")
        btn_save.clicked.connect(self._save)
        main_layout.addWidget(btn_save)

    def _browse_dir(self) -> None:
        sel = QFileDialog.getExistingDirectory(self, "Выберите папку RFAD", self.txt_game_dir.text())
        if sel:
            self.txt_game_dir.setText(sel)

    def _save(self) -> None:
        # Сохранение базовых настроек
        self.config_mgr.set("game_dir", self.txt_game_dir.text())
        self.config_mgr.set("mangohud", self.chk_mangohud.isChecked())
        self.config_mgr.set("gamescope", self.chk_gamescope.isChecked())
        self.config_mgr.set("fsr", self.chk_fsr.isChecked())
        self.config_mgr.set("shader_cache", self.chk_shader_cache.isChecked())
        self.config_mgr.set("steam_drm", self.chk_steam_fix.isChecked())
        self.config_mgr.set("random_background", self.chk_random_bg.isChecked())
        self.config_mgr.set("fps_limit", self.spin_fps.value())

        # Сохранение профиля оптимизации оборудования
        self.config_mgr.set_optimization("nvidia_prime", self.chk_nvidia_prime.isChecked())
        self.config_mgr.set_optimization("dxvk_async", self.chk_dxvk_async.isChecked())
        self.config_mgr.set_optimization("persistent_shader_cache", self.chk_persistent_shader_cache.isChecked())
        self.config_mgr.set_optimization("cachyos_ntsync", self.chk_cachyos_ntsync.isChecked())
        self.config_mgr.set_optimization("gamemode", self.chk_gamemode.isChecked())

        # Немедленное применение настройки Steam DRM (если сборка установлена и содержит файлы фикса)
        try:
            updated_paths = GamePaths(self.txt_game_dir.text())
            ModManager(updated_paths).set_steam_drm(self.chk_steam_fix.isChecked())
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("Не удалось применить Steam DRM фикс при сохранении настроек: %s", e)

        logger.info("Настройки лаунчера и профиль оптимизации оборудования успешно сохранены.")
        self.accept()
