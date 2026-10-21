"""
Модуль инициализации и настройки префикса Wine (.NET 6, DXVK, VC++).
Загружает и распаковывает готовый протестированный префикс RFAD с Яндекс.Диска
и интегрирует необходимые библиотеки DirectX/Vulkan/DotNet.
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from src.core.paths import GamePaths

logger = logging.getLogger(__name__)

YANDEX_PUBLIC_URL = "https://disk.yandex.ru/d/y3mx1DXn83CbgQ"
YANDEX_API_URL = "https://cloud-api.yandex.net/v1/disk/public/resources/download"


class PrefixManager:
    """Управление загрузкой, распаковкой и восстановлением префикса Wine."""

    def __init__(self, paths: GamePaths) -> None:
        self.paths = paths

    def get_yandex_direct_url(self, public_url: str = YANDEX_PUBLIC_URL) -> str:
        """Получает прямую ссылку на скачивание архива префикса через Яндекс API."""
        query = urllib.parse.urlencode({"public_key": public_url})
        req = urllib.request.Request(
            f"{YANDEX_API_URL}?{query}",
            headers={"User-Agent": "RFAD-Linux-Launcher/2.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            direct_url = data.get("href")
            if not direct_url:
                raise RuntimeError("API Яндекс.Диска не вернул ссылку на скачивание.")
            return direct_url

    def download_prefix_archive(
        self,
        dest_path: Path,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Скачивает архив префикса (pfx dotnet.7z) с прогрессом."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        direct_url = self.get_yandex_direct_url()

        tmp_path = dest_path.with_suffix(".tmp")
        req = urllib.request.Request(
            direct_url,
            headers={"User-Agent": "RFAD-Linux-Launcher/2.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 1024 * 1024  # 1 МБ

                with open(tmp_path, "wb") as f:
                    while True:
                        if cancel_check and cancel_check():
                            raise InterruptedError("Загрузка префикса отменена пользователем.")
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total_size > 0:
                            percent = downloaded / total_size
                            mb_got = downloaded / (1024 * 1024)
                            mb_tot = total_size / (1024 * 1024)
                            progress_cb(
                                percent * 0.7,
                                f"Загрузка префикса Wine: {mb_got:.1f} МБ / {mb_tot:.1f} МБ",
                            )

            if tmp_path.exists():
                tmp_path.replace(dest_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    download_archive = download_prefix_archive

    def extract_prefix(
        self,
        archive_path: Path,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        """Распаковывает 7z архив префикса с помощью утилиты 7z."""
        if not shutil.which("7z"):
            raise RuntimeError("Утилита '7z' (p7zip) не найдена в системе.")

        target_wine_dir = self.paths.root / "wine"
        target_wine_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = self.paths.root / "temp_prefix_extract"
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            if progress_cb:
                progress_cb(0.75, "Распаковка архива префикса Wine (7z)...")

            cmd = ["7z", "x", "-y", f"-o{staging_dir}", str(archive_path)]
            res = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL)
            if res.returncode != 0:
                archive_path.unlink(missing_ok=True)
                raise RuntimeError(f"7z завершился с кодом {res.returncode} (повреждённый архив удалён)")

            if progress_cb:
                progress_cb(0.90, "Интеграция префикса в структуру сборки...")

            # Ищем распакованную папку (pfx dotnet или RFAD_SE)
            source_dir = None
            for item in staging_dir.iterdir():
                if item.is_dir() and item.name in ("pfx dotnet", "RFAD_SE", "prefix"):
                    source_dir = item
                    break
                elif (item / "drive_c").is_dir():
                    source_dir = item
                    break

            if not source_dir:
                source_dir = staging_dir

            dest_prefix = target_wine_dir / "prefix"
            if dest_prefix.exists():
                shutil.rmtree(dest_prefix, ignore_errors=True)

            # Перемещаем распакованное в wine/prefix
            shutil.move(str(source_dir), str(dest_prefix))

            shutil.rmtree(staging_dir, ignore_errors=True)

            if progress_cb:
                progress_cb(1.0, "Префикс Wine успешно настроен!")

        except Exception as e:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise RuntimeError(f"Ошибка при распаковке префикса: {e}")

    def setup_prefix(
        self,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Полный цикл: проверка, скачивание и распаковка префикса."""
        download_dir = self.paths.root / "download"
        archive_path = download_dir / "pfx dotnet.7z"

        if not archive_path.is_file():
            self.download_prefix_archive(archive_path, progress_cb, cancel_check=cancel_check)

        if cancel_check and cancel_check():
            raise InterruptedError("Настройка префикса отменена пользователем.")

        self.extract_prefix(archive_path, progress_cb)
