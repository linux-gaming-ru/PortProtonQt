import argparse
import configparser
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from portprotonqt.config.portproton import (
    PortProtonConfig,
    extract_exec_target_path,
    read_portdata_path_from_config,
    resolve_custom_data_dir,
)
from portprotonqt.icon_extractor import generate_thumbnail, get_exe_icon_cache_path
from portprotonqt.steam_api import get_cached_steam_game_info, get_steam_home

LAUNCH_FILE_EXTENSIONS = ('.exe', '.bat', '.cmd', '.msi', '.reg', '.iso', '.mdf', '.nrg')
PP_EXTENSIONS = ('.ppack', '.ppai')
PREFIX_BACKUP_EXTENSION = PP_EXTENSIONS[0]


def parse_args():
    """
    Parses command-line arguments.
    """
    parser = argparse.ArgumentParser(description="PortProtonQt CLI")
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
        help="Launch supported Windows file in tray without showing the main window"
    )
    parser.add_argument(
        "--list-games",
        action="store_true",
        help="List games registered in the PortProtonQt library",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the game list as JSON (use with --list-games)",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Enable PortProton logging for the launched Windows file"
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
        help="Launch file path (.exe/.bat/.cmd/.msi/.reg/.iso/.mdf/.nrg) or portproton:// URL"
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

    args.launch_args = launch_args
    return args


def get_library_games() -> list[dict]:
    """Return PortProtonQt desktop games with their launch command and cover."""
    portproton_dir = read_portdata_path_from_config() or PortProtonConfig().get_location()
    if not portproton_dir:
        return []

    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))
    custom_data_dir = data_home / "PortProtonQt" / "custom_data"
    try:
        desktop_files = sorted(Path(portproton_dir).glob("*.desktop"))
    except OSError:
        return []
    return [
        game for desktop_file in desktop_files
        if (game := _get_desktop_game(desktop_file, custom_data_dir)) is not None
    ]


def _get_desktop_game(desktop_file: Path, custom_data_dir: Path) -> dict | None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(desktop_file, encoding="utf-8")
        entry = parser["Desktop Entry"]
        name = entry.get("Name", "").strip()
        command = shlex.split(entry.get("Exec", "").strip())
        hidden = entry.get("NoDisplay", "false").strip().lower() == "true"
    except (KeyError, configparser.Error, OSError, UnicodeError, ValueError):
        return None
    if not name or name.casefold() in {"portproton", "readme"} or not command:
        return None

    game_exe = extract_exec_target_path(command)
    cover = _get_desktop_game_cover(
        desktop_file, custom_data_dir, name, command, game_exe
    )

    launch_args = [
        part for part in command[1:]
        if part not in {"%f", "%F", "%u", "%U", "%i", "%c", "%k"}
    ]
    game_id = hashlib.sha256(desktop_file.name.encode("utf-8")).hexdigest()[:16]
    return {
        "id": game_id,
        "name": name,
        "source": "portproton",
        "installed": True,
        "hidden": hidden,
        "cover": cover,
        "command": command[0],
        "args": launch_args,
    }


def _get_desktop_game_cover(
    desktop_file: Path,
    custom_data_dir: Path,
    name: str,
    command: list[str],
    game_exe: str | None,
) -> str:
    if game_exe:
        game_data_dir = Path(resolve_custom_data_dir(str(custom_data_dir), game_exe))
        for suffix in (
            ".png", ".apng", ".jpg", ".jpeg", ".gif", ".webp", ".jxl", ".svg"
        ):
            cover = game_data_dir / f"cover{suffix}"
            if cover.is_file():
                return str(cover)

    cached_cover = get_cached_steam_game_info(name, shlex.join(command)).get("cover", "")
    if cached_cover and Path(cached_cover).is_file():
        return cached_cover

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(desktop_file, encoding="utf-8")
        icon = parser["Desktop Entry"].get("Icon", "").strip()
    except (KeyError, configparser.Error, OSError, UnicodeError):
        icon = ""
    if icon:
        icon_path = Path(icon).expanduser()
        if icon_path.is_file():
            return str(icon_path)
        image_path = desktop_file.parent / "data" / "img" / icon
        if not image_path.suffix:
            image_path = image_path.with_suffix(".png")
        if image_path.is_file():
            return str(image_path)

    if game_exe and game_exe.lower().endswith(".exe") and Path(game_exe).is_file():
        icon_cache = Path(get_exe_icon_cache_path(game_exe))
        if not icon_cache.is_file():
            icon_cache.parent.mkdir(parents=True, exist_ok=True)
            generate_thumbnail(game_exe, str(icon_cache), size=128)
        if icon_cache.is_file():
            return str(icon_cache)
    return ""


def print_library_games(as_json: bool = False) -> None:
    """Print the PortProtonQt game list for CLI consumers."""
    games = get_library_games()
    if as_json:
        print(json.dumps(games, ensure_ascii=False))
        return
    for game in games:
        print(game["name"])


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
