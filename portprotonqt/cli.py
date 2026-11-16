import argparse
import os
import re
import shutil
import shlex
import sys
from pathlib import Path

from portprotonqt.steam_api import get_steam_home

LAUNCH_FILE_EXTENSIONS = ('.exe', '.bat', '.cmd', '.msi', '.reg', '.iso', '.mdf', '.nrg')
PP_EXTENSIONS = ('.ppack', '.ppai')
PREFIX_BACKUP_EXTENSION = PP_EXTENSIONS[0]


def parse_args():
    """
    Parses command-line arguments.
    """
    parser = argparse.ArgumentParser(description="PortProtonQt CLI")
    library = parser.add_mutually_exclusive_group()
    library.add_argument(
        "--list-games", action="store_true",
        help="Print local PortProton, Steam, GOG and EGS library data as JSON and exit"
    )
    library.add_argument(
        "--game-info", metavar="ID",
        help="Print one game as JSON using its source-qualified ID from --list-games"
    )
    library.add_argument("--edit-game", metavar="ID", help="Edit a game's PortProton settings and print its updated data")
    parser.add_argument("--set", dest="settings", action="append", default=[], metavar="KEY=VALUE",
                        help="Set a game setting; repeat to change multiple values with --edit-game")
    parser.add_argument("--all", dest="all_games", action="store_true",
                        help="Include uninstalled games from cached libraries in --list-games")
    parser.add_argument("--fields", metavar="FIELD,...",
                        help="Select JSON fields for --list-games or --game-info (e.g. executable,icon,name)")
    formatting = parser.add_mutually_exclusive_group()
    formatting.add_argument("--pretty", dest="pretty", action="store_true", default=True,
                            help="Format JSON with indentation (default)")
    formatting.add_argument("--raw", dest="pretty", action="store_false",
                            help="Print compact JSON without indentation")
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Launch the application in fullscreen mode and save this setting"
    )
    parser.add_argument(
        "--resolution",
        type=str,
        metavar="WIDTHxHEIGHT",
        help="Launch the application with a specific resolution (e.g., 1920x1080)"
    )
    parser.add_argument(
        "--debug-level",
        choices=['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='NOTSET',
        help="Set logging level (ALL for all messages, default: NOTSET)"
    )
    parser.add_argument(
        "--add-steam-compat-tool",
        action="store_true",
        help="Add PortProtonQt as a Steam compatibility tool if not already installed"
    )
    parser.add_argument(
        "--reinstall-steam-compat-tool",
        action="store_true",
        help="Reinstall PortProtonQt Steam compatibility tool in user Steam directory"
    )
    parser.add_argument(
        "--remove-steam-compat-tool",
        action="store_true",
        help="Remove PortProtonQt Steam compatibility tool from user Steam directory"
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear PortProtonQt cache and exit"
    )
    parser.add_argument(
        "--reset-settings",
        action="store_true",
        help="Reset PortProtonQt settings and exit"
    )
    parser.add_argument(
        "--ppqtos",
        action="store_true",
        help="Show the system tab in the application"
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Launch supported Windows file or native game in tray without showing the main window"
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable logging for the launched Windows file or native game"
    )
    parser.add_argument(
        "--restore-prefix",
        action="store_true",
        help="Restore prefix from .ppack backup"
    )
    parser.add_argument(
        "--create-backup",
        nargs=2,
        metavar=("PREFIX", "BACKUP_DIR"),
        help="Create prefix backup"
    )
    # Add positional argument to accept launch files or portproton:// URLs
    parser.add_argument(
        'file_or_url',
        nargs='?',
        help="Launch file path (.exe/.bat/.cmd/.msi/.reg/.iso/.mdf/.nrg), native executable, or portproton:// URL"
    )
    if os.environ.get("STEAM_COMPAT") == "1" and "--" in sys.argv[1:]:
        separator_index = sys.argv.index("--")
        args = parser.parse_args(sys.argv[1:separator_index])
        steam_args = sys.argv[separator_index + 1:]
        if steam_args:
            args.file_or_url = steam_args[0]
            launch_args = steam_args[1:]
        else:
            launch_args = []
    elif os.environ.get("STEAM_COMPAT") == "1":
        args, launch_args = parser.parse_known_args()
    else:
        args = parser.parse_args()
        launch_args = []

    if args.settings and not args.edit_game:
        parser.error("--set requires --edit-game")
    if args.edit_game and not args.settings:
        parser.error("--edit-game requires at least one --set KEY=VALUE")
    if args.all_games and not args.list_games:
        parser.error("--all requires --list-games")
    if args.fields is not None:
        if not (args.list_games or args.game_info):
            parser.error("--fields requires --list-games or --game-info")
        args.fields = [field.strip() for field in args.fields.split(",")]
        if any(not re.fullmatch(r"[a-z][a-z_0-9]*", field) for field in args.fields):
            parser.error("--fields requires comma-separated field names without empty entries")
    args.launch_args = launch_args
    return args


def _read_game_settings(path: Path) -> dict[str, str]:
    """Read literal shell assignments without executing configuration code."""
    from portprotonqt.logger import get_logger

    settings: dict[str, str] = {}
    if not path.is_file():
        return settings
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        get_logger(__name__).warning("Failed to read %s: %s", path, error)
        return settings
    for line in content.splitlines():
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)=(.*)", line)
        if not match:
            match = re.fullmatch(r"check_variables ([A-Za-z_][A-Za-z_0-9]*) (.*)", line)
        if not match:
            continue
        value = match[2]
        if any(token in value for token in ("$", "`")):
            continue
        try:
            lexer = shlex.shlex(value, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            parts = list(lexer)
        except ValueError:
            continue
        if len(parts) <= 1:
            settings[match[1]] = parts[0] if parts else ""
    return settings


def _get_game_metadata(name: str, exec_line: str, executable: str | None) -> dict:
    """Read custom artwork and cached metadata without fetching remote resources."""
    from portprotonqt.config.portproton import get_custom_icon_path, resolve_custom_data_dir
    from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS
    from portprotonqt.localization import get_metadata_language, read_metadata_translations
    from portprotonqt.steam_api.api import get_cached_steam_game_info
    from portprotonqt.time_utils import (
        get_last_launch_timestamp, get_playtime_for_exe, get_statistics_path,
    )

    metadata = get_cached_steam_game_info(name, exec_line)
    metadata.setdefault("name", name)
    metadata.setdefault("description", "")
    metadata.setdefault("cover", "")
    if not executable:
        return metadata
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    folder = Path(resolve_custom_data_dir(str(data_home / "PortProtonQt/custom_data"), executable))
    metadata["custom_data_directory"] = str(folder)
    metadata_file = folder / "metadata.txt"
    if metadata_file.is_file():
        translations = read_metadata_translations(str(metadata_file), get_metadata_language())
        metadata.update({key: value for key, value in translations.items() if value})
    for extension in COVER_IMAGE_EXTENSIONS:
        cover = folder / f"cover{extension}"
        if cover.is_file():
            metadata["cover"] = str(cover)
            break
    metadata["custom_icon"] = get_custom_icon_path(executable)
    metadata["playtime_seconds"] = get_playtime_for_exe(get_statistics_path(), executable)
    metadata["last_launch_timestamp"] = get_last_launch_timestamp(Path(executable).stem)
    return metadata


def _get_game_runtime(
    location: Path, executable: str | None, variables: dict[str, str], overrides: dict[str, str]
) -> dict:
    """Export configured runtime values; never source PPDB files or launch Wine."""
    user_conf = location / "data/user.conf"
    ppdb = Path(f"{executable}.ppdb") if executable else None
    settings = _read_game_settings(ppdb) if ppdb else {}
    runner = settings.get("PW_WINE_USE", overrides.get("PW_DEFAULT_WINE_USE", variables.get("PW_WINE_USE")))
    prefix = settings.get("PW_PREFIX_NAME", overrides.get("PW_DEFAULT_PREFIX_NAME", variables.get("PW_PREFIX_NAME")))
    settings.update(overrides)
    runner = overrides.get("PW_WINE_VER") or overrides.get("PW_WINE_USE", runner)
    prefix = overrides.get("PW_PREFIX_NAME", prefix)
    resolved_runner = runner
    if runner == "PROTON_LG":
        resolved_runner = variables.get("PW_PROTON_LG_VER")
    elif runner and (runner == "WINE_LG" or runner.startswith("WINE_") and runner.endswith("_LG")):
        resolved_runner = variables.get("PW_WINE_LG_VER")
    runner_path = None
    if resolved_runner and resolved_runner != "USE_SYSTEM_WINE":
        runner_path = Path(resolved_runner) if Path(resolved_runner).is_absolute() else (
            location / "data/dist" / resolved_runner.upper()
        )
    elif resolved_runner == "USE_SYSTEM_WINE":
        wine = shutil.which("wine")
        runner_path = Path(wine).parent.parent if wine else None
    wine_directory = runner_path
    if wine_directory and (wine_directory / "files").is_dir() and not (wine_directory / "dist").is_dir():
        wine_directory /= "files"
    wine_bin = "bin-wow64" if settings.get("PW_USE_WOW64") == "1" and wine_directory and (
        wine_directory / "bin-wow64"
    ).is_dir() else "bin"
    prefix_path = location / "data/prefixes" / prefix if prefix else None
    return {
        "wine_path": str(wine_directory / wine_bin / "wine") if wine_directory else None,
        "wineserver_path": str(wine_directory / wine_bin / "wineserver") if wine_directory else None,
        "runner": resolved_runner,
        "runner_path": str(runner_path) if runner_path else None,
        "runner_installed": runner_path.is_dir() if runner_path else False,
        "prefix": prefix, "prefix_path": str(prefix_path) if prefix_path else None,
        "settings": settings, "user_config": str(user_conf),
        "ppdb_exists": ppdb.is_file() if ppdb else False,
    }


def _list_store_games(source: str, location: str | None, variables: dict, overrides: dict) -> list[dict]:
    """Export a cached GOG or Epic library using the existing store backends."""
    from portprotonqt.egs_api import EGSAPI
    from portprotonqt.gog_api import GOGAPI
    from portprotonqt.main_window import MainWindow

    api = GOGAPI() if source == "gog" else EGSAPI()
    installed = api.load_installed()
    games = []
    for record in api.load_library():
        app_id = str(record.get("app_id", ""))
        if not app_id:
            continue
        is_installed = api.is_game_installed(app_id, installed)
        target = api.get_launch_target(app_id) if is_installed else None
        name, cover = MainWindow._get_custom_store_data(source, app_id, str(record.get("title", app_id)))
        metadata = _get_game_metadata(name, target, target) if target else {}
        metadata.pop("name", None)
        icon = metadata.pop("custom_icon", "") or record.get("icon", "")
        games.append({
            **{key: value for key, value in record.items() if key not in {"app_id", "title"}},
            **metadata,
            "id": f"{source}:{app_id}", "source": source, "name": name,
            "description": record.get("description") or metadata.get("description", ""),
            "cover": cover or record.get("cover") or metadata.get("cover", ""),
            "icon": icon, "installed": is_installed,
            "exec": f"{source}://{'launch' if is_installed else 'install'}/{app_id}",
            "executable": target, "directory": str(Path(target).parent) if target else None,
            "runtime": _get_game_runtime(Path(location), target, variables, overrides) if location and target else None,
        })
    return games


def _list_steam_games() -> list[dict]:
    """Export installed Steam games and their locally cached metadata."""
    from portprotonqt.main_window import MainWindow
    from portprotonqt.steam_api import get_steam_installed_games
    from portprotonqt.steam_api.api import get_cached_full_steam_game_info

    games = []
    for name, appid, last_played, playtime in get_steam_installed_games():
        metadata = get_cached_full_steam_game_info(appid, name)
        name, cover = MainWindow._get_custom_store_data("steam", appid, name)
        games.append({
            **metadata,
            "id": f"steam:{appid}", "source": "steam", "name": name,
            "cover": cover or metadata.get("cover", ""),
            "installed": True, "exec": f"steam://rungameid/{appid}",
            "last_launch_timestamp": last_played, "playtime_seconds": playtime,
        })
    return games


def _list_portproton_games(location: str | None, variables: dict, overrides: dict) -> list[dict]:
    """Return local PortProton shortcuts without launching games or downloading metadata."""
    from portprotonqt.config.portproton import extract_exec_target_path, parse_desktop_entry

    if not location:
        return []
    games = []
    for desktop_path in sorted(Path(location).glob("*.desktop")):
        entry = parse_desktop_entry(str(desktop_path))
        if entry is None:
            continue
        exec_line = entry.get("Exec", "")
        executable = extract_exec_target_path(exec_line)
        metadata = _get_game_metadata(entry.get("Name", desktop_path.stem), exec_line, executable)
        icon = metadata.pop("custom_icon", "") or entry.get("Icon", "")
        games.append({
            **metadata,
            "id": f"portproton:{desktop_path.name}", "source": "portproton",
            "installed": bool(executable and Path(executable).is_file()),
            "name": metadata.get("name") or entry.get("Name", desktop_path.stem),
            "runtime": _get_game_runtime(Path(location), executable, variables, overrides),
            "desktop_file": str(desktop_path),
            "exec": exec_line,
            "executable": executable,
            "directory": str(Path(executable).parent) if executable else None,
            "icon": icon,
            "ppdb": f"{executable}.ppdb" if executable else None,
        })
    return games


def list_games() -> list[dict]:
    """Return locally available library data from all supported game sources."""
    from portprotonqt.config.portproton import get_portproton_location, get_portproton_scripts_path

    location = get_portproton_location()
    scripts = get_portproton_scripts_path()
    variables = _read_game_settings(Path(scripts) / "var") if scripts else {}
    overrides = _read_game_settings(Path(location) / "data/user.conf") if location else {}
    games = _list_portproton_games(location, variables, overrides)
    games.extend(_list_steam_games())
    for source in ("gog", "egs"):
        games.extend(_list_store_games(source, location, variables, overrides))
    return games


def edit_game(game_id: str, changes: list[str]) -> dict:
    """Update a game's PPDB through PortProton and verify the saved settings."""
    import subprocess

    from portprotonqt.config.portproton import WINDOWS_LAUNCH_EXTENSIONS, get_portproton_start_command
    from portprotonqt.settings_manager import ADVANCED_SETTING_KEYS, get_toggle_settings

    game = next((game for game in list_games() if game["id"] == game_id), None)
    if game is None:
        raise ValueError(f"Game not found: {game_id}")
    executable = game.get("executable")
    if (game.get("source") not in {"portproton", "gog", "egs"} or not executable
            or not Path(executable).is_file() or Path(executable).suffix.lower() not in WINDOWS_LAUNCH_EXTENSIONS):
        raise ValueError("Editing requires an installed Windows game managed by PortProton, GOG or EGS")
    toggles = set(get_toggle_settings()) | {"PW_MANGOHUD", "PW_VKBASALT", "PW_GAMESCOPE"}
    allowed = set(ADVANCED_SETTING_KEYS) | toggles | set((game.get("runtime") or {}).get("settings", {}))
    values: dict[str, str] = {}
    for change in changes:
        key, separator, value = change.partition("=")
        if not separator or key not in allowed or not re.fullmatch(r"[A-Z_][A-Z_0-9]*", key):
            raise ValueError(f"Unknown or invalid game setting: {key}")
        if any(character in value for character in ("$", "`", "|", "\n", "\r", "\0")):
            raise ValueError(f"Unsupported shell syntax in setting: {key}")
        if key in toggles and value not in {"0", "1"}:
            raise ValueError(f"{key} must be 0 or 1")
        if key == "PW_PREFIX_NAME" and (not value or value in {".", ".."} or "/" in value or "\\" in value):
            raise ValueError("PW_PREFIX_NAME must be a prefix name, not a path")
        values[key] = value
    if not values:
        raise ValueError("At least one setting is required")
    command = get_portproton_start_command()
    if not command:
        raise ValueError("PortProton start.sh was not found")
    result = subprocess.run(
        [*command, "cli", "--edit-db", executable, *[f"{key}={value}" for key, value in values.items()]],
        capture_output=True, text=True, errors="replace", check=False,
    )
    if result.returncode:
        raise RuntimeError(f"PortProton failed to edit game settings: {result.stderr.strip()}")
    saved = _read_game_settings(Path(f"{executable}.ppdb"))
    if any(saved.get(key) != value for key, value in values.items()):
        raise RuntimeError("PortProton did not save the requested settings; check PPDB permissions")
    return next(game for game in list_games() if game["id"] == game_id)


def add_steam_compat_tool(force_install: bool = False) -> bool:
    """
    Add PortProtonQt as a Steam compatibility tool.

    Creates the following files in Steam's compatibilitytools.d directory:
    - compatibilitytool.vdf
    - toolmanifest.vdf
    - portproton (launch script)

    Returns:
        True if successful, False otherwise
    """
    if sys.platform == "darwin":
        return False
    steam_home = get_steam_home()
    if not steam_home:
        print("Steam directory not found")
        return False

    compat_tools_dir = steam_home / "compatibilitytools.d" / "PortProtonQt"
    system_compat_dir = Path("/usr/share/steam/compatibilitytools.d/PortProtonQt")

    # Check if already installed in user or system directory
    if compat_tools_dir.exists():
        if not force_install:
            print("PortProtonQt is already installed as a Steam compatibility tool")
            return True
        shutil.rmtree(compat_tools_dir)

    if system_compat_dir.exists() and not force_install:
        print("PortProtonQt is already installed as a Steam compatibility tool (system-wide)")
        return True

    # Create directory structure
    compat_tools_dir.mkdir(parents=True, exist_ok=True)

    # Create compatibilitytool.vdf
    compatibilitytool_vdf = compat_tools_dir / "compatibilitytool.vdf"
    compatibilitytool_vdf.write_text('''"compatibilitytools"
{
	"compat_tools"
	{
		"PortProtonQt"
		{
			"install_path" "."
			"display_name" "PortProtonQt"
			"from_oslist" "windows"
			"to_oslist" "linux"
			"Priority" "75"
		}
	}
}
''')

    # Create toolmanifest.vdf
    toolmanifest_vdf = compat_tools_dir / "toolmanifest.vdf"
    toolmanifest_vdf.write_text('''"manifest"
{
	"commandline" "/portproton"
}
''')

    # Create portproton launch script
    portproton_script = compat_tools_dir / "portproton"
    portproton_script.write_text('''#!/usr/bin/env bash

# Remove Steam Runtime libraries
unset LD_LIBRARY_PATH

export STEAM_COMPAT=1

launch_args=("$@")
case "${1:-}" in
    run|waitforexitandrun)
        launch_args=("${@:2}")
        ;;
esac

launch_target="${launch_args[0]:-}"
exe_name="$(basename "$launch_target")"
exe_dir="$(dirname "$launch_target")"

# Ignore specific executables
if [[ "$exe_name" == "iscriptevaluator.exe" ]] \\
|| [[ "$exe_name" == "d3ddriverquery64.exe" ]]
then
    exit 0
fi

# Activate virtual environment if available
if [[ -n "$PPQT_VENV_PATH" ]]; then
    cd "$PPQT_VENV_PATH" || exit 1
    source .venv/bin/activate || exit 1
fi

if [[ "$UPDATE_CT_PPQT" != "1" ]]; then
    export UPDATE_CT_PPQT="1"
    full_command_line=("$(realpath "$0")" "$@")
    if [[ -n "$PPQT_BIN_PATH" ]]; then
        "$PPQT_BIN_PATH" --reinstall-steam-compat-tool
    elif command -v flatpak >/dev/null 2>&1 && flatpak info ru.linux_gaming.PortProtonQt >/dev/null 2>&1; then
        flatpak run ru.linux_gaming.PortProtonQt --reinstall-steam-compat-tool
    else
        portprotonqt --reinstall-steam-compat-tool
    fi
    exec "${full_command_line[@]}"
    exit 0
fi

# Copy PPDB file from steam_scripts to exe directory if it exists
# Steam passes the appid via SteamAppId environment variable
if [[ -n "$SteamAppId" ]]; then
    # Get PortProton directory from config file or Flatpak defaults
    portproton_dir=""
    new_config_file="$HOME/.config/PortProtonQt.conf"
    legacy_config_file="$HOME/.config/PortProton.conf"
    new_flatpak_id="ru.linux_gaming.PortProtonQt"
    legacy_flatpak_id="ru.linux_gaming.PortProton"
    new_flatpak_config_file="$HOME/.var/app/$new_flatpak_id/config/PortProtonQt.conf"
    new_flatpak_dir="$HOME/.var/app/$new_flatpak_id/data"
    legacy_flatpak_dir="$HOME/.var/app/$legacy_flatpak_id/data"

    if [[ -f "$new_config_file" ]]; then
        portproton_dir="$(awk -F'= ' '/^portdata_path/ {print $2; exit}' "$new_config_file" | tr -d '\\n')"
    fi

    if [[ -z "$portproton_dir" ]] || [[ ! -d "$portproton_dir" ]]; then
        if [[ -f "$legacy_config_file" ]]; then
            portproton_dir="$(cat "$legacy_config_file" | tr -d '\\n')"
        fi
    fi

    if [[ -z "$portproton_dir" ]] || [[ ! -d "$portproton_dir" ]]; then
        if [[ -f "$new_flatpak_config_file" ]]; then
            portproton_dir="$(awk -F'= ' '/^portdata_path/ {print $2; exit}' "$new_flatpak_config_file" | tr -d '\\n')"
        fi
    fi

    if [[ -z "$portproton_dir" ]] || [[ ! -d "$portproton_dir" ]]; then
        if [[ -d "$new_flatpak_dir" ]]; then
            portproton_dir="$new_flatpak_dir"
        elif [[ -d "$legacy_flatpak_dir" ]]; then
            portproton_dir="$legacy_flatpak_dir"
        fi
    fi

    ppdb_source="$portproton_dir/steam_scripts/${SteamAppId}.exe.ppdb"
    ppdb_dest="$exe_dir/${exe_name}.ppdb"

    if [[ -f "$ppdb_source" ]]; then
        cp "$ppdb_source" "$ppdb_dest"
        echo "Copied PPDB from $ppdb_source to $ppdb_dest"
    fi
fi

# Use AppImage if specified, then Flatpak if installed, otherwise use portprotonqt from PATH
if [[ -n "$PPQT_BIN_PATH" ]]; then
    "$PPQT_BIN_PATH" --debug-level INFO -- "${launch_args[@]}"
elif command -v flatpak >/dev/null 2>&1 && flatpak info ru.linux_gaming.PortProtonQt >/dev/null 2>&1; then
    flatpak run ru.linux_gaming.PortProtonQt --debug-level INFO -- "${launch_args[@]}"
else
    portprotonqt --debug-level INFO -- "${launch_args[@]}"
fi
''')

    # Make script executable
    os.chmod(portproton_script, 0o755)

    print("PortProtonQt has been added as a Steam compatibility tool")
    print(f"Installed to: {compat_tools_dir}")
    print("Restart Steam to use the new compatibility tool")

    return True


def reinstall_steam_compat_tool() -> bool:
    """Reinstall PortProtonQt as a Steam compatibility tool."""
    steam_home = get_steam_home()
    if not steam_home:
        print("Steam directory not found")
        return False

    compat_tools_dir = steam_home / "compatibilitytools.d" / "PortProtonQt"
    if compat_tools_dir.exists():
        try:
            shutil.rmtree(compat_tools_dir)
        except OSError as e:
            print(f"Failed to remove existing compatibility tool: {e}")
            return False

    return add_steam_compat_tool(force_install=True)


def remove_steam_compat_tool() -> bool:
    """Remove PortProtonQt Steam compatibility tool from user Steam directory."""
    if sys.platform == "darwin":
        return False
    steam_home = get_steam_home()
    if not steam_home:
        print("Steam directory not found")
        return False

    compat_tools_dir = steam_home / "compatibilitytools.d" / "PortProtonQt"
    if not compat_tools_dir.exists():
        print("PortProtonQt Steam compatibility tool is not installed in user directory")
        return True

    try:
        shutil.rmtree(compat_tools_dir)
    except OSError as e:
        print(f"Failed to remove compatibility tool: {e}")
        return False

    print("PortProtonQt Steam compatibility tool removed")
    print("Restart Steam to apply changes")
    return True


def clear_cache() -> bool:
    """Clear PortProtonQt cache."""
    from portprotonqt.config import cache_config
    from portprotonqt.gog_api import GOGAPI

    cache_config.clear_cache()
    GOGAPI().clear_library_cache()
    print("PortProtonQt cache cleared")
    return True


def reset_settings() -> bool:
    """Reset PortProtonQt settings."""
    from portprotonqt.config import (
        get_portproton_location,
        reset_main_config,
    )

    portproton_location = get_portproton_location()
    reset_main_config()
    if portproton_location:
        user_conf_path = Path(portproton_location) / "data" / "user.conf"
        try:
            if user_conf_path.is_file():
                user_conf_path.unlink()
        except OSError as e:
            print(f"Failed to delete user.conf: {e}")
            return False

    print("PortProtonQt settings reset")
    return True


def is_steam_compat_tool_installed() -> bool:
    """Check if PortProtonQt is installed as Steam compatibility tool."""
    if sys.platform == "darwin":
        return False
    steam_home = get_steam_home()
    if not steam_home:
        return False

    compat_tools_dir = steam_home / "compatibilitytools.d" / "PortProtonQt"
    system_compat_dir = Path("/usr/share/steam/compatibilitytools.d/PortProtonQt")

    return compat_tools_dir.exists() or system_compat_dir.exists()


def is_portproton_url(url: str) -> bool:
    """Check if the given URL is a portproton:// URL.

    Args:
        url: The URL to check

    Returns:
        True if it's a portproton:// URL, False otherwise
    """
    return url.lower().startswith('portproton://')


def parse_portprotonqt_theme_url(url: str) -> int | None:
    """Parse portprotonqt://theme/<id> URL and return theme id."""
    prefix = "portprotonqt://theme/"
    if not url.lower().startswith(prefix):
        return None

    theme_id = url[len(prefix):].strip("/")
    if not theme_id.isdecimal():
        return None
    return int(theme_id)


def is_exe_file(path: str) -> bool:
    """Check if the given path is an exe file.

    Args:
        path: The path to check

    Returns:
        True if it's an exe file, False otherwise
    """
    normalized_path = normalize_launch_path(path)
    return normalized_path.lower().endswith('.exe') and os.path.isfile(normalized_path)


def normalize_launch_path(path: str) -> str:
    """Normalize path and convert file:// URI to local filesystem path."""
    if path.lower().startswith("file://"):
        path = path[7:]
        path = path.replace("%20", " ")
    return os.path.abspath(os.path.expanduser(path))


def is_launch_file(path: str) -> bool:
    """Check if the given path is a supported launch file."""
    normalized_path = normalize_launch_path(path)
    return normalized_path.lower().endswith(LAUNCH_FILE_EXTENSIONS) and os.path.isfile(normalized_path)


def is_prefix_backup_file(path: str) -> bool:
    """Check if the given path is a PortProton prefix backup."""
    normalized_path = normalize_launch_path(path)
    return normalized_path.lower().endswith(PREFIX_BACKUP_EXTENSION) and os.path.isfile(normalized_path)


def is_autoinstall_file(path: str) -> bool:
    """Check if the given path is a PortProton Auto Install file."""
    normalized_path = normalize_launch_path(path)
    return normalized_path.lower().endswith(PP_EXTENSIONS[1]) and os.path.isfile(normalized_path)


def parse_portproton_url(url: str) -> str | None:
    """Parse a portproton:// URL to extract the full download URL.

    Expected format: portproton://https//linux-gaming.ru/api/games/130127/ppdb/download

    Args:
        url: The portproton:// URL to parse

    Returns:
        The full download URL if parsing is successful, None otherwise
    """
    # Remove the portproton:// prefix
    if not url.lower().startswith('portproton://'):
        return None

    # Extract the actual URL part after portproton://
    actual_url = url[13:]  # Length of 'portproton://'

    # Check if the URL starts with 'https//' (without colon) and fix it
    if actual_url.startswith('https//'):
        # Replace 'https//' with 'https://'
        corrected_url = 'https://' + actual_url[7:]  # Remove 'https//' (7 chars) and add '://'
    elif actual_url.startswith('http//'):
        # Replace 'http//' with 'http://'
        corrected_url = 'http://' + actual_url[6:]  # Remove 'http//' (6 chars) and add '://'
    elif not actual_url.startswith(('http://', 'https://')):
        # Add the protocol if it's missing
        corrected_url = 'https://' + actual_url
    else:
        corrected_url = actual_url

    return corrected_url


def parse_resolution(resolution: str) -> tuple[int, int] | None:
    """Parse a resolution string in the format WIDTHxHEIGHT.

    Args:
        resolution: Resolution string (e.g., "1920x1080")

    Returns:
        Tuple of (width, height) if valid, None otherwise
    """
    try:
        # Match pattern like "1920x1080"
        match = re.match(r'^(\d+)x(\d+)$', resolution, re.IGNORECASE)
        if not match:
            return None

        width = int(match.group(1))
        height = int(match.group(2))

        # Validate reasonable resolution bounds
        if width < 320 or height < 200:
            return None
        if width > 7680 or height > 4320:
            return None

        return (width, height)
    except (ValueError, AttributeError):
        return None
