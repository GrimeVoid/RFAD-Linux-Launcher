"""
Модуль прямого и безопасного запуска игры и Mod Organizer 2 через Proton Wine.
Работает напрямую через subprocess.Popen без шелл-костылей и Flatpak-оберток.
Гарантирует изоляцию окружения, корректные переменные DXVK/FSR/Wine и отсутствие зомби-процессов.
"""

from __future__ import annotations
import logging
import os
import shutil
import subprocess
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.core.paths import GamePaths

logger = logging.getLogger(__name__)


def to_wine_path(path: Path) -> str:
    """Преобразует путь Linux в путь через Wine диск Z: с обратными слэшами."""
    resolved = path.resolve()
    win_part = str(resolved).replace("/", "\\")
    return f"Z:{win_part}"


def _optimize_process_limits() -> None:
    """Устанавливает максимальный лимит открытых файловых дескрипторов (ulimit -n 1048576) для OAR/DAR и Wine USVFS."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(1048576, hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except Exception:
        pass


def auto_fix_rfad(game_dir: Path | str) -> list[str]:
    """
    Комплексная предстартовая подготовка и автоматическое исправление сборки RFAD:
    1. Создание физических каталогов для OBody, BodySlide и SKSE.
    2. Исправление nemesis.ini (путь к Data через Z: и first=false).
    3. Создание симлинка Data/Nemesis_Engine -> MO2/.../Nemesis_Engine.
    4. Исправление skee64.ini (bEnableBodyGen=0 без мусорных комментариев).
    5. Исправление MO2/ModOrganizer.ini (workingDirectory для Nemesis и BodySlide).
    6. Исправление Config.xml для BodySlide (путь к Data и очистка OutputDataPath).
    """
    root = Path(game_dir).resolve()
    logs: list[str] = []

    if not root.is_dir():
        logs.append(f"Каталог сборки не найден: {root}")
        return logs

    data_dir = root / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    wine_data_dir = to_wine_path(data_dir) + "\\"

    # Гарантируем регистронезависимый симлинк data -> Data
    data_lower = root / "data"
    if not data_lower.exists() and not data_lower.is_symlink():
        try:
            data_lower.symlink_to(data_dir)
            logs.append("Создан симлинк data -> Data")
        except Exception as e:
            logs.append(f"Ошибка создания симлинка data: {e}")

    # 1. Физические каталоги для OBody, SKSE и вывода BodySlide
    target_dirs = [
        root / "MO2" / "overwrite" / "SKSE" / "Plugins" / "OBody" / "obody_includes",
        root / "MO2" / "overwrite" / "meshes" / "actors" / "character" / "character assets",
        root / "MO2" / "overwrite" / "CalienteTools" / "BodySlide" / "SliderPresets",
        root / "Data" / "SKSE" / "Plugins" / "OBody" / "obody_includes",
        root / "Data" / "SKSE" / "Plugins" / "StorageUtilData",
    ]
    for d in target_dirs:
        if not d.exists():
            try:
                d.mkdir(parents=True, exist_ok=True)
                logs.append(f"Создан каталог: {d.relative_to(root)}")
            except Exception as e:
                logs.append(f"Ошибка создания каталога {d}: {e}")

    # 2. Исправление nemesis.ini
    nemesis_ini = (
        root
        / "MO2"
        / "mods"
        / "Project New Reign - Nemesis Unlimited Behavior Engine"
        / "Nemesis_Engine"
        / "nemesis.ini"
    )
    if nemesis_ini.is_file():
        try:
            content = nemesis_ini.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            new_lines = []
            has_skyrim_data = False
            has_first = False

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("SkyrimDataDirectory="):
                    new_lines.append(f"SkyrimDataDirectory={wine_data_dir}")
                    has_skyrim_data = True
                elif stripped.startswith("first="):
                    new_lines.append("first=false")
                    has_first = True
                else:
                    new_lines.append(line)

            if not has_skyrim_data:
                new_lines.insert(0, f"SkyrimDataDirectory={wine_data_dir}")
            if not has_first:
                new_lines.append("first=false")

            updated_content = "\n".join(new_lines) + "\n"
            if updated_content != content:
                nemesis_ini.write_text(updated_content, encoding="utf-8")
                logs.append(f"Обновлен nemesis.ini: SkyrimDataDirectory={wine_data_dir}, first=false")
        except Exception as e:
            logs.append(f"Ошибка обновления nemesis.ini: {e}")

    # 3. Байт-патч и создание симлинка Data/Nemesis_Engine
    nemesis_exe = (
        root
        / "MO2"
        / "mods"
        / "Project New Reign - Nemesis Unlimited Behavior Engine"
        / "Nemesis_Engine"
        / "Nemesis Unlimited Behavior Engine.exe"
    )
    if nemesis_exe.is_file():
        try:
            # Смещение 0x111cec: проверка m_mutex (0f 84 e5 00 00 00 / je 0x111dd7)
            # В Wine/Proton GetLastError() не сбрасывается и попадает в default: return true (зависание).
            # Заменяем на безусловный переход: e9 e6 00 00 00 90 (jmp 0x111dd7 + nop) на месте без чтения всего .exe
            pos = 0x111CEC
            target_je = bytes.fromhex("0f84e5000000")
            target_jmp = bytes.fromhex("e9e600000090")
            alt_call = b"\xFF\x15\x36\x8F\x0D\x00"
            alt_nop = b"\x90" * 6

            if nemesis_exe.stat().st_size > pos + 6:
                with open(nemesis_exe, "r+b") as f:
                    f.seek(pos)
                    cur_bytes = f.read(6)
                    replacement = None
                    if cur_bytes == target_je:
                        replacement = target_jmp
                    elif cur_bytes == alt_call:
                        replacement = alt_nop

                    if replacement is not None:
                        bak_file = nemesis_exe.with_suffix(".exe.bak")
                        if not bak_file.exists():
                            shutil.copy2(nemesis_exe, bak_file)
                        f.seek(pos)
                        f.write(replacement)
                        logs.append(
                            "Применен байт-патч для Nemesis Unlimited Behavior Engine.exe "
                            "(устранено ложное зависание в Wine/Proton)"
                        )
        except Exception as e:
            logs.append(f"Ошибка применения байт-патча Nemesis: {e}")

    symlink_nemesis = root / "Data" / "Nemesis_Engine"
    target_nemesis = (
        root
        / "MO2"
        / "mods"
        / "Project New Reign - Nemesis Unlimited Behavior Engine"
        / "Nemesis_Engine"
    )
    if target_nemesis.is_dir():
        try:
            if symlink_nemesis.is_symlink():
                if symlink_nemesis.resolve() != target_nemesis.resolve():
                    symlink_nemesis.unlink()
                    symlink_nemesis.symlink_to(target_nemesis)
                    logs.append("Обновлен симлинк Data/Nemesis_Engine -> Nemesis_Engine")
            elif not symlink_nemesis.exists():
                symlink_nemesis.symlink_to(target_nemesis)
                logs.append("Создан симлинк Data/Nemesis_Engine -> Nemesis_Engine")
        except Exception as e:
            logs.append(f"Ошибка настройки симлинка Nemesis: {e}")

    # 4. Исправление skee64.ini (отключение конфликта BodyGen для OBody)
    skee_ini = root / "MO2" / "mods" / "RaceMenu" / "SKSE" / "Plugins" / "skee64.ini"
    if skee_ini.is_file():
        try:
            content = skee_ini.read_text(encoding="utf-8", errors="replace")
            pattern = r"^[ \t]*bEnableBodyGen[ \t]*=.*$"
            if re.search(pattern, content, flags=re.MULTILINE):
                new_content = re.sub(pattern, "bEnableBodyGen=0", content, flags=re.MULTILINE)
            else:
                if "[Features]" in content:
                    new_content = content.replace("[Features]", "[Features]\nbEnableBodyGen=0")
                else:
                    new_content = content + "\n[Features]\nbEnableBodyGen=0\n"

            if new_content != content:
                skee_ini.write_text(new_content, encoding="utf-8")
                logs.append("Обновлен skee64.ini: bEnableBodyGen=0 (отключение BodyGen для OBody)")
        except Exception as e:
            logs.append(f"Ошибка обновления skee64.ini: {e}")

    # 5. Исправление MO2/ModOrganizer.ini (workingDirectory для Nemesis и BodySlide строго в [customExecutables])
    mo2_ini = root / "MO2" / "ModOrganizer.ini"
    if mo2_ini.is_file():
        try:
            content = mo2_ini.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            new_lines = []

            nemesis_idx: Optional[str] = None
            bodyslide_idx: Optional[str] = None
            pandora_idx: Optional[str] = None

            in_custom_exec = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    in_custom_exec = stripped.lower() == "[customexecutables]"
                    continue
                if not in_custom_exec:
                    continue

                m_nem = re.match(r"^(\d+)\\(?:title|binary)=.*Nemesis.*", line, re.IGNORECASE)
                if m_nem and not nemesis_idx:
                    nemesis_idx = m_nem.group(1)
                m_bs = re.match(r"^(\d+)\\(?:title|binary)=.*BodySlide.*", line, re.IGNORECASE)
                if m_bs and not bodyslide_idx:
                    bodyslide_idx = m_bs.group(1)
                m_pan = re.match(r"^(\d+)\\(?:title|binary)=.*Pandora.*", line, re.IGNORECASE)
                if m_pan and not pandora_idx:
                    pandora_idx = m_pan.group(1)

            modified_mo2 = False
            nem_target_exe = (
                root
                / "MO2"
                / "mods"
                / "Project New Reign - Nemesis Unlimited Behavior Engine"
                / "Nemesis_Engine"
                / "Nemesis Unlimited Behavior Engine.exe"
            )
            nem_binary = f"Z:{nem_target_exe.as_posix()}"
            nem_args = ""
            nem_working = f"Z:{nem_target_exe.parent.as_posix()}"
            bs_working = "./mods/BodySlide and Outfit Studio/CalienteTools/BodySlide"

            pandora_target_exe = (
                root
                / "MO2"
                / "mods"
                / "Pandora Behaviour Engine"
                / "Pandora Behaviour Engine+.exe"
            )
            pandora_binary = f"Z:{pandora_target_exe.as_posix()}"
            pandora_working = f"Z:{pandora_target_exe.parent.as_posix()}"

            in_custom_exec = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    in_custom_exec = stripped.lower() == "[customexecutables]"
                    new_lines.append(line)
                    continue

                if not in_custom_exec:
                    new_lines.append(line)
                    continue

                if nemesis_idx and re.match(rf"^{nemesis_idx}\\binary=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != nem_binary:
                        new_lines.append(f"{nemesis_idx}\\binary={nem_binary}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif nemesis_idx and re.match(rf"^{nemesis_idx}\\arguments=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != nem_args:
                        new_lines.append(f"{nemesis_idx}\\arguments={nem_args}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif nemesis_idx and re.match(rf"^{nemesis_idx}\\workingDirectory=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != nem_working:
                        new_lines.append(f"{nemesis_idx}\\workingDirectory={nem_working}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif bodyslide_idx and re.match(rf"^{bodyslide_idx}\\workingDirectory=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if not cur_val or cur_val != bs_working:
                        new_lines.append(f"{bodyslide_idx}\\workingDirectory={bs_working}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif pandora_idx and re.match(rf"^{pandora_idx}\\binary=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != pandora_binary:
                        new_lines.append(f"{pandora_idx}\\binary={pandora_binary}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif pandora_idx and re.match(rf"^{pandora_idx}\\arguments=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != "":
                        new_lines.append(f"{pandora_idx}\\arguments=")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                elif pandora_idx and re.match(rf"^{pandora_idx}\\workingDirectory=.*$", line):
                    cur_val = line.split("=", 1)[1]
                    if cur_val != pandora_working:
                        new_lines.append(f"{pandora_idx}\\workingDirectory={pandora_working}")
                        modified_mo2 = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            if not pandora_idx and pandora_target_exe.is_file():
                # Находим границы секции [customExecutables] в new_lines
                sec_start: Optional[int] = None
                sec_end: int = len(new_lines)
                for i, line in enumerate(new_lines):
                    stripped = line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        if stripped.lower() == "[customexecutables]":
                            sec_start = i
                        elif sec_start is not None:
                            sec_end = i
                            break

                if sec_start is None:
                    new_lines.append("")
                    new_lines.append("[customExecutables]")
                    new_lines.append("size=1")
                    sec_start = len(new_lines) - 2
                    sec_end = len(new_lines)
                    new_idx = 1
                    insert_pos = sec_end
                else:
                    max_idx = 0
                    size_line_idx: Optional[int] = None
                    for i in range(sec_start + 1, sec_end):
                        m = re.match(r"^(\d+)\\", new_lines[i])
                        if m:
                            max_idx = max(max_idx, int(m.group(1)))
                        if new_lines[i].strip().startswith("size="):
                            size_line_idx = i
                    new_idx = max_idx + 1
                    if size_line_idx is not None:
                        new_lines[size_line_idx] = f"size={new_idx}"
                    else:
                        new_lines.insert(sec_start + 1, f"size={new_idx}")
                        sec_end += 1

                    p = sec_end
                    while p > sec_start + 1 and not new_lines[p - 1].strip():
                        p -= 1
                    insert_pos = p

                pandora_entry = [
                    f"{new_idx}\\arguments=",
                    f"{new_idx}\\binary={pandora_binary}",
                    f"{new_idx}\\hide=false",
                    f"{new_idx}\\ownicon=false",
                    f"{new_idx}\\steamAppID=",
                    f"{new_idx}\\title=Pandora Behaviour Engine+",
                    f"{new_idx}\\toolbar=false",
                    f"{new_idx}\\workingDirectory={pandora_working}",
                ]
                new_lines = new_lines[:insert_pos] + pandora_entry + new_lines[insert_pos:]
                modified_mo2 = True

            if modified_mo2:
                mo2_ini.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logs.append("Обновлен ModOrganizer.ini: настроен запуск Pandora, Nemesis и workingDirectory для BodySlide")
        except Exception as e:
            logs.append(f"Ошибка обновления ModOrganizer.ini: {e}")

    # 6. Исправление Config.xml для BodySlide
    bs_config = (
        root
        / "MO2"
        / "mods"
        / "BodySlide and Outfit Studio"
        / "CalienteTools"
        / "BodySlide"
        / "Config.xml"
    )
    if bs_config.is_file():
        try:
            bs_text = bs_config.read_text(encoding="utf-8", errors="replace")
            orig_bs_text = bs_text

            bs_text = re.sub(
                r"<SkyrimSpecialEdition>.*?</SkyrimSpecialEdition>",
                lambda _: f"<SkyrimSpecialEdition>{wine_data_dir}</SkyrimSpecialEdition>",
                bs_text,
            )
            bs_text = re.sub(
                r"<GameDataPath>.*?</GameDataPath>",
                lambda _: f"<GameDataPath>{wine_data_dir}</GameDataPath>",
                bs_text,
            )
            bs_text = re.sub(
                r"<OutputDataPath>.*?</OutputDataPath>",
                lambda _: "<OutputDataPath></OutputDataPath>",
                bs_text,
            )

            if bs_text != orig_bs_text:
                bs_config.write_text(bs_text, encoding="utf-8")
                logs.append(f"Обновлен BodySlide Config.xml: GameDataPath={wine_data_dir}, OutputDataPath очищен")
        except Exception as e:
            logs.append(f"Ошибка обновления BodySlide Config.xml: {e}")

    # 7. Каталоги кэша шейдеров и исправление ShaderCache в enblocal.ini для ENBSeries
    enb_cache_dirs = [
        root / "enbcache",
        root / "enbseries" / "cache",
        root / "reshade-shaders" / "Cache",
    ]
    for d in enb_cache_dirs:
        if not d.exists():
            try:
                d.mkdir(parents=True, exist_ok=True)
                logs.append(f"Создан каталог кэша: {d.relative_to(root)}")
            except Exception as e:
                logs.append(f"Ошибка создания каталога {d}: {e}")

    enblocal_ini = root / "enblocal.ini"
    if enblocal_ini.is_file():
        try:
            enb_text = enblocal_ini.read_text(encoding="utf-8", errors="replace")
            new_enb_text = re.sub(
                r"(?im)^([ \t]*ShaderCache[ \t]*=[ \t]*)false\b",
                r"\1true",
                enb_text,
            )
            if new_enb_text != enb_text:
                enblocal_ini.write_text(new_enb_text, encoding="utf-8")
                logs.append("Обновлен enblocal.ini: включен ShaderCache=true для устранения повторной компиляции шейдеров")
        except Exception as e:
            logs.append(f"Ошибка обновления enblocal.ini: {e}")

    # 8. Проверка и автоматическая активация обязательных плагинов сборки в profiles (Rfad_Runes.esp для refrain_nextgen.dll)
    profiles_dir = root / "MO2" / "profiles"
    if profiles_dir.is_dir():
        for p_dir in profiles_dir.iterdir():
            if not p_dir.is_dir():
                continue
            plugins_file = p_dir / "plugins.txt"
            if plugins_file.is_file():
                try:
                    p_content = plugins_file.read_text(encoding="utf-8", errors="replace")
                    p_lines = p_content.splitlines()
                    updated = False
                    new_p_lines = []
                    for line in p_lines:
                        stripped = line.strip()
                        if stripped.lower() == "rfad_runes.esp":
                            new_p_lines.append("*Rfad_Runes.esp")
                            updated = True
                        else:
                            new_p_lines.append(line)
                    if updated:
                        plugins_file.write_text("\n".join(new_p_lines) + "\n", encoding="utf-8")
                        logs.append(f"Обновлен {plugins_file.relative_to(root)}: активирован *Rfad_Runes.esp (требуется для refrain_nextgen.dll)")
                except Exception as e:
                    logs.append(f"Ошибка проверки {plugins_file}: {e}")

    # 10. Отключение сбойной экспериментальной сборки Alchemy.dll из 6_2_Base
    broken_alchemy = root / "MO2" / "mods" / "6_2_Base" / "SKSE" / "Plugins" / "Alchemy.dll"
    if broken_alchemy.is_file():
        try:
            disabled_target = broken_alchemy.with_suffix(".dll.disabled")
            broken_alchemy.rename(disabled_target)
            logs.append("Отключена сбойная экспериментальная Alchemy.dll из 6_2_Base (активна стабильная из RFAD_New_Alchemy)")
        except Exception as e:
            logs.append(f"Ошибка отключения Alchemy.dll в 6_2_Base: {e}")

    return logs


class GameRunner:
    """Управляет подготовкой окружения и запуском MO2 / игры."""

    def __init__(self, paths: GamePaths, config: Dict[str, Any]) -> None:
        self.paths = paths
        self.config = config

    def _is_opt_enabled(self, name: str, default: bool = True) -> bool:
        """Проверяет статус оптимизации с поддержкой вложенного словаря и плоских ключей."""
        opts = self.config.get("optimizations")
        if isinstance(opts, dict) and name in opts:
            return bool(opts[name])
        return bool(self.config.get(name, default))

    def _get_wine_env(self) -> Dict[str, str]:
        """Формирует изолированные переменные окружения для запуска Wine."""
        env = os.environ.copy()

        pfx = self.paths.wine_prefix
        if not pfx:
            raise RuntimeError("Не удалось определить WINEPREFIX")

        proton_dir = self.paths.proton_files_dir
        wine_bin = self.paths.wine_bin
        mo2_dir = self.paths.mo2_exe.parent

        # 1. Формирование путей библиотек и DLL
        wine_dll_candidates: List[str] = []
        ld_candidates: List[str] = []
        wine_bin_dir: Optional[Path] = None

        if proton_dir:
            wine_bin_dir = proton_dir / "bin"
            w_lib = proton_dir / "lib"
            w_lib64 = proton_dir / "lib64"

            # LD_LIBRARY_PATH кандидаты
            for p in [
                w_lib,
                w_lib64,
                w_lib / "x86_64-linux-gnu",
                w_lib / "i386-linux-gnu",
                w_lib64 / "x86_64-linux-gnu",
                w_lib64 / "i386-linux-gnu",
            ]:
                if p.is_dir():
                    ld_candidates.append(str(p))

            # WINEDLLPATH кандидаты (включая 32-битные i386-unix и i386-windows)
            for p in [
                w_lib / "wine" / "x86_64-unix",
                w_lib / "wine" / "x86_64-windows",
                w_lib / "wine" / "i386-unix",
                w_lib / "wine" / "i386-windows",
                w_lib / "wine",
                w_lib64 / "wine" / "x86_64-unix",
                w_lib64 / "wine" / "x86_64-windows",
                w_lib64 / "wine" / "i386-unix",
                w_lib64 / "wine" / "i386-windows",
                w_lib64 / "wine",
            ]:
                if p.is_dir():
                    wine_dll_candidates.append(str(p))

        elif wine_bin:
            wine_bin_dir = wine_bin.parent

        wine_dll_candidates.append(str(mo2_dir))

        # LD_LIBRARY_PATH
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        if existing_ld:
            ld_candidates.append(existing_ld)
        if ld_candidates:
            env["LD_LIBRARY_PATH"] = ":".join(ld_candidates)

        # WINEDLLPATH
        if wine_dll_candidates:
            env["WINEDLLPATH"] = ":".join(wine_dll_candidates)

        # PATH (каталог bin помещаем в начало)
        existing_path = env.get("PATH", "")
        if wine_bin_dir and wine_bin_dir.is_dir():
            env["PATH"] = f"{wine_bin_dir}:{existing_path}"

        # 2. Основные переменные Wine
        env["WINEPREFIX"] = str(pfx)
        env["WINEDLLOVERRIDES"] = str(
            self.config.get(
                "wine_dll_overrides",
                (
                    "concrt140=n;xaudio2_7=n,b;d3d11=n,b;dxgi=n,b;d3dx9_42=n,b;"
                    "d3dcompiler_47=n,b;dinput8=n,b;mscoree=n;d3d12=n,b;d3d12core=n,b;"
                    "uiautomationcore=b,n"
                ),
            )
        )

        # 3. Аппаратная оптимизация: NVIDIA Prime Offload (дискретная GPU NVIDIA вместо встроенной iGPU)
        if self._is_opt_enabled("nvidia_prime", True):
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            env["VKD3D_CONFIG"] = "dxr11,dxr"

        # 4. Аппаратная оптимизация: Асинхронная компиляция шейдеров (DXVK Async)
        # ВНИМАНИЕ: ENBSeries требует синхронной компиляции Direct3D 11 шейдеров.
        # При dxvk.enableAsync=true ENB намертво зависает на первом кадре ("ENBSeries compiling shaders, please wait...").
        has_enb = (self.paths.root / "d3d11.dll").is_file() and (
            (self.paths.root / "enblocal.ini").is_file() or (self.paths.root / "enbseries").is_dir()
        )
        if self._is_opt_enabled("dxvk_async", False):
            if not has_enb:
                env["DXVK_ASYNC"] = "1"
                env["DXVK_GPLASYNCCACHE"] = "1"
                env["DXVK_CONFIG"] = (
                    "dxvk.enableAsync = true; "
                    "dxvk.numCompilerThreads = 4; "
                    "dxvk.useRawSsbo = True; "
                    "dxgi.maxFrameLatency = 1"
                )
            else:
                env["DXVK_ASYNC"] = "0"
                env["DXVK_GPLASYNCCACHE"] = "0"
                env["DXVK_CONFIG"] = (
                    "dxvk.enableAsync = false; "
                    "dxvk.numCompilerThreads = 4; "
                    "dxvk.useRawSsbo = True; "
                    "dxgi.maxFrameLatency = 1"
                )
                logger.info("DXVK Async принудительно выключен для совместимости с ENBSeries")
        else:
            env["DXVK_ASYNC"] = "0"
            env["DXVK_GPLASYNCCACHE"] = "0"


        fps_limit = int(self.config.get("fps_limit", 60))
        if fps_limit > 0:
            env["DXVK_FRAME_RATE"] = str(fps_limit)

        # 5. Аппаратная оптимизация: Персистентный дисковый кэш шейдеров NVIDIA и DXVK
        if self.config.get("shader_cache", True):
            shader_dir = pfx / "shadercache"
            try:
                shader_dir.mkdir(parents=True, exist_ok=True)
                env["DXVK_STATE_CACHE"] = "1"
                env["DXVK_STATE_CACHE_PATH"] = str(shader_dir)
            except Exception as e:
                logger.warning("Не удалось создать каталог кэша DXVK: %s", e)

            if self._is_opt_enabled("persistent_shader_cache", True):
                gl_cache_dir = Path.home() / ".cache" / "nvidia" / "GLCache"
                try:
                    gl_cache_dir.mkdir(parents=True, exist_ok=True)
                    env["__GL_SHADER_DISK_CACHE_PATH"] = str(gl_cache_dir)
                except Exception as e:
                    logger.warning("Не удалось создать каталог кэша шейдеров NVIDIA: %s", e)
                env["__GL_SHADER_DISK_CACHE"] = "1"
                env["__GL_SHADER_DISK_CACHE_SIZE"] = "10737418240"  # 10 GB
                env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"
            else:
                env["__GL_SHADER_DISK_CACHE"] = "1"
                env["__GL_SHADER_DISK_CACHE_PATH"] = str(shader_dir)
        else:
            env["__GL_SHADER_DISK_CACHE"] = "0"
            env["DXVK_STATE_CACHE"] = "0"

        # 6. Аппаратная оптимизация: Синхронизация потоков CachyOS (WINE_FSYNC / WINE_NT_SYNC)
        if self._is_opt_enabled("cachyos_ntsync", True):
            env["WINE_FSYNC"] = "1"
            env["WINE_NT_SYNC"] = "1"
            env["PROTON_NO_ESYNC"] = "1"
            env["PROTON_ENABLE_NVAPI"] = "1"

        # 7. FSR и HDR
        if self.config.get("hdr", False):
            env["DXVK_HDR"] = "1"

        if self.config.get("fsr", False):
            env["WINE_FULLSCREEN_FSR"] = "1"
            fsr_level = int(self.config.get("fsr_level", 95))
            # Масштаб резкости от 0 (макс) до 5 (мин)
            strength = max(0, min(5, int(5 * (1 - fsr_level / 100))))
            env["WINE_FULLSCREEN_FSR_STRENGTH"] = str(strength)

        # 8. Стабильность интерфейса Wine и подавление лишнего спама
        env["WINEDEBUG"] = "-all"
        env["QT_OPENGL"] = "software"

        return env

    def build_environment(self) -> Dict[str, str]:
        """Формирует изолированные переменные окружения для запуска Wine (обертка над _get_wine_env)."""
        return self._get_wine_env()

    def build_command_prefix(self) -> List[str]:
        """Строит цепочку системных оберток (gamemoderun, mangohud, gamescope)."""
        prefix: List[str] = []

        # Gamescope
        if self.config.get("gamescope", False) and shutil.which("gamescope"):
            prefix.extend(["gamescope", "-f", "--"])

        # Gamemode (перевод процессора CPU в режим 'performance' governor)
        if self._is_opt_enabled("gamemode", True) and shutil.which("gamemoderun"):
            prefix.append("gamemoderun")

        # MangoHud
        if self.config.get("mangohud", False) and shutil.which("mangohud"):
            prefix.append("mangohud")

        return prefix

    def _ensure_dosdevices(self) -> None:
        """Гарантирует наличие симлинков c: и z: в dosdevices для избежания ошибки status c0000135."""
        pfx = self.paths.wine_prefix
        if not pfx:
            return
        dosdevices = pfx / "dosdevices"
        dosdevices.mkdir(parents=True, exist_ok=True)
        drive_c = pfx / "drive_c"
        if drive_c.is_dir():
            c_link = dosdevices / "c:"
            z_link = dosdevices / "z:"
            try:
                if not c_link.exists() and not c_link.is_symlink():
                    os.symlink("../drive_c", c_link)
                if not z_link.exists() and not z_link.is_symlink():
                    os.symlink("/", z_link)
            except Exception as e:
                logger.warning("Ошибка восстановления dosdevices: %s", e)

    def launch(
        self,
        target: str = "mo2",
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """
        Запускает MO2 или игру напрямую с необходимыми аргументами.
        target: 'mo2' для запуска Mod Organizer, 'game' для прямого старта через SKSE.
        Безопасно перенаправляет логи без утечки файловых дескрипторов.
        """
        self._ensure_dosdevices()

        # Автоматическое предстартовое исправление утилит сборки (Nemesis, BodySlide, OBody, SKSE)
        try:
            fixes = auto_fix_rfad(self.paths.root)
            for fix in fixes:
                logger.info("[Pre-flight Fix] %s", fix)
        except Exception as e:
            logger.warning("Ошибка автоматического предстартового исправления: %s", e)

        # Автоматическая синхронизация графического пресета (изоляция ENB / ReShade)
        try:
            from src.core.graphics import GraphicsManager
            gfx = GraphicsManager(self.paths)
            active_gfx = self.config.get("graphic_mod", "ReShade")
            gfx.apply_graphic_preset(active_gfx)
            logger.info("[Pre-flight Graphics] Синхронизирован профиль графики: %s", active_gfx)
        except Exception as e:
            logger.warning("Ошибка синхронизации графического профиля: %s", e)

        # Синхронизация Steam DRM фикса
        try:
            from src.core.mods import ModManager
            ModManager(self.paths).set_steam_drm(bool(self.config.get("steam_drm", False)))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("Ошибка применения настройки Steam DRM: %s", e)

        wine_bin = self.paths.wine_bin
        if not wine_bin:
            raise FileNotFoundError("Исполняемый файл Wine не найден.")

        mo2_exe = self.paths.mo2_exe
        if not mo2_exe.is_file():
            raise FileNotFoundError(f"ModOrganizer.exe не найден: {mo2_exe}")

        env = self.build_environment()
        cmd: List[str] = self.build_command_prefix()
        cmd.extend([str(wine_bin), str(mo2_exe)])

        if target == "game":
            cmd.append("moshortcut://:SKSE")

        logger.info("Запуск команды: %s", " ".join(cmd))
        logger.info("Рабочий каталог: %s", mo2_exe.parent)

        out_fd = subprocess.DEVNULL
        out_file_obj = None

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            out_file_obj = open(log_file, "w", encoding="utf-8", errors="replace")
            out_fd = out_file_obj.fileno()

        _optimize_process_limits()
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(mo2_exe.parent),
                env=env,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            return process
        finally:
            if out_file_obj:
                out_file_obj.close()

    def launch_nemesis(
        self,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """
        Запускает Nemesis Unlimited Behavior Engine в изолированном виртуальном рабочем столе Wine Desktop (1280x720).
        Это гарантирует обход багов WS_POPUP / WM_NCCALCSIZE в Wine 11 и предотвращает дедлоки USVFS.
        """
        self._ensure_dosdevices()

        try:
            fixes = auto_fix_rfad(self.paths.root)
            for fix in fixes:
                logger.info("[Pre-flight Fix] %s", fix)
        except Exception as e:
            logger.warning("Ошибка автоматического предстартового исправления: %s", e)

        wine_bin = self.paths.wine_bin
        if not wine_bin:
            raise FileNotFoundError("Исполняемый файл Wine не найден.")

        nem_dir = (
            self.paths.root
            / "MO2"
            / "mods"
            / "Project New Reign - Nemesis Unlimited Behavior Engine"
            / "Nemesis_Engine"
        )
        nem_exe = nem_dir / "Nemesis Unlimited Behavior Engine.exe"
        if not nem_exe.is_file():
            raise FileNotFoundError(f"Nemesis Unlimited Behavior Engine.exe не найден: {nem_exe}")

        env = self.build_environment()
        cmd: List[str] = self.build_command_prefix()
        cmd.extend([str(wine_bin), "explorer", "/desktop=Nemesis,1280x720", str(nem_exe)])

        logger.info("Запуск Nemesis (Wine Desktop): %s", " ".join(cmd))
        logger.info("Рабочий каталог: %s", nem_dir)

        out_fd = subprocess.DEVNULL
        out_file_obj = None

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            out_file_obj = open(log_file, "w", encoding="utf-8", errors="replace")
            out_fd = out_file_obj.fileno()

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(nem_dir),
                env=env,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            return process
        finally:
            if out_file_obj:
                out_file_obj.close()

    def launch_cao(
        self,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """
        Запускает Cathedral Assets Optimizer под Proton Wine в виртуальном рабочем столе Wine Desktop (1280x800).
        Используется для безопасного сжатия текстур сборки под 4 ГБ VRAM.
        """
        self._ensure_dosdevices()

        wine_bin = self.paths.wine_bin
        if not wine_bin:
            raise FileNotFoundError("Исполняемый файл Wine не найден.")

        cao_exe: Optional[Path] = None
        search_roots = [
            self.paths.root / "tools",
            self.paths.root,
            Path.home() / "Temp",
            Path.home() / "Downloads",
        ]
        for s_root in search_roots:
            if not s_root.is_dir():
                continue
            direct_cand = s_root / "Cathedral_Assets_Optimizer.exe"
            if direct_cand.is_file():
                cao_exe = direct_cand
                break
            for sub in sorted(s_root.glob("Cathedral Assets Optimizer*"), reverse=True):
                cand = sub / "Cathedral_Assets_Optimizer.exe"
                if cand.is_file():
                    cao_exe = cand
                    break
            if cao_exe:
                break

        if not cao_exe or not cao_exe.is_file():
            raise FileNotFoundError(
                f"Cathedral_Assets_Optimizer.exe не найден в {self.paths.root / 'tools'} или стандартных каталогах."
            )
        cao_dir = cao_exe.parent

        env = self.build_environment()
        env["WINEDLLOVERRIDES"] = "concrt140=n;mscoree=n"

        cmd: List[str] = self.build_command_prefix()
        cmd.extend([str(wine_bin), "explorer", "/desktop=CAO,1280x800", str(cao_exe)])

        logger.info("Запуск CAO (Wine Desktop): %s", " ".join(cmd))
        logger.info("Рабочий каталог: %s", cao_dir)

        out_fd = subprocess.DEVNULL
        out_file_obj = None

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            out_file_obj = open(log_file, "w", encoding="utf-8", errors="replace")
            out_fd = out_file_obj.fileno()

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(cao_dir),
                env=env,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            return process
        finally:
            if out_file_obj:
                out_file_obj.close()

    def launch_pandora(
        self,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """
        Запускает Pandora Behaviour Engine+ под Wine.
        Pandora — 64-битный современный генератор на базе .NET (Avalonia UI),
        превосходно работающий напрямую под Proton/Wine без необходимости в Wine Desktop.
        """
        self._ensure_dosdevices()

        try:
            fixes = auto_fix_rfad(self.paths.root)
            for fix in fixes:
                logger.info("[Pre-flight Fix] %s", fix)
        except Exception as e:
            logger.warning("Ошибка автоматического предстартового исправления: %s", e)

        wine_bin = self.paths.wine_bin
        if not wine_bin:
            raise FileNotFoundError("Исполняемый файл Wine не найден.")

        mo2_exe = self.paths.mo2_exe
        pandora_dir = (
            self.paths.root
            / "MO2"
            / "mods"
            / "Pandora Behaviour Engine"
        )
        pandora_exe = pandora_dir / "Pandora Behaviour Engine+.exe"
        if not pandora_exe.is_file():
            pandora_exe = pandora_dir / "Pandora.exe"
        if not pandora_exe.is_file():
            raise FileNotFoundError(f"Pandora Behaviour Engine+.exe не найден: {pandora_exe}")

        env = self.build_environment()
        cmd: List[str] = self.build_command_prefix()

        # Приоритет: запуск через виртуальную файловую систему Mod Organizer 2 (VFS shortcut),
        # чтобы Pandora видела все установленные моды сборки (360 Movement, TK Dodge, Ultimate Combat, XPMSSE и др.)
        if mo2_exe.is_file():
            cmd.extend([str(wine_bin), str(mo2_exe), "moshortcut://:Pandora Behaviour Engine+"])
            working_dir = mo2_exe.parent
            logger.info("Запуск Pandora Behaviour Engine+ через MO2 VFS: %s", " ".join(cmd))
        else:
            cmd.extend([str(wine_bin), str(pandora_exe)])
            working_dir = pandora_dir
            logger.info("Запуск Pandora Behaviour Engine+ напрямую: %s", " ".join(cmd))

        logger.info("Рабочий каталог: %s", working_dir)

        out_fd = subprocess.DEVNULL
        out_file_obj = None

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            out_file_obj = open(log_file, "w", encoding="utf-8", errors="replace")
            out_fd = out_file_obj.fileno()

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(working_dir),
                env=env,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            return process
        finally:
            if out_file_obj:
                out_file_obj.close()

    def launch_bethini(
        self,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """
        Запускает BethINI Standalone под Wine.
        Рабочая директория (cwd) устанавливается в каталог BethINI.exe для корректного чтения BethINI.ini.
        """
        self._ensure_dosdevices()

        wine_bin = self.paths.wine_bin
        if not wine_bin:
            raise FileNotFoundError("Исполняемый файл Wine не найден.")

        bethini_exe = self.paths.bethini_exe
        if not bethini_exe or not bethini_exe.is_file():
            raise FileNotFoundError(f"BethINI.exe не найден в {self.paths.root}")

        bethini_dir = bethini_exe.parent
        env = self.build_environment()
        cmd: List[str] = self.build_command_prefix()
        cmd.extend([str(wine_bin), str(bethini_exe)])

        logger.info("Запуск BethINI: %s", " ".join(cmd))
        logger.info("Рабочий каталог: %s", bethini_dir)

        out_fd = subprocess.DEVNULL
        out_file_obj = None

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            out_file_obj = open(log_file, "w", encoding="utf-8", errors="replace")
            out_fd = out_file_obj.fileno()

        _optimize_process_limits()
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(bethini_dir),
                env=env,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
            return process
        finally:
            if out_file_obj:
                out_file_obj.close()


