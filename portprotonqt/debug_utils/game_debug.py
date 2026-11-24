"""Game-specific debug information: PPDB, winetricks, overrides."""

import os

from portprotonqt.logger import get_logger
from portprotonqt.config import get_portproton_location, get_portproton_scripts_path

from portprotonqt.debug_utils.env_utils import get_file_content

logger = get_logger(__name__)

_DUPLICATE_LOG_VARS = {
    "PW_SCREEN_PRIMARY",
    "PW_SCREEN_RESOLUTION",
    "PW_SCREEN_REFRESH_RATE",
    "PW_WINE_USE",
}


def _get_export_key(line: str) -> str:
    stripped_line = line.strip()
    if stripped_line.startswith("export "):
        stripped_line = stripped_line[7:].strip()
    if "=" not in stripped_line:
        return ""
    return stripped_line.split("=", 1)[0].strip()


def _filter_duplicate_log_vars(content: str) -> str:
    lines = []
    for line in content.split("\n"):
        if _get_export_key(line) not in _DUPLICATE_LOG_VARS:
            lines.append(line)
    return "\n".join(lines).strip()


def get_ppdb_content(exe_path: str | None, start_cmd: list[str] | None = None) -> str:
    """Get content of PPDB file for the executable."""
    if not exe_path:
        return ""

    ppdb_path = f"{exe_path}.ppdb"

    content = ""
    if os.path.exists(ppdb_path):
        content = get_file_content(ppdb_path)
    else:
        portproton_path = get_portproton_location()
        if portproton_path:
            scripts_path = get_portproton_scripts_path()
            if scripts_path:
                default_ppdb_path = os.path.join(scripts_path, "portwine_db", "default")
                if os.path.exists(default_ppdb_path):
                    content = get_file_content(default_ppdb_path)

    return _filter_duplicate_log_vars(content) if content else ""


def get_user_overrides(portproton_path: str) -> str:
    """Get user override settings from user.conf."""
    user_conf = os.path.join(portproton_path, "data", "user.conf")
    if not os.path.exists(user_conf):
        return ""

    content = get_file_content(user_conf)
    if not content:
        return ""

    lines = []
    lines.append('# User overrides db and var settings...')

    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "bash" not in line.lower():
            if _get_export_key(line) in _DUPLICATE_LOG_VARS:
                continue
            if line.startswith("export "):
                lines.append(line)
            else:
                lines.append(f"export {line}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


def get_prefix_name(exe_path: str | None) -> str:
    """Get prefix name from PPDB file."""
    if not exe_path:
        return "DEFAULT"

    ppdb_path = f"{exe_path}.ppdb"
    if os.path.exists(ppdb_path):
        content = get_file_content(ppdb_path)
        for line in content.split("\n"):
            if line.startswith("export PW_PREFIX_NAME="):
                return line.split("=", 1)[1].strip().strip('"')

    return "DEFAULT"


def get_winetricks_log(portproton_path: str, prefix_name: str = "DEFAULT") -> str:
    """Get winetricks log content for a prefix."""
    winetricks_log = os.path.join(
        portproton_path, "data", "prefixes", prefix_name, "winetricks.log"
    )
    if not os.path.exists(winetricks_log):
        winetricks_log = os.path.join(
            portproton_path, "data", "prefixes", "DEFAULT", "winetricks.log"
        )

    content = get_file_content(winetricks_log)
    if not content:
        return ""

    lines = content.split('\n')
    filtered_lines = []
    for line in lines:
        if not (line.startswith('d3dcomp') or line.startswith('d3dx')):
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)
