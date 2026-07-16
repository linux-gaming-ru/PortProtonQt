"""Utility functions for Steam API module."""

import os
import shutil
import struct
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError
import vdf

from portprotonqt.config import game_config
from portprotonqt.logger import get_logger
from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS

logger = get_logger(__name__)

STEAM_DATA_DIRS = (
    "~/.steam/steam",
    "~/snap/steam/common/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",
    "/usr/share/steam",
)
APPINFO_MAGIC_V40 = 0x07564428
APPINFO_MAGIC_V41 = 0x07564429
APPINFO_ENTRY_METADATA_SIZE = 60
STEAM_ID64_INDIVIDUAL_BASE = 76561197960265728


def safe_vdf_load(path: str | Path) -> dict:
    """Load VDF file, trying binary format first, then text."""
    path = str(path)
    # Check first byte to determine format
    try:
        with open(path, "rb") as f:
            first_byte = f.read(1)
            if not first_byte:
                return {}
    except Exception:
        return {}

    # Binary VDF starts with 0x00 or 0x01, text VDF starts with ASCII
    if first_byte in (b"\x00", b"\x01"):
        try:
            with open(path, "rb") as f:
                return vdf.binary_load(f)
        except Exception as e:
            logger.debug("Failed to load binary VDF %s: %s", path, e)
            return {}
    else:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return vdf.load(f)
        except Exception as e:
            logger.debug("Failed to load text VDF %s: %s", path, e)
            return {}


def decode_text(text: str) -> str:
    """Decode HTML entities in a string."""
    import html
    return html.unescape(text)


def _iter_existing_steam_data_dirs() -> list[Path]:
    """Return existing Steam data dirs with symlinks resolved."""
    steam_dirs = []
    seen_dirs = set()
    for dir_path in STEAM_DATA_DIRS:
        expanded_path = Path(os.path.expanduser(dir_path))
        if not expanded_path.exists():
            continue
        try:
            steam_path = expanded_path.resolve()
        except (OSError, RuntimeError) as e:
            logger.debug("Failed to resolve Steam directory %s: %s", expanded_path, e)
            steam_path = expanded_path
        if steam_path in seen_dirs:
            continue
        seen_dirs.add(steam_path)
        steam_dirs.append(steam_path)
    return steam_dirs


def get_steam_home() -> Path | None:
    """Return path to Steam directory."""
    for steam_path in _iter_existing_steam_data_dirs():
        return steam_path
    return None


def get_steam_runtime_library_paths() -> list[str]:
    """Return runtime library directories from all Steam installations."""
    runtime_paths = []
    for steam_path in _iter_existing_steam_data_dirs():
        for runtime_dir in ("ubuntu12_32", "ubuntu12_64"):
            library_path = steam_path / runtime_dir
            if library_path.is_dir():
                runtime_paths.append(str(library_path))
    return runtime_paths


def get_steam_launch_commands(appid: str) -> list[list[str]]:
    """Return Steam launch commands based on detected Steam data dir."""
    steam_home = get_steam_home()
    if steam_home is None:
        return []

    steam_home_str = str(steam_home)
    if "/.var/app/com.valvesoftware.Steam/" in steam_home_str:
        flatpak_cmd = shutil.which("flatpak")
        if flatpak_cmd:
            return [[flatpak_cmd, "run", "com.valvesoftware.Steam", "-applaunch", appid]]
        return []

    if "/snap/steam/" in steam_home_str:
        steam_cmd = shutil.which("steam")
        if steam_cmd:
            return [[steam_cmd, "-applaunch", appid]]
        snap_cmd = shutil.which("snap")
        if snap_cmd:
            return [[snap_cmd, "run", "steam", "-applaunch", appid]]
        return []

    steam_cmd = shutil.which("steam")
    if steam_cmd:
        return [[steam_cmd, "-applaunch", appid]]
    return []


def get_steam_compatibilitytools_dir() -> Path | None:
    """Return writable Steam compatibility tools directory."""
    steam_home = get_steam_home()
    if steam_home is None:
        return None

    compat_dir = steam_home / "compatibilitytools.d"
    try:
        compat_dir.mkdir(exist_ok=True)
    except OSError as e:
        logger.debug("Failed to create Steam compatibility tools dir %s: %s", compat_dir, e)
        return None

    if compat_dir.is_dir() and os.access(compat_dir, os.R_OK | os.W_OK):
        return compat_dir
    return None


def _is_portrait_image(path: Path) -> bool:
    """Return True when image is taller than wide."""
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError) as e:
        logger.debug("Failed to read Steam cover dimensions %s: %s", path, e)
        return False
    except ValueError as e:
        logger.debug("Rejected unsafe Steam cover metadata %s: %s", path, e)
        return False
    return height > width


def get_local_steam_cover(appid: int | str, prefer_exact: bool = True) -> str:
    """Return local Steam library cover path for appid."""
    steam_home = get_steam_home()
    if steam_home is None:
        return ""

    appid_str = str(appid).strip()
    if not appid_str:
        return ""

    librarycache = steam_home / "appcache" / "librarycache"
    if not librarycache.exists():
        return ""

    exact_paths = (
        librarycache / appid_str / "library_600x900.jpg",
        librarycache / appid_str / "library_600x900.png",
        librarycache / appid_str / "library_600x900_2x.jpg",
        librarycache / appid_str / "library_600x900_2x.png",
        librarycache / f"{appid_str}_library_600x900.jpg",
        librarycache / f"{appid_str}_library_600x900.png",
        librarycache / f"{appid_str}_library_600x900_2x.jpg",
        librarycache / f"{appid_str}_library_600x900_2x.png",
    )
    for cover_path in exact_paths:
        if cover_path.is_file():
            return str(cover_path)

    for suffix in (ext.removeprefix(".") for ext in COVER_IMAGE_EXTENSIONS):
        patterns = (
            f"{appid_str}/**/library_600x900*.{suffix}",
            f"{appid_str}_library_600x900*.{suffix}",
        )
        for pattern in patterns:
            for cover_path in sorted(librarycache.glob(pattern)):
                if cover_path.is_file():
                    return str(cover_path)

    for suffix in (ext.removeprefix(".") for ext in COVER_IMAGE_EXTENSIONS):
        patterns = (
            f"{appid_str}/**/*.{suffix}",
            f"{appid_str}_*.{suffix}",
        )
        for pattern in patterns:
            for cover_path in sorted(librarycache.glob(pattern)):
                if cover_path.is_file() and _is_portrait_image(cover_path):
                    return str(cover_path)

    capsule_paths = (
        librarycache / appid_str / "library_capsule.jpg",
        librarycache / appid_str / "library_capsule.png",
        librarycache / appid_str / "capsule_616x353.jpg",
        librarycache / appid_str / "capsule_616x353.png",
        librarycache / f"{appid_str}_library_capsule.jpg",
        librarycache / f"{appid_str}_library_capsule.png",
        librarycache / f"{appid_str}_capsule_616x353.jpg",
        librarycache / f"{appid_str}_capsule_616x353.png",
    )
    for cover_path in capsule_paths:
        if cover_path.is_file():
            return str(cover_path)

    if prefer_exact:
        return ""

    for suffix in (ext.removeprefix(".") for ext in COVER_IMAGE_EXTENSIONS):
        patterns = (
            f"{appid_str}/library_capsule*.{suffix}",
            f"{appid_str}/capsule_*.{suffix}",
            f"{appid_str}/**/library_capsule*.{suffix}",
            f"{appid_str}/**/capsule_*.{suffix}",
            f"{appid_str}/*.{suffix}",
            f"{appid_str}_library_capsule*.{suffix}",
            f"{appid_str}_capsule_*.{suffix}",
            f"{appid_str}_*.{suffix}",
        )
        for pattern in patterns:
            for cover_path in sorted(librarycache.glob(pattern)):
                if cover_path.is_file():
                    return str(cover_path)

    return ""


def get_steam_compat_tool(appid: int) -> str | None:
    """Return compatibility tool name for given Steam appid."""
    steam_home = get_steam_home()
    if steam_home is None or not steam_home.exists():
        return None

    config_vdf = steam_home / "config" / "config.vdf"
    if not config_vdf.exists():
        return None

    data = safe_vdf_load(config_vdf)
    compat_tools = data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {})

    appid_str = str(appid)
    if appid_str in compat_tools:
        tool_info = compat_tools[appid_str]
        if isinstance(tool_info, dict):
            return tool_info.get('name')

    return None


def get_last_steam_user(steam_home: Path) -> dict | None:
    """Return data for last Steam user from loginusers.vdf."""
    users = get_steam_users(steam_home)
    configured_user_id = game_config.get_steam_account_id()
    if configured_user_id != "auto" and configured_user_id in users:
        return {'SteamID': int(configured_user_id)}
    selected_user_id = None
    auto_login_user_id = None
    most_recent_user_id = None
    latest_timestamp = -1
    for user_id, user_info in users.items():
        try:
            timestamp = int(user_info.get('Timestamp', ''))
        except ValueError:
            timestamp = -1
        if timestamp > latest_timestamp:
            latest_timestamp = timestamp
            selected_user_id = user_id
        if auto_login_user_id is None and user_info.get('AutoLogin') == '1':
            auto_login_user_id = user_id
        if most_recent_user_id is None and user_info.get('MostRecent') == '1':
            most_recent_user_id = user_id
    if selected_user_id is None:
        selected_user_id = auto_login_user_id or most_recent_user_id
    if selected_user_id is None:
        userdata_dir = steam_home / "userdata"
        try:
            candidates = [
                entry for entry in userdata_dir.iterdir()
                if entry.name.isdigit()
                and entry.name != '0'
                and not entry.is_symlink()
                and entry.is_dir()
                and (entry / "config/localconfig.vdf").is_file()
            ]
        except OSError as e:
            logger.info("Could not inspect Steam userdata: %s", e)
            return None
        if len(candidates) != 1:
            logger.info("No unambiguous Steam userdata profile found")
            return None
        selected_user_id = str(
            STEAM_ID64_INDIVIDUAL_BASE + int(candidates[0].name)
        )
    try:
        return {'SteamID': int(selected_user_id)}
    except ValueError:
        logger.error(f"Invalid SteamID format: {selected_user_id}")
        return None


def get_steam_users(steam_home: Path) -> dict[str, dict]:
    """Return valid Steam users from loginusers.vdf."""
    data = safe_vdf_load(steam_home / "config/loginusers.vdf")
    users = data.get("users", {}) if data else {}
    return {
        str(user_id): user_info
        for user_id, user_info in users.items()
        if str(user_id).isdigit() and isinstance(user_info, dict)
    }


def convert_steam_id(steam_id: int) -> int:
    """Convert signed 32-bit integer to unsigned 32-bit integer."""
    return steam_id & 0xFFFFFFFF


def get_steam_libs(steam_dir: Path) -> set[Path]:
    """Return set of Steam library folders."""
    libs = set()
    libs_vdf = steam_dir / "steamapps/libraryfolders.vdf"
    data = safe_vdf_load(libs_vdf)
    folders = data.get('libraryfolders', {})
    for key, info in folders.items():
        if key.isdigit():
            path_str = info.get('path') if isinstance(info, dict) else None
            if path_str:
                path = Path(path_str).expanduser()
                if path.exists():
                    libs.add(path)
    libs.add(steam_dir)
    return libs


def _is_steam_proton_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.joinpath("files", "bin", "wine").is_file():
        return True
    return path.joinpath("dist", "bin", "wine").is_file()


def get_steam_proton_versions() -> list[str]:
    """Return Steam Proton install directories usable by PortProton."""
    roots = set()
    for steam_home in _iter_existing_steam_data_dirs():
        roots.add(steam_home / "compatibilitytools.d")
        for steam_lib in get_steam_libs(steam_home):
            roots.add(steam_lib / "steamapps" / "common")

    versions: dict[Path, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = root.iterdir()
        except OSError as e:
            logger.debug("Failed to read Steam Proton directory %s: %s", root, e)
            continue
        for entry in entries:
            if _is_steam_proton_dir(entry):
                versions[entry.resolve()] = entry.absolute()

    return sorted((str(path) for path in versions.values()), key=lambda path: Path(path).name.lower())


def get_playtime_data(steam_home: Path | None = None) -> dict[int, tuple[int, int]]:
    """Return playtime data for last user."""
    play_data: dict[int, tuple[int, int]] = {}
    if steam_home is None:
        steam_home = get_steam_home()
    if steam_home is None or not steam_home.exists():
        logger.error("Steam home directory not found or does not exist")
        return play_data

    userdata_dir = steam_home / "userdata"
    if not userdata_dir.exists():
        logger.info("Userdata directory not found")
        return play_data

    last_user = get_last_steam_user(steam_home)
    if not last_user:
        logger.info("Could not identify the last Steam user")
        return play_data

    user_id = last_user['SteamID']
    unsigned_id = convert_steam_id(user_id)
    user_dir = userdata_dir / str(unsigned_id)
    if not user_dir.exists():
        logger.info(f"User directory {unsigned_id} not found")
        return play_data

    localconfig = user_dir / "config/localconfig.vdf"
    data = safe_vdf_load(localconfig)
    cfg = data.get('UserLocalConfigStore', {})
    apps = cfg.get('Software', {}).get('Valve', {}).get('Steam', {}).get('apps', {})
    for appid_str, info in apps.items():
        try:
            appid = int(appid_str)
            last_played = int(info.get('LastPlayed', 0))
            playtime = int(info.get('Playtime', 0))
            play_data[appid] = (last_played, playtime)
        except ValueError:
            logger.warning(f"Invalid playtime data for app {appid_str}")
    return play_data


def _read_appinfo_string_table(appinfo: BinaryIO, table_offset: int) -> list[str]:
    appinfo.seek(table_offset)
    string_count = struct.unpack("<I", appinfo.read(4))[0]
    strings = appinfo.read().split(b"\x00", string_count)
    if len(strings) < string_count:
        raise ValueError("Incomplete Steam appinfo string table")
    return [value.decode("utf-8", "replace") for value in strings[:string_count]]


def _expand_appinfo_keys(data: bytes, strings: list[str]) -> bytes:
    """Expand appinfo v41 string indexes for python-vdf."""
    expanded = bytearray()
    position = 0
    fixed_sizes = {
        vdf.BIN_NONE[0]: 0,
        vdf.BIN_INT32[0]: 4,
        vdf.BIN_FLOAT32[0]: 4,
        vdf.BIN_POINTER[0]: 4,
        vdf.BIN_COLOR[0]: 4,
        vdf.BIN_UINT64[0]: 8,
        vdf.BIN_INT64[0]: 8,
    }
    while position < len(data):
        value_type = data[position]
        position += 1
        expanded.append(value_type)
        if value_type == vdf.BIN_END[0]:
            continue
        string_index = struct.unpack_from("<I", data, position)[0]
        position += 4
        expanded.extend(strings[string_index].encode("utf-8") + b"\x00")
        if value_type in fixed_sizes:
            value_end = position + fixed_sizes[value_type]
        elif value_type == vdf.BIN_STRING[0]:
            value_end = data.index(b"\x00", position) + 1
        elif value_type == vdf.BIN_WIDESTRING[0]:
            value_end = position
            while value_end + 1 < len(data) and data[value_end:value_end + 2] != b"\x00\x00":
                value_end += 2
            if value_end + 1 >= len(data):
                raise ValueError("Unterminated binary VDF wide string")
            value_end += 2
        else:
            raise ValueError(f"Unsupported binary VDF type: {value_type}")
        expanded.extend(data[position:value_end])
        position = value_end
    return bytes(expanded)


def _load_steam_app_metadata(
    steam_home: Path,
    appids: set[int],
) -> dict[int, dict] | None:
    """Load common metadata for installed apps from Steam appinfo.vdf."""
    metadata = {}
    appinfo_path = steam_home / "appcache" / "appinfo.vdf"
    try:
        with open(appinfo_path, "rb") as appinfo:
            magic, _ = struct.unpack("<II", appinfo.read(8))
            if magic not in (APPINFO_MAGIC_V40, APPINFO_MAGIC_V41):
                raise ValueError(f"Unsupported Steam appinfo format: {magic:#x}")
            strings = []
            if magic == APPINFO_MAGIC_V41:
                table_offset = struct.unpack("<q", appinfo.read(8))[0]
                strings = _read_appinfo_string_table(appinfo, table_offset)
                appinfo.seek(16)
            while True:
                appid = struct.unpack("<I", appinfo.read(4))[0]
                if appid == 0:
                    break
                entry_size = struct.unpack("<I", appinfo.read(4))[0]
                entry_end = appinfo.tell() + entry_size
                if entry_size < APPINFO_ENTRY_METADATA_SIZE:
                    raise ValueError(f"Invalid Steam appinfo entry size: {entry_size}")
                appinfo.seek(APPINFO_ENTRY_METADATA_SIZE, 1)
                if appid in appids:
                    blob = appinfo.read(entry_end - appinfo.tell())
                    if strings:
                        blob = _expand_appinfo_keys(blob, strings)
                    data = vdf.binary_loads(blob).get("appinfo", {})
                    metadata[appid] = data.get("common", {})
                appinfo.seek(entry_end)
    except Exception as e:
        logger.warning("Failed to load Steam app metadata from %s: %s", appinfo_path, e)
        return None
    return metadata


def _is_steam_game(common: dict) -> bool:
    """Return whether Steam metadata describes a game or related application."""
    app_type = str(common.get("type", "")).lower()
    return app_type in {"game", "demo", "mod", "application", "beta"}


def get_steam_installed_games() -> list[tuple[str, int, int, int]]:
    """Return list of installed Steam games (name, appid, last_played, playtime_sec)."""
    games: list[tuple[str, int, int, int]] = []
    steam_home = get_steam_home()
    if steam_home is None or not steam_home.exists():
        logger.error("Steam home directory not found or does not exist")
        return games

    installed_apps: list[tuple[dict, int]] = []
    for lib in get_steam_libs(steam_home):
        steamapps_dir = lib / "steamapps"
        if not steamapps_dir.exists():
            continue
        for manifest in steamapps_dir.glob("appmanifest_*.acf"):
            data = safe_vdf_load(manifest)
            app = data.get('AppState', {})
            try:
                appid = int(app.get('appid', 0))
            except ValueError:
                continue
            installed_apps.append((app, appid))

    play_data = get_playtime_data(steam_home)
    app_metadata = _load_steam_app_metadata(
        steam_home,
        {appid for _, appid in installed_apps},
    )
    for app, appid in installed_apps:
        common = app_metadata.get(appid) if app_metadata is not None else None
        if common is not None and not _is_steam_game(common):
            continue
        name = app.get('name', f"Unknown ({appid})")
        lname = name.lower()
        if any(token in lname for token in ["proton", "steamworks", "steam linux runtime"]):
            continue
        last_played, playtime_min = play_data.get(appid, (0, 0))
        games.append((name, appid, last_played, playtime_min * 60))
    return games


def normalize_name(s: str) -> str:
    """Normalize string: lowercase, remove symbols, replace separators."""
    s = s.lower()
    for ch in ["™", "®"]:
        s = s.replace(ch, "")
    for ch in ["-", ":", ","]:
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    for suffix in ["bin", "app"]:
        if s.endswith(suffix):
            s = s[:-len(suffix)].strip()
    keywords_to_remove = {"ultimate", "edition", "definitive", "complete", "remastered"}
    words = s.split()
    filtered_words = [word for word in words if word not in keywords_to_remove]
    return " ".join(filtered_words)


def is_valid_candidate(candidate: str) -> bool:
    """Check if candidate string is valid for use as game name."""
    normalized_candidate = normalize_name(candidate)
    if normalized_candidate == "game":
        return False
    normalized_no_space = normalized_candidate.replace(" ", "")
    forbidden = ["win32", "win64", "gamelauncher"]
    for token in forbidden:
        if token in normalized_no_space:
            return False
    return True


def filter_candidates(candidates: list[str]) -> list[str]:
    """Filter candidates, discarding invalid ones."""
    valid = []
    dropped = []
    for cand in candidates:
        if cand.strip() and is_valid_candidate(cand):
            valid.append(cand)
        else:
            dropped.append(cand)
    if dropped:
        logger.info("Discarding candidates: %s", dropped)
    return valid


def remove_duplicates(candidates: list[str]) -> list[str]:
    """Remove duplicates from list while preserving order."""
    return list(dict.fromkeys(candidates))
