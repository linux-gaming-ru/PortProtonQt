"""Headless access to the PortProton game library."""
import configparser
import hashlib
import json
import logging
import locale
import os
import re
import shlex
import shutil
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

GAME_ID_LENGTH = 16
LAUNCH_EXTENSIONS = (".exe", ".bat", ".cmd", ".msi", ".reg", ".iso", ".mdf", ".nrg")
IMAGE_EXTENSIONS = (".png", ".apng", ".jpg", ".jpeg", ".gif", ".webp", ".jxl", ".svg")
AUTOINSTALL_API_URL = "https://linux-gaming.ru/api/games/autoinstall"
logger = logging.getLogger(__name__)


def get_library_games(filters: dict[str, object] | None = None) -> list[dict[str, object]]:
    """Return locally available games without importing GUI modules."""
    filters = filters or {}
    selected = filters.get("source")
    loaders = {
        "portproton": _get_portproton_games,
        "steam": _get_steam_games,
        "gog": lambda: _get_store_games("gog"),
        "egs": lambda: _get_store_games("egs"),
    }
    games = []
    for source, loader in loaders.items():
        if selected is None or selected == source:
            games.extend(loader())
    return [game for game in games if _matches_filters(game, filters)]


def get_wine_options() -> list[str]:
    """Return installed Wine and Proton choices without GUI imports."""
    directory = _get_portproton_directory()
    options = set()
    if directory is not None:
        dist = directory / "data" / "dist"
        if dist.is_dir():
            options.update(path.name for path in dist.iterdir() if path.is_dir())
    if shutil.which("wine"):
        options.add("USE_SYSTEM_WINE")
    for root in (
        Path.home() / ".steam/root/compatibilitytools.d",
        Path.home() / ".local/share/Steam/compatibilitytools.d",
    ):
        if root.is_dir():
            options.update(str(path) for path in root.iterdir() if path.is_dir())
    return sorted(options, key=str.casefold)


def get_prefix_options() -> list[str]:
    """Return existing prefixes and the built-in choices."""
    directory = _get_portproton_directory()
    options = {"DEFAULT", "DOTNET"}
    if directory is not None:
        prefixes = directory / "data" / "prefixes"
        if prefixes.is_dir():
            options.update(path.name for path in prefixes.iterdir() if path.is_dir())
    return ["DEFAULT", "DOTNET", *sorted(options - {"DEFAULT", "DOTNET"}, key=str.casefold)]


def get_autoinstall_games(force_refresh: bool = False) -> list[dict[str, str]]:
    """Use PortProtonQt's catalog cache, fetching it when missing or requested."""
    cache = _data_home() / "PortProtonQt/cache/autoinstall_games_cache.json"
    data = _read_json(cache, {})
    if force_refresh or not isinstance(data, dict) or not isinstance(data.get("games"), list):
        temporary_path = None
        try:
            data = _fetch_autoinstall_games()
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=cache.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(data, temporary)
            os.replace(temporary.name, cache)
        except (OSError, ValueError, urllib.error.URLError) as error:
            logger.warning("Failed to refresh autoinstall catalog: %s", error)
            data = _read_json(cache, {})
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    cached_games = data.get("games") if isinstance(data, dict) else None
    if not isinstance(cached_games, list):
        return []
    games = []
    for item in cached_games:
        if isinstance(item, list) and len(item) > 5:
            games.append({
                "name": str(item[0]), "description": str(item[1]),
                "cover": str(item[2]), "script": str(item[5]),
            })
    return games


def _fetch_autoinstall_games() -> dict[str, object]:
    with urllib.request.urlopen(AUTOINSTALL_API_URL, timeout=10) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Invalid autoinstall catalog")
    api_games = data.get("games")
    if not isinstance(api_games, list):
        raise ValueError("Invalid autoinstall catalog")
    language = (locale.getlocale()[0] or "en").split("_", 1)[0].lower()
    if language not in {"ru", "es", "pt"}:
        language = "en"
    games = []
    for game in api_games:
        if not isinstance(game, dict) or not isinstance(game.get("id"), int):
            continue
        url = game.get("ppai_url")
        name = game.get(f"name_{language}") or game.get("name_en") or game.get("name")
        if not isinstance(url, str) or not isinstance(name, str) or not name:
            continue
        description = game.get(f"description_{language}") or game.get("description_en") or ""
        cover = game.get("icon_full_url") or ""
        games.append([name, description, cover, "", "", f"autoinstall:{url}",
                      "Never", "0h 0m", "", "", 0, 0, "autoinstall",
                      f"game_{game['id']}", game.get("icon_compact_url") or "", cover])
    return {"api_url": AUTOINSTALL_API_URL, "games": games}


def _get_portproton_games() -> list[dict[str, object]]:
    directory = _get_portproton_directory()
    if directory is None:
        return []
    try:
        desktop_files = sorted(directory.glob("*.desktop"))
    except OSError as error:
        logger.warning("Failed to list PortProton games: %s", error)
        return []
    games = []
    for desktop_file in desktop_files:
        game = _read_desktop_game(desktop_file)
        if game is not None:
            games.append(game)
    return games


def _get_portproton_directory() -> Path | None:
    config_dir = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config_dir / "PortProtonQt.conf", encoding="utf-8")
        configured = parser.get("PortProton", "portdata_path", fallback="").strip()
    except (configparser.Error, OSError, UnicodeError) as error:
        logger.warning("Failed to read PortProtonQt configuration: %s", error)
        configured = ""
    candidates = [configured, _read_legacy_path(config_dir)]
    candidates.append(str(Path.home() / ".var/app/ru.linux_gaming.PortProton"))
    return next((Path(path) for path in candidates if path and Path(path).is_dir()), None)


def _read_legacy_path(config_dir: Path) -> str:
    try:
        return (config_dir / "PortProton.conf").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _read_desktop_game(desktop_file: Path) -> dict[str, object] | None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(desktop_file, encoding="utf-8")
        entry = parser["Desktop Entry"]
        name = entry.get("Name", "").strip()
        hidden = entry.get("NoDisplay", "false").strip().lower() == "true"
    except (KeyError, configparser.Error, OSError, UnicodeError):
        return None
    if not name or name.casefold() in {"portproton", "readme"}:
        return None
    launch_target = _get_launch_target(entry.get("Exec", ""))
    identity = os.path.normpath(os.path.abspath(launch_target)) if launch_target else str(desktop_file.resolve())
    game_id = hashlib.sha256(identity.encode()).hexdigest()[:GAME_ID_LENGTH]
    return {
        "id": f"portproton:{game_id}",
        "name": name,
        "executable": launch_target,
        "source": "portproton",
        "installed": True,
        "hidden": hidden,
        "cover": _get_cover(entry.get("Icon", ""), desktop_file.parent),
        "playtime": _get_playtime(launch_target),
        "last_launch": _get_last_launch(Path(launch_target).stem),
    }


def _get_steam_games() -> list[dict[str, object]]:
    steam = next((path for path in (
        Path.home() / ".steam/root", Path.home() / ".local/share/Steam"
    ) if path.is_dir()), None)
    if steam is None:
        return []
    playtime = _get_steam_playtime(steam)
    games = []
    for manifest in steam.glob("steamapps/appmanifest_*.acf"):
        text = _read_text(manifest)
        app_id = _vdf_value(text, "appid")
        name = _vdf_value(text, "name")
        if not app_id or not name:
            continue
        last_launch, seconds = playtime.get(app_id, (0, 0))
        cover = steam / "appcache/librarycache" / f"{app_id}_library_600x900.jpg"
        games.append(_game(
            app_id, name, "steam",
            (True, str(cover) if cover.is_file() else "", seconds, last_launch),
        ))
    return games


def _get_store_games(source: str) -> list[dict[str, object]]:
    root = _data_home() / "PortProtonQt/launcher" / source
    library = _read_json(root / "library.json", [])
    installed_path = root / ("legendary/installed.json" if source == "egs" else "installed.json")
    installed = _read_json(installed_path, {})
    if not isinstance(library, list) or not isinstance(installed, dict):
        return []
    games = []
    for item in library:
        if not isinstance(item, dict) or not item.get("app_id"):
            continue
        app_id = str(item["app_id"])
        record = installed.get(app_id, {})
        target = _store_target(source, app_id, record)
        games.append(_game(app_id, str(item.get("title", app_id)), source, (
            bool(target), str(item.get("cover", "")),
            _get_playtime(target), _get_last_launch(f"{source}-{app_id}"),
        )))
    return games


def _game(
    app_id: str, name: str, source: str, details: tuple[bool, str, int, int],
) -> dict[str, object]:
    installed, cover, playtime, last_launch = details
    return {
        "id": f"{source}:{app_id}", "name": name, "source": source,
        "installed": installed, "hidden": False,
        "cover": cover,
        "playtime": playtime, "last_launch": last_launch,
    }


def _data_home() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))


def _store_target(source: str, app_id: str, record: object) -> str:
    if not isinstance(record, dict):
        return ""
    install_path = Path(str(record.get("install_path", "")))
    if source == "egs":
        target = install_path / str(record.get("executable", "")).replace("\\", "/")
        return str(target) if target.is_file() else ""
    info = install_path / f"goggame-{app_id}.info"
    metadata = _read_json(info, {})
    tasks = metadata.get("playTasks", []) if isinstance(metadata, dict) else []
    primary = next((task for task in tasks if task.get("isPrimary")), None)
    if not isinstance(primary, dict):
        return ""
    target = install_path.joinpath(*str(primary.get("path", "")).replace("\\", "/").split("/"))
    return str(target) if target.is_file() else ""


def _get_playtime(target: str) -> int:
    if not target:
        return 0
    target_path = os.path.normpath(target)
    for line in _read_text(_data_home() / "PortProtonQt/statistics").splitlines():
        parts = line.split()
        if len(parts) >= 3 and os.path.normpath(parts[0].replace("#@_@#", " ")) == target_path:
            try:
                return int(parts[2])
            except ValueError:
                return 0
    return 0


def _get_last_launch(key: str) -> int:
    if not key:
        return 0
    for line in _read_text(_data_home() / "PortProtonQt/last_launch").splitlines():
        parts = line.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[0] == key:
            try:
                return int(datetime.fromisoformat(parts[1]).timestamp())
            except ValueError:
                return 0
    return 0


def _get_steam_playtime(steam: Path) -> dict[str, tuple[int, int]]:
    configs = sorted((steam / "userdata").glob("*/config/localconfig.vdf"))
    text = _read_text(configs[-1]) if configs else ""
    result = {}
    for app_id, block in re.findall(r'"(\d+)"\s*\{([^{}]*)\}', text, re.DOTALL):
        result[app_id] = (
            int(_vdf_value(block, "LastPlayed") or 0),
            int(_vdf_value(block, "Playtime") or 0) * 60,
        )
    return result


def _vdf_value(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text, re.IGNORECASE)
    return match.group(1) if match else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def _get_launch_target(exec_line: str) -> str:
    try:
        command = shlex.split(exec_line)
    except ValueError:
        return ""
    if "--silent" in command:
        target_index = command.index("--silent") + 1
        return command[target_index] if target_index < len(command) else ""
    return next(
        (part for part in reversed(command) if part.lower().endswith(LAUNCH_EXTENSIONS)),
        "",
    )


def _get_cover(icon: str, game_dir: Path) -> str:
    icon_path = Path(icon.strip()).expanduser()
    if icon_path.is_file():
        return str(icon_path)
    local_icon = game_dir / "data" / "img" / icon_path
    if local_icon.is_file():
        return str(local_icon)
    if not local_icon.suffix:
        for suffix in IMAGE_EXTENSIONS:
            candidate = local_icon.with_suffix(suffix)
            if candidate.is_file():
                return str(candidate)
    return ""


def _matches_filters(game: dict[str, object], filters: dict[str, object]) -> bool:
    source = filters.get("source")
    if source is not None and source != game["source"]:
        return False
    installed = filters.get("installed")
    if installed is not None and installed != game["installed"]:
        return False
    search = filters.get("search")
    return not isinstance(search, str) or search.casefold() in str(game["name"]).casefold()
