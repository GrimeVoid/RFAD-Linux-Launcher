"""
Модуль безопасной установки сборки RFAD из инсталлятора Inno Setup.
Обеспечивает монотонный расчет реального объема распакованных байтов на диске,
надежную обработку структуры папок innoextract (app, sd, tmp) и гарантированное завершение процесса.
"""

from __future__ import annotations
import logging
import os
import re
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Ожидаемый общий объем распакованной сборки RFAD SE (~77.7 ГБ)
EXPECTED_UNPACKED_BYTES: int = 77_737_979_510
# Минимально необходимое свободное место на диске (80 ГБ)
MIN_REQUIRED_FREE_SPACE_BYTES: int = 80 * 1024 * 1024 * 1024

# Игнорируемые служебные папки innoextract
IGNORED_STAGING_DIRS = {"tmp", "temp", "embedded"}


def find_default_installer() -> Optional[Path]:
    """
    Ищет исполняемый файл установщика RFAD SE 6.2 в типовых расположениях на диске.
    """
    # 1. Прямые типовые пути
    search_candidates = [
        Path.home() / "Archive" / "Downloads" / "RFAD_6_2_Installer" / "RfaD SE 6.2.exe",
        Path.home() / "Downloads" / "RFAD_6_2_Installer" / "RfaD SE 6.2.exe",
        Path.home() / "Downloads" / "RfaD SE 6.2.exe",
        Path.home() / "Downloads" / "RFAD SE 6.2.exe",
    ]

    for cand in search_candidates:
        if cand.is_file():
            logger.info("Найден установщик RFAD по стандартному пути: %s", cand)
            return cand

    # 2. Поиск в каталогах загрузок
    scan_dirs = [
        Path.home() / "Archive" / "Downloads" / "RFAD_6_2_Installer",
        Path.home() / "Archive" / "Downloads",
        Path.home() / "Downloads",
    ]

    for s_dir in scan_dirs:
        if s_dir.is_dir():
            try:
                for p in s_dir.glob("*.exe"):
                    name_l = p.name.lower()
                    if "rfad" in name_l and ("6.2" in name_l or "setup" in name_l or "installer" in name_l or "se" in name_l):
                        logger.info("Найден установщик RFAD в каталоге %s: %s", s_dir, p)
                        return p
            except Exception as e:
                logger.debug("Ошибка сканирования каталога %s: %s", s_dir, e)

    return None



def calculate_dir_size_bytes(directory: Path) -> int:
    """
    Быстро вычисляет размер папки в байтах.
    Сначала пытается использовать системный вызов 'du -s -B1',
    а в случае ошибки производит рекурсивный обход os.scandir.
    """
    if not directory.is_dir():
        return 0

    # Способ 1: Быстрый du на Linux
    try:
        res = subprocess.run(
            ["du", "-s", "-B1", str(directory)],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.strip().split()
            if parts and parts[0].isdigit():
                return int(parts[0])
    except Exception:
        pass

    # Способ 2: Надежный fallback на os.scandir
    total = 0
    try:
        stack = [str(directory)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            else:
                                total += entry.stat(follow_symlinks=False).st_size
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
    except Exception as e:
        logger.debug("Ошибка подсчета размера через scandir: %s", e)

    return total


class SafeInstaller:
    """Безопасный установщик RFAD на базе innoextract с монотонным прогрессом."""

    def __init__(
        self,
        installer_exe: str | Path,
        target_dir: str | Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        self.installer_exe = Path(installer_exe).expanduser().resolve()
        target = Path(target_dir).expanduser().resolve()

        # ЗАЩИТА: Если выбрана родительская папка, гарантируем суффикс /RFAD
        if target.name != "RFAD":
            self.target_dir = target / "RFAD"
        else:
            self.target_dir = target

        self.progress_cb = progress_callback
        self._is_cancelled = False
        self.process: Optional[subprocess.Popen] = None
        self._last_progress: float = 0.0

    def cancel(self) -> None:
        """Безопасный флаг отмены установки."""
        logger.info("Получен запрос на отмену установки RFAD")
        self._is_cancelled = True
        self._terminate_process()

    def _terminate_process(self) -> None:
        """Принудительно останавливает процесс innoextract во избежание зомби."""
        if self.process and self.process.poll() is None:
            try:
                logger.info("Завершение процесса innoextract (PID %s)...", self.process.pid)
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    logger.warning("Процесс не завершился по SIGTERM, отправляем SIGKILL...")
                    self.process.kill()
                    self.process.wait(timeout=3)
            except Exception as e:
                logger.warning("Ошибка при остановке процесса innoextract: %s", e)

    def _report_progress(self, percent: float, message: str) -> None:
        # Гарантируем монотонность прогресса
        clamped = max(self._last_progress, min(1.0, percent))
        self._last_progress = clamped
        if self.progress_cb:
            self.progress_cb(clamped, message)

    def validate(self) -> None:
        """Проверка входных параметров и доступности дискового пространства."""
        if not self.installer_exe.is_file():
            raise FileNotFoundError(f"Установщик не найден: {self.installer_exe}")

        # Проверка наличия innoextract
        if not shutil.which("innoextract"):
            raise RuntimeError(
                "Утилита 'innoextract' не найдена в системе. Установите её через пакетный менеджер (например, pacman/apt/nix)."
            )

        # Проверка свободного места
        self.target_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(self.target_dir)
        if stat.free < MIN_REQUIRED_FREE_SPACE_BYTES:
            free_gb = stat.free / (1024**3)
            req_gb = MIN_REQUIRED_FREE_SPACE_BYTES / (1024**3)
            raise RuntimeError(
                f"Недостаточно свободного места на диске. Доступно: {free_gb:.1f} ГБ, требуется минимум: {req_gb:.1f} ГБ"
            )

    def _move_item_safe(self, src: Path, dest_parent: Path) -> None:
        """Перемещает файл или каталог с заменой существующего."""
        dest = dest_parent / src.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest, ignore_errors=True)
            else:
                dest.unlink(missing_ok=True)
        shutil.move(str(src), str(dest))

    def run(self) -> None:
        """Выполняет процесс распаковки с монотонным расчетом прогресса и интеграцию структуры."""
        self._last_progress = 0.0
        self.validate()
        self._report_progress(0.01, f"Подготовка целевого каталога: {self.target_dir}")

        # Временная папка для распаковки
        extract_dir = self.target_dir / ".staging_extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "innoextract",
            "--progress",
            "-d",
            str(extract_dir),
            str(self.installer_exe),
        ]

        logger.info("Запуск распаковки innoextract: %s", " ".join(cmd))
        self._report_progress(0.03, "Инициализация распаковки сборки...")

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        file_regex = re.compile(r'Extracting\s+"([^"]+)"', re.IGNORECASE)
        last_disk_check_time = 0.0
        current_file_name = "подготовка файлов..."
        expected_bytes = EXPECTED_UNPACKED_BYTES
        total_gb = expected_bytes / (1024**3)

        try:
            while True:
                if self._is_cancelled:
                    self._terminate_process()
                    raise InterruptedError("Установка отменена пользователем.")

                line = ""
                if self.process.stdout is not None:
                    try:
                        ready, _, _ = select.select([self.process.stdout], [], [], 0.25)
                        if ready:
                            line = self.process.stdout.readline()
                    except (ValueError, OSError):
                        line = self.process.stdout.readline()

                if line:
                    line_clean = line.strip()
                    match = file_regex.search(line_clean)
                    if match:
                        current_file_name = Path(match.group(1)).name
                else:
                    if self.process.poll() is not None:
                        break

                now = time.monotonic()
                # Опрашиваем реальный размер распакованных данных на диске каждые ~1.2 секунды
                if now - last_disk_check_time >= 1.2:
                    last_disk_check_time = now
                    current_bytes = calculate_dir_size_bytes(extract_dir)
                    current_gb = current_bytes / (1024**3)

                    # Рассчитываем монотонный процент распаковки (диапазон 0.03 - 0.92)
                    ratio = min(1.0, current_bytes / expected_bytes)
                    progress = 0.03 + (ratio * 0.89)
                    percent = ratio * 100.0

                    msg = (
                        f"Распаковка: {current_gb:.1f} ГБ / {total_gb:.1f} ГБ "
                        f"({percent:.1f}%) — {current_file_name}"
                    )
                    self._report_progress(progress, msg)

            self.process.wait()
            if self.process.returncode != 0:
                if self._is_cancelled:
                    raise InterruptedError("Установка отменена пользователем.")
                raise RuntimeError(
                    f"innoextract завершился с ошибкой: код возврата {self.process.returncode}"
                )

            # Переходим к финализации структуры каталогов
            self._report_progress(0.93, "Анализ и перенос распакованных файлов сборки...")

            # Обработка структуры innoextract
            app_dir = extract_dir / "app"
            if app_dir.is_dir():
                logger.info("Обнаружена папка app/, перенос содержимого в %s", self.target_dir)
                for item in list(app_dir.iterdir()):
                    self._move_item_safe(item, self.target_dir)
                shutil.rmtree(app_dir, ignore_errors=True)

            # Проверяем возможные файлы игры в папке sd (с сохранением иерархии подпапок)
            sd_dir = extract_dir / "sd"
            if sd_dir.is_dir():
                for root_path, dirs, files in os.walk(str(sd_dir)):
                    rel_parent = Path(root_path).relative_to(sd_dir)
                    dest_parent = (
                        self.target_dir / rel_parent
                        if str(rel_parent) != "."
                        else self.target_dir
                    )
                    dest_parent.mkdir(parents=True, exist_ok=True)
                    for file_name in files:
                        full_path = Path(root_path) / file_name
                        logger.info("Найден файл в sd/: %s -> %s", full_path, dest_parent)
                        self._move_item_safe(full_path, dest_parent)
                shutil.rmtree(sd_dir, ignore_errors=True)

            # Переносим любые оставшиеся файлы и папки из extract_dir (кроме служебных)
            for item in list(extract_dir.iterdir()):
                if item.name.lower() in IGNORED_STAGING_DIRS:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    continue
                logger.info("Перенос корневого элемента из staging: %s", item.name)
                self._move_item_safe(item, self.target_dir)

            self._report_progress(0.98, "Очистка временных файлов установки...")
            shutil.rmtree(extract_dir, ignore_errors=True)

            self._report_progress(1.0, "Установка RFAD SE успешно завершена!")
            logger.info("Установка успешно завершена в: %s", self.target_dir)

        except Exception as e:
            logger.error("Сбой установки: %s", e)
            self._terminate_process()
            # При сбое или отмене безопасно очищаем staging каталог
            if extract_dir.exists():
                logger.info("Очистка временного каталога после сбоя: %s", extract_dir)
                shutil.rmtree(extract_dir, ignore_errors=True)
            raise
