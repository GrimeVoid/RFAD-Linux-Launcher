"""
Главное окно лаунчера RFAD SE на PyQt5.
Аутентичный визуальный интерфейс оригинального лаунчера RFAD:
- Гарантированный рендер фона bg.png и арта Matrona.webp через QPainter paintEvent.
- Левая панель: только необходимые ссылки (Discord, База знаний, Папка игры).
- Центральный блок: крупный заголовок RFAD SE 6.2, баннер обновлений (16.09),
  две большие кнопки запуска: [ ▶ ИГРАТЬ ] и [ ⚡ MOD ORGANIZER 2 ], кнопка шестеренки, блок версий.
- Правая колонка: структурированная лента патчноутов с прокруткой.
- Автоматическое восстановление dosdevices c: и z: для исключения зависаний Wine.
"""

from __future__ import annotations
import logging
import os
import re
import subprocess
import urllib.request
import webbrowser
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QRect, QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import ConfigManager
from src.core.backgrounds import BackgroundInfo, BackgroundManager
from src.core.graphics import GraphicsManager
from src.core.installer import SafeInstaller, find_default_installer
from src.core.mods import ModManager
from src.core.paths import GamePaths
from src.core.runner import GameRunner, auto_fix_rfad
from src.core.updater import Updater
from src.ui.styles import ASSETS_DIR, apply_rfad_theme

logger = logging.getLogger(__name__)

ICON_DIR = ASSETS_DIR / "icons" / "png"


URL_DISCORD = "https://discord.gg/q2ygjdk8Gv"
URL_KNOWLEDGE_BASE = "https://docs.google.com/spreadsheets/d/1XsKJBINxQxzXa2TtUoSLqt1Kp0-03Sz2tZ65PlJY94M"


# === Фоновые потоки Worker ===

class InstallWorker(QThread):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, installer_exe: Path, target_dir: Path) -> None:
        super().__init__()
        self.installer_exe = installer_exe
        self.target_dir = target_dir
        self.installer: Optional[SafeInstaller] = None

    def run(self) -> None:
        try:
            self.installer = SafeInstaller(
                self.installer_exe,
                self.target_dir,
                lambda p, m: self.progress.emit(p, m),
            )
            self.installer.run()
            self.finished.emit(True, "Установка RFAD SE успешно завершена!")
        except InterruptedError:
            self.finished.emit(False, "Установка отменена пользователем.")
        except Exception as e:
            logger.exception("Ошибка установки:")
            self.finished.emit(False, str(e))

    def cancel(self) -> None:
        if self.installer:
            self.installer.cancel()


class UpdateCheckWorker(QThread):
    finished = pyqtSignal(bool, str, str, str)

    def __init__(self, paths: GamePaths) -> None:
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        updater = Updater(self.paths)
        has_update, loc, rem = updater.check_for_updates()
        notes = updater.get_patch_notes()
        self.finished.emit(has_update, loc, rem, notes)


class PrefixSetupWorker(QThread):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, paths: GamePaths) -> None:
        super().__init__()
        self.paths = paths
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        from src.core.prefix import PrefixManager
        try:
            pm = PrefixManager(self.paths)
            pm.setup_prefix(
                lambda p, m: self.progress.emit(p, m),
                cancel_check=lambda: self._is_cancelled,
            )
            self.finished.emit(True, "Префикс Wine (.NET 6 / DXVK) успешно настроен!")
        except InterruptedError:
            self.finished.emit(False, "Настройка префикса отменена пользователем.")
        except Exception as e:
            logger.exception("Ошибка настройки префикса Wine:")
            self.finished.emit(False, str(e))


class PatchDownloadWorker(QThread):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, paths: GamePaths) -> None:
        super().__init__()
        self.paths = paths
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            download_dir = self.paths.root / "download"
            download_dir.mkdir(parents=True, exist_ok=True)
            archive_path = download_dir / "16_09_RFAD_PATCH.zip"

            self.progress.emit(0.05, "Подключение к серверу загрузки патча...")
            updater = Updater(self.paths)

            def _on_dl_progress(downloaded: int, total_size: int) -> None:
                if total_size > 0:
                    pct = min(0.75, (downloaded / total_size) * 0.75)
                    mb_cur = downloaded / (1024 * 1024)
                    mb_tot = total_size / (1024 * 1024)
                    self.progress.emit(
                        pct,
                        f"Скачивание патча: {mb_cur:.1f} МБ / {mb_tot:.1f} МБ",
                    )

            updater.download_patch(
                archive_path,
                progress_callback=_on_dl_progress,
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                raise InterruptedError("Загрузка обновления отменена пользователем.")

            self.progress.emit(0.80, "Распаковка и интеграция патча в MO2...")
            updater.apply_patch_archive(
                archive_path,
                lambda p, m: self.progress.emit(0.80 + (p * 0.20), m),
            )
            self.finished.emit(True, "Обновление сборки успешно завершено!")
        except InterruptedError:
            self.finished.emit(False, "Обновление отменено пользователем.")
        except Exception as e:
            logger.exception("Ошибка при загрузке обновления:")
            self.finished.emit(False, str(e))


# === Фоновый холст с артом ===

class CanvasWidget(QWidget):
    """Виджет отрисовки аутентичного фона, арта Матроны или случайных обоев из модов."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.bg_pixmap: Optional[QPixmap] = None
        self.matrona_pixmap: Optional[QPixmap] = None
        self.custom_bg_pixmap: Optional[QPixmap] = None
        self.custom_bg_title: Optional[str] = None
        self._cached_scaled_pixmap: Optional[QPixmap] = None
        self._cached_scaled_key: Optional[tuple] = None

        bg_path = ASSETS_DIR / "bg.png"
        matrona_png = ASSETS_DIR / "Matrona.png"
        matrona_webp = ASSETS_DIR / "Matrona.webp"

        if bg_path.is_file():
            self.bg_pixmap = QPixmap(str(bg_path))
        if matrona_png.is_file():
            self.matrona_pixmap = QPixmap(str(matrona_png))
        elif matrona_webp.is_file():
            self.matrona_pixmap = QPixmap(str(matrona_webp))

    def set_custom_background(self, pixmap: Optional[QPixmap], title: Optional[str] = None) -> None:
        """Устанавливает или сбрасывает динамическое фоновое изображение из модов."""
        self.custom_bg_pixmap = pixmap
        self.custom_bg_title = title
        self._cached_scaled_pixmap = None
        self._cached_scaled_key = None
        self.update()

    def _get_scaled_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Кэширует масштабированный QPixmap под текущий размер виджета для исключения повторных аллокаций."""
        cur_w = self.width()
        cur_h = self.height()
        key = (pixmap.cacheKey(), cur_w, cur_h)
        if self._cached_scaled_pixmap is not None and self._cached_scaled_key == key:
            return self._cached_scaled_pixmap

        scaled = pixmap.scaled(
            cur_w,
            cur_h,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self._cached_scaled_pixmap = scaled
        self._cached_scaled_key = key
        return scaled

    def _draw_center_crop(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        opacity: float = 1.0,
    ) -> None:
        """
        Отрисовывает pixmap с сохранением естественных пропорций (Aspect Fill).
        При изменении размера окна лаунчера динамически меняется масштаб (скейл),
        а картинка мягко центрируется без искажения геометрии.
        """
        if not pixmap or pixmap.isNull():
            return
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        scaled = self._get_scaled_pixmap(pixmap)
        x = (w - scaled.width()) // 2
        y = (h - scaled.height()) // 2

        if opacity < 1.0:
            painter.setOpacity(opacity)
        painter.drawPixmap(x, y, scaled)
        if opacity < 1.0:
            painter.setOpacity(1.0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. Заливка базовым обсидиановым цветом
        painter.fillRect(self.rect(), QColor("#0D0C0A"))

        # 2. Если установлен динамический фон из мода (обои меню или загрузочный экран)
        if self.custom_bg_pixmap and not self.custom_bg_pixmap.isNull():
            self._draw_center_crop(painter, self.custom_bg_pixmap)

            # Атмосферное затемнение для безупречной читаемости текста и золотых кнопок
            painter.fillRect(self.rect(), QColor(13, 12, 10, 115))
        else:
            # 2. Отрисовка дефолтной фоновой текстуры bg.png с легким затемнением в режиме Center Crop
            if self.bg_pixmap and not self.bg_pixmap.isNull():
                self._draw_center_crop(painter, self.bg_pixmap, opacity=0.40)

            # 3. Отрисовка оригинального арта Матроны в правой части при дефолтном фоне
            if self.matrona_pixmap and not self.matrona_pixmap.isNull():
                target_h = int(self.height() * 0.98)
                target_w = target_h
                scaled_matrona = self.matrona_pixmap.scaled(
                    target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                x = self.width() - scaled_matrona.width() + 20
                y = self.height() - scaled_matrona.height()

                painter.setOpacity(0.65)
                painter.drawPixmap(x, y, scaled_matrona)
                painter.setOpacity(1.0)


# === Модальное окно настроек RFAD ===
from src.ui.settings_dialog import SettingsDialog


# === Модальное окно выбора: установка или импорт сборки ===

class SetupChoiceDialog(QDialog):
    """Окно выбора способа настройки: чистая установка или импорт существующей сборки."""

    CHOICE_INSTALL = 1
    CHOICE_IMPORT = 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка RFAD SE 6.2")
        self.resize(540, 290)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Инициализация сборки RFAD SE 6.2")
        title.setObjectName("sectionTitle")
        title.setStyleSheet("font-size: 17px; font-weight: 800; color: #FFEABF;")
        layout.addWidget(title)

        desc = QLabel(
            "Сборка Requiem For A Dream SE не найдена по текущему пути.\n"
            "Выберите желаемый вариант настройки:"
        )
        desc.setObjectName("secondaryLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        options_box = QVBoxLayout()
        options_box.setSpacing(12)

        # Вариант 1: Чистая установка
        btn_install = QPushButton("  Чистая установка сборки")
        btn_install.setIcon(QIcon(str(ICON_DIR / "Package.png")))
        btn_install.setIconSize(QSize(22, 22))
        btn_install.setObjectName("accentAction")
        btn_install.setMinimumHeight(50)
        btn_install.setStyleSheet(
            "font-size: 15px; font-weight: bold; text-align: left; padding-left: 20px;"
        )
        btn_install.setToolTip("Распаковка инсталлятора RfaD SE 6.2.exe в целевой каталог")
        btn_install.clicked.connect(lambda: self.done(self.CHOICE_INSTALL))
        options_box.addWidget(btn_install)

        lbl_inst_sub = QLabel("Распаковка официального инсталлятора через innoextract в новую папку")
        lbl_inst_sub.setObjectName("dimLabel")
        lbl_inst_sub.setStyleSheet("margin-left: 20px; margin-top: -8px; margin-bottom: 4px;")
        options_box.addWidget(lbl_inst_sub)

        # Вариант 2: Импорт готовой сборки
        btn_import = QPushButton("  Импортировать готовую сборку...")
        btn_import.setIcon(QIcon(str(ICON_DIR / "Folder.png")))
        btn_import.setIconSize(QSize(22, 22))
        btn_import.setMinimumHeight(50)
        btn_import.setStyleSheet(
            "font-size: 15px; font-weight: bold; text-align: left; padding-left: 20px; background-color: #1E1A14;"
        )
        btn_import.setToolTip("Выбор существующей папки со сборкой (SkyrimSE.exe, MO2) на диске")
        btn_import.clicked.connect(lambda: self.done(self.CHOICE_IMPORT))
        options_box.addWidget(btn_import)

        lbl_imp_sub = QLabel("Указать каталог с уже установленной игрой и Mod Organizer 2")
        lbl_imp_sub.setObjectName("dimLabel")
        lbl_imp_sub.setStyleSheet("margin-left: 20px; margin-top: -8px;")
        options_box.addWidget(lbl_imp_sub)

        layout.addLayout(options_box)
        layout.addStretch()

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_cancel.setFixedWidth(100)
        bottom_h = QHBoxLayout()
        bottom_h.addStretch()
        bottom_h.addWidget(btn_cancel)
        layout.addLayout(bottom_h)


# === Модальное окно чистой установки ===

class InstallDialog(QDialog):
    """Окно чистой распаковки RFAD из Inno Setup."""

    def __init__(self, parent: QWidget, on_installed_callback) -> None:
        super().__init__(parent)
        self.on_installed_cb = on_installed_callback
        self.worker: Optional[InstallWorker] = None
        self.setWindowTitle("Установка сборки RFAD SE 6.2")
        self.resize(560, 320)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        t = QLabel("Чистая установка RFAD SE (innoextract)")
        t.setObjectName("sectionTitle")
        layout.addWidget(t)

        layout.addWidget(QLabel("Файл установщика (.exe):"))
        inst_h = QHBoxLayout()
        self.txt_installer = QLineEdit()
        found_inst = find_default_installer()
        if found_inst:
            self.txt_installer.setText(str(found_inst))
        btn_b_inst = QPushButton("Обзор...")
        btn_b_inst.clicked.connect(self._browse_installer)
        inst_h.addWidget(self.txt_installer)
        inst_h.addWidget(btn_b_inst)
        layout.addLayout(inst_h)

        layout.addWidget(QLabel("Папка установки (автоматически создаст /RFAD):"))
        tgt_h = QHBoxLayout()
        default_target = str(Path.home() / "Games" / "RFAD")
        if hasattr(self.parent(), "config_mgr"):
            default_target = self.parent().config_mgr.get("game_dir", default_target)
        self.txt_target = QLineEdit(str(default_target))
        btn_b_tgt = QPushButton("Обзор...")
        btn_b_tgt.clicked.connect(self._browse_target)
        tgt_h.addWidget(self.txt_target)
        tgt_h.addWidget(btn_b_tgt)
        layout.addLayout(tgt_h)

        self.btn_start = QPushButton("Начать установку сборки")
        self.btn_start.setObjectName("accentAction")
        self.btn_start.clicked.connect(self._start)
        layout.addWidget(self.btn_start)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setVisible(False)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.lbl_status)

    def _browse_installer(self) -> None:
        sel, _ = QFileDialog.getOpenFileName(self, "Выберите установщик", self.txt_installer.text(), "*.exe")
        if sel:
            self.txt_installer.setText(sel)

    def _browse_target(self) -> None:
        sel = QFileDialog.getExistingDirectory(self, "Выберите папку назначения", self.txt_target.text())
        if sel:
            self.txt_target.setText(sel)

    def _start(self) -> None:
        exe = Path(self.txt_installer.text())
        tgt = Path(self.txt_target.text())
        if not exe.is_file():
            QMessageBox.critical(self, "Ошибка", f"Файл не найден: {exe}")
            return

        self.btn_start.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.lbl_status.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = InstallWorker(exe, tgt)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, p: float, msg: str) -> None:
        self.progress_bar.setValue(int(p * 100))
        self.lbl_status.setText(msg)

    def _on_finished(self, success: bool, msg: str) -> None:
        self.btn_start.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setVisible(False)
        if success:
            QMessageBox.information(self, "Успех", msg)
            final_path = Path(self.txt_target.text())
            if final_path.name != "RFAD":
                final_path = final_path / "RFAD"
            self.on_installed_cb(str(final_path))
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", msg)

    def _cancel_running_worker(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)

    def reject(self) -> None:
        self._cancel_running_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        self._cancel_running_worker()
        super().closeEvent(event)


# === Адаптивный контейнер строки кнопок действий ===

class ActionButtonsWidget(QWidget):
    """
    Адаптивный контейнер для строки действий (ИГРАТЬ / УСТАНОВИТЬ и Настройки).
    Предотвращает наложение элементов друг на друга при любых изменениях размера окна в Niri.
    Поддерживает двухкнопочный режим [ btn_play | btn_gear ] и трёхкнопочный для обратной совместимости.
    """

    def __init__(
        self,
        btn_play: QPushButton,
        btn_second: QPushButton,
        btn_third: Optional[QPushButton] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.btn_play = btn_play

        if btn_third is not None:
            # Трёхкнопочный режим: btn_play, btn_extra, btn_gear
            self.btn_extra: Optional[QPushButton] = btn_second
            self.btn_gear = btn_third
        else:
            # Двухкнопочный режим: btn_play, btn_gear
            self.btn_extra = None
            self.btn_gear = btn_second

        # Совместимость со старыми тестами
        self.btn_mo2 = self.btn_extra

        self.btn_play.setParent(self)
        self.btn_gear.setParent(self)
        if self.btn_extra:
            self.btn_extra.setParent(self)

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)

        self._compact_mode: Optional[bool] = None
        self._apply_layout(compact=False)

    def _apply_layout(self, compact: bool) -> None:
        if self._compact_mode == compact:
            return
        self._compact_mode = compact

        self.grid.removeWidget(self.btn_play)
        self.grid.removeWidget(self.btn_gear)
        if self.btn_extra:
            self.grid.removeWidget(self.btn_extra)

        if self.btn_extra:
            if compact:
                self.grid.addWidget(self.btn_play, 0, 0)
                self.grid.addWidget(self.btn_gear, 0, 1)
                self.grid.addWidget(self.btn_extra, 1, 0, 1, 2)
            else:
                self.grid.addWidget(self.btn_play, 0, 0)
                self.grid.addWidget(self.btn_extra, 0, 1)
                self.grid.addWidget(self.btn_gear, 0, 2)
        else:
            # Двухкнопочный режим: большая кнопка Play и шестеренка настроек
            self.grid.addWidget(self.btn_play, 0, 0)
            self.grid.addWidget(self.btn_gear, 0, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.btn_extra:
            self._apply_layout(compact=event.size().width() < 410)
        else:
            self._apply_layout(compact=False)


# === Основное окно лаунчера ===

class MainWindow(QMainWindow):
    """Главный экран RFAD SE 6.2 Launcher."""

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self.config_mgr = config_manager
        self.paths = GamePaths(self.config_mgr.get("game_dir"))
        self.mod_mgr = ModManager(self.paths)
        self.gfx_mgr = GraphicsManager(self.paths)
        self.bg_mgr = BackgroundManager(self.paths)
        self.current_bg_info: Optional[BackgroundInfo] = None

        self.running_process: Optional[subprocess.Popen] = None
        self.update_worker: Optional[UpdateCheckWorker] = None
        self.prefix_thread: Optional[PrefixSetupWorker] = None
        self.patch_download_thread: Optional[PatchDownloadWorker] = None

        self._local_version: str = "..."
        self._remote_version: str = "..."
        self.lbl_local_ver: QLabel = QLabel("...")
        self.lbl_remote_ver: QLabel = QLabel("...")
        self.lbl_version: Optional[QLabel] = None

        self.setWindowTitle("Requiem For A Dream — SE 6.2")
        self.resize(1120, 680)
        self.setMinimumSize(960, 580)

        icon_path = ASSETS_DIR / "appicon.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Применяем сохраненный пресет графики при инициализации, если игра установлена
        if self.paths.is_game_installed:
            try:
                preset = self.config_mgr.get("graphic_mod", "ReShade")
                self.gfx_mgr.apply_graphic_preset(preset)
            except Exception as e:
                logger.warning("Ошибка начальной синхронизации графики: %s", e)

        self._init_ui()
        self._refresh_status()
        self._load_initial_background()
        self._check_remote_version_background()

    def _init_ui(self) -> None:
        # Корневой виджет с отрисовкой фонового арта
        self.canvas = CanvasWidget(self)
        self.setCentralWidget(self.canvas)

        root_layout = QHBoxLayout(self.canvas)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        # 1. ЛЕВАЯ КОЛОНКА: Навигация и утилиты
        left_panel = QWidget()
        left_panel.setFixedWidth(170)
        left_col = QVBoxLayout(left_panel)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)
        left_col.setAlignment(Qt.AlignTop)

        btn_discord = QPushButton("  Discord")
        btn_discord.setIcon(QIcon(str(ICON_DIR / "Discord.png")))
        btn_discord.setIconSize(QSize(18, 18))
        btn_discord.setObjectName("navBtn")
        btn_discord.setMinimumHeight(42)
        btn_discord.setToolTip("Официальный Discord-сервер RFAD")
        btn_discord.clicked.connect(lambda: webbrowser.open(URL_DISCORD))
        left_col.addWidget(btn_discord)

        btn_db = QPushButton("  База знаний")
        btn_db.setIcon(QIcon(str(ICON_DIR / "OpenBook.png")))
        btn_db.setIconSize(QSize(18, 18))
        btn_db.setObjectName("navBtn")
        btn_db.setMinimumHeight(42)
        btn_db.setToolTip("Google Таблицы с гайдами, квестами и оружием RFAD")
        btn_db.clicked.connect(lambda: webbrowser.open(URL_KNOWLEDGE_BASE))
        left_col.addWidget(btn_db)

        btn_folder = QPushButton("  Папка игры")
        btn_folder.setIcon(QIcon(str(ICON_DIR / "Folder.png")))
        btn_folder.setIconSize(QSize(18, 18))
        btn_folder.setObjectName("navBtn")
        btn_folder.setMinimumHeight(42)
        btn_folder.setToolTip("Открыть каталог RFAD в проводнике")
        btn_folder.clicked.connect(self._open_game_folder)
        left_col.addWidget(btn_folder)

        # Mod Organizer 2
        self.btn_mo2 = QPushButton("  Mod Organizer 2")
        self.btn_mo2.setIcon(QIcon(str(ICON_DIR / "MO2.png")))
        self.btn_mo2.setIconSize(QSize(18, 18))
        self.btn_mo2.setObjectName("navBtn")
        self.btn_mo2.setMinimumHeight(42)
        self.btn_mo2.setToolTip("Запуск Mod Organizer 2")
        self.btn_mo2.clicked.connect(self._on_mo2_clicked)
        left_col.addWidget(self.btn_mo2)

        # BethINI (расположен строго под кнопкой Mod Organizer 2)
        self.btn_bethini = QPushButton("  BethINI")
        self.btn_bethini.setIcon(QIcon(str(ICON_DIR / "BethINI.png")))
        self.btn_bethini.setIconSize(QSize(18, 18))
        self.btn_bethini.setObjectName("navBtn")
        self.btn_bethini.setMinimumHeight(42)
        self.btn_bethini.setToolTip("Запуск BethINI для настройки параметров графики и INI")
        self.btn_bethini.clicked.connect(self._on_bethini_clicked)
        left_col.addWidget(self.btn_bethini)

        # Фикс утилит (самый нижний инструмент в левой панели)
        self.btn_fix = QPushButton("  Фикс утилит")
        self.btn_fix.setIcon(QIcon(str(ICON_DIR / "Wrench.png")))
        self.btn_fix.setIconSize(QSize(18, 18))
        self.btn_fix.setObjectName("navBtn")
        self.btn_fix.setMinimumHeight(42)
        self.btn_fix.setToolTip("Исправить Nemesis, BodySlide & OBody")
        self.btn_fix.clicked.connect(self._run_auto_fix)
        left_col.addWidget(self.btn_fix)

        left_col.addStretch()
        root_layout.addWidget(left_panel)


        # 2. Тонкий вертикальный разделитель
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet("color: #2D271E; width: 1px;")
        root_layout.addWidget(divider)

        # 3. ЦЕНТРАЛЬНАЯ КОЛОНКА (Главная игровая панель)
        center_col = QVBoxLayout()
        center_col.setSpacing(14)

        # Заголовок и версия сборки
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("RFAD SE 6.2")
        title_label.setObjectName("brandTitle")
        title_box.addWidget(title_label)

        self.lbl_version = QLabel("Версия: ...")
        self.lbl_version.setObjectName("versionBadge")
        title_box.addWidget(self.lbl_version)
        center_col.addLayout(title_box)

        # Статус
        self.status_box = QLabel("Проверка файлов...")
        self.status_box.setObjectName("secondaryLabel")
        self.status_box.setWordWrap(True)
        center_col.addWidget(self.status_box)

        # БАННЕР ОБНОВЛЕНИЯ (появляется только если есть новая версия)
        self.update_banner = QFrame()
        self.update_banner.setObjectName("card")
        self.update_banner.setStyleSheet(
            "background-color: rgba(46, 37, 22, 0.95); border: 1px solid #C49742; border-radius: 10px;"
        )
        self.update_banner.setVisible(False)
        ub_lay = QVBoxLayout(self.update_banner)
        self.lbl_update_banner_title = QLabel("Доступно обновление!")
        self.lbl_update_banner_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFEABF;")
        self.lbl_update_banner_title.setWordWrap(True)
        ub_lay.addWidget(self.lbl_update_banner_title)

        ub_btn_row = QHBoxLayout()
        self.btn_download_patch = QPushButton("  Скачать и обновить патч")
        self.btn_download_patch.setIcon(QIcon(str(ICON_DIR / "Download.png")))
        self.btn_download_patch.setIconSize(QSize(18, 18))
        self.btn_download_patch.setObjectName("accentAction")
        self.btn_download_patch.clicked.connect(self._start_patch_download)
        ub_btn_row.addWidget(self.btn_download_patch)

        btn_dismiss = QPushButton("Скрыть")
        btn_dismiss.clicked.connect(lambda: self.update_banner.setVisible(False))
        ub_btn_row.addWidget(btn_dismiss)
        ub_lay.addLayout(ub_btn_row)

        center_col.addWidget(self.update_banner)

        # Прогресс бар
        self.central_progress = QProgressBar()
        self.central_progress.setVisible(False)
        center_col.addWidget(self.central_progress)

        # Кнопка инициализации префикса
        self.btn_init_prefix = QPushButton("ИНИЦИАЛИЗИРОВАТЬ ОКРУЖЕНИЕ WINE (.NET 6 / DXVK)")
        self.btn_init_prefix.setObjectName("accentAction")
        self.btn_init_prefix.setMinimumHeight(44)
        self.btn_init_prefix.clicked.connect(self._init_prefix)
        self.btn_init_prefix.setVisible(False)
        center_col.addWidget(self.btn_init_prefix)

        # КНОПКИ ДЕЙСТВИЙ: [ ИГРАТЬ ] и [ Шестеренка ] (чистая монументальная зона)
        self.btn_play = QPushButton("  ИГРАТЬ")
        self.btn_play.setIcon(QIcon(str(ICON_DIR / "Gamepad.png")))
        self.btn_play.setIconSize(QSize(22, 22))
        self.btn_play.setObjectName("mainPlayBtn")
        self.btn_play.setMinimumHeight(56)
        self.btn_play.setMinimumWidth(180)
        self.btn_play.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_play.setToolTip("Запуск игры через SKSE")
        self.btn_play.clicked.connect(self._on_main_action_clicked)
        self.btn_play.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_play.customContextMenuRequested.connect(self._on_play_btn_context_menu)

        self.btn_gear = QPushButton("")
        self.btn_gear.setIcon(QIcon(str(ICON_DIR / "Cog.png")))
        self.btn_gear.setIconSize(QSize(24, 24))
        self.btn_gear.setObjectName("gearBtn")
        self.btn_gear.setFixedSize(50, 50)
        self.btn_gear.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_gear.clicked.connect(self._show_gear_menu)

        self.action_bar = ActionButtonsWidget(self.btn_play, self.btn_gear)
        center_col.addWidget(self.action_bar)

        # Выбор графического пресета
        gfx_card = QFrame()
        gfx_card.setObjectName("card")
        gfx_h = QHBoxLayout(gfx_card)
        gfx_h.setContentsMargins(14, 10, 14, 10)
        lbl_gfx = QLabel("Графика:")
        lbl_gfx.setStyleSheet("font-weight: 600; color: #FFEABF;")
        gfx_h.addWidget(lbl_gfx)
        self.combo_gfx = QComboBox()
        self.combo_gfx.addItems(["ReShade", "CommunityShader", "ENB", "None"])
        self.combo_gfx.setCurrentText(self.config_mgr.get("graphic_mod", "ReShade"))
        self.combo_gfx.currentTextChanged.connect(self._on_gfx_changed)
        self.combo_gfx.setMinimumWidth(160)
        gfx_h.addWidget(self.combo_gfx)
        gfx_h.addStretch()
        center_col.addWidget(gfx_card)

        center_col.addStretch()
        root_layout.addLayout(center_col, stretch=4)

        # 4. ПРАВАЯ КОЛОНКА: Лента патчноутов
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        patch_header = QLabel("Список изменений")
        patch_header.setObjectName("sectionTitle")
        right_col.addWidget(patch_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(280)
        scroll.setMaximumWidth(360)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

        self.patches_container = QWidget()
        self.patches_layout = QVBoxLayout(self.patches_container)
        self.patches_layout.setContentsMargins(0, 0, 10, 0)
        self.patches_layout.setSpacing(10)
        self.patches_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self.patches_container)
        right_col.addWidget(scroll)

        root_layout.addLayout(right_col, stretch=2)

    def _check_and_refresh_state(self) -> bool:
        """
        Проверяет актуальное состояние установки игры на диске и бесшовно обновляет UI.
        Синхронизирует пути с конфигурацией, проверяет наличие ключевых файлов
        (SkyrimSE.exe, MO2/ModOrganizer.exe) и мгновенно переключает вид и логику кнопок.
        Возвращает True, если игра установлена, иначе False.
        """
        target_dir = self.config_mgr.get("game_dir")
        if self.paths.root != Path(target_dir).expanduser().resolve():
            self.paths = GamePaths(target_dir)
            self.mod_mgr = ModManager(self.paths)
            self.gfx_mgr = GraphicsManager(self.paths)
            self.bg_mgr = BackgroundManager(self.paths)
            self.bg_mgr.invalidate_cache()


        is_installed = self.paths.is_game_installed
        self._refresh_status()
        return is_installed

    def _load_initial_background(self) -> None:
        """Загружает случайный фон при запуске лаунчера, если включена настройка."""
        if not self.config_mgr.get("random_background", True):
            return
        res = self.bg_mgr.get_random_background()
        if res:
            info, pix = res
            self.current_bg_info = info
            self.canvas.set_custom_background(pix, info.display_name)
            logger.info("Установлен случайный фон: %s", info.display_name)

    def _cycle_background(self) -> None:
        """Переключает фон на следующий случайный арт из модов RFAD."""
        curr_path = self.current_bg_info.path if self.current_bg_info else None
        res = self.bg_mgr.get_next_background(curr_path)
        if res:
            info, pix = res
            self.current_bg_info = info
            self.canvas.set_custom_background(pix, info.display_name)
            self.config_mgr.set("random_background", True)
            self.status_box.setText(f"✓ Фон изменен: {info.display_name}")
            logger.info("Пользователь переключил фон: %s", info.display_name)
        else:
            QMessageBox.information(
                self,
                "Фоны не найдены",
                "Не удалось обнаружить фоновые изображения в модах RFAD.\n"
                f"Проверьте каталог модов: {self.paths.mods_dir}",
            )

    def _reset_background_to_default(self) -> None:
        """Сбрасывает фон лаунчера к стандартному оригинальному арту (Матрона)."""
        self.current_bg_info = None
        self.canvas.set_custom_background(None, None)
        self.config_mgr.set("random_background", False)
        self.status_box.setText("✓ Восстановлен оригинальный фон (Матрона)")
        logger.info("Пользователь сбросил фон к дефолтному")

    def _show_gear_menu(self) -> None:
        self._check_and_refresh_state()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #12100E;
                border: 1px solid #3E3426;
                border-radius: 8px;
                padding: 6px;
                color: #FFEABF;
            }
            QMenu::item {
                padding: 8px 20px 8px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #27221A;
                color: #FFEABF;
            }
        """)

        act_settings = menu.addAction(QIcon(str(ICON_DIR / "Cog.png")), "Настройки лаунчера")
        act_import = menu.addAction(QIcon(str(ICON_DIR / "Folder.png")), "Импортировать другую папку со сборкой...")
        act_patch_zip = menu.addAction(QIcon(str(ICON_DIR / "Package.png")), "Установить патч из ZIP-архива...")
        act_cycle_bg = menu.addAction(QIcon(str(ICON_DIR / "Expand.png")), "Сменить фоновый арт")
        act_reset_bg = menu.addAction(QIcon(str(ICON_DIR / "Refresh.png")), "Восстановить стандартный фон")
        act_fix_tools = menu.addAction(QIcon(str(ICON_DIR / "Wrench.png")), "Проверить целостность сборки (Auto-Fix)")

        action = menu.exec_(self.btn_gear.mapToGlobal(self.btn_gear.rect().bottomLeft()))
        if action == act_settings:
            self._open_settings_dialog()
        elif action == act_import:
            self._import_existing_build()
        elif action == act_patch_zip:
            self._apply_patch_dialog()
        elif action == act_cycle_bg:
            self._cycle_background()
        elif action == act_reset_bg:
            self._reset_background_to_default()
        elif action == act_fix_tools:
            self._run_auto_fix()


    def _run_auto_fix(self) -> None:
        """Принудительно запускает автофикс Nemesis, BodySlide, OBody и SKSE с предварительной валидацией."""
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Невозможно исправить утилиты: сборка RFAD не найдена по пути:\n{self.paths.root}\n\n"
                "Сначала установите игру кнопкой «УСТАНОВИТЬ» или укажите верную папку в настройках.",
            )
            return

        try:
            fixes = auto_fix_rfad(self.paths.root)
            if fixes:
                msg = "\n".join(f"• {f}" for f in fixes)
                self.status_box.setText("✓ Утилиты успешно исправлены")
                QMessageBox.information(
                    self,
                    "Исправление утилит (Nemesis & OBody)",
                    f"Применены следующие исправления:\n\n{msg}",
                )
            else:
                self.status_box.setText("✓ Все утилиты и конфигурации в порядке")
                QMessageBox.information(
                    self,
                    "Исправление утилит",
                    "Все каталоги и конфигурации (Nemesis, BodySlide, OBody) уже настроены корректно.",
                )
        except Exception as e:
            logger.exception("Ошибка при исправлении утилит:")
            QMessageBox.critical(self, "Ошибка", f"Не удалось применить исправления:\n{e}")

    def _update_version_display(self) -> None:
        """Обновляет компактную метку версии сборки под главным заголовком."""
        loc = self._local_version
        rem = self._remote_version

        # Синхронизация для обратной совместимости
        if hasattr(self, "lbl_local_ver") and self.lbl_local_ver is not None:
            self.lbl_local_ver.setText(loc)
        if hasattr(self, "lbl_remote_ver") and self.lbl_remote_ver is not None:
            self.lbl_remote_ver.setText(rem or "...")

        if not hasattr(self, "lbl_version") or self.lbl_version is None:
            return

        if loc == "Не установлена":
            if rem and rem not in ("...", "Неизвестно"):
                self.lbl_version.setText(f"Версия: не установлена (Актуальная: {rem})")
            else:
                self.lbl_version.setText("Версия: не установлена")
            return

        if loc == "...":
            self.lbl_version.setText("Версия: ...")
            return

        # Игра установлена
        if rem and rem not in ("...", "Неизвестно") and rem != loc:
            self.lbl_version.setText(f"Версия: {loc} (Актуальная: {rem})")
        else:
            self.lbl_version.setText(f"Версия: {loc}")

    def _refresh_status(self) -> None:
        """
        Обновляет статус и элементы интерфейса лаунчера в зависимости от наличия игры:
        - Если игра НЕ установлена: главная кнопка превращается в «📦  УСТАНОВИТЬ» (акцентный стиль),
          кнопка MO2 отключается (disabled), статус информирует об отсутствии файлов.
        - Если игра установлена: главная кнопка переключается на «▶  ИГРАТЬ»,
          кнопка MO2 становится доступной, проверяется готовность префикса и компонентов Wine.
        """
        is_installed = self.paths.is_game_installed

        if not is_installed:
            self._local_version = "Не установлена"
            self._update_version_display()
            self.status_box.setText(f"[ Внимание ] Сборка не установлена по пути: {self.paths.root}")
            self.status_box.setStyleSheet("color: #E6B34A;")

            # Переключение главной кнопки в режим УСТАНОВИТЬ
            self.btn_play.setIcon(QIcon(str(ICON_DIR / "Package.png")))
            self.btn_play.setIconSize(QSize(22, 22))
            self.btn_play.setText("  УСТАНОВИТЬ")
            self.btn_play.setToolTip(
                f"Сборка не найдена в {self.paths.root}.\n"
                "Нажмите, чтобы запустить установку или импортировать готовую сборку RFAD SE."
            )
            if self.btn_play.objectName() != "mainInstallBtn":
                self.btn_play.setObjectName("mainInstallBtn")
                self.btn_play.style().unpolish(self.btn_play)
                self.btn_play.style().polish(self.btn_play)
                self.btn_play.update()
            self.btn_play.setEnabled(True)

            # Деактивация кнопок MO2 и BethINI
            self.btn_mo2.setEnabled(False)
            self.btn_mo2.setToolTip("Mod Organizer 2 недоступен: игра не найдена по целевому пути")
            if hasattr(self, "btn_bethini"):
                self.btn_bethini.setEnabled(False)
                self.btn_bethini.setToolTip("BethINI недоступен: игра не найдена по целевому пути")
            self.btn_init_prefix.setVisible(False)
            return

        # Игра установлена на диске
        ready, msg = self.paths.check_readiness()
        loc_ver = self.paths.get_local_version()
        self._local_version = loc_ver
        self._update_version_display()

        # Переключение главной кнопки в режим ИГРАТЬ
        self.btn_play.setIcon(QIcon(str(ICON_DIR / "Gamepad.png")))
        self.btn_play.setIconSize(QSize(22, 22))
        self.btn_play.setText("  ИГРАТЬ")
        self.btn_play.setToolTip("Запуск игры через SKSE")
        if self.btn_play.objectName() != "mainPlayBtn":
            self.btn_play.setObjectName("mainPlayBtn")
            self.btn_play.style().unpolish(self.btn_play)
            self.btn_play.style().polish(self.btn_play)
            self.btn_play.update()

        pfx = self.paths.wine_prefix
        needs_prefix = not pfx or not (pfx / "drive_c").is_dir()
        has_bethini = self.paths.bethini_exe is not None and self.paths.bethini_exe.is_file()

        if ready:
            self.status_box.setText("[ Готово ] Сборка готова к запуску")
            self.status_box.setStyleSheet("color: #FFEABF;")
            self.btn_play.setEnabled(True)
            self.btn_mo2.setEnabled(True)
            self.btn_mo2.setToolTip("Запуск Mod Organizer 2")
            if hasattr(self, "btn_bethini"):
                self.btn_bethini.setEnabled(has_bethini)
                self.btn_bethini.setToolTip(
                    "Запуск BethINI" if has_bethini else "BethINI.exe не найден в каталоге сборки"
                )
            self.btn_init_prefix.setVisible(False)
        else:
            self.status_box.setText(f"[ Внимание ] {msg}")
            self.status_box.setStyleSheet("color: #D42E4F;")
            self.btn_play.setEnabled(False)
            self.btn_mo2.setEnabled(False)
            self.btn_mo2.setToolTip(f"Запуск невозможен: {msg}")
            if hasattr(self, "btn_bethini"):
                self.btn_bethini.setEnabled(False)
                self.btn_bethini.setToolTip(f"Запуск невозможен: {msg}")
            self.btn_init_prefix.setVisible(needs_prefix)

    def _check_remote_version_background(self) -> None:
        self.update_worker = UpdateCheckWorker(self.paths)
        self.update_worker.finished.connect(self._on_update_checked)
        self.update_worker.start()

    def _on_update_checked(self, has_update: bool, loc: str, rem: str, notes: str) -> None:
        self._remote_version = rem
        if loc and loc != "...":
            self._local_version = loc
        self._update_version_display()
        if has_update:
            self.lbl_update_banner_title.setText(f"Доступно обновление: {rem} (текущая {loc})")
            self.update_banner.setVisible(True)
        self._populate_patches(notes, rem)


    def _start_patch_download(self) -> None:
        if not self._check_and_refresh_state():
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Невозможно обновить сборку: игра не установлена по пути:\n{self.paths.root}\n\n"
                "Сначала выполните установку сборки.",
            )
            return

        self.update_banner.setVisible(False)
        self.central_progress.setVisible(True)
        self.central_progress.setValue(0)
        self.status_box.setText("Подготовка к загрузке обновления...")

        self.patch_download_thread = PatchDownloadWorker(self.paths)
        self.patch_download_thread.progress.connect(self._on_patch_download_progress)
        self.patch_download_thread.finished.connect(self._on_patch_download_finished)
        self.patch_download_thread.start()

    def _on_patch_download_progress(self, p: float, msg: str) -> None:
        self.central_progress.setValue(int(p * 100))
        self.status_box.setText(msg)

    def _on_patch_download_finished(self, success: bool, msg: str) -> None:
        self.central_progress.setVisible(False)
        self._check_and_refresh_state()
        if success:
            QMessageBox.information(self, "Обновление завершено", msg)
        else:
            QMessageBox.critical(self, "Ошибка обновления", msg)

    def _populate_patches(self, raw_notes: str, latest_version: str) -> None:
        while self.patches_layout.count():
            item = self.patches_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Разбираем текст на секции обновлений
        lines = raw_notes.split("\n")
        patches = []
        current_header = ""
        current_desc: List[str] = []

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("[") and "]" in line_str:
                if current_header and current_desc:
                    patches.append((current_header, "\n".join(current_desc)))
                current_header = line_str.strip("[] ")
                current_desc = []
            else:
                if current_header and "разработке" not in current_header.lower():
                    current_desc.append(line_str)

        if current_header and current_desc:
            patches.append((current_header, "\n".join(current_desc)))

        display_patches = patches[:5] if patches else [("Патч", raw_notes[:500])]

        for ver_name, desc_text in display_patches:
            card = QFrame()
            card.setObjectName("boxCard")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(12, 10, 12, 10)
            c_lay.setSpacing(6)

            h = QHBoxLayout()
            h.setSpacing(8)
            v_lbl = QLabel(ver_name)
            v_lbl.setWordWrap(True)
            v_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #FFEABF;")
            h.addWidget(v_lbl, stretch=1)

            author_lbl = QLabel("RFAD Team")
            author_lbl.setObjectName("dimLabel")
            author_lbl.setAlignment(Qt.AlignRight | Qt.AlignTop)
            h.addWidget(author_lbl)
            c_lay.addLayout(h)

            desc = QLabel(desc_text[:300] + ("..." if len(desc_text) > 300 else ""))
            desc.setWordWrap(True)
            desc.setObjectName("secondaryLabel")
            c_lay.addWidget(desc)

            self.patches_layout.addWidget(card)

    def _on_play_btn_context_menu(self, pos) -> None:
        """Контекстное меню главной кнопки: быстрый выбор чистой установки или импорта сборки."""
        if self.paths.is_game_installed:
            return

        menu = QMenu(self)
        act_inst = menu.addAction(QIcon(str(ICON_DIR / "Package.png")), "Чистая установка сборки (innoextract)...")
        act_imp = menu.addAction(QIcon(str(ICON_DIR / "Folder.png")), "Импортировать готовую сборку...")
        action = menu.exec_(self.btn_play.mapToGlobal(pos))
        if action == act_inst:
            self._open_install_dialog()
        elif action == act_imp:
            self._import_existing_build()


    def _on_main_action_clicked(self) -> None:
        """
        Умная маршрутизация клика по главной кнопке:
        - Если игра не установлена: предлагает выбор между чистой установкой и импортом готовой сборки.
        - Если игра установлена: проверяет готовность компонентов и запускает игру через SKSE.
        """
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            logger.info("Главная кнопка нажата в режиме установки: открытие диалога выбора действия")
            choice_dlg = SetupChoiceDialog(self)
            res = choice_dlg.exec_()
            if res == SetupChoiceDialog.CHOICE_INSTALL:
                self._open_install_dialog()
            elif res == SetupChoiceDialog.CHOICE_IMPORT:
                self._import_existing_build()
            return

        ready, msg = self.paths.check_readiness()
        if not ready:
            QMessageBox.warning(
                self,
                "Сборка не готова к запуску",
                f"Невозможно запустить игру:\n\n{msg}\n\nПроверьте настройки или настройте префикс Wine.",
            )
            return

        self._launch("game")

    def _on_mo2_clicked(self) -> None:
        """
        Обработка нажатия на кнопку Mod Organizer 2:
        Проверяет наличие игры на диске и готовность к запуску.
        """
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Сборка RFAD не найдена по указанному пути:\n{self.paths.root}\n\n"
                "Сначала установите сборку кнопкой «УСТАНОВИТЬ».",
            )
            return

        ready, msg = self.paths.check_readiness()
        if not ready:
            QMessageBox.warning(
                self,
                "Сборка не готова к запуску",
                f"Невозможно запустить Mod Organizer 2:\n\n{msg}",
            )
            return

        self._launch("mo2")

    def _on_bethini_clicked(self) -> None:
        """
        Обработка нажатия на кнопку BethINI:
        Проверяет наличие игры на диске, доступность BethINI.exe и запускает его под Wine.
        """
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Сборка RFAD не найдена по указанному пути:\n{self.paths.root}\n\n"
                "Сначала установите сборку кнопкой «УСТАНОВИТЬ».",
            )
            return

        ready, msg = self.paths.check_readiness()
        if not ready:
            QMessageBox.warning(
                self,
                "Сборка не готова к запуску",
                f"Невозможно запустить BethINI:\n\n{msg}",
            )
            return

        bethini_exe = self.paths.bethini_exe
        if not bethini_exe or not bethini_exe.is_file():
            QMessageBox.warning(
                self,
                "BethINI не найден",
                f"Исполняемый файл BethINI.exe не найден в каталоге сборки:\n{self.paths.root}\n\n"
                "Убедитесь, что папка «BethINI Standalone» присутствует в каталоге RFAD.",
            )
            return

        runner = GameRunner(self.paths, self.config_mgr.data)
        log_file = Path.home() / ".config" / "rfad-launcher" / "launch-bethini.log"

        try:
            self.running_process = runner.launch_bethini(log_file=log_file)
            self.status_box.setText(f"✓ BethINI запущен (PID {self.running_process.pid})")
        except Exception as e:
            logger.exception("Ошибка запуска BethINI:")
            QMessageBox.critical(self, "Ошибка запуска BethINI", f"Не удалось запустить BethINI:\n{e}")


    def _launch(self, target: str) -> None:
        runner = GameRunner(self.paths, self.config_mgr.data)
        log_file = Path.home() / ".config" / "rfad-launcher" / f"launch-{target}.log"

        try:
            self.running_process = runner.launch(target=target, log_file=log_file)
            target_name = "Mod Organizer 2" if target == "mo2" else "Игра (SKSE)"
            self.status_box.setText(f"✓ {target_name} запущен (PID {self.running_process.pid})")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка запуска", f"Не удалось запустить процесс:\n{e}")

    def _launch_pandora(self) -> None:
        """Запускает Pandora Behaviour Engine+ под Wine."""
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Сборка RFAD не найдена по указанному пути:\n{self.paths.root}\n\n"
                "Сначала установите сборку кнопкой «УСТАНОВИТЬ».",
            )
            return

        ready, msg = self.paths.check_readiness()
        if not ready:
            QMessageBox.warning(
                self,
                "Сборка не готова к запуску",
                f"Невозможно запустить Pandora:\n\n{msg}",
            )
            return

        runner = GameRunner(self.paths, self.config_mgr.data)
        log_file = Path.home() / ".config" / "rfad-launcher" / "launch-pandora.log"

        try:
            self.running_process = runner.launch_pandora(log_file=log_file)
            self.status_box.setText(f"✓ Pandora Engine запущен (PID {self.running_process.pid})")
        except Exception as e:
            logger.exception("Ошибка запуска Pandora:")
            QMessageBox.critical(self, "Ошибка запуска Pandora", f"Не удалось запустить генератор Pandora:\n{e}")

    def _launch_nemesis(self) -> None:
        """Запускает Nemesis Unlimited Behavior Engine в изолированном виртуальном рабочем столе Wine Desktop."""
        is_installed = self._check_and_refresh_state()
        if not is_installed:
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Сборка RFAD не найдена по указанному пути:\n{self.paths.root}\n\n"
                "Сначала установите сборку кнопкой «УСТАНОВИТЬ».",
            )
            return

        ready, msg = self.paths.check_readiness()
        if not ready:
            QMessageBox.warning(
                self,
                "Сборка не готова к запуску",
                f"Невозможно запустить Nemesis:\n\n{msg}",
            )
            return

        runner = GameRunner(self.paths, self.config_mgr.data)
        log_file = Path.home() / ".config" / "rfad-launcher" / "launch-nemesis.log"

        try:
            self.running_process = runner.launch_nemesis(log_file=log_file)
            self.status_box.setText(f"✓ Nemesis Engine запущен (Wine Desktop, PID {self.running_process.pid})")
        except Exception as e:
            logger.exception("Ошибка запуска Nemesis:")
            QMessageBox.critical(self, "Ошибка запуска Nemesis", f"Не удалось запустить генератор Nemesis:\n{e}")

    def _init_prefix(self) -> None:
        self._check_and_refresh_state()
        if not self.paths.root.is_dir():
            QMessageBox.warning(
                self,
                "Каталог не найден",
                f"Каталог игры не существует:\n{self.paths.root}\n\n"
                "Сначала установите игру кнопкой «УСТАНОВИТЬ».",
            )
            return

        reply = QMessageBox.question(
            self,
            "Инициализация префикса Wine",
            "Настроить готовый префикс Wine для RFAD SE?\n\n"
            "Будет загружен протестированный префикс с .NET 6, .NET 4.8 и DXVK (~990 МБ с Яндекс.Диска).",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_init_prefix.setEnabled(False)
        self.central_progress.setVisible(True)
        self.central_progress.setValue(0)

        self.prefix_thread = PrefixSetupWorker(self.paths)
        self.prefix_thread.progress.connect(self._on_prefix_progress)
        self.prefix_thread.finished.connect(self._on_prefix_finished)
        self.prefix_thread.start()

    def _on_prefix_progress(self, p: float, msg: str) -> None:
        self.central_progress.setValue(int(p * 100))
        self.status_box.setText(msg)

    def _on_prefix_finished(self, success: bool, msg: str) -> None:
        self.btn_init_prefix.setEnabled(True)
        self.central_progress.setVisible(False)
        self._check_and_refresh_state()
        if success:
            QMessageBox.information(self, "Префикс готов", msg)
        else:
            QMessageBox.critical(self, "Ошибка", msg)

    def _on_gfx_changed(self, preset: str) -> None:
        self.config_mgr.set("graphic_mod", preset)
        if self._check_and_refresh_state():
            try:
                self.gfx_mgr.apply_graphic_preset(preset)
                self.status_box.setText(f"[ Готово ] Профиль графики переключен: {preset}")
                logger.info("Графика переключена на: %s", preset)
            except Exception as e:
                logger.exception("Ошибка переключения графики:")
                QMessageBox.warning(self, "Ошибка графики", str(e))


    def _open_game_folder(self) -> None:
        self._check_and_refresh_state()
        if not self.paths.root.is_dir():
            QMessageBox.warning(
                self,
                "Папка не найдена",
                f"Каталог игры не существует:\n{self.paths.root}\n\n"
                "Укажите корректный путь в настройках (⚙️) или нажмите «УСТАНОВИТЬ».",
            )
            return
        subprocess.Popen(["xdg-open", str(self.paths.root)])

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self, self.config_mgr, self.paths)
        if dlg.exec_() == QDialog.Accepted:
            self._check_and_refresh_state()
            try:
                self.mod_mgr.set_steam_drm(bool(self.config_mgr.get("steam_drm", False)))
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning("Ошибка применения Steam DRM после закрытия настроек: %s", e)

    def _open_install_dialog(self) -> None:
        def on_installed(path_str: str):
            self.config_mgr.set("game_dir", path_str)
            self._check_and_refresh_state()

        dlg = InstallDialog(self, on_installed)
        dlg.exec_()
        self._check_and_refresh_state()

    def _apply_patch_dialog(self) -> None:
        if not self._check_and_refresh_state():
            QMessageBox.warning(
                self,
                "Игра не установлена",
                f"Невозможно применить патч: игра не установлена в {self.paths.root}",
            )
            return

        sel, _ = QFileDialog.getOpenFileName(self, "Выберите ZIP архив патча", "", "*.zip")
        if not sel:
            return
        updater = Updater(self.paths)
        try:
            updater.apply_patch_archive(Path(sel))
            self._check_and_refresh_state()
            QMessageBox.information(self, "Обновление", "Патч успешно применен!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка обновления", str(e))

    def _import_existing_build(self) -> bool:
        """
        Импортирует готовую сборку RFAD из существующей директории на диске:
        - Позволяет выбрать каталог через диалог QFileDialog.
        - Валидирует наличие ключевых файлов (SkyrimSE.exe, MO2/ModOrganizer.exe или Data).
        - В случае отсутствия файлов запрашивает явное подтверждение у пользователя.
        - Сохраняет путь в конфигурацию (game_dir).
        - Автоматически применяет фиксы сборки (auto_fix_rfad).
        - Мгновенно обновляет интерфейс лаунчера до состояния «ИГРАТЬ».
        """
        initial_dir = str(self.paths.root) if self.paths.root.exists() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с установленной сборкой RFAD SE",
            initial_dir,
        )
        if not chosen:
            return False

        chosen_path = Path(chosen).resolve()

        # Если пользователь выбрал родительский каталог, внутри которого находится папка RFAD
        if not (chosen_path / "SkyrimSE.exe").is_file() and (chosen_path / "RFAD" / "SkyrimSE.exe").is_file():
            chosen_path = chosen_path / "RFAD"

        has_skyrim = (chosen_path / "SkyrimSE.exe").is_file()
        has_mo2 = (
            (chosen_path / "MO2" / "ModOrganizer.exe").is_file()
            or (chosen_path / "ModOrganizer.exe").is_file()
        )
        has_data = (chosen_path / "Data").is_dir() or (chosen_path / "data").is_dir()

        if not (has_skyrim or has_mo2 or has_data):
            reply = QMessageBox.warning(
                self,
                "Файлы игры не обнаружены",
                f"В выбранном каталоге не найдены ключевые компоненты RFAD / Skyrim SE:\n"
                f"{chosen_path}\n\n"
                "Ожидаемые файлы:\n"
                "• SkyrimSE.exe\n"
                "• MO2/ModOrganizer.exe\n"
                "• Каталог Data\n\n"
                "Вы уверены, что хотите использовать этот каталог как папку сборки?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False

        # Сохранение пути в конфигурацию
        self.config_mgr.set("game_dir", str(chosen_path))
        self.paths = GamePaths(chosen_path)
        self.mod_mgr = ModManager(self.paths)
        self.gfx_mgr = GraphicsManager(self.paths)
        self.bg_mgr = BackgroundManager(self.paths)
        self.bg_mgr.invalidate_cache()
        if self.config_mgr.get("random_background", True) and not self.canvas.custom_bg_pixmap:
            self._load_initial_background()

        # Автоматическое применение системных исправлений (Wine dosdevices, Nemesis, BodySlide, OBody)
        fixes: List[str] = []
        try:
            fixes = auto_fix_rfad(chosen_path)
        except Exception as e:
            logger.exception("Ошибка при выполнении auto_fix_rfad при импорте:")

        # Мгновенно обновляем состояние главного окна
        self._check_and_refresh_state()

        fix_msg = ""
        if fixes:
            sample_fixes = fixes[:4]
            if len(fixes) > 4:
                sample_fixes.append(f"... и ещё {len(fixes) - 4} исправлений")
            fix_msg = "\n\nПрименены автоисправления окружения:\n" + "\n".join(f"• {f}" for f in sample_fixes)

        QMessageBox.information(
            self,
            "Импорт сборки завершён",
            f"Сборка RFAD SE успешно импортирована!\n\n"
            f"Каталог: {chosen_path}{fix_msg}\n\n"
            "Кнопка запуска обновлена на «▶ ИГРАТЬ».",
        )
        return True

    def closeEvent(self, event) -> None:
        """Корректно завершает активные фоновые потоки при закрытии главного окна."""
        for worker in (self.prefix_thread, self.patch_download_thread, self.update_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.wait(1500)
        super().closeEvent(event)


