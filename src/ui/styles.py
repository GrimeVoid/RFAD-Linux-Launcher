"""
Официальный визуальный стиль Requiem For A Dream SE 6.2 (Nordic Gold / Obsidian).
Воссоздает аутентичный интерфейс официального Windows/Linux лаунчера RFAD:
- Цвета: #FFEABF (золото/пергамент), #BFAF8F (бронза), #867A64 (тёмная бронза), #0D0C0A (обсидиан).
- Карточки Box, круглые кнопки CircleButton, золотые акценты и свечение.
"""

from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
BG_IMAGE_PATH = (ASSETS_DIR / "bg.png").as_posix()

RFAD_THEME_QSS = f"""
/* Основные окна */
QMainWindow, QDialog, QMessageBox {{
    background-color: #0D0C0A;
    color: #FFEABF;
    font-family: 'Segoe UI', 'Ubuntu', 'Noto Sans', sans-serif;
}}

QWidget {{
    color: #FFEABF;
    font-size: 13px;
}}

/* Диалоговые окна сообщений (QMessageBox) */
QMessageBox {{
    background-color: #12100E;
    border: 1px solid #3D3425;
    border-radius: 14px;
}}

QMessageBox QLabel {{
    color: #FFEABF;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.5;
    padding: 10px;
    background: transparent;
}}

QMessageBox QPushButton {{
    min-width: 95px;
    min-height: 36px;
    padding: 6px 20px;
    font-size: 13px;
    font-weight: bold;
    background-color: #1A1713;
    border: 1px solid #4A3E2C;
    border-radius: 8px;
    color: #FFEABF;
}}

QMessageBox QPushButton:hover {{
    background-color: #27221B;
    border-color: #FFEABF;
}}

/* Карточки Box в стиле RFAD */
QFrame#boxCard {{
    background-color: rgba(18, 16, 13, 0.88);
    border: 1px solid #382F22;
    border-radius: 12px;
    padding: 10px;
}}

QFrame#card {{
    background-color: rgba(18, 16, 13, 0.88);
    border: 1px solid #382F22;
    border-radius: 12px;
    padding: 12px;
}}

/* Заголовки */
QLabel#brandTitle {{
    font-size: 38px;
    font-weight: 800;
    color: #FFEABF;
    letter-spacing: 2px;
}}

QLabel#versionBadge {{
    font-size: 13px;
    font-weight: 600;
    color: #C49742;
    letter-spacing: 0.5px;
    padding-left: 2px;
}}

QLabel#sectionTitle {{
    font-size: 16px;
    font-weight: bold;
    color: #FFEABF;
    margin-bottom: 4px;
}}

QLabel#secondaryLabel {{
    color: #BFAF8F;
    font-size: 13px;
}}

QLabel#dimLabel {{
    color: #867A64;
    font-size: 12px;
}}

/* Кнопки соцсетей (CircleButton) */
QPushButton#circleBtn {{
    background-color: rgba(18, 16, 13, 0.85);
    border: 1px solid #2D271E;
    border-radius: 24px;
    min-width: 48px;
    max-width: 48px;
    min-height: 48px;
    max-height: 48px;
    padding: 8px;
}}

QPushButton#circleBtn:hover {{
    background-color: #262119;
    border-color: #FFEABF;
}}

QPushButton#circleBtn:pressed {{
    background-color: #12100E;
}}

/* Главная большая кнопка ИГРАТЬ (Main Play Button) */
QPushButton#mainPlayBtn {{
    background-color: rgba(15, 13, 10, 0.9);
    border: 1px solid #4D402B;
    border-radius: 12px;
    padding: 8px 16px;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: #FFEABF;
}}

QPushButton#mainPlayBtn:hover {{
    background-color: #221D15;
    border-color: #FFEABF;
    color: #FFFFFF;
}}

QPushButton#mainPlayBtn:pressed {{
    background-color: #12100E;
}}

QPushButton#mainPlayBtn:disabled {{
    background-color: #12110E;
    border-color: #221E17;
    color: #615847;
}}

/* Главная кнопка УСТАНОВИТЬ (когда сборка не установлена) */
QPushButton#mainInstallBtn {{
    background-color: #2D2214;
    border: 2px solid #E6B34A;
    border-radius: 12px;
    padding: 8px 14px;
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0px;
    color: #FFEABF;
}}

QPushButton#mainInstallBtn:hover {{
    background-color: #40301B;
    border-color: #FFF0C8;
    color: #FFFFFF;
}}

QPushButton#mainInstallBtn:pressed {{
    background-color: #1A140B;
}}

QPushButton#mainInstallBtn:disabled {{
    background-color: #1A1713;
    border-color: #3D3425;
    color: #6B6252;
}}

/* Кнопка Mod Organizer 2 */
QPushButton#mo2Btn {{
    background-color: rgba(22, 19, 15, 0.9);
    border: 1px solid #5A4B32;
    border-radius: 12px;
    padding: 0 10px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.2px;
    color: #FFEABF;
}}

QPushButton#mo2Btn:hover {{
    background-color: #2B2317;
    border-color: #FFEABF;
    color: #FFFFFF;
}}

QPushButton#mo2Btn:pressed {{
    background-color: #12100E;
}}

QPushButton#mo2Btn:disabled {{
    background-color: #12110E;
    border-color: #221E17;
    color: #615847;
}}

/* Кнопки левой навигационной панели (Discord, База знаний, Папка игры, MO2, BethINI, Фикс) */
QPushButton#navBtn {{
    background-color: #191612;
    border: 1px solid #362D1F;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
    text-align: left;
    color: #FFEABF;
}}

QPushButton#navBtn:hover {{
    background-color: #27211A;
    border-color: #FFEABF;
    color: #FFFFFF;
}}

QPushButton#navBtn:pressed {{
    background-color: #12100E;
}}

QPushButton#navBtn:disabled {{
    background-color: #12110E;
    border-color: #221E17;
    color: #615847;
}}

/* Кнопка-шестеренка и вспомогательные */
QPushButton#gearBtn {{
    background-color: rgba(15, 13, 10, 0.9);
    border: 1px solid #3A3121;
    border-radius: 12px;
    min-width: 50px;
    max-width: 50px;
    min-height: 50px;
    max-height: 50px;
    padding: 6px;
}}

QPushButton#gearBtn:hover {{
    background-color: #262119;
    border-color: #FFEABF;
}}


/* Стандартные кнопки */
QPushButton {{
    background-color: #191612;
    border: 1px solid #362D1F;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 600;
    color: #FFEABF;
}}

QPushButton:hover {{
    background-color: #25201A;
    border-color: #FFEABF;
}}

QPushButton:pressed {{
    background-color: #12100E;
}}

QPushButton#accentAction {{
    background-color: #2E2516;
    border: 1px solid #C49742;
    color: #FFEABF;
    font-weight: bold;
}}

QPushButton#accentAction:hover {{
    background-color: #3D311C;
    border-color: #FFEABF;
}}

/* Всплывающие контекстные меню (QMenu) */
QMenu {{
    background-color: #12100E;
    border: 1px solid #3E3426;
    border-radius: 8px;
    padding: 6px;
    color: #FFEABF;
}}

QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
    color: #FFEABF;
    font-weight: 500;
}}

QMenu::item:selected {{
    background-color: #27221A;
    color: #FFEABF;
}}

QMenu::separator {{
    height: 1px;
    background-color: #2D271E;
    margin: 4px 8px;
}}

/* Поля ввода и комбобоксы */
QLineEdit, QComboBox, QSpinBox {{
    background-color: #12100D;
    border: 1px solid #2D271E;
    border-radius: 6px;
    padding: 7px 12px;
    color: #FFEABF;
    selection-background-color: #594622;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: #FFEABF;
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: #16130F;
    border: 1px solid #3A3121;
    color: #FFEABF;
    selection-background-color: #2E2516;
    selection-color: #FFEABF;
}}

/* Чекбоксы */
QCheckBox {{
    spacing: 8px;
    font-size: 13px;
    color: #BFAF8F;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #3E3426;
    background-color: #12100D;
}}

QCheckBox::indicator:hover {{
    border-color: #FFEABF;
}}

QCheckBox::indicator:checked {{
    background-color: #8C6A28;
    border-color: #FFEABF;
}}

/* Вкладки (QTabWidget) */
QTabWidget::pane {{
    border: 1px solid #2D271E;
    background-color: rgba(13, 12, 10, 0.8);
    border-radius: 10px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: #13110E;
    border: 1px solid #241F17;
    border-bottom: none;
    padding: 9px 22px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #867A64;
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background-color: #1C1813;
    color: #FFEABF;
    border-color: #3E3426;
}}

QTabBar::tab:hover:!selected {{
    background-color: #181511;
    color: #BFAF8F;
}}

/* Прогресс-бар */
QProgressBar {{
    background-color: #100E0B;
    border: 1px solid #2A241A;
    border-radius: 6px;
    height: 20px;
    text-align: center;
    color: #FFEABF;
    font-size: 11px;
    font-weight: bold;
}}

QProgressBar::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #75551A, stop:1 #C49742);
    border-radius: 5px;
}}

/* Статус-бар */
QStatusBar {{
    background-color: #0A0907;
    border-top: 1px solid #1F1B14;
    color: #867A64;
}}

/* Скроллбары */
QScrollBar:vertical {{
    background: rgba(10, 9, 7, 0.4);
    width: 6px;
    margin: 0px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical {{
    background: rgba(196, 151, 66, 0.35);
    min-height: 28px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(196, 151, 66, 0.75);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

/* Текстовые области логов и патчноутов */
QPlainTextEdit {{
    background-color: #0E0C0A;
    border: 1px solid #241F18;
    border-radius: 8px;
    color: #BFAF8F;
    font-size: 12px;
    line-height: 1.4;
}}
"""


def apply_rfad_theme(app: QApplication) -> None:
    """Устанавливает официальную тёмно-золотую палитру RFAD."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0D0C0A"))
    palette.setColor(QPalette.WindowText, QColor("#FFEABF"))
    palette.setColor(QPalette.Base, QColor("#100E0B"))
    palette.setColor(QPalette.AlternateBase, QColor("#16130F"))
    palette.setColor(QPalette.ToolTipBase, QColor("#12100E"))
    palette.setColor(QPalette.ToolTipText, QColor("#FFEABF"))
    palette.setColor(QPalette.Text, QColor("#FFEABF"))
    palette.setColor(QPalette.Button, QColor("#1A1713"))
    palette.setColor(QPalette.ButtonText, QColor("#FFEABF"))
    palette.setColor(QPalette.BrightText, QColor("#D42E4F"))
    palette.setColor(QPalette.Link, QColor("#C49742"))
    palette.setColor(QPalette.Highlight, QColor("#75551A"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFEABF"))

    app.setPalette(palette)
    app.setStyleSheet(RFAD_THEME_QSS)
