"""Discover installed native games from desktop application entries."""

import configparser
import platform
import hashlib
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QStandardPaths, QThread

from portprotonqt.config import LAUNCH_FILE_EXTENSIONS, WINDOWS_LAUNCH_EXTENSIONS, get_portproton_location, get_portproton_scripts_path, get_custom_data_dir_name
from portprotonqt.config.portproton import get_custom_icon_path, extract_exec_target_path
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.time_utils import (
    get_statistics_path, parse_playtime_file, get_last_launch_path, _parse_last_launch_line,
    format_last_launch, format_playtime,
)

logger = get_logger(__name__)
NATIVE_URI_PREFIX = "native://"
NATIVE_SETTINGS_SECTION = "X-PortProtonQt"
NATIVE_TOGGLE_KEYS = frozenset({"PW_USE_GAMEMODE", "PW_USE_RUNTIME", "PW_REDUCE_PULSE_LATENCY",
                              "PW_USE_GALLIUM_ZINK", "PW_USE_OBS_VKCAPTURE", "PW_USE_INHIBIT_SLEEP"})
NATIVE_ADVANCED_KEYS = frozenset({"LAUNCH_PARAMETERS", "PW_MESA_GL_VERSION_OVERRIDE", "PW_LOCALE_SELECT",
                                "PW_MESA_VK_WSI_PRESENT_MODE", "PW_WINE_CPU_TOPOLOGY"})


def is_native_executable(path: str) -> bool:
    """Recognize native launch files while preserving Windows and disc formats."""
    suffix = Path(path).suffix.lower()
    return bool(path) and suffix not in LAUNCH_FILE_EXTENSIONS and (
        not suffix or suffix in (".sh", ".bin", ".bash", ".appimage") or os.access(path, os.X_OK)
    )


def quote_native_arguments(arguments: list[str]) -> str:
    """Quote arguments using desktop entry escaping, without a shell."""
    escaped = []
    for argument in arguments:
        value = argument.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        escaped.append('"' + value.replace("\\", "\\\\").replace("%", "%%") + '"')
    return " ".join(escaped)


def build_native_shortcut_command(command: str, mode: str = "--silent") -> str:
    """Use the installed application launcher for native desktop shortcuts."""
    flatpak_id = os.getenv("FLATPAK_ID")
    appimage = os.getenv("APPIMAGE", "").strip()
    launcher = ["portprotonqt"]
    if flatpak_id:
        launcher = ["flatpak", "run", flatpak_id]
    elif appimage and os.path.isfile(appimage):
        launcher = [appimage]
    if mode:
        launcher.append(mode)
    return quote_native_arguments(launcher) + " " + command


def get_native_source_command(command: str) -> str:
    """Unwrap a PortProtonQt desktop command before applying native settings."""
    parts = shlex.split(command.replace("\\\\", "\\"))
    if "--silent" in parts and (parts[0] in {"portprotonqt", "flatpak", os.getenv("APPIMAGE", "").strip()} or parts[0].lower().endswith(".appimage")):
        target = extract_exec_target_path(parts)
        if target:
            target = target.replace("\\$", "$").replace("\\`", "`").replace("%%", "%")
            return quote_native_arguments([target])
    return command


def get_native_tool_paths() -> dict[str, str]:
    """Locate the existing PortProton runtime and shader bundle without loading Wine."""
    scripts = get_portproton_scripts_path()
    location = get_portproton_location()
    if not scripts or not location:
        return {}
    values = {}
    try:
        for line in (Path(scripts) / "var").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.removeprefix("export ").partition("=")
            if separator and key in {"PW_LIBS_VER", "PW_PLUGINS_VER"}:
                values[key] = value.strip().strip('"\'')
    except OSError as error:
        logger.warning("Cannot read native runtime versions: %s", error)
        return {}
    root = Path(location) / "data/tmp"
    return {"runtime": str(root / ("libs" + values.get("PW_LIBS_VER", ""))),
            "plugins": str(root / ("plugins" + values.get("PW_PLUGINS_VER", ""))),
            "PW_PLUGINS_VER": values.get("PW_PLUGINS_VER", "")}


def read_native_variables(path: Path) -> dict[str, str]:
    """Read literal var/PPDB assignments without executing shell commands."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith(("export ", "check_variables ")):
            continue
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        if parts[0] == "check_variables" and len(parts) == 3:
            values[parts[1]] = parts[2]
        elif parts[0] == "export" and len(parts) == 2 and "=" in parts[1]:
            key, value = parts[1].split("=", 1)
            values[key] = value.replace("\\$", "$").replace("\\`", "`")
    return values


def get_native_ppdb_path(desktop_path: str, settings: dict[str, str]) -> Path:
    """Resolve the game's PPDB beside its executable, including wrapped commands."""
    command = settings["Exec"].replace("\\\\", "\\")
    parts = shlex.split(command)
    executable = next((part.replace("%%", "%") for part in reversed(parts)
                       if os.path.isabs(part.replace("%%", "%")) and Path(part.replace("%%", "%")).is_file()), None)
    if executable is None:
        executable = next((part.replace("%%", "%") for part in parts if os.path.isabs(part)), None)
    if executable is None and parts:
        executable = shutil.which(parts[0])
    if not executable:
        return Path(desktop_path + ".ppdb")
    return Path(executable + ".ppdb")


def get_native_defaults() -> dict[str, str]:
    """Read supported Linux defaults from the existing PortProton var file."""
    values = dict.fromkeys(NATIVE_TOGGLE_KEYS | NATIVE_ADVANCED_KEYS, "0")
    values.update(dict.fromkeys(NATIVE_ADVANCED_KEYS, "disabled"))
    values.update({"LAUNCH_PARAMETERS": "", "PW_MANGOHUD": "0", "PW_MANGOHUD_USER_CONF": "0",
                   "PW_VKBASALT": "0", "PW_VKBASALT_USER_CONF": "0", "PW_GAMESCOPE": "0",
                   "MANGOHUD_CONFIG": "", "FPS_LIMIT": ""})
    scripts = get_portproton_scripts_path()
    if scripts and (Path(scripts) / "var").is_file():
        defaults = read_native_variables(Path(scripts) / "var")
        values.update({key: value for key, value in defaults.items()
                       if (key in values and key != "PW_USE_RUNTIME") or key.startswith(("PW_VKBASALT_", "PW_GAMESCOPE_"))})
        values["MANGOHUD_CONFIG"] = ",".join(item for item in defaults.get("DEFAULT_MANGOHUD_CONFIG", "").split(",")
                                              if item not in {"wine", "winesync"})
    return values


def load_native_settings(desktop_path: str) -> dict[str, str]:
    """Load var defaults, existing desktop settings, and the game PPDB."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = lambda optionstr: optionstr
    parser.read_string(Path(desktop_path).read_text(encoding="utf-8"))
    settings = get_native_defaults()
    if parser.has_section(NATIVE_SETTINGS_SECTION):
        settings.update(parser[NATIVE_SETTINGS_SECTION])
    settings["Path"] = parser["Desktop Entry"].get("Path", "").replace("\\\\", "\\")
    database = Path(desktop_path + ".ppdb")
    if database.is_file():
        content = database.read_text(encoding="utf-8")
        if content.lstrip().startswith("["):
            parser.read_string(content)
            settings.update(parser[NATIVE_SETTINGS_SECTION])
        else:
            settings.update(read_native_variables(database))
    settings.setdefault("Exec", parser["Desktop Entry"]["Exec"])
    settings["Exec"] = get_native_source_command(settings["Exec"])
    database = get_native_ppdb_path(desktop_path, settings)
    if database.is_file():
        settings.update(read_native_variables(database))
    settings.setdefault("PW_PLUGINS_VER", get_native_tool_paths().get("PW_PLUGINS_VER", ""))
    return settings


def build_native_runtime(settings: dict[str, str]) -> tuple[list[str], list[str]]:
    """Use PortProton's runtime and portable Linux tools without loading Wine."""
    paths = get_native_tool_paths()
    runtime = Path(paths.get("runtime", ""))
    wrapper = runtime / "pressure-vessel/bin/pressure-vessel-unruntime"
    if not wrapper.is_file() or not (runtime / "runtime/files").is_dir():
        raise ValueError("PortProton container runtime is not installed")
    environment = [f"PRESSURE_VESSEL_RUNTIME_BASE={runtime}", "PRESSURE_VESSEL_RUNTIME=runtime",
                   f"PRESSURE_VESSEL_VARIABLE_DIR={runtime / 'var'}", "PRESSURE_VESSEL_COPY_RUNTIME=1",
                   "PRESSURE_VESSEL_IMPORT_VULKAN_LAYERS=1"]
    if platform.freedesktop_os_release().get("ID") == "altlinux":
        drivers = [str(path.resolve()) for path in (Path("/etc/libnvidiacurrent"), Path("/etc/libnvidia32current"))
                   if path.is_dir()]
        if drivers:
            environment.append("PRESSURE_VESSEL_APP_LD_LIBRARY_PATH=" + ":".join(filter(None, [os.getenv("LD_LIBRARY_PATH", ""), *drivers])))
            environment.append("LIBGL_DRIVERS_PATH=/usr/lib/X11/modules/dri:/usr/lib64/X11/modules/dri")
    command = [str(wrapper), "--share-home", "--remove-game-overlay", "--share-pid", "--", "env"]
    portable = Path(paths.get("plugins", "")) / "portable"
    command += [f"PATH={portable / 'bin'}:{os.environ.get('PATH', '')}"]
    if settings.get("PW_MANGOHUD") == "1" or settings.get("PW_VKBASALT") == "1":
        layers = portable / "share/vulkan/implicit_layer.d"
        libraries = ":".join(str(portable / "lib" / arch) for arch in ("lib64", "lib32"))
        command += [f"LD_LIBRARY_PATH={libraries}:/overrides/lib/x86_64-linux-gnu:/overrides/lib/i386-linux-gnu",
                    f"VK_ADD_LAYER_PATH={layers}", f"VK_ADD_IMPLICIT_LAYER_PATH={layers}"]
        environment.remove("PRESSURE_VESSEL_IMPORT_VULKAN_LAYERS=1")
        environment.append("PRESSURE_VESSEL_IMPORT_VULKAN_LAYERS=0")
        if settings.get("PW_MANGOHUD") == "1":
            if not (portable / "lib/lib64/libMangoHud_shim.so").is_file():
                raise ValueError("PortProton portable MangoHud is not installed")
            preload = ":".join(filter(None, [os.getenv("LD_PRELOAD", ""), "libMangoHud_shim.so"]))
            command += ["MANGOHUD=1", f"LD_PRELOAD={preload}"]
    return command, environment


def build_native_launch_command(command: str, settings: dict[str, str]) -> str:
    """Compose Linux launch wrappers and environment for a desktop entry."""
    prefix = []
    environment = []
    for key, variable in (("PW_REDUCE_PULSE_LATENCY", "PULSE_LATENCY_MSEC=60"),
                          ("PW_USE_GALLIUM_ZINK", "MESA_LOADER_DRIVER_OVERRIDE=zink"),
                          ("PW_USE_OBS_VKCAPTURE", "OBS_VKCAPTURE=1")):
        if settings.get(key) == "1":
            environment.append(variable)
    for key, variable in (("PW_LOCALE_SELECT", "LC_ALL"), ("PW_MESA_GL_VERSION_OVERRIDE", "MESA_GL_VERSION_OVERRIDE"),
                          ("PW_MESA_VK_WSI_PRESENT_MODE", "MESA_VK_WSI_PRESENT_MODE")):
        if settings.get(key) not in (None, "", "disabled"):
            environment.append(f"{variable}={settings[key]}")
    if settings.get("PW_USE_INHIBIT_SLEEP") == "1":
        prefix += ["systemd-inhibit", "--what=idle:sleep", "--why=Native game", "--"]
    if settings.get("PW_GAMESCOPE") == "1":
        prefix += ["gamescope", *shlex.split(settings.get("PW_GAMESCOPE_ARGS_NEW", "")), "--"]
    if settings.get("PW_USE_RUNTIME") == "1":
        runtime_command, runtime_env = build_native_runtime(settings)
        prefix += runtime_command
        environment += runtime_env
    cores = settings.get("PW_WINE_CPU_TOPOLOGY", "disabled")
    if cores not in ("", "disabled"):
        available = sorted(os.sched_getaffinity(0))
        count = int(cores)
        if not 1 <= count <= len(available):
            raise ValueError("Invalid CPU cores limit")
        prefix += ["taskset", "-c", ",".join(str(cpu) for cpu in available[:count])]
    if settings.get("PW_USE_GAMEMODE") == "1":
        prefix.append("gamemoderun")
    if settings.get("PW_MANGOHUD") == "1":
        if settings.get("PW_USE_RUNTIME") != "1":
            prefix += ["mangohud", "--dlsym"]
        if settings.get("PW_MANGOHUD_USER_CONF") != "1":
            config = settings.get("MANGOHUD_CONFIG", "")
            if settings.get("FPS_LIMIT"):
                config += f",fps_limit={settings['FPS_LIMIT']}"
            environment.append(f"MANGOHUD_CONFIG={config.strip(',')}")
    if settings.get("PW_VKBASALT") == "1":
        environment.append("ENABLE_VKBASALT=1")
        if settings.get("VKBASALT_CONFIG_FILE"):
            environment.append(f"VKBASALT_CONFIG_FILE={settings['VKBASALT_CONFIG_FILE']}")
    if environment:
        prefix = ["env", *environment, *prefix]
    suffix = quote_native_arguments(shlex.split(settings.get("LAUNCH_PARAMETERS", "")))
    return " ".join(part for part in (quote_native_arguments(prefix), command, suffix) if part)


def write_native_vkbasalt_config(desktop_path: str, settings: dict[str, str]) -> None:
    """Keep native vkBasalt configuration isolated from global settings."""
    if settings.get("PW_VKBASALT") != "1" or settings.get("PW_VKBASALT_USER_CONF") == "1":
        settings.pop("VKBASALT_CONFIG_FILE", None)
        return
    config = Path(desktop_path).with_suffix(".vkbasalt.conf")
    plugins = Path(get_native_tool_paths().get("plugins", "")) / "reshade"
    lines = [f"effects = {settings.get('PW_VKBASALT_EFFECTS', 'cas')}",
             f"casSharpness = {settings.get('PW_VKBASALT_FFX_CAS', '0.50')}",
             f"toggleKey = {settings.get('PW_VKBASALT_TOOGLE_KEY', 'Home')}",
             f"reshadeTexturePath = {plugins / 'textures'}", f"reshadeIncludePath = {plugins}"]
    for shader in settings.get("PW_VKBASALT_EFFECTS", "").split(":"):
        if shader and shader != "cas":
            if Path(shader).name != shader:
                raise ValueError("Invalid vkBasalt shader name")
            shader_path = plugins / "shaders" / (shader + ".fx")
            if not shader_path.is_file():
                raise ValueError(f"vkBasalt shader is not installed: {shader}")
            lines.append(f"{shader} = {shader_path}")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings["VKBASALT_CONFIG_FILE"] = str(config)


def save_native_settings(desktop_path: str, changes: dict[str, str]) -> None:
    """Save native PPDB settings and update the desktop launch command."""
    settings = load_native_settings(desktop_path)
    settings.update(changes)
    settings["Exec"] = get_native_source_command(settings["Exec"])
    command, directory = settings["Exec"], settings.get("Path", "")
    if not shlex.split(command.replace("\\\\", "\\")) or any(char in "".join(settings.values()) for char in "\n\r\x00"):
        raise ValueError("Invalid native launch command or directory")
    if directory and (not os.path.isabs(directory) or not os.path.isdir(directory)):
        raise ValueError("Working directory must be an existing absolute path")
    path = Path(desktop_path)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = lambda optionstr: optionstr
    parser.read_string(path.read_text(encoding="utf-8"))
    for key in ("Name", "Icon"):
        if key in changes:
            parser["Desktop Entry"][key] = settings.pop(key)
    write_native_vkbasalt_config(desktop_path, settings)
    parser["Desktop Entry"]["Exec"] = build_native_shortcut_command(command)
    parser["Desktop Entry"]["Comment"] = _('Launch "{name}" with PortProton').format(name=parser["Desktop Entry"].get("Name", ""))
    for action, mode in (("RunSilent", "--silent"), ("RunLog", "--log")):
        section = f"Desktop Action {action}"
        if parser.has_section(section):
            parser[section]["Exec"] = build_native_shortcut_command(command, mode)
            parser[section]["Icon"] = parser["Desktop Entry"].get("Icon", "")
    parser["Desktop Entry"]["Path"] = directory.replace("\\", "\\\\")
    parser.remove_section(NATIVE_SETTINGS_SECTION)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            parser.write(output, space_around_delimiters=False)
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
        database = get_native_ppdb_path(desktop_path, settings)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=database.parent, delete=False) as output:
            temporary = Path(output.name)
            for key, value in sorted(settings.items()):
                if key in {"Exec", "Path"}:
                    continue
                escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
                output.write(f'export {key}="{escaped}"\n')
        os.replace(temporary, database)
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        for directory in (data_home / "applications", Path(desktop) if desktop else None):
            if directory is not None:
                copy = directory / path.name
                if copy != path and copy.is_file():
                    shutil.copyfile(path, copy)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_native_desktop_file(executable: str, name: str, icon: str = "") -> tuple[str, str] | None:
    """Build a native launcher through PortProtonQt with the game's directory."""
    path = Path(executable).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK) or path.suffix.lower() in WINDOWS_LAUNCH_EXTENSIONS:
        logger.warning("Not an executable native game: %s", path)
        return None
    if not name.strip() or any(char in str(path) + icon for char in "\n\r\x00"):
        logger.warning("Invalid native game name or path")
        return None
    name = " ".join(name.splitlines()).strip()
    # Desktop Exec uses double quoting and doubles literal percent signs.
    command = build_native_shortcut_command(quote_native_arguments([str(path)]))
    directory = str(path.parent).replace("\\", "\\\\")
    icon = get_custom_icon_path(str(path)) or icon
    icon = icon.replace("\\", "\\\\") if os.path.isfile(icon) else "applications-games"
    comment = _('Launch "{name}" with PortProton').format(name=name)
    content = (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\nExec={command}\n"
               f"Path={directory}\nIcon={icon}\nTerminal=false\nCategories=Game;\nStartupNotify=true\nActions=RunSilent;RunLog;\n")
    for action, label, mode in (("RunSilent", _("Run in silent mode"), "--silent"),
                                ("RunLog", _("Run in logging mode"), "--log")):
        action_command = build_native_shortcut_command(quote_native_arguments([str(path)]), mode)
        content += f"\n[Desktop Action {action}]\nName={label}\nExec={action_command}\nIcon={icon}\n"
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    filename = "portprotonqt-native-" + hashlib.sha256(os.fsencode(path)).hexdigest() + ".desktop"
    destination = data_home / "PortProtonQt/native_games" / filename
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.warning("Cannot create native library directory: %s", error)
        return None
    return content, str(destination)


def read_native_game(path: Path) -> tuple | None:
    """Read a game entry without modifying the installed desktop file."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
        if not parser.has_section("Desktop Entry"):
            return None
        entry = parser["Desktop Entry"]
        if entry.get("Type") != "Application" or "Game" not in entry.get("Categories", "").split(";"):
            return None
        if any(entry.get(key, "false").lower() == "true" for key in ("Hidden", "NoDisplay")):
            return None
        if any(mime.startswith("x-scheme-handler/") for mime in entry.get("MimeType", "").split(";")):
            return None
        name, command = entry.get("Name", ""), entry.get("Exec", "")
        parts = shlex.split(command.replace("\\\\", "\\"))
        if not name or not parts:
            return None
        if any(part.lower().endswith(WINDOWS_LAUNCH_EXTENSIONS)
               or part.lower().startswith(("steam://", "gog://", "egs://")) for part in parts):
            return None
        if entry.get("TryExec") and not shutil.which(entry["TryExec"]):
            return None
        original = parser[NATIVE_SETTINGS_SECTION].get("Exec", command) if parser.has_section(NATIVE_SETTINGS_SECTION) else command
        executable = extract_exec_target_path(shlex.split(original.replace("\\\\", "\\"))) or ""
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        custom = data_home / "PortProtonQt/custom_data" / get_custom_data_dir_name(executable)
        cover = next((str(path) for path in custom.glob("cover.*") if path.is_file()), "")
        return (name, entry.get("Comment", ""), cover,
                "", "", NATIVE_URI_PREFIX + str(path), _("Never"), "", "", "", 0, 0,
                "native", "", "", "")
    except configparser.Error as error:
        logger.warning("Invalid native desktop entry %s: %s", path, error)
    except OSError as error:
        logger.warning("Cannot read native desktop entry %s: %s", path, error)
    except UnicodeError as error:
        logger.warning("Invalid native desktop encoding %s: %s", path, error)
    except ValueError as error:
        logger.warning("Invalid native desktop command %s: %s", path, error)
    return None


def get_native_launch(desktop_path: str) -> tuple[list[str], str]:
    """Resolve desktop field codes into a direct Linux process command."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(Path(desktop_path).read_text(encoding="utf-8"))
    entry = parser["Desktop Entry"]
    settings = load_native_settings(desktop_path)
    entry["Exec"] = settings["Exec"]
    if get_native_ppdb_path(desktop_path, settings).is_file():
        entry["Exec"] = build_native_launch_command(settings["Exec"], settings)
        entry["Path"] = settings.get("Path", "").replace("\\", "\\\\")
    escapes = {"\\": "\\", "s": " ", "n": "\n", "t": "\t", "r": "\r"}
    command = re.sub(r"\\([\\sntr])", lambda match: escapes[match[1]], entry.get("Exec", ""))
    arguments = []
    for part in shlex.split(command):
        part = part.replace("\\$", "$").replace("\\`", "`")
        if part == "%i":
            if entry.get("Icon"):
                arguments.extend(["--icon", entry["Icon"]])
            continue
        value = re.sub(r"%%|%[fFuUdDnNvmick]", lambda match:
                       {"%%": "%", "%c": entry.get("Name", ""), "%k": desktop_path}.get(match[0], ""), part)
        if value:
            arguments.append(value)
    if not arguments:
        raise ValueError("Empty native launch command")
    directory = re.sub(r"\\([\\sntr])", lambda match: escapes[match[1]], entry.get("Path", ""))
    if directory and not os.path.isdir(directory):
        raise ValueError(f"Working directory does not exist: {directory}")
    executable = next((part for part in reversed(arguments)
                       if os.path.isabs(part) and os.path.isfile(part) and os.access(part, os.X_OK)), arguments[0])
    fallback = Path(executable).parent if os.path.isabs(executable) else Path.home()
    return arguments, directory or str(fallback)


def load_native_game_times(games: list[tuple]) -> list[tuple]:
    """Read shared statistics once for the native library batch."""
    statistics, launches = {}, {}
    try:
        path = get_statistics_path()
        if os.path.isfile(path):
            statistics = parse_playtime_file(path)
        path = get_last_launch_path()
        if os.path.isfile(path):
            launches = dict(parsed for line in Path(path).read_text(encoding="utf-8").splitlines()
                            if (parsed := _parse_last_launch_line(line)))
    except OSError as error:
        logger.warning("Cannot read native game statistics: %s", error)
    updated_games = []
    for game in games:
        path = Path(game[5].removeprefix(NATIVE_URI_PREFIX))
        updated = list(game)
        updated[11] = statistics.get(str(path).replace(" ", "#@_@#"), 0)
        updated[7] = format_playtime(updated[11])
        if path.stem in launches:
            try:
                launched = datetime.fromisoformat(launches[path.stem])
                updated[6], updated[10] = format_last_launch(launched), launched.timestamp()
            except ValueError as error:
                logger.warning("Invalid native last launch time for %s: %s", path, error)
        updated_games.append(tuple(updated))
    return updated_games


class NativeLibraryWorker(QThread):
    """Scan application directories outside the UI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.games: list[tuple] = []

    def run(self) -> None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
        roots = [data_home, *(Path(directory) for directory in data_dirs if directory),
                 data_home / "flatpak/exports/share", Path("/var/lib/flatpak/exports/share")]
        directories = [root / "applications" for root in roots]
        directories.insert(0, data_home / "PortProtonQt/native_games")
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if desktop:
            directories.append(Path(desktop))
        seen: set[str] = set()
        for applications in directories:
            try:
                for path in sorted(applications.rglob("*.desktop")):
                    if self.isInterruptionRequested():
                        return
                    desktop_id = str(path.relative_to(applications)).replace(os.sep, "-")
                    if desktop_id in seen:
                        continue
                    seen.add(desktop_id)
                    game = read_native_game(path)
                    if game:
                        self.games.append(game)
            except OSError as error:
                logger.warning("Cannot scan native games in %s: %s", applications, error)
        self.games = load_native_game_times(self.games)
