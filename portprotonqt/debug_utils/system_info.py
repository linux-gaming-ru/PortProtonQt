"""System information gathering: OS, CPU, RAM, locale, filesystem, screen."""

import os
import platform
import re
import subprocess
from datetime import datetime

import psutil

from portprotonqt.logger import get_logger
from portprotonqt.localization import _
from portprotonqt.qt_utils import get_screen_info

from portprotonqt.debug_utils.env_utils import get_file_content
from portprotonqt.debug_utils.gpu_info import get_graphics_info_detailed
from portprotonqt.debug_utils.game_debug import (
    get_ppdb_content,
    get_user_overrides,
    get_prefix_name,
    get_winetricks_log,
)

logger = get_logger(__name__)


def get_os_info() -> str:
    """Get operating system info using platform module."""
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME", platform.platform())
    except Exception as e:
        logger.debug("Failed to get OS info: %s", e)
        return platform.platform()


def get_cpu_info() -> dict[str, str]:
    """Get CPU information from /proc/cpuinfo."""
    info: dict[str, str] = {
        "model": "Unknown",
        "physical_cores": "0",
        "logical_cores": "0"
    }

    content = get_file_content("/proc/cpuinfo")
    if not content:
        return info

    model_names: set[str] = set()
    cpu_cores: set[str] = set()
    processors = 0

    for line in content.split("\n"):
        if line.startswith("model name"):
            parts = line.split(":", 1)
            if len(parts) > 1:
                model_names.add(parts[1].strip())
        elif line.startswith("cpu cores"):
            parts = line.split(":", 1)
            if len(parts) > 1:
                cpu_cores.add(parts[1].strip())
        elif line.startswith("processor"):
            processors += 1

    if model_names:
        info["model"] = list(model_names)[0]
    if cpu_cores:
        info["physical_cores"] = list(cpu_cores)[0]
    info["logical_cores"] = str(processors)

    return info


def get_ram_info() -> str:
    """Get RAM information using psutil."""
    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        mem_total = f"{mem.total // 1024} kB"
        mem_available = f"{mem.available // 1024} kB"
        swap_total = f"{swap.total // 1024} kB"

        return f"MemTotal: {mem_total}\nMemAvailable: {mem_available}\nSwapTotal: {swap_total}"
    except Exception as e:
        logger.debug("Failed to get RAM info: %s", e)
        return "Unable to retrieve RAM info"


def get_ram_info_detailed() -> str:
    """Get RAM info in free command format."""
    try:
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug("Failed to get free memory info: %s", e)

    return get_ram_info()


def get_desktop_environment() -> dict[str, str]:
    """Get desktop environment information."""
    return {
        "session": os.environ.get("DESKTOP_SESSION", "Unknown"),
        "current_desktop": os.environ.get("XDG_CURRENT_DESKTOP", "Unknown"),
        "session_type": os.environ.get("XDG_SESSION_TYPE", "Unknown")
    }


def get_locale_info() -> str:
    """Get locale info, filling missing LC_* from LANG if empty."""
    try:
        lang = os.environ.get("LANG", "")

        locale_vars = [
            "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_COLLATE",
            "LC_TIME", "LC_NUMERIC", "LC_MONETARY", "LC_PAPER",
            "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE", "LC_MEASUREMENT",
            "LC_IDENTIFICATION"
        ]

        lines = []
        for var in locale_vars:
            value = os.environ.get(var, "")
            if not value and var != "LC_ALL" and lang:
                value = lang
            lines.append(f"{var}={value}")

        return "\n".join(lines) if lines else "No locale info available"

    except Exception as e:
        return f"Error getting locale info: {e}"


def get_locale_available() -> str:
    """Get available locales matching current LANG."""
    try:
        lang = os.environ.get("LANG", "")
        if not lang:
            return ""

        base_locale = lang.replace("-8", "").replace(".UTF", "").replace(".utf", "")

        result = subprocess.run(
            ["locale", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            locales = result.stdout.strip().split("\n")
            matching = [
                loc for loc in locales
                if base_locale.lower().replace(".utf-8", "") in loc.lower()
            ]
            if matching:
                return "\n".join(matching)
    except Exception as e:
        logger.debug("Failed to get available locales: %s", e)
    return ""


def get_libc_version() -> str:
    """Get C library version (musl or glibc)."""
    try:
        result = subprocess.run(
            ['ldd', '--version'],
            capture_output=True,
            text=True,
            check=False
        )
        libc_version_output = result.stdout or result.stderr

        if 'musl' in libc_version_output.lower():
            lines = libc_version_output.split('\n')
            for line in lines:
                if 'version' in line.lower() and re.search(r'\d+\.\d+', line):
                    version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', line)
                    if version_match:
                        return f"musl {version_match.group(1)}"
            return "musl (version unknown)"
        else:
            for line in libc_version_output.split('\n'):
                if 'ldd' in line.lower():
                    version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', line)
                    if version_match:
                        return f"glibc {version_match.group(1)}"

            version_match = re.search(
                r'(\d+\.\d+(?:\.\d+)?)', libc_version_output
            )
            if version_match:
                return f"glibc {version_match.group(1)}"

            return "glibc (version unknown)"
    except Exception as e:
        logger.debug("Failed to get libc version: %s", e)
        return "Unknown"


def get_program_bit_depth(exe_path: str | None) -> str:
    """Get program bit depth (32 or 64 bit) from PE header."""
    if not exe_path or not os.path.exists(exe_path):
        return "Unknown"

    try:
        with open(exe_path, 'rb') as f:
            dos_header = f.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b'MZ':
                return "Not a valid PE file"

            pe_offset = int.from_bytes(dos_header[60:64], 'little')
            f.seek(pe_offset)

            pe_sig = f.read(4)
            if pe_sig != b'PE\x00\x00':
                return "Not a valid PE file"

            machine = f.read(2)
            machine_type = int.from_bytes(machine, 'little')

            if machine_type == 0x014c:
                return "32 bit"
            elif machine_type == 0x8664:
                return "64 bit"
            elif machine_type == 0x01c4:
                return "32 bit (ARM)"
            elif machine_type == 0xAA64:
                return "64 bit (ARM64)"
            else:
                return f"Unknown (0x{machine_type:04x})"
    except Exception as e:
        logger.debug("Failed to detect bit depth: %s", e)
        return "Unknown"


def get_filesystem_info(exe_path: str | None, portproton_path: str) -> str:
    """Get filesystem info for game and PortProton directories."""

    def get_fs_type(path: str) -> str:
        """Get filesystem type using psutil, with lsblk fallback for fuseblk."""
        try:
            path = os.path.realpath(path)
            partitions = {
                p.mountpoint: (p.device, p.fstype)
                for p in psutil.disk_partitions(all=True)
            }

            device, fstype = None, None
            check_path = path
            while check_path != "/":
                if check_path in partitions:
                    device, fstype = partitions[check_path]
                    break
                check_path = os.path.dirname(check_path)

            if fstype is None:
                device, fstype = partitions.get("/", (None, "Unknown"))

            if fstype == "fuseblk" and device:
                try:
                    result = subprocess.run(
                        ["lsblk", "-no", "FSTYPE", device],
                        capture_output=True,
                        text=True,
                        timeout=2,
                        check=False
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        fstype = result.stdout.strip()
                except Exception as e:
                    logger.debug("Failed to get fstype for %s: %s", device, e)

            return fstype
        except Exception as e:
            logger.debug("Failed to get filesystem info: %s", e)
            return "Unknown"

    lines = []

    if exe_path:
        game_dir = os.path.dirname(exe_path)
        lines.append(f"Filesystem {game_dir} - {get_fs_type(game_dir)}")

    if portproton_path:
        lines.append(f"Filesystem {portproton_path} - {get_fs_type(portproton_path)}")

    tmp_dir = f"/tmp/PortProton_{os.environ.get('USER', 'user')}"
    if os.path.exists(tmp_dir):
        lines.append(f"Filesystem {tmp_dir} - {get_fs_type(tmp_dir)}")

    return "\n".join(lines) if lines else "Unable to retrieve filesystem info"


def generate_system_info(
    exe_path: str | None = None,
    start_cmd: list[str] | None = None,
    runtime_env: dict[str, str] | None = None
) -> str:
    """Generate system information part of debug log."""
    from portprotonqt.config import get_portproton_location
    from portprotonqt.debug_utils.env_utils import (
        get_runtime_status,
        get_vulkan_use_info,
        get_wine_version,
        get_d3d_extras_status,
    )

    from portprotonqt.native_games import load_native_settings, get_native_launch, get_native_ppdb_path

    native = bool(exe_path and exe_path.startswith("native://"))
    desktop_path = exe_path.removeprefix("native://") if native and exe_path else None
    if desktop_path:
        runtime_env = load_native_settings(desktop_path)
        command, directory = get_native_launch(desktop_path)
        exe_path = next((part for part in reversed(command)
                         if os.path.isabs(part) and os.path.isfile(part) and os.access(part, os.X_OK)), directory)
    portproton_path = get_portproton_location() or ""
    if not portproton_path and not native:
        return "Error: PortProton location not found"

    lines = []

    lines.append(_("Debug log mode was launched"))
    lines.append(
        _("To diagnose the problem, copy the ENTIRE log to the site:") +
        " https://linux-gaming.ru/forum/help/portprotonqt-pomosch"
    )
    lines.append("-" * 61)

    lines.append("PortProtonQt version:")
    from portprotonqt.app import get_version
    ppqt_version = get_version()
    lines.append(ppqt_version)
    lines.append("-" * 61)

    lines.append(get_runtime_status(portproton_path, exe_path, start_cmd, runtime_env))
    lines.append("-" * 61)

    if exe_path:
        lines.append("Debug for programm:")
        lines.append(exe_path)
        lines.append("-" * 61)

    lines.append("libc version:")
    lines.append(get_libc_version())
    lines.append("-" * 61)

    if not native:
        lines.append(get_vulkan_use_info(portproton_path, exe_path))
        lines.append("-" * 61)

        lines.append("Version WINE in use:")
        lines.append(get_wine_version(portproton_path, exe_path))
        lines.append("-" * 61)

        lines.append("Program bit depth:")
        lines.append(get_program_bit_depth(exe_path))
        lines.append("-" * 61)

    lines.append("Date and time of start debug for PortProton:")
    lines.append(datetime.now().strftime("%c %z"))
    lines.append("-" * 61)

    lines.append("The installation path of the PortProton:")
    lines.append(portproton_path)
    lines.append("-" * 61)

    lines.append("Operating system:")
    lines.append(get_os_info())
    lines.append("-" * 61)

    lines.append("Desktop environment:")
    desktop = get_desktop_environment()
    lines.append(f"Desktop session: {desktop['session']}")
    lines.append(f"Current desktop: {desktop['current_desktop']}")
    lines.append(f"Session type: {desktop['session_type']}")
    lines.append("-" * 61)

    lines.append("Kernel:")
    lines.append(platform.release())
    lines.append("-" * 61)

    lines.append("CPU:")
    cpu = get_cpu_info()
    lines.append(f"CPU physical cores: {cpu['physical_cores']}")
    lines.append(f"CPU logical cores: {cpu['logical_cores']}")
    lines.append(f"CPU model name: {cpu['model']}")
    lines.append("-" * 61)

    lines.append("RAM:")
    lines.append(get_ram_info_detailed())
    lines.append("-" * 61)

    lines.append(get_filesystem_info(exe_path, portproton_path))
    lines.append("-" * 61)

    lines.append("Graphic cards and drivers:")
    graphics_lines = []
    ppdb_log_vars = []
    for line in get_graphics_info_detailed().split("\n"):
        if line.startswith("export PW_GPU_INFO="):
            ppdb_log_vars.append(line)
        else:
            graphics_lines.append(line)
    lines.append("\n".join(graphics_lines).strip())
    lines.append("-" * 61)

    screen_resolution, screen_primary = get_screen_info()
    if screen_resolution:
        lines.append(screen_resolution)

    if screen_primary:
        lines.append(screen_primary)
    lines.append("-" * 61)

    lines.append("locale:")
    lines.append(get_locale_info())
    lines.append("-" * 61)
    locale_avail = get_locale_available()
    if locale_avail:
        lines.append(locale_avail)
        lines.append("-" * 61)

    if not native:
        lines.append(get_d3d_extras_status(portproton_path, exe_path))
        lines.append("-" * 61)

        prefix_name = get_prefix_name(exe_path)
        winetricks_content = get_winetricks_log(portproton_path, prefix_name)
        if winetricks_content:
            lines.append("winetricks.log:")
            lines.append(winetricks_content)
            lines.append("-" * 61)

    if exe_path:
        ppdb_path = str(get_native_ppdb_path(desktop_path, runtime_env)).removesuffix(".ppdb") if desktop_path and runtime_env else exe_path
        ppdb_content = get_file_content(ppdb_path + ".ppdb") if native else get_ppdb_content(exe_path, start_cmd)
        if ppdb_content:
            lines.append(f"Use {ppdb_path}.ppdb db file:")
            if ppdb_log_vars:
                lines.append("\n".join(ppdb_log_vars))
            lines.append(ppdb_content)
            lines.append("-" * 61)

    user_overrides = "" if native else get_user_overrides(portproton_path)
    if user_overrides:
        lines.append(user_overrides)
        lines.append("-" * 61)

    lines.append("-" * 61)

    safe_lines = []
    for i, line in enumerate(lines):
        if line is None:
            logger.warning("None value found at index %d in generate_system_info", i)
            safe_lines.append("")
        else:
            safe_lines.append(str(line))

    return "\n".join(safe_lines)
