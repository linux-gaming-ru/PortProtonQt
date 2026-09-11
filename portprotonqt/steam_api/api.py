"""Steam API functions for PortProtonQt."""

import os
import shlex
import threading
import time
import urllib.parse
from collections.abc import Callable
from functools import lru_cache

import orjson
from PIL import Image, UnidentifiedImageError

from portprotonqt.logger import get_logger
from portprotonqt.downloader import Downloader
from portprotonqt.localization import get_steam_language
from portprotonqt.config import CACHE_DIR, THEMED_LAUNCH_ICON_NAMES, extract_exec_target_path, ui_config
from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS
from portprotonqt.steam_api.utils import decode_text, get_local_steam_cover
from portprotonqt.steam_api.cache import (
    CACHE_DURATION,
    load_app_details,
    save_app_details,
    load_steam_apps_async,
    build_index,
    search_app,
    load_weanticheatyet_data_async,
    load_ppdb_data_async,
    build_weanticheatyet_index,
    build_ppdb_index,
    search_anticheat_entry,
    search_ppdb_entry,
    load_protondb_status,
    save_protondb_status,
)
from portprotonqt.config.cache import CacheManager

logger = get_logger(__name__)
downloader = Downloader()

_STEAM_APPS_CACHE = CacheManager(name="steam_apps")
_ANTICHEAT_CACHE = CacheManager(name="anticheat")
_PPDB_CACHE = CacheManager(name="ppdb")
_CACHED_INDEX_LOCK = threading.RLock()
SGDB_CACHE_DURATION = 24 * 60 * 60
STEAM_CLIENT_ICON_SIZES = (16, 32, 64, 128, 256)


def fetch_sgdb_cover_async(game_name: str, callback: Callable[[str], None]) -> None:
    """Asynchronously fetch cover image URL from steamgrid.usebottles.com."""
    encoded = urllib.parse.quote(game_name)
    url = f"https://steamgrid.usebottles.com/api/search/{encoded}"

    def process_response(result: str | None) -> None:
        if not result or not os.path.exists(result):
            logger.warning("Failed to download SGDB data for %s", game_name)
            try:
                cache_file.write_text('""', encoding="utf-8")
            except OSError as e:
                logger.warning("Failed to save SGDB miss cache for %s: %s", game_name, e)
            callback("")
            return
        try:
            with open(result, encoding="utf-8") as f:
                text = f.read().strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            if text:
                logger.debug("Got SGDB cover URL for %s: %s", game_name, text)
            callback(text)
        except Exception as e:
            logger.warning("Failed to process SGDB data for %s: %s", game_name, e)
            callback("")

    cache_manager = CacheManager()
    safe_name = "".join(c for c in game_name if c.isalnum() or c in " -_")[:50]
    cache_file = cache_manager.cache_dir / f"sgdb_{safe_name}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < SGDB_CACHE_DURATION:
        process_response(str(cache_file))
        return
    downloader.download_async(url, str(cache_file), timeout=3, callback=process_response)


def fetch_app_info_async(app_id: int, callback: Callable[[dict | None], None]) -> None:
    """Asynchronously fetch detailed app info from Steam API."""
    cached = load_app_details(app_id)
    if cached is not None:
        callback(cached)
        return

    lang = get_steam_language()
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l={lang}"

    def process_response(result: str | None) -> None:
        if not result or not os.path.exists(result):
            logger.error("Failed to download Steam app info for appid %s", app_id)
            callback(None)
            return
        try:
            with open(result, "rb") as f:
                data = orjson.loads(f.read())
            details = data.get(str(app_id), {})
            if not details.get("success"):
                callback(None)
                return
            app_data_full = details.get("data", {})
            app_data = {
                "steam_appid": app_data_full.get("steam_appid", app_id),
                "name": app_data_full.get("name", ""),
                "short_description": app_data_full.get("short_description", ""),
                "controller_support": app_data_full.get("controller_support", "")
            }
            save_app_details(app_id, app_data)
            callback(app_data)
        except Exception as e:
            logger.error("Failed to process Steam app info for appid %s: %s", app_id, e)
            callback(None)

    cache_manager = CacheManager()
    cache_file = cache_manager.cache_dir / f"steam_app_{app_id}.json"
    downloader.download_async(url, str(cache_file), timeout=5, callback=process_response)


def _get_icon_theme_dir() -> str:
    xdg_data_home = os.getenv(
        "XDG_DATA_HOME",
        os.path.join(os.path.expanduser("~"), ".local", "share"),
    )
    return os.path.join(xdg_data_home, "icons", "hicolor")


def _install_client_icon(icon_path: str, icon_name: str) -> str:
    try:
        with Image.open(icon_path) as image:
            source_image = image.convert("RGBA")
            theme_dir = _get_icon_theme_dir()
            for size in STEAM_CLIENT_ICON_SIZES:
                icon_dir = os.path.join(theme_dir, f"{size}x{size}", "apps")
                os.makedirs(icon_dir, exist_ok=True)
                png_path = os.path.join(icon_dir, f"{icon_name}.png")
                resized = source_image.resize((size, size), Image.Resampling.LANCZOS)
                resized.save(png_path, "PNG")
        return icon_name
    except (OSError, UnidentifiedImageError) as e:
        logger.warning("Failed to convert Steam icon %s: %s", icon_path, e)
        return ""


def _download_client_icon(
    appid_str: str,
    icon_hash: str,
    icon_dir: str,
    callback: Callable[[str], None],
) -> None:
    icon_path = os.path.join(icon_dir, appid_str, f"{icon_hash}.ico")
    icon_name = f"steam_icon_{appid_str}"
    if os.path.exists(icon_path):
        callback(_install_client_icon(icon_path, icon_name))
        return

    icon_url = (
        "https://shared.fastly.steamstatic.com/community_assets/images/apps/"
        f"{appid_str}/{icon_hash}.ico"
    )
    os.makedirs(os.path.dirname(icon_path), exist_ok=True)

    def on_icon_download(path: str | None) -> None:
        callback(_install_client_icon(path, icon_name) if path else "")

    downloader.download_async(
        icon_url,
        icon_path,
        timeout=5,
        callback=on_icon_download,
    )


def fetch_client_icon_async(appid: int | str, callback: Callable[[str], None]) -> None:
    """Asynchronously fetch Steam client icon and return icon theme name."""
    appid_str = str(appid).strip()
    if not appid_str.isdigit():
        callback("")
        return

    cache_dir = CacheManager().cache_dir
    info_path = cache_dir / f"steamcmd_app_{appid_str}_{time.time_ns()}.json"
    url = f"https://api.steamcmd.net/v1/info/{appid_str}"

    def process_info(result: str | None) -> None:
        try:
            if not result or not os.path.exists(result):
                callback("")
                return
            with open(result, "rb") as f:
                data = orjson.loads(f.read())
            common = data.get("data", {}).get(appid_str, {}).get("common", {})
            icon_hash = common.get("clienticon", "")
            if not icon_hash:
                callback("")
                return
            _download_client_icon(
                appid_str,
                icon_hash,
                str(cache_dir / "steam_icons"),
                callback,
            )
        except (OSError, orjson.JSONDecodeError) as e:
            logger.warning("Failed to process Steam icon info for appid %s: %s", appid_str, e)
            callback("")
        finally:
            if result:
                try:
                    os.remove(result)
                except OSError:
                    pass

    downloader.download_async(url, str(info_path), timeout=5, callback=process_info)


def get_protondb_tier_async(appid: int, callback: Callable[[str], None]) -> None:
    """Asynchronously fetch ProtonDB tier for an app."""
    cached = load_protondb_status(appid)
    if cached is not None:
        callback(cached.get("tier", ""))
        return

    url = f"https://www.protondb.com/api/v1/reports/summaries/{appid}.json"

    def process_response(result: str | None) -> None:
        if not result or not os.path.exists(result):
            logger.info("Failed to download ProtonDB data for appid %s", appid)
            callback("")
            return
        try:
            with open(result, "rb") as f:
                data = orjson.loads(f.read())
            filtered_data = {"tier": data.get("tier", "")}
            save_protondb_status(appid, filtered_data)
            callback(filtered_data["tier"])
        except Exception as e:
            logger.info("Failed to process ProtonDB data for appid %s: %s", appid, e)
            callback("")

    cache_manager = CacheManager()
    cache_file = cache_manager.cache_dir / f"protondb_{appid}.json"
    downloader.download_async(url, str(cache_file), timeout=5, callback=process_response)


def get_steam_apps_and_index_async(
    callback: Callable[[tuple[list | None, dict | None]], None]
) -> None:
    """Asynchronously load and cache Steam apps and their index."""
    _STEAM_APPS_CACHE.get_data_and_index_async(
        load_steam_apps_async,
        build_index,
        callback,
        CACHE_DURATION
    )


def get_anticheat_data_and_index_async(
    callback: Callable[[tuple[list | None, dict | None]], None]
) -> None:
    """Asynchronously load and cache anti-cheat data and their index."""
    _ANTICHEAT_CACHE.get_data_and_index_async(
        load_weanticheatyet_data_async,
        build_weanticheatyet_index,
        callback,
        CACHE_DURATION
    )


def get_ppdb_data_and_index_async(
    callback: Callable[[tuple[list | None, dict | None]], None]
) -> None:
    """Asynchronously load and cache PPDB data and their index."""
    _PPDB_CACHE.get_data_and_index_async(
        load_ppdb_data_async,
        build_ppdb_index,
        callback,
        CACHE_DURATION
    )


def get_weanticheatyet_status_async(game_name: str, callback: Callable[[str], None]) -> None:
    """Asynchronously retrieve WeAntiCheatYet status for a game by name."""
    def on_anticheat_info(anticheat_info: dict) -> None:
        callback(anticheat_info.get("status", ""))

    get_weanticheatyet_info_async(game_name, on_anticheat_info)


def get_weanticheatyet_info_async(game_name: str, callback: Callable[[dict], None]) -> None:
    """Asynchronously retrieve WeAntiCheatYet status and slug for a game by name."""
    def on_anticheat_data_and_index(
        data_and_index: tuple[list | None, dict | None]
    ) -> None:
        anti_cheat_data, anti_cheat_index = data_and_index
        if anti_cheat_data and anti_cheat_index:
            entry = search_anticheat_entry(game_name, anti_cheat_index) or {}
        else:
            entry = {}
        callback(
            {
                "status": entry.get("status", ""),
                "slug": entry.get("slug", ""),
            }
        )

    get_anticheat_data_and_index_async(on_anticheat_data_and_index)


def get_ppdb_info_async(game_name: str, callback: Callable[[dict], None]) -> None:
    """Asynchronously retrieve PPDB info for a game by name."""
    def on_ppdb_data_and_index(
        data_and_index: tuple[list | None, dict | None]
    ) -> None:
        ppdb_data, ppdb_index = data_and_index
        if ppdb_data and ppdb_index:
            entry = search_ppdb_entry(game_name, ppdb_index) or {}
        else:
            entry = {}
        callback(
            {
                "id": entry.get("id", ""),
                "overall_rating": entry.get("overall_rating", ""),
            }
        )

    get_ppdb_data_and_index_async(on_ppdb_data_and_index)


def _add_ppdb_info(result: dict, game_name: str, callback: Callable[[dict], None]) -> None:
    def on_ppdb_info(ppdb_info: dict) -> None:
        result["ppdb_id"] = ppdb_info.get("id", "")
        result["ppdb_rating"] = ppdb_info.get("overall_rating", "")
        callback(result)

    get_ppdb_info_async(game_name, on_ppdb_info)


def clear_steam_api_caches() -> None:
    """Clear all cached data to force reload from files."""
    _STEAM_APPS_CACHE.clear_memory_cache()
    _ANTICHEAT_CACHE.clear_memory_cache()
    _PPDB_CACHE.clear_memory_cache()
    with _CACHED_INDEX_LOCK:
        _load_cached_data_and_index.cache_clear()
    logger.info("Cleared Steam API in-memory caches")


def _build_game_info_result(
    appid: str | int,
    name: str,
    description: str,
    cover: str,
    controller_support: str,
    protondb_tier: str,
    steam_game: str,
    anticheat_status: str,
    anticheat_slug: str = "",
    ppdb_id: str | int = "",
    ppdb_rating: str = "",
) -> dict:
    """Build game info result dictionary."""
    return {
        "appid": appid,
        "name": name,
        "description": description,
        "cover": cover,
        "controller_support": controller_support,
        "protondb_tier": protondb_tier,
        "steam_game": steam_game,
        "anticheat_status": anticheat_status,
        "anticheat_slug": anticheat_slug,
        "ppdb_id": ppdb_id,
        "ppdb_rating": ppdb_rating,
    }


def _has_custom_data_for_exe(exe_name: str) -> bool:
    """Return True when custom_data contains metadata or cover for executable name."""
    if not exe_name:
        return False

    clean_exe_name = exe_name.removeprefix("autoinstall:")
    xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    custom_data_root = os.path.join(xdg_data_home, "PortProtonQt", "custom_data")
    candidate_dirs = [
        os.path.join(custom_data_root, clean_exe_name),
        os.path.join(custom_data_root, "autoinstall", clean_exe_name),
    ]
    cover_names = {f"cover{ext}" for ext in COVER_IMAGE_EXTENSIONS}
    metadata_name = "metadata.txt"

    for game_dir in candidate_dirs:
        if not os.path.isdir(game_dir):
            continue
        try:
            files = set(os.listdir(game_dir))
        except OSError:
            continue
        if metadata_name in files:
            return True
        if files & cover_names:
            return True
    return False


def get_full_steam_game_info_async(
    appid: int,
    callback: Callable[[dict], None],
    fallback_name: str = "",
) -> None:
    """Asynchronously retrieve full Steam game info, including WeAntiCheatYet status."""
    if ui_config.get_economy_mode():
        callback(get_cached_full_steam_game_info(appid, fallback_name))
        return

    def on_app_info(app_info: dict | None) -> None:
        if not app_info:
            callback({})
            return
        title = decode_text(app_info.get("name", "") or fallback_name)
        description = decode_text(app_info.get("short_description", ""))
        cover = get_local_steam_cover(appid, prefer_exact=False)
        if not cover:
            cover = f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900_2x.jpg"

        def on_protondb_tier(tier: str) -> None:
            def on_anticheat_info(anticheat_info: dict) -> None:
                result = _build_game_info_result(
                    appid=appid,
                    name=title,
                    description=description,
                    cover=cover,
                    controller_support=app_info.get('controller_support', ''),
                    protondb_tier=tier,
                    steam_game="true",
                    anticheat_status=anticheat_info.get("status", ""),
                    anticheat_slug=anticheat_info.get("slug", ""),
                )
                _add_ppdb_info(result, title, callback)

            get_weanticheatyet_info_async(title, on_anticheat_info)

        get_protondb_tier_async(appid, on_protondb_tier)

    fetch_app_info_async(appid, on_app_info)


def _load_cached_json_file(path: str) -> dict | list | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return orjson.loads(f.read())
    except OSError as e:
        logger.warning("Failed to read cached Steam data %s: %s", path, e)
    except orjson.JSONDecodeError as e:
        logger.warning("Failed to parse cached Steam data %s: %s", path, e)
    return None


def _read_cached_app_data(appid: int) -> dict:
    cache_file = CacheManager().cache_dir / f"steam_app_{appid}.json"
    cached = _load_cached_json_file(str(cache_file))
    if not isinstance(cached, dict):
        return {}
    details = cached.get(str(appid), {})
    if isinstance(details, dict) and details.get("success"):
        data = details.get("data", {})
        return data if isinstance(data, dict) else {}
    return cached


@lru_cache(maxsize=4)
def _load_cached_data_and_index(
    cache_path: str,
    cache_mtime_ns: int,
    build_index_func: Callable[[list], dict],
) -> tuple[list, dict]:
    cached = _load_cached_json_file(cache_path)
    if not isinstance(cached, list):
        return [], {}
    return cached, build_index_func(cached)


def _get_cached_data_and_index(
    cache_file: os.PathLike,
    build_index_func: Callable[[list], dict],
) -> tuple[list, dict]:
    try:
        cache_mtime_ns = os.stat(cache_file).st_mtime_ns
    except OSError:
        return [], {}
    with _CACHED_INDEX_LOCK:
        return _load_cached_data_and_index(
            os.fspath(cache_file), cache_mtime_ns, build_index_func
        )


def _get_cached_steam_cover_path(appid: int) -> str:
    image_folder = str(CACHE_DIR / "images")
    for ext in COVER_IMAGE_EXTENSIONS:
        cover_path = os.path.join(image_folder, f"{appid}{ext}")
        if os.path.exists(cover_path):
            return cover_path
    return ""


def _read_cached_protondb_tier(appid: int) -> str:
    cache_file = CacheManager().cache_dir / f"protondb_{appid}.json"
    cached = _load_cached_json_file(str(cache_file))
    if isinstance(cached, dict):
        tier = cached.get("tier", "")
        return tier if isinstance(tier, str) else ""
    return ""


def _read_cached_ppdb_id(game_name: str) -> str:
    cache_file = CacheManager().cache_dir / "ppdb_games.json"
    _, ppdb_index = _get_cached_data_and_index(cache_file, build_ppdb_index)
    entry = search_ppdb_entry(game_name, ppdb_index) or {}
    return str(entry.get("id", ""))


def _read_cached_ppdb_rating(game_name: str) -> str:
    cache_file = CacheManager().cache_dir / "ppdb_games.json"
    _, ppdb_index = _get_cached_data_and_index(cache_file, build_ppdb_index)
    entry = search_ppdb_entry(game_name, ppdb_index) or {}
    return str(entry.get("overall_rating", ""))


def get_cached_full_steam_game_info(appid: int, fallback_name: str = "") -> dict:
    """Return installed Steam game metadata from local cache only."""
    app_data = _read_cached_app_data(appid)
    name = decode_text(app_data.get("name", "") or fallback_name)
    description = decode_text(app_data.get("short_description", ""))
    cover = get_local_steam_cover(appid, prefer_exact=False) or _get_cached_steam_cover_path(appid)
    return _build_game_info_result(
        appid=appid,
        name=name,
        description=description,
        cover=cover,
        controller_support=app_data.get("controller_support", ""),
        protondb_tier=_read_cached_protondb_tier(appid),
        steam_game="true",
        anticheat_status="",
        anticheat_slug="",
        ppdb_id=_read_cached_ppdb_id(name),
        ppdb_rating=_read_cached_ppdb_rating(name),
    )


def get_cached_steam_game_info(desktop_name: str, exec_line: str) -> dict:
    """Return Steam metadata from local cache only."""
    from portprotonqt.steam_api.utils import filter_candidates, remove_duplicates

    game_exe = extract_exec_target_path(exec_line) or exec_line
    exe_name = os.path.splitext(os.path.basename(game_exe))[0]
    folder_name = os.path.basename(os.path.dirname(game_exe)) if game_exe else ""
    candidates = remove_duplicates(filter_candidates([desktop_name, exe_name, folder_name]))
    apps_path = CacheManager().cache_dir / "steam_apps.json"
    steam_apps, steam_apps_index = _get_cached_data_and_index(apps_path, build_index)
    if not steam_apps:
        return {}

    matching_app = None
    for candidate in sorted(candidates, key=lambda s: len(s.split()), reverse=True):
        matching_app = search_app(candidate, steam_apps_index)
        if matching_app:
            break
    if not matching_app:
        return {}

    appid = int(matching_app["appid"])
    return get_cached_full_steam_game_info(appid, matching_app.get("name", ""))


def get_steam_game_info_async(
    desktop_name: str,
    exec_line: str,
    callback: Callable[[dict], None]
) -> None:
    """Asynchronously retrieve game info based on desktop name and exec line."""
    game_exe = extract_exec_target_path(exec_line) or exec_line
    if os.path.splitext(game_exe)[1].lower() in THEMED_LAUNCH_ICON_NAMES:
        game_name = desktop_name or os.path.splitext(os.path.basename(game_exe))[0]
        callback(_build_game_info_result(
            appid="",
            name=decode_text(game_name),
            description="",
            cover="",
            controller_support="",
            protondb_tier="",
            steam_game="false",
            anticheat_status="",
            anticheat_slug="",
        ))
        return

    if ui_config.get_economy_mode():
        cached_info = get_cached_steam_game_info(desktop_name, exec_line)
        if cached_info:
            callback(cached_info)
            return
        exe_name = os.path.splitext(os.path.basename(game_exe))[0]
        game_name = desktop_name or exe_name
        callback(_build_game_info_result(
            appid="",
            name=decode_text(game_name),
            description="",
            cover="",
            controller_support="",
            protondb_tier="",
            steam_game="false",
            anticheat_status="",
            anticheat_slug="",
        ))
        return

    from portprotonqt.steam_api.cache import get_exiftool_data
    from portprotonqt.steam_api.utils import filter_candidates, remove_duplicates

    is_autoinstall = exec_line.startswith("autoinstall:")
    is_store_uri = exec_line.startswith(("gog://", "egs://"))

    if game_exe.lower().endswith(('.bat', '.cmd')):
        if os.path.exists(game_exe):
            try:
                with open(game_exe, encoding='utf-8') as f:
                    cmd_lines = f.readlines()
                for line in cmd_lines:
                    line = line.strip()
                    if '.exe' in line.lower():
                        tokens = shlex.split(line)
                        for token in tokens:
                            if token.lower().endswith('.exe'):
                                game_exe = token
                                break
                        if game_exe.lower().endswith('.exe'):
                            break
            except Exception as e:
                logger.error("Failed to process command file %s: %s", game_exe, e)
        else:
            logger.error("Command file not found: %s", game_exe)

    if is_store_uri:
        meta_data = {}
    elif not game_exe.lower().endswith('.exe'):
        logger.error("Invalid executable path: %s. Expected .exe", game_exe)
        meta_data = {}
    else:
        meta_data = get_exiftool_data(game_exe)

    exe_name = os.path.splitext(os.path.basename(game_exe))[0]
    folder_path = os.path.dirname(game_exe)
    folder_name = os.path.basename(folder_path)
    if folder_name.lower() in ['bin', 'binaries']:
        folder_path = os.path.dirname(folder_path)
        folder_name = os.path.basename(folder_path)

    candidates = []
    product_name = meta_data.get("ProductName", "")
    file_description = meta_data.get("FileDescription", "")
    if product_name and product_name not in ['BootstrapPackagedGame']:
        candidates.append(product_name)
    if file_description and file_description not in ['BootstrapPackagedGame']:
        candidates.append(file_description)
    if desktop_name:
        candidates.append(desktop_name)
    if exe_name and not is_store_uri:
        candidates.append(exe_name)
    if folder_name and not is_store_uri:
        candidates.append(folder_name)
    candidates = filter_candidates(candidates)
    candidates = remove_duplicates(candidates)
    candidates_ordered = sorted(candidates, key=lambda s: len(s.split()), reverse=True)
    has_custom_data = (
        is_autoinstall or is_store_uri or _has_custom_data_for_exe(exe_name)
    )

    def on_steam_apps_and_index(
        data_and_index: tuple[list | None, dict | None]
    ) -> None:
        steam_apps, steam_apps_index = data_and_index
        matching_app = None

        if not steam_apps or not steam_apps_index:
            game_name = desktop_name or exe_name

            def on_sgdb_cover_failure(cover: str) -> None:
                result = _build_game_info_result(
                    appid="",
                    name=decode_text(game_name),
                    description="",
                    cover=cover,
                    controller_support="",
                    protondb_tier="",
                    steam_game="false",
                    anticheat_status="",
                )

                def on_anticheat_info_failure(anticheat_info: dict) -> None:
                    result["anticheat_status"] = anticheat_info.get("status", "")
                    result["anticheat_slug"] = anticheat_info.get("slug", "")
                    _add_ppdb_info(result, game_name, callback)

                get_weanticheatyet_info_async(game_name, on_anticheat_info_failure)

            if has_custom_data:
                on_sgdb_cover_failure("")
            else:
                fetch_sgdb_cover_async(game_name, on_sgdb_cover_failure)
            return

        for candidate in candidates_ordered:
            if not candidate:
                continue
            matching_app = search_app(candidate, steam_apps_index)
            if matching_app:
                break

        game_name = desktop_name or exe_name.capitalize()

        if not matching_app:
            def on_sgdb_cover_non_steam(cover: str) -> None:
                def on_anticheat_info_non_steam(anticheat_info: dict) -> None:
                    result = _build_game_info_result(
                        appid="",
                        name=decode_text(game_name),
                        description="",
                        cover=cover,
                        controller_support="",
                        protondb_tier="",
                        steam_game="false",
                        anticheat_status=anticheat_info.get("status", ""),
                        anticheat_slug=anticheat_info.get("slug", ""),
                    )
                    _add_ppdb_info(result, game_name, callback)

                get_weanticheatyet_info_async(game_name, on_anticheat_info_non_steam)

            if has_custom_data:
                on_sgdb_cover_non_steam("")
            else:
                fetch_sgdb_cover_async(game_name, on_sgdb_cover_non_steam)
            return

        appid = matching_app["appid"]

        def on_app_info(app_info: dict | None) -> None:
            if not app_info:
                def on_anticheat_info_no_info(anticheat_info: dict) -> None:
                    result = _build_game_info_result(
                        appid="",
                        name=decode_text(game_name),
                        description="",
                        cover="",
                        controller_support="",
                        protondb_tier="",
                        steam_game="false",
                        anticheat_status=anticheat_info.get("status", ""),
                        anticheat_slug=anticheat_info.get("slug", ""),
                    )
                    _add_ppdb_info(result, game_name, callback)

                get_weanticheatyet_info_async(game_name, on_anticheat_info_no_info)
                return

            title = decode_text(app_info.get("name", game_name))
            description = decode_text(app_info.get("short_description", ""))
            cover = get_local_steam_cover(appid, prefer_exact=False)
            if not cover and not has_custom_data:
                cover = f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900_2x.jpg"
            controller_support = app_info.get("controller_support", "")

            def on_protondb_tier(tier: str) -> None:
                def on_anticheat_info_final(anticheat_info: dict) -> None:
                    result = _build_game_info_result(
                        appid=appid,
                        name=title,
                        description=description,
                        cover=cover,
                        controller_support=controller_support,
                        protondb_tier=tier,
                        steam_game="true",
                        anticheat_status=anticheat_info.get("status", ""),
                        anticheat_slug=anticheat_info.get("slug", ""),
                    )
                    _add_ppdb_info(result, title, callback)

                get_weanticheatyet_info_async(title, on_anticheat_info_final)

            get_protondb_tier_async(appid, on_protondb_tier)

        fetch_app_info_async(appid, on_app_info)

    get_steam_apps_and_index_async(on_steam_apps_and_index)
