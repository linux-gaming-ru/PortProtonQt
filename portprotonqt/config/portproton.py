"""PortProton configuration and launch helpers."""
import configparser
import hashlib
import os
import re
import shlex
import sys
import shutil
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from portprotonqt.config.base import (
    BaseConfig,
    CONFIG_FILE,
    PORTPROTON_CONFIG_FILE,
    _config_cache,
    _config_mtime,
)
from portprotonqt.config.validators import validate_path
from portprotonqt.localization import _
from portprotonqt.logger import get_logger

logger = get_logger(__name__)
_portproton_start_command: list[str] | None = None


def _sanitize_icon_name(name: str) -> str:
    """Convert a game name to a safe icon file name."""
    sanitized_name = name.replace(" ", "_")
    for char in ("!", "%", "$", "&", "<"):
        sanitized_name = sanitized_name.replace(char, "")
    return sanitized_name


class PortProtonConfig(BaseConfig):
    """PortProton location configuration."""

    _section = "PortProton"
    _portproton_location: str | None = None

    def __init__(self):
        super().__init__()
        self._config_file = PORTPROTON_CONFIG_FILE

    def get_location(self) -> str | None:
        """Get PortProton directory location."""
        if self._portproton_location is not None:
            return self._portproton_location

        if self._config_file.exists():
            try:
                location = self._config_file.read_text(encoding="utf-8").strip()
                if location and os.path.isdir(location):
                    self._portproton_location = location
                    logger.info("PortProton path from configuration: %s", location)
                    return self._portproton_location
                logger.warning("Invalid PortProton path in configuration: %s", location)
            except (OSError, PermissionError) as error:
                logger.warning("Failed to read PortProton configuration file: %s", error)
            except Exception as error:
                logger.warning("Unexpected error reading PortProton configuration file: %s", error)

        flatpak_path = os.path.join(os.path.expanduser("~"), ".var", "app", "ru.linux_gaming.PortProton")
        if os.path.isdir(flatpak_path):
            self._portproton_location = flatpak_path
            logger.info("PortProton path from Flatpak location: %s", flatpak_path)
            return self._portproton_location

        logger.warning("PortProton configuration not found")
        return None

    def set_location(self, location: str):
        """Set PortProton directory location."""
        validate_path(location, "portproton_location", must_exist=True)
        self._config_file.write_text(location, encoding="utf-8")
        self._portproton_location = location
        logger.info("PortProton location set to: %s", location)


def _read_config_safely(config_file: Path = CONFIG_FILE) -> configparser.ConfigParser | None:
    """Read a config file with local cache awareness."""
    config_path = str(config_file)
    if not config_file.exists():
        return None
    try:
        current_mtime = config_file.stat().st_mtime
    except OSError:
        return None

    if config_path in _config_cache and config_path in _config_mtime:
        if _config_mtime[config_path] == current_mtime:
            return _config_cache[config_path]

    cp = configparser.ConfigParser()
    try:
        cp.read(config_path, encoding="utf-8")
        _config_cache[config_path] = cp
        _config_mtime[config_path] = current_mtime
        return cp
    except (configparser.DuplicateSectionError, configparser.DuplicateOptionError):
        return None


def read_portdata_path_from_config() -> str | None:
    """Read PortProton data path from main config."""
    cp = _read_config_safely(CONFIG_FILE)
    if cp is None or not cp.has_section("PortProton"):
        return None

    portdata_path = cp.get("PortProton", "portdata_path", fallback="").strip()
    if not portdata_path or not os.path.isdir(portdata_path):
        return None
    return portdata_path


def get_portproton_location() -> str | None:
    """Return PortProton directory path."""
    if os.getenv("FLATPAK_ID"):
        portdata_path = os.getenv("XDG_DATA_HOME", "").strip()
        if portdata_path:
            return str(Path(portdata_path).parent)

    saved_portdata_path = read_portdata_path_from_config()
    if saved_portdata_path:
        return saved_portdata_path

    portproton_location = PortProtonConfig().get_location()
    if portproton_location:
        save_portdata_path_to_config(portproton_location)
    return portproton_location


def save_portdata_path_to_config(portdata_path: str) -> bool:
    """Save PortProton data path to main config."""
    if not portdata_path or not os.path.isdir(portdata_path):
        logger.warning("Invalid PORT_DATA_PATH for config save: %s", portdata_path)
        return False

    cp = _read_config_safely(CONFIG_FILE) or configparser.ConfigParser()
    if "PortProton" not in cp:
        cp["PortProton"] = {}
    cp["PortProton"]["portdata_path"] = portdata_path
    try:
        os.makedirs(CONFIG_FILE.parent, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
            cp.write(config_file)
        _config_cache.pop(str(CONFIG_FILE), None)
        _config_mtime.pop(str(CONFIG_FILE), None)
        return True
    except OSError as error:
        logger.warning("Failed to save PORT_DATA_PATH to config: %s", error)
        return False


def get_portproton_scripts_path() -> str | None:
    """Return PortProton scripts directory path."""
    appdir_prefix = os.getenv("APPDIR")
    sharun_prefix = os.getenv("SHARUN_DIR")
    appimage_path = os.getenv("APPIMAGE", "").strip()
    prefixes = []
    if appdir_prefix:
        prefixes.append(("AppImage appdir", Path(appdir_prefix)))
    if sharun_prefix:
        prefixes.append(("AppImage", Path(sharun_prefix)))
    if appimage_path:
        appimage_root = Path(sys.executable).resolve().parent.parent
        prefixes.append(("AppImage executable", appimage_root))
    prefixes.append(("system package", Path("/usr")))
    xdg_scripts_dirs = [
        ("XDG data", Path(data_dir) / "portproton" / "scripts")
        for data_dir in os.getenv(
            "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
        ).split(os.pathsep)
        if data_dir
    ]

    scripts_dirs = (
        ("repository", Path.cwd() / "build-aux" / "share" / "portproton" / "scripts"),
        *[(source, prefix / "share" / "portproton" / "scripts") for source, prefix in prefixes],
        *xdg_scripts_dirs,
    )
    for source, scripts_dir in scripts_dirs:
        if (scripts_dir / "start.sh").is_file():
            logger.info("Using PortProton scripts from %s: %s", source, scripts_dir)
            return str(scripts_dir)
    logger.info(
        "PortProton scripts directory not found in: %s",
        ", ".join(str(path) for _, path in scripts_dirs),
    )
    return None


def get_portproton_start_command() -> list[str] | None:
    """Return command list for PortProton launch."""
    global _portproton_start_command
    if _portproton_start_command is not None:
        return _portproton_start_command

    scripts_path = get_portproton_scripts_path()
    if scripts_path:
        _portproton_start_command = [os.path.join(scripts_path, "start.sh")]
        return _portproton_start_command

    logger.warning("start.sh not found for PortProton")
    return None


def _get_current_launcher_command() -> list[str] | None:
    """Return the current launcher command for shortcut migration."""
    appimage_path = os.getenv("APPIMAGE", "").strip()
    if appimage_path and os.path.isfile(appimage_path):
        return [appimage_path, "--silent"]

    flatpak_id = os.getenv("FLATPAK_ID", "").strip()
    if flatpak_id:
        return ["flatpak", "run", flatpak_id, "--silent"]

    scripts_path = get_portproton_scripts_path()
    if scripts_path:
        return [os.path.join(scripts_path, "start.sh")]

    if shutil.which("portprotonqt"):
        return ["portprotonqt", "--silent"]
    return None


def _extract_launcher_tail(parts: list[str]) -> list[str] | None:
    """Return shortcut args after the launcher command."""
    if not parts:
        return None

    command_name = os.path.basename(parts[0])
    appimage_name = command_name.casefold()
    is_portproton_appimage = re.fullmatch(
        r"portproton(?:qt)?(?:[-_.].*)?\.appimage",
        appimage_name,
    ) is not None
    if (
        is_portproton_appimage
        or command_name == "portprotonqt"
        or command_name == "start.sh"
    ):
        tail = parts[1:]
        if tail[:1] == ["--silent"]:
            tail = tail[1:]
        return tail

    if parts[0] == "flatpak" and len(parts) >= 3 and parts[1] == "run":
        tail = parts[3:]
        if tail[:1] == ["--silent"]:
            tail = tail[1:]
        return tail
    return None


def _migrate_launcher_line(line: str, launcher_command: list[str] | None) -> str:
    """Update launcher command in desktop Exec or shell script line."""
    if not launcher_command:
        return line

    prefix = "Exec=" if line.startswith("Exec=") else ""
    command = line[len(prefix):].strip() if prefix else line.strip()
    if not command or command.startswith("#"):
        return line

    try:
        parts = shlex.split(command)
    except ValueError:
        return line

    tail = _extract_launcher_tail(parts)
    if tail is None:
        return line

    updated_parts = launcher_command + tail
    if not prefix and updated_parts[-1:] == ["$@"]:
        return f'{shlex.join(updated_parts[:-1])} "$@"'
    return f"{prefix}{shlex.join(updated_parts)}"


def _get_desktop_paths(desktop_dir: str | None) -> tuple[str, ...]:
    """Return desktop directories to scan for shortcuts."""
    if desktop_dir:
        return (desktop_dir,)

    desktop_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    if desktop_path:
        return (desktop_path,)

    return (os.path.join(os.path.expanduser("~"), "Desktop"),)


# Remove after the legacy shortcut migration period.
def migrate_legacy_shortcut(
    portproton_path: str,
    desktop_dir: str | None = None,
    launcher_command: list[str] | None = None,
) -> int:
    """Migrate legacy PortProton shortcuts in known desktop directories."""
    flatpak_id = os.getenv("FLATPAK_ID", "").strip()
    user_home = os.path.expanduser("~")
    legacy_home_path = os.path.join(user_home, "PortProton")
    current_home_path = os.path.join(user_home, "PortProtonQt")
    legacy_flatpak_root = os.path.join(user_home, ".var", "app", "ru.linux_gaming.PortProton")
    current_flatpak_root = os.path.join(user_home, ".var", "app", flatpak_id) if flatpak_id else ""
    escaped_current_home = re.escape(current_home_path)
    escaped_current_flatpak_root = re.escape(current_flatpak_root) if current_flatpak_root else ""
    legacy_portdata_paths = []
    if PORTPROTON_CONFIG_FILE.exists():
        try:
            legacy_config_path = PORTPROTON_CONFIG_FILE.read_text(encoding="utf-8").strip()
            if legacy_config_path:
                legacy_portdata_paths.append(legacy_config_path)
        except OSError as error:
            logger.warning("Failed to read legacy PortProton config %s: %s", PORTPROTON_CONFIG_FILE, error)

    if launcher_command is None:
        launcher_command = _get_current_launcher_command()
    desktop_paths = (
        portproton_path,
        os.path.join(user_home, ".local", "share", "applications"),
        *_get_desktop_paths(desktop_dir),
    )
    migrated = 0
    for current_path in desktop_paths:
        if not os.path.isdir(current_path):
            continue

        for entry in os.scandir(current_path):
            if not entry.name.endswith(".desktop") or not entry.is_file():
                continue

            try:
                lines = Path(entry.path).read_text(encoding="utf-8").splitlines(keepends=True)
            except OSError as error:
                logger.warning("Failed to read desktop file %s: %s", entry.path, error)
                continue

            changed = False
            for idx, line in enumerate(lines):
                line_end = "\r\n" if line.endswith("\r\n") else "\n"
                line_content = line[:-len(line_end)] if line.endswith(("\n", "\r\n")) else line

                if line_content.startswith("Path="):
                    lines[idx] = ""
                    changed = True
                    continue

                updated_line = line_content
                if not current_flatpak_root:
                    for legacy_portdata_path in legacy_portdata_paths:
                        updated_line = re.sub(
                            rf"{re.escape(legacy_portdata_path)}(?=/|$)",
                            portproton_path,
                            updated_line,
                        )

                if current_flatpak_root:
                    updated_line = re.sub(
                        rf"{re.escape(legacy_home_path)}(?=/|$)",
                        current_home_path,
                        updated_line,
                    )
                    updated_line = re.sub(
                        rf"{re.escape(legacy_flatpak_root)}(?=/|$)",
                        current_flatpak_root,
                        updated_line,
                    )
                    updated_line = re.sub(
                        rf"{escaped_current_flatpak_root}(?:Qt)+(?=/|$)",
                        current_flatpak_root,
                        updated_line,
                    )
                    updated_line = re.sub(
                        rf"{escaped_current_home}(?:Qt)+(?=/|$)",
                        current_home_path,
                        updated_line,
                    )

                if updated_line.startswith("Exec="):
                    exec_value = updated_line[len("Exec="):].strip()
                    try:
                        parts = shlex.split(exec_value)
                    except ValueError:
                        parts = []

                    if (
                        len(parts) >= 4
                        and parts[0] == "flatpak"
                        and parts[1] == "run"
                        and parts[2] == "ru.linux_gaming.PortProton"
                        and flatpak_id
                    ):
                        parts[2] = flatpak_id
                        if "--silent" not in parts:
                            parts.insert(3, "--silent")
                        updated_line = f"Exec={shlex.join(parts)}"
                    elif len(parts) >= 3 and parts[0] == "env" and os.path.basename(parts[1]) == "start.sh":
                        if "--silent" not in parts:
                            updated_line = f'Exec={shlex.join(["portprotonqt", "--silent", *parts[2:]])}'

                if updated_line.startswith("Exec="):
                    updated_line = _migrate_launcher_line(updated_line, launcher_command)

                if updated_line == line_content:
                    continue

                lines[idx] = f"{updated_line}{line_end}"
                changed = True

            if not changed:
                continue

            try:
                Path(entry.path).write_text("".join(lines), encoding="utf-8")
                migrated += 1
            except OSError as error:
                logger.warning("Failed to update desktop file %s: %s", entry.path, error)

    steam_scripts_path = os.path.join(portproton_path, "steam_scripts")
    if not os.path.isdir(steam_scripts_path):
        return migrated

    for entry in os.scandir(steam_scripts_path):
        if not entry.name.endswith(".sh") or not entry.is_file():
            continue

        try:
            lines = Path(entry.path).read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as error:
            logger.warning("Failed to read steam script %s: %s", entry.path, error)
            continue

        changed = False
        for idx, line in enumerate(lines):
            line_end = "\r\n" if line.endswith("\r\n") else "\n"
            line_content = line[:-len(line_end)] if line.endswith(("\n", "\r\n")) else line
            updated_line = _migrate_launcher_line(line_content, launcher_command)
            if updated_line == line_content:
                continue

            lines[idx] = f"{updated_line}{line_end}"
            changed = True

        if not changed:
            continue

        try:
            Path(entry.path).write_text("".join(lines), encoding="utf-8")
            migrated += 1
        except OSError as error:
            logger.warning("Failed to update steam script %s: %s", entry.path, error)
    return migrated


def parse_desktop_entry(file_path: str) -> configparser.SectionProxy | None:
    """Read and parse a .desktop file using configparser."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(file_path, encoding="utf-8")
    if "Desktop Entry" not in cp:
        return None
    return cp["Desktop Entry"]


WINDOWS_LAUNCH_EXTENSIONS = (".exe", ".bat", ".cmd", ".msi", ".reg")
DISC_IMAGE_EXTENSIONS = (".iso", ".mdf", ".nrg")
LAUNCH_FILE_EXTENSIONS = WINDOWS_LAUNCH_EXTENSIONS + DISC_IMAGE_EXTENSIONS
THEMED_LAUNCH_ICON_NAMES = {
    ".bat": "bat",
    ".cmd": "bat",
    ".msi": "msi",
    ".reg": "reg",
}


def extract_exec_target_path(exec_value: str | list[str]) -> str | None:
    """Extract target executable or image path from a desktop Exec value."""
    if isinstance(exec_value, str):
        try:
            parts = shlex.split(exec_value)
        except ValueError:
            return None
    else:
        parts = exec_value

    if not parts:
        return None

    if "--silent" in parts:
        silent_index = parts.index("--silent")
        if len(parts) > silent_index + 1:
            return os.path.expanduser(parts[silent_index + 1])
        return None

    for part in reversed(parts):
        if part.lower().endswith(LAUNCH_FILE_EXTENSIONS):
            return os.path.expanduser(part)

    if parts[0] in ("env", "flatpak"):
        return None
    return os.path.expanduser(parts[0])


def find_game_by_exe(exe_path: str) -> configparser.SectionProxy | None:
    """Find a game desktop entry by executable path."""
    portproton_path = get_portproton_location()
    if not portproton_path:
        return None

    target_exe = os.path.abspath(exe_path)
    for entry in os.scandir(portproton_path):
        if not entry.name.endswith(".desktop"):
            continue
        if entry.name.lower() in ("portproton.desktop", "readme.desktop"):
            continue

        desktop_entry = parse_desktop_entry(entry.path)
        if not desktop_entry:
            continue
        exec_line = desktop_entry.get("Exec", "")
        if not exec_line:
            continue

        game_exe = extract_exec_target_path(exec_line)
        if game_exe and os.path.abspath(game_exe) == target_exe:
            return desktop_entry
    return None


def get_custom_data_dir_name(exe_path: str) -> str:
    """Return a collision-safe custom data directory name for an executable."""
    normalized_path = os.path.normpath(os.path.abspath(os.path.expanduser(exe_path)))
    path_hash = hashlib.md5(
        normalized_path.encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    exe_name = os.path.splitext(os.path.basename(exe_path))[0]
    return f"{exe_name}_{path_hash}"


def resolve_custom_data_dir(custom_data_root: str, exe_path: str) -> str:
    """Return hashed custom data directory, falling back to the legacy name."""
    hashed_dir = os.path.join(custom_data_root, get_custom_data_dir_name(exe_path))
    legacy_name = os.path.splitext(os.path.basename(exe_path))[0]
    legacy_dir = os.path.join(custom_data_root, legacy_name)
    if not os.path.isdir(hashed_dir) and os.path.isdir(legacy_dir):
        return legacy_dir
    return hashed_dir


def create_desktop_file(
    exe_path: str,
    game_name: str | None = None,
    icon_source: str | None = None,
) -> tuple[str, str, str] | None:
    """Create desktop entry content, destination path and icon path for a game."""
    portproton_path = get_portproton_location()
    is_store_uri = re.fullmatch(r"(?:gog|egs)://launch/[^/]+", exe_path) is not None
    if not is_store_uri and not os.path.isfile(exe_path):
        logger.error("Executable not found: %s", exe_path)
        return None
    if not portproton_path:
        logger.error("PortProton location not found")
        return None

    if not game_name:
        game_name = os.path.splitext(os.path.basename(exe_path))[0]
    base_path = os.path.join(portproton_path, "data")
    icon_name = _sanitize_icon_name(game_name)
    has_icon_source = bool(icon_source and os.path.isfile(icon_source))
    icon_path = (
        "applications-games" if is_store_uri and not has_icon_source
        else os.path.join(base_path, "img", f"{icon_name}.png")
    )
    desktop_path = os.path.join(portproton_path, f"{game_name}.desktop")
    if icon_path != "applications-games":
        os.makedirs(os.path.dirname(icon_path), exist_ok=True)

    flatpak_id = os.getenv("FLATPAK_ID")
    appimage_path = os.getenv("APPIMAGE", "").strip()
    if flatpak_id:
        exec_str = f'flatpak run {flatpak_id} --silent "{exe_path}"'
        log_exec = f'flatpak run {flatpak_id} --log "{exe_path}"'
    elif appimage_path and os.path.isfile(appimage_path):
        exec_str = shlex.join([appimage_path, "--silent", exe_path])
        log_exec = shlex.join([appimage_path, "--log", exe_path])
    else:
        exec_str = f'portprotonqt --silent "{exe_path}"'
        log_exec = f'portprotonqt --log "{exe_path}"'

    comment = _('Launch "{name}" with PortProton').format(name=game_name)
    silent_name = _("Run in silent mode")
    log_name = _("Run in logging mode")
    desktop_entry = (
        "[Desktop Entry]\n"
        f"Name={game_name}\n"
        f"Comment={comment}\n"
        f"Exec={exec_str}\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=Game;\n"
        "StartupNotify=true\n"
        f"Icon={icon_path}\n"
        "Actions=RunSilent;RunLog;\n"
        "\n[Desktop Action RunSilent]\n"
        f"Name={silent_name}\n"
        f"Exec={exec_str}\n"
        f"Icon={icon_path}\n"
        "\n[Desktop Action RunLog]\n"
        f"Name={log_name}\n"
        f"Exec={log_exec}\n"
        f"Icon={icon_path}\n"
    )
    return desktop_entry, desktop_path, icon_path
