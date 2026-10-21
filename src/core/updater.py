"""
Модуль проверки версий и обновления сборки RFAD.
Загружает данные об актуальной версии, скачивает патчи и безопасно распаковывает их.
Обрабатывает сетевые таймауты, ошибки и гарантирует защиту от ZipSlip.
"""

from __future__ import annotations
import http.cookiejar
import logging
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional, Tuple
from src.core.paths import GamePaths

logger = logging.getLogger(__name__)

DOC_VERSION_URL = (
    "https://docs.google.com/document/d/17qsV5xDeJZyGZNFbxm3eZ50DYYm1URAvvhx588fAiSo/export?format=txt"
)
DOC_PATCHNOTES_URL = (
    "https://docs.google.com/document/export?format=txt&id=1W2fnMXCORWJJu157EwMQP1xAC-qN0_Ke0LS4Hvo58FQ"
)
GDRIVE_PATCH_FILE_ID = "13uptnuqLDUeTWiBC7Lb6nixcQRES8CDL"
EXPECTED_PATCH_BYTES = 752_208_272
HTTP_TIMEOUT_SECONDS = 8


class Updater:
    """Управление проверкой версий и безопасным применением обновлений."""

    def __init__(self, paths: GamePaths) -> None:
        self.paths = paths

    def get_remote_version(self) -> str:
        """
        Получает номер актуальной версии из Google Docs.
        При ошибках сети или пустом ответе возвращает текущую локальную версию.
        """
        try:
            req = urllib.request.Request(
                DOC_VERSION_URL,
                headers={"User-Agent": "RFAD-Linux-Launcher/2.0"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8-sig", errors="ignore").strip()
                    # Исключаем HTML-страницы ошибок Google
                    if "<html" in raw.lower() or "<!doctype" in raw.lower():
                        logger.warning("Удаленный сервер вернул HTML вместо текстовой версии")
                        return self.paths.get_local_version()

                    # Фильтруем чистую строку версии (например, '6.2.1' или '6.2')
                    clean = re.sub(r"[^\w\.\-\_]", "", raw)
                    if clean and 1 <= len(clean) <= 20:
                        return clean
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            logger.warning("Сетевая ошибка при проверке версии: %s", e)
        except Exception as e:
            logger.warning("Неожиданная ошибка при проверке версии: %s", e)

        return self.paths.get_local_version()

    def check_for_updates(self) -> Tuple[bool, str, str]:
        """
        Проверяет наличие обновления.
        Возвращает (has_update, local_ver, remote_ver).
        """
        local_ver = self.paths.get_local_version()
        remote_ver = self.get_remote_version()
        if not self.paths.is_game_installed or local_ver == "0.0":
            return False, local_ver, remote_ver
        has_update = (remote_ver != "0.0") and (local_ver != remote_ver)
        return has_update, local_ver, remote_ver

    def get_patch_notes(self) -> str:
        """Загружает текст патчноутов из Google Docs с обработкой ошибок сети."""
        try:
            req = urllib.request.Request(
                DOC_PATCHNOTES_URL,
                headers={"User-Agent": "RFAD-Linux-Launcher/2.0"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    raw_text = resp.read().decode("utf-8-sig", errors="ignore").strip()
                    if "<html" in raw_text.lower() or "<!doctype" in raw_text.lower():
                        return "Сервер вернул некорректный ответ (HTML вместо текста патчноута)."
                    if raw_text:
                        return raw_text
                    return "Список изменений пуст на сервере."
        except urllib.error.HTTPError as e:
            logger.warning("HTTP ошибка при загрузке патчноутов: %s", e)
            return f"Не удалось загрузить патчноут (HTTP {e.code})."
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning("Сетевая ошибка при загрузке патчноутов: %s", e)
            return "Не удалось связаться с сервером обновлений. Проверьте подключение к интернету."
        except Exception as e:
            logger.warning("Не удалось получить список изменений: %s", e)
            return "Не удалось загрузить список изменений."

        return "Список изменений недоступен."

    def download_patch(
        self,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        file_id: str = GDRIVE_PATCH_FILE_ID,
    ) -> Path:
        """
        Скачивает публичный архив патча с Google Drive без использования API-ключей.
        Поддерживает обход страницы подтверждения проверки на вирусы для больших файлов.
        """
        dest_path = Path(dest_path).expanduser().resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_suffix(".tmp")

        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) RFAD-Linux-Launcher/2.0"}

        urls_to_try = [
            f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
            f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
        ]

        last_err: Optional[Exception] = None
        for initial_url in urls_to_try:
            try:
                req = urllib.request.Request(initial_url, headers=headers)
                resp = opener.open(req, timeout=30)
                content_type = resp.headers.get("Content-Type", "").lower()

                if "text/html" in content_type:
                    html = resp.read().decode("utf-8", errors="ignore")
                    resp.close()

                    action_m = re.search(r'<form[^>]+action="([^"]+)"', html)
                    action_url = action_m.group(1).replace("&amp;", "&") if action_m else "https://drive.usercontent.google.com/download"
                    params = dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
                    if not params:
                        params = {"id": file_id, "export": "download", "confirm": "t"}
                    query = urllib.parse.urlencode(params)
                    download_url = f"{action_url}?{query}" if "?" not in action_url else f"{action_url}&{query}"
                    req2 = urllib.request.Request(download_url, headers=headers)
                    resp = opener.open(req2, timeout=30)

                try:
                    cl_header = resp.headers.get("Content-Length")
                    total_size = int(cl_header) if cl_header and cl_header.isdigit() else EXPECTED_PATCH_BYTES
                    downloaded = 0
                    chunk_size = 256 * 1024  # 256 КБ

                    with open(tmp_path, "wb") as f:
                        while True:
                            if cancel_check and cancel_check():
                                raise InterruptedError("Загрузка патча отменена пользователем.")
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, max(total_size, downloaded))
                finally:
                    resp.close()

                if tmp_path.exists():
                    tmp_path.replace(dest_path)

                if not zipfile.is_zipfile(dest_path):
                    dest_path.unlink(missing_ok=True)
                    raise RuntimeError("Скачанный с Google Drive файл не является валидным ZIP-архивом.")

                return dest_path
            except InterruptedError:
                tmp_path.unlink(missing_ok=True)
                raise
            except Exception as e:
                last_err = e
                tmp_path.unlink(missing_ok=True)
                logger.warning("Попытка скачивания патча с %s не удалась: %s", initial_url, e)

        raise RuntimeError(f"Не удалось скачать патч с Google Drive: {last_err}")

    def apply_patch_archive(
        self,
        archive_path: Path,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        """
        Безопасно распаковывает архив патча в MO2/mods/RFAD_PATCH
        с валидацией путей и защитой от повреждения существующей сборки.
        """
        archive_path = Path(archive_path).expanduser().resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(f"Файл архива не найден: {archive_path}")

        if not zipfile.is_zipfile(archive_path):
            raise ValueError(f"Выбранный файл не является корректным ZIP-архивом: {archive_path}")

        mods_root = self.paths.root / "MO2" / "mods"
        target_dir = mods_root / "RFAD_PATCH"
        temp_dir = mods_root / ".staging_patch"

        if progress_cb:
            progress_cb(0.05, "Подготовка к распаковке патча...")

        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                members = z.infolist()
                total_files = max(1, len(members))

                # Проверка безопасности путей (защита от Zip Slip)
                resolved_temp = temp_dir.resolve()
                for member in members:
                    member_path = (resolved_temp / member.filename).resolve()
                    if not member_path.is_relative_to(resolved_temp):
                        raise RuntimeError(f"Обнаружен небезопасный путь в архиве: {member.filename}")

                # Распаковка
                for i, member in enumerate(members):
                    z.extract(member, resolved_temp)
                    if progress_cb and (i % 25 == 0 or i == total_files - 1):
                        percent = 0.05 + (0.75 * ((i + 1) / total_files))
                        progress_cb(percent, f"Распаковка патча: {Path(member.filename).name}")

            if progress_cb:
                progress_cb(0.85, "Интеграция файлов патча...")

            # Анализ содержимого: если архив содержит единственную общую корневую папку
            extracted_items = list(temp_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                source_dir = extracted_items[0]
            else:
                source_dir = temp_dir

            # Очищаем старую папку мода патча только после успешной распаковки
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.mkdir(parents=True, exist_ok=True)

            # Перенос файлов
            for item in list(source_dir.iterdir()):
                dest = target_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest, ignore_errors=True)
                    else:
                        dest.unlink(missing_ok=True)
                shutil.move(str(item), str(dest))

            if progress_cb:
                progress_cb(0.98, "Завершение обновления...")

        finally:
            # Гарантированная очистка staging каталога
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

        if progress_cb:
            progress_cb(1.0, "Патч успешно установлен!")
        logger.info("Патч успешно применен в %s", target_dir)
