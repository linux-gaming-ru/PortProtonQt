"""Cache management for Steam API module."""

import glob
import os
import shutil
import subprocess
import tarfile
import time
from collections.abc import Callable

import orjson

from portprotonqt.logger import get_logger
from portprotonqt.downloader import Downloader
from portprotonqt.config.cache import CacheManager
from portprotonqt.steam_api.utils import normalize_name

logger = get_logger(__name__)
downloader = Downloader()

CACHE_DURATION = 30 * 24 * 60 * 60
PPDB_DATA_URL = "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/data/ppdb_games.tar.xz"

_EXIFTOOL_CACHE: dict[str, tuple[dict, float]] = {}
_CACHE_MAX_ENTRIES = 64
_CACHE_TTL = 300


def get_exiftool_data(game_exe: str) -> dict:
    """Retrieve metadata using exiftool with TTL-based caching."""
    current_time = time.time()

    if not os.path.isfile(game_exe):
        logger.debug("Skipping exiftool for missing executable: %s", game_exe)
        return {}
    if shutil.which("exiftool") is None:
        logger.debug("Skipping exiftool for %s: executable not found", game_exe)
        return {}

    if len(_EXIFTOOL_CACHE) > _CACHE_MAX_ENTRIES // 2:
        expired_keys = [
            key for key, (data, timestamp) in _EXIFTOOL_CACHE.items()
            if current_time - timestamp > _CACHE_TTL
        ]
        for key in expired_keys:
            del _EXIFTOOL_CACHE[key]

    if game_exe in _EXIFTOOL_CACHE:
        data, timestamp = _EXIFTOOL_CACHE[game_exe]
        if current_time - timestamp <= _CACHE_TTL:
            return data
        else:
            del _EXIFTOOL_CACHE[game_exe]

    try:
        proc = subprocess.run(
            ["exiftool", "-j", game_exe],
            capture_output=True,
            text=True,
            check=False,
            timeout=10
        )
        if proc.returncode != 0:
            logger.error(f"exiftool failed for {game_exe}: {proc.stderr.strip()}")
            return {}
        meta_data_list = orjson.loads(proc.stdout.encode("utf-8"))
        result = meta_data_list[0] if meta_data_list else {}

        if result and len(_EXIFTOOL_CACHE) < _CACHE_MAX_ENTRIES:
            _EXIFTOOL_CACHE[game_exe] = (result, current_time)

        return result
    except subprocess.TimeoutExpired:
        logger.error(f"exiftool timed out for {game_exe}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error in get_exiftool_data for {game_exe}: {e}")
        return {}


def delete_cached_app_files(cache_dir: str, pattern: str) -> None:
    """Delete cached files matching the given pattern."""
    try:
        for file_path in glob.glob(os.path.join(cache_dir, pattern)):
            os.remove(file_path)
            logger.info(f"Deleted cached file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to delete cached files matching {pattern}: {e}")


def load_app_details(app_id: int) -> dict | None:
    """Load cached game data by appid if not outdated."""
    cache_manager = CacheManager()
    cache_key = f"steam_app_{app_id}"
    if cache_manager.is_fresh(cache_key, CACHE_DURATION):
        return cache_manager.load_json(cache_key)
    return None


def save_app_details(app_id: int, data: dict) -> None:
    """Save appid data to a cache file."""
    cache_manager = CacheManager()
    cache_manager.save_json(f"steam_app_{app_id}", data)


def load_steam_apps(callback: Callable[[list], None]) -> None:
    """Load Steam applications, using cache if available."""
    cache_manager = CacheManager()
    cache_tar_path = cache_manager.cache_dir / "games_appid.tar.xz"
    cache_json_path = cache_manager.cache_dir / "steam_apps.json"

    def process_tar(result: str | None) -> None:
        if not result or not os.path.exists(result):
            logger.error("Failed to download Steam apps archive")
            callback([])
            return
        try:
            with tarfile.open(result, mode='r:xz') as tar:
                member = next((m for m in tar.getmembers() if m.name.endswith('.json')), None)
                if member is None:
                    raise RuntimeError("JSON file not found in archive")
                fobj = tar.extractfile(member)
                if fobj is None:
                    raise RuntimeError(f"Failed to extract file {member.name} from archive")
                raw = fobj.read()
                fobj.close()
                data = orjson.loads(raw)
            with open(cache_json_path, "wb") as f:
                f.write(orjson.dumps(data))
            if os.path.exists(cache_tar_path):
                os.remove(cache_tar_path)
                logger.info("Deleted archive: %s", cache_tar_path)
            delete_cached_app_files(str(cache_manager.cache_dir), "steam_app_*.json")
            delete_cached_app_files(str(cache_manager.cache_dir), "protondb_*.json")

            steam_apps = data if isinstance(data, list) else []
            logger.info("Loaded %d apps from archive", len(steam_apps))
            callback(steam_apps)
        except Exception as e:
            logger.error("Failed to extract Steam apps archive: %s", e)
            callback([])

    if cache_json_path.exists() and (time.time() - cache_json_path.stat().st_mtime < CACHE_DURATION):
        logger.info("Using cached Steam apps JSON: %s", cache_json_path)
        try:
            with open(cache_json_path, "rb") as f:
                data = orjson.loads(f.read())
            if not isinstance(data, list):
                logger.error("Invalid JSON format in %s (not a list), re-downloading", cache_json_path)
                raise ValueError("Invalid JSON structure")
            for app in data:
                if not isinstance(app, dict) or "appid" not in app or "normalized_name" not in app:
                    logger.error("Invalid app entry in cached JSON %s, re-downloading", cache_json_path)
                    raise ValueError("Invalid app entry structure")
            callback(data)
        except Exception as e:
            logger.error("Failed to read or validate cached JSON %s: %s", cache_json_path, e)
            app_list_url = (
                "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/data/games_appid.tar.xz"
            )
            delete_cached_app_files(str(cache_manager.cache_dir), "steam_app_*.json")
            delete_cached_app_files(str(cache_manager.cache_dir), "protondb_*.json")
            process_tar(downloader.download(app_list_url, str(cache_tar_path), timeout=5))
    else:
        app_list_url = (
            "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/data/games_appid.tar.xz"
        )
        delete_cached_app_files(str(cache_manager.cache_dir), "steam_app_*.json")
        delete_cached_app_files(str(cache_manager.cache_dir), "protondb_*.json")
        process_tar(downloader.download(app_list_url, str(cache_tar_path), timeout=5))


def build_index(steam_apps: list) -> dict:
    """Build index of applications by normalized_name field."""
    steam_apps_index: dict[str, dict] = {}
    if not steam_apps:
        return steam_apps_index
    logger.info("Building Steam apps index")
    for app in steam_apps:
        normalized = app.get("normalized_name", "")
        if normalized:
            steam_apps_index.setdefault(normalized, app)
    return steam_apps_index


def search_app(candidate: str, steam_apps_index: dict) -> dict | None:
    """Search for application by candidate: exact match first, then partial."""
    candidate_norm = normalize_name(candidate)

    if candidate_norm in steam_apps_index:
        return steam_apps_index[candidate_norm]

    for name_norm, app in steam_apps_index.items():
        if candidate_norm in name_norm:
            ratio = len(candidate_norm) / len(name_norm)
            if ratio > 0.8:
                return app

    return None


def load_weanticheatyet_data(callback: Callable[[list], None]) -> None:
    """Load WeAntiCheatYet data, using cache if available."""
    cache_manager = CacheManager()
    cache_tar_path = cache_manager.cache_dir / "anticheat_games.tar.xz"
    cache_json_path = cache_manager.cache_dir / "anticheat_games.json"

    def process_tar(result: str | None) -> None:
        if not result or not os.path.exists(result):
            logger.error("Failed to download WeAntiCheatYet archive")
            callback([])
            return
        try:
            with tarfile.open(result, mode='r:xz') as tar:
                member = next((m for m in tar.getmembers() if m.name.endswith('anticheat_games_min.json')), None)
                if member is None:
                    raise RuntimeError("JSON file not found in archive")
                fobj = tar.extractfile(member)
                if fobj is None:
                    raise RuntimeError(f"Failed to extract file {member.name} from archive")
                raw = fobj.read()
                fobj.close()
                data = orjson.loads(raw)
            with open(cache_json_path, "wb") as f:
                f.write(orjson.dumps(data))
            if os.path.exists(cache_tar_path):
                os.remove(cache_tar_path)
                logger.info("Deleted archive: %s", cache_tar_path)

            anti_cheat_data = data or []
            logger.info("Loaded %d anti-cheat entries from archive", len(anti_cheat_data))
            callback(anti_cheat_data)
        except Exception as e:
            logger.error("Failed to extract WeAntiCheatYet archive: %s", e)
            callback([])

    if cache_json_path.exists() and (time.time() - cache_json_path.stat().st_mtime < CACHE_DURATION):
        logger.info("Using cached WeAntiCheatYet JSON: %s", cache_json_path)
        try:
            with open(cache_json_path, "rb") as f:
                data = orjson.loads(f.read())
            if not isinstance(data, list):
                logger.error("Invalid JSON format in %s (not a list), re-downloading", cache_json_path)
                raise ValueError("Invalid JSON structure")
            for entry in data:
                if not isinstance(entry, dict) or "normalized_name" not in entry or "status" not in entry:
                    logger.error("Invalid anti-cheat entry in cached JSON %s, re-downloading", cache_json_path)
                    raise ValueError("Invalid anti-cheat entry structure")
                if "slug" not in entry:
                    logger.error("Anti-cheat entry without slug in cached JSON %s, re-downloading", cache_json_path)
                    raise ValueError("Missing anti-cheat slug field")
            callback(data)
        except Exception as e:
            logger.error("Failed to read or validate cached WeAntiCheatYet JSON %s: %s", cache_json_path, e)
            app_list_url = (
                "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/data/anticheat_games.tar.xz"
            )
            process_tar(downloader.download(app_list_url, str(cache_tar_path), timeout=5))
    else:
        app_list_url = (
            "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/data/anticheat_games.tar.xz"
        )
        process_tar(downloader.download(app_list_url, str(cache_tar_path), timeout=5))


def _extract_ppdb_archive(
    result: str | None,
    cache_tar_path: os.PathLike,
    cache_json_path: os.PathLike,
) -> list:
    if not result or not os.path.exists(result):
        logger.error("Failed to download PPDB archive")
        return []
    try:
        with tarfile.open(result, mode='r:xz') as tar:
            member = next((m for m in tar.getmembers() if m.name.endswith('ppdb_games_min.json')), None)
            if member is None:
                raise RuntimeError("JSON file not found in archive")
            fobj = tar.extractfile(member)
            if fobj is None:
                raise RuntimeError(f"Failed to extract file {member.name} from archive")
            raw = fobj.read()
            fobj.close()
            data = orjson.loads(raw)
        with open(cache_json_path, "wb") as f:
            f.write(orjson.dumps(data))
        if os.path.exists(cache_tar_path):
            os.remove(cache_tar_path)
            logger.info("Deleted archive: %s", cache_tar_path)
        return data or []
    except Exception as e:
        logger.error("Failed to extract PPDB archive: %s", e)
        return []


def load_ppdb_data(callback: Callable[[list], None]) -> None:
    """Load PPDB data, using cache if available."""
    cache_manager = CacheManager()
    cache_tar_path = cache_manager.cache_dir / "ppdb_games.tar.xz"
    cache_json_path = cache_manager.cache_dir / "ppdb_games.json"

    def process_tar(result: str | None) -> None:
        ppdb_data = _extract_ppdb_archive(result, cache_tar_path, cache_json_path)
        logger.info("Loaded %d PPDB entries from archive", len(ppdb_data))
        callback(ppdb_data)

    if cache_json_path.exists() and (time.time() - cache_json_path.stat().st_mtime < CACHE_DURATION):
        logger.info("Using cached PPDB JSON: %s", cache_json_path)
        try:
            with open(cache_json_path, "rb") as f:
                data = orjson.loads(f.read())
            if not isinstance(data, list):
                logger.error("Invalid JSON format in %s (not a list), re-downloading", cache_json_path)
                raise ValueError("Invalid JSON structure")
            for entry in data:
                if not isinstance(entry, dict) or "normalized_name" not in entry or "id" not in entry:
                    logger.error("Invalid PPDB entry in cached JSON %s, re-downloading", cache_json_path)
                    raise ValueError("Invalid PPDB entry structure")
            callback(data)
        except Exception as e:
            logger.error("Failed to read or validate cached PPDB JSON %s: %s", cache_json_path, e)
            process_tar(downloader.download(PPDB_DATA_URL, str(cache_tar_path), timeout=5))
    else:
        process_tar(downloader.download(PPDB_DATA_URL, str(cache_tar_path), timeout=5))


def build_weanticheatyet_index(anti_cheat_data: list) -> dict:
    """Build index of anti-cheat data by normalized_name field."""
    anti_cheat_index: dict[str, dict] = {}
    if not anti_cheat_data:
        return anti_cheat_index
    logger.info("Building WeAntiCheatYet data index")
    for entry in anti_cheat_data:
        normalized = entry.get("normalized_name", "")
        if normalized:
            anti_cheat_index[normalized] = entry
    return anti_cheat_index


def build_ppdb_index(ppdb_data: list) -> dict:
    """Build index of PPDB data by normalized_name field."""
    ppdb_index: dict[str, dict] = {}
    if not ppdb_data:
        return ppdb_index
    logger.info("Building PPDB data index")
    for entry in ppdb_data:
        normalized = entry.get("normalized_name", "")
        if normalized:
            ppdb_index[normalized] = entry
    return ppdb_index


def load_protondb_status(appid: int) -> dict | None:
    """Load cached ProtonDB data for a game by appid if not outdated."""
    cache_manager = CacheManager()
    if cache_manager.is_fresh(f"protondb_{appid}", CACHE_DURATION):
        return cache_manager.load_json(f"protondb_{appid}")
    return None


def save_protondb_status(appid: int, data: dict) -> None:
    """Save ProtonDB data for a game by appid to a cache file."""
    cache_manager = CacheManager()
    cache_manager.save_json(f"protondb_{appid}", data)


def search_anticheat_status(candidate: str, anti_cheat_index: dict) -> str:
    """Search for anti-cheat status by candidate: exact match first, then partial."""
    entry = search_anticheat_entry(candidate, anti_cheat_index)
    if not entry:
        return ""
    return entry.get("status", "")


def search_anticheat_entry(candidate: str, anti_cheat_index: dict) -> dict | None:
    """Search for anti-cheat entry by candidate: exact match first, then partial."""
    if not candidate:
        return None
    candidate_norm = normalize_name(candidate)

    if candidate_norm in anti_cheat_index:
        return anti_cheat_index[candidate_norm]

    for name_norm, entry in anti_cheat_index.items():
        if candidate_norm in name_norm:
            ratio = len(candidate_norm) / len(name_norm)
            if ratio > 0.8:
                return entry

    return None


def search_ppdb_entry(candidate: str, ppdb_index: dict) -> dict | None:
    """Search for PPDB entry by candidate: exact match first, then partial."""
    if not candidate:
        return None
    candidate_norm = normalize_name(candidate)

    if candidate_norm in ppdb_index:
        return ppdb_index[candidate_norm]

    for name_norm, entry in ppdb_index.items():
        if candidate_norm in name_norm:
            ratio = len(candidate_norm) / len(name_norm)
            if ratio > 0.8:
                return entry

    return None
