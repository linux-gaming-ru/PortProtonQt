import os
import subprocess
import requests
import urllib.parse
import time
import re
import hashlib
import queue
import shutil
import locale
import tempfile
from collections.abc import Callable
from typing import Any
from PySide6.QtCore import QThread, Signal, QUrl, QObject
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication
from portprotonqt.downloader import Downloader, get_requests_session
from portprotonqt.logger import get_logger
from portprotonqt.config import (
    extract_exec_target_path,
    get_portproton_location,
    get_portproton_start_command,
)
from portprotonqt.localization import _
from portprotonqt.dialogs import FileExplorer
from portprotonqt.config.cache import CacheManager
from portprotonqt.image_utils import (
    COVER_IMAGE_EXTENSIONS,
    clear_ppdb_autoinstall_image_cache,
)

logger = get_logger(__name__)
AUTOINSTALL_API_URL = "https://linux-gaming.ru/api/games/autoinstall"
HEAD_FAILURE_RETRY_DELAY = 60  # 1 minute cooldown for failed HEAD checks
HEAD_CACHE_DURATION = 24 * 60 * 60
HEAD_CACHE_NAME = "head_cache"
HEAD_CACHE_OLD_PATTERN = "head_*.json"


def remove_empty_custom_data_dirs(custom_data_dir: str) -> None:
    if not os.path.isdir(custom_data_dir):
        return

    for root, dirs, _files in os.walk(custom_data_dir, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            try:
                os.rmdir(dir_path)
            except OSError:
                continue
    try:
        os.rmdir(custom_data_dir)
    except OSError:
        return


def _create_bootstrap_file_explorer_parent() -> tuple[QObject | None, Any]:
    """Create a minimal parent with InputManager before MainWindow exists."""
    parent = QApplication.activeWindow()
    if parent is not None:
        return parent, None

    try:
        from portprotonqt.input_manager import InputManager
        from portprotonqt.port_data_path_selector import _BootstrapInputHost
    except ImportError as e:
        logger.warning("Cannot initialize gamepad support for PPDB file dialog: %s", e)
        return None, None

    input_host = _BootstrapInputHost()
    input_manager = InputManager(input_host)
    input_host.input_manager = input_manager
    return input_host, input_manager


def normalize_name(s):
    """
    Normalize string:
    - convert to lowercase,
    - remove ™ and ® symbols,
    - replace separators (-, :, ,) with space,
    - remove extra spaces,
    - remove 'bin' or 'app' suffixes at end of string,
    - remove keywords like 'ultimate', 'edition', etc.
    """
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


def extract_exe_name(exec_line: str) -> str:
    """Extract executable name from exec_line.

    Handles various exec_line formats:
    - Full command: 'env VAR=val /path/to/script /path/to/game.exe' -> 'game.exe'
    - Autoinstall: 'autoinstall:script_name' -> ''
    - Simple path: '/path/to/game.exe' -> 'game.exe'

    Returns:
        Executable name with .exe extension, or empty string if not found
    """

    if not exec_line:
        return ""

    # Handle autoinstall scripts - they don't have a direct exe
    if exec_line.startswith("autoinstall:"):
        return ""

    game_exe = extract_exec_target_path(exec_line)
    if game_exe and game_exe.lower().endswith(".exe"):
        return os.path.basename(game_exe)
    return ""


class PortProtonAPI:
    """API helpers for PPDB and autoinstall data."""
    def __init__(self, downloader: Downloader | None = None):
        self.downloader = downloader or Downloader(max_workers=4)
        self.xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
        self.custom_data_dir = os.path.join(self.xdg_data_home, "PortProtonQt", "custom_data")
        self.portproton_location = get_portproton_location()
        self._autoinstall_cache = None  # In-memory cache
        self._head_positive_cache: set[str] = set()
        self._head_negative_cache: set[str] = set()
        self._head_failure_cache: dict[str, float] = {}
        self._head_disk_cache_cleaned = False

    def _load_head_cache_entry(self, cache_manager: CacheManager, cache_key: str) -> bool | None:
        cached = cache_manager.load_json(HEAD_CACHE_NAME)
        if not isinstance(cached, dict):
            return None
        entry = cached.get(cache_key)
        if not isinstance(entry, dict):
            return None
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, int | float):
            return None
        if time.time() - timestamp > HEAD_CACHE_DURATION:
            return None
        return entry.get("exists") is True

    def _save_head_cache_entry(self, cache_manager: CacheManager, cache_key: str, exists: bool) -> None:
        cached = cache_manager.load_json(HEAD_CACHE_NAME)
        if not isinstance(cached, dict):
            cached = {}
        cached[cache_key] = {"exists": exists, "timestamp": time.time()}
        cache_manager.save_json(HEAD_CACHE_NAME, cached)
        self._remove_old_head_cache_files(cache_manager)

    def _remove_old_head_cache_files(self, cache_manager: CacheManager) -> None:
        if self._head_disk_cache_cleaned:
            return
        for cache_file in cache_manager.cache_dir.glob(HEAD_CACHE_OLD_PATTERN):
            try:
                cache_file.unlink()
            except OSError as e:
                logger.debug("Failed to remove old HEAD cache %s: %s", cache_file, e)
        self._head_disk_cache_cleaned = True

    def _check_file_exists(self, url: str, timeout: int = 5) -> bool:
        if url in self._head_negative_cache:
            return False
        if url in self._head_positive_cache:
            return True
        last_failed_check = self._head_failure_cache.get(url)
        if last_failed_check and (time.time() - last_failed_check) < HEAD_FAILURE_RETRY_DELAY:
            return False

        cache_manager = CacheManager()
        cache_key = hashlib.sha256(url.encode('utf-8')).hexdigest()
        cached_exists = self._load_head_cache_entry(cache_manager, cache_key)
        if cached_exists is not None:
            return cached_exists

        try:
            session = get_requests_session()
            response = session.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 404:
                self._head_negative_cache.add(url)
                self._head_positive_cache.discard(url)
                self._head_failure_cache.pop(url, None)
                self._save_head_cache_entry(cache_manager, cache_key, False)
                return False
            response.raise_for_status()
            if response.status_code == 200:
                self._head_positive_cache.add(url)
                self._head_failure_cache.pop(url, None)
                self._save_head_cache_entry(cache_manager, cache_key, True)
                return True
            return False
        except requests.RequestException as e:
            logger.debug(f"Failed to check file at {url}: {e}")
            self._head_failure_cache[url] = time.time()
            return False

    def _load_autoinstall_cache(self):
        """Load cached autoinstall games."""
        if self._autoinstall_cache is not None:
            return self._autoinstall_cache
        cache_manager = CacheManager()
        if cache_manager.exists("autoinstall_games_cache"):
            try:
                data = cache_manager.load_json("autoinstall_games_cache")
                if isinstance(data, dict):
                    if data.get("api_url") != AUTOINSTALL_API_URL:
                        return None
                    games = data["games"]
                    if not self._autoinstall_cache_uses_urls(games):
                        return None
                    self._autoinstall_cache = games
                    logger.info(f"Loaded {len(self._autoinstall_cache)} cached autoinstall games")
                    return self._autoinstall_cache
            except Exception as e:
                logger.error(f"Failed to load autoinstall cache: {e}")
        return None

    def _autoinstall_cache_uses_urls(self, games: list) -> bool:
        for game in games:
            if len(game) <= 5 or not isinstance(game[5], str):
                return False
            if not game[5].startswith("autoinstall:http"):
                return False
        return True

    def _save_autoinstall_cache(self, games):
        """Save autoinstall games to cache."""
        try:
            cache_manager = CacheManager()
            data = {"games": games, "api_url": AUTOINSTALL_API_URL, "timestamp": time.time()}
            cache_manager.save_json("autoinstall_games_cache", data)
            logger.debug(f"Saved {len(games)} autoinstall games to cache")
        except Exception as e:
            logger.error(f"Failed to save autoinstall cache: {e}")

    def clear_autoinstall_cache(self) -> None:
        """Clear cached autoinstall API data."""
        self._autoinstall_cache = None
        cache_manager = CacheManager()
        cache_manager.remove("autoinstall_games_cache")

    def clear_autoinstall_image_cache(self) -> None:
        """Clear cached autoinstall PPDB images."""
        games = self._load_autoinstall_cache() or []
        cover_urls = []
        for game in games:
            if len(game) > 14 and isinstance(game[14], str):
                cover_urls.append(game[14])
            if len(game) > 15 and isinstance(game[15], str):
                cover_urls.append(game[15])
        clear_ppdb_autoinstall_image_cache(cover_urls)

    def _get_autoinstall_lang_code(self) -> str:
        try:
            current_locale = locale.getlocale()[0] or "en"
        except (AttributeError, IndexError, TypeError):
            current_locale = "en"
        for lang_code in ("ru", "es", "pt"):
            if lang_code in current_locale.lower():
                return lang_code
        return "en"

    def _get_autoinstall_field(self, game: dict, field: str, lang_code: str) -> str:
        value = game.get(f"{field}_{lang_code}") or game.get(f"{field}_en") or game.get(field)
        return value if isinstance(value, str) else ""

    def _get_custom_game_dir(self, exe_name: str) -> str:
        game_dir = os.path.join(self.custom_data_dir, exe_name)
        os.makedirs(game_dir, exist_ok=True)
        return game_dir

    def _clean_metadata_value(self, value: str) -> str:
        return value.replace("\r", " ").replace("\n", " ").strip()

    def read_local_autoinstall_metadata(self, script_path: str) -> dict[str, str]:
        metadata: dict[str, str] = {}
        try:
            with open(script_path, encoding="utf-8") as script_file:
                for line in script_file:
                    clean_line = line.strip()
                    if clean_line.startswith("# name:"):
                        metadata["name"] = clean_line.split(":", 1)[1].strip()
                    elif clean_line.startswith("# info_"):
                        key, _, value = clean_line[2:].partition(":")
                        metadata[key.strip()] = value.strip()
        except OSError as e:
            logger.warning("Failed to read local autoinstall script %s: %s", script_path, e)

        lang_code = self._get_autoinstall_lang_code()
        description = metadata.get(f"info_{lang_code}") or metadata.get("info_en") or ""
        return {
            "name": metadata.get("name", ""),
            "description": description,
        }

    def _write_autoinstall_metadata(self, game_data: dict, game_dir: str) -> None:
        metadata_path = os.path.join(game_dir, "metadata.txt")
        name = game_data.get("name", "")
        description = game_data.get("description", "")
        try:
            with open(metadata_path, "w", encoding="utf-8") as metadata_file:
                if isinstance(name, str) and name.strip():
                    metadata_file.write(f"name={self._clean_metadata_value(name)}\n")
                if isinstance(description, str) and description.strip():
                    clean_description = self._clean_metadata_value(description)
                    metadata_file.write(f"description={clean_description}\n")
        except OSError as e:
            logger.warning("Failed to write autoinstall metadata %s: %s", metadata_path, e)

    def _get_custom_cover_path(self, game_dir: str, cover_url: str) -> str:
        ext = os.path.splitext(urllib.parse.urlparse(cover_url).path)[1].lower()
        if ext not in COVER_IMAGE_EXTENSIONS:
            ext = ".png"
        return os.path.join(game_dir, f"cover{ext}")

    def _cache_autoinstall_cover(self, cover_path: str, game_dir: str) -> str:
        if not cover_path.startswith(("http://", "https://")):
            return ""
        local_path = self._get_custom_cover_path(game_dir, cover_path)
        downloaded_path = self.downloader.download(cover_path, local_path, timeout=10)
        return downloaded_path or ""

    def _extract_exe_name_from_script_line(self, line: str) -> str:
        for part in line.replace("\\", "/").split("/"):
            clean_part = part.strip().strip('"\' }')
            if clean_part.lower().endswith(".exe"):
                return clean_part
        return ""

    def _get_autoinstall_exe_name(self, script_path: str) -> str:
        install_exe = ""
        shortcut_name = ""
        try:
            with open(script_path, encoding="utf-8") as script_file:
                for line in script_file:
                    if line.lstrip().startswith("#"):
                        continue
                    if "PORTWINE_CREATE_SHORTCUT_NAME=" in line:
                        match = re.search(
                            r'PORTWINE_CREATE_SHORTCUT_NAME=["\']([^"\']+)', line
                        )
                        if match:
                            shortcut_name = match.group(1)
                    if "PW_EXE_FILE" in line:
                        exe_name = self._extract_exe_name_from_script_line(line)
                        if exe_name:
                            install_exe = exe_name
                    if line.strip().startswith("pw_create_unique_exe"):
                        match = re.search(r'pw_create_unique_exe\s+["\']?([^"\' ]+)', line)
                        unique_name = match.group(1) if match else shortcut_name
                        if unique_name:
                            return f"{os.path.splitext(unique_name)[0]}.exe"
                    if "PW_AUTOINSTALL_EXE" not in line:
                        continue
                    exe_name = self._extract_exe_name_from_script_line(line)
                    if exe_name and not install_exe:
                        install_exe = exe_name
        except OSError as e:
            logger.warning("Failed to read autoinstall script %s: %s", script_path, e)
        return install_exe

    def write_autoinstall_custom_data(self, script_path: str, game_data: dict) -> None:
        if not game_data:
            return
        exe_file = self._get_autoinstall_exe_name(script_path)
        if not exe_file:
            return

        exe_name = os.path.splitext(os.path.basename(exe_file))[0]
        cover_path = game_data.get("cover_path", "")
        has_cover = isinstance(cover_path, str) and cover_path.startswith(("http://", "https://"))
        has_metadata = any(
            isinstance(game_data.get(key, ""), str) and game_data.get(key, "").strip()
            for key in ("name", "description")
        )
        if not has_metadata and not has_cover:
            return

        game_dir = self._get_custom_game_dir(exe_name)
        if has_metadata:
            self._write_autoinstall_metadata(game_data, game_dir)
        if has_cover:
            self._cache_autoinstall_cover(cover_path, game_dir)
        remove_empty_custom_data_dirs(self.custom_data_dir)

    def _get_autoinstall_script_path(self, ppai_url: str) -> str:
        script_name = os.path.basename(urllib.parse.urlparse(ppai_url).path)
        if not script_name.endswith(".ppai"):
            return ""
        cache_dir = os.path.join(tempfile.gettempdir(), "PortProtonQt", "autoinstall")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, script_name)

    def download_autoinstall_script(self, ppai_url: str) -> str:
        script_path = self._get_autoinstall_script_path(ppai_url)
        if not script_path:
            return ""

        temp_path = ""
        try:
            session = get_requests_session()
            response = session.get(ppai_url, timeout=10)
            response.raise_for_status()
            cache_dir = os.path.dirname(script_path)
            os.makedirs(cache_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=cache_dir,
                prefix=f"{os.path.basename(script_path)}.",
                suffix=".tmp",
                delete=False,
            ) as script_file:
                temp_path = script_file.name
                script_file.write(response.text)
            os.replace(temp_path, script_path)
            return script_path
        except (OSError, requests.RequestException) as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError as cleanup_error:
                    logger.debug(
                        "Failed to remove temp autoinstall script %s: %s",
                        temp_path,
                        cleanup_error,
                    )
            logger.warning("Failed to download autoinstall script %s: %s", ppai_url, e)
        return ""

    def start_autoinstall_script_download(
        self,
        ppai_url: str,
        callback: Callable[[str], None],
    ) -> QThread:
        class AutoinstallScriptWorker(QThread):
            script_ready = Signal(str)
            api: "PortProtonAPI"
            ppai_url: str

            def run(self):
                script_path = self.api.download_autoinstall_script(self.ppai_url)
                self.script_ready.emit(script_path)

        worker = AutoinstallScriptWorker()
        worker.api = self
        worker.ppai_url = ppai_url
        worker.script_ready.connect(callback)
        worker.start()
        return worker

    def start_autoinstall_custom_data_write(
        self,
        script_path: str,
        game_data: dict,
    ) -> QThread:
        class AutoinstallCustomDataWorker(QThread):
            api: "PortProtonAPI"
            script_path: str
            game_data: dict

            def run(self):
                self.api.write_autoinstall_custom_data(self.script_path, self.game_data)

        worker = AutoinstallCustomDataWorker()
        worker.api = self
        worker.script_path = script_path
        worker.game_data = game_data
        worker.start()
        return worker

    def _create_autoinstall_game_tuple(self, game: dict, lang_code: str) -> tuple | None:
        game_id = game.get("id")
        if not isinstance(game_id, int):
            return None

        display_name = self._get_autoinstall_field(game, "name", lang_code)
        if not display_name:
            return None

        ppai_url = game.get("ppai_url")
        if not isinstance(ppai_url, str):
            return None

        description = self._get_autoinstall_field(game, "description", lang_code)
        compact_icon = game.get("icon_compact_url") or ""
        full_icon = game.get("icon_full_url") or ""
        exe_name = f"game_{game_id}"

        return (
            display_name, description, full_icon, "",
            "", f"autoinstall:{ppai_url}", "Never", "0h 0m", "", "", 0, 0,
            "autoinstall", exe_name, compact_icon, full_icon
        )

    def start_autoinstall_games_load(
        self,
        callback: Callable[[list[tuple]], None],
        force_refresh: bool = False,
    ) -> QThread | None:
        """Start loading auto-install games in a background thread. Returns the thread for management."""
        class AutoinstallWorker(QThread):
            finished = Signal(list)
            api: "PortProtonAPI"
            portproton_location: str | None
            force_refresh: bool

            def run(self):
                if not self.force_refresh:
                    cached_games = self.api._load_autoinstall_cache()
                    if cached_games is not None:
                        self.finished.emit(cached_games)
                        return

                games = []
                try:
                    session = get_requests_session()
                    response = session.get(AUTOINSTALL_API_URL, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                except (ValueError, requests.RequestException) as e:
                    logger.warning("Failed to load autoinstall API: %s", e)
                    if self.force_refresh:
                        cached_games = self.api._load_autoinstall_cache()
                        if cached_games is not None:
                            self.finished.emit(cached_games)
                            return
                    self.finished.emit(games)
                    return

                api_games = data.get("games", []) if isinstance(data, dict) else []
                if not isinstance(api_games, list):
                    logger.warning("Invalid autoinstall API response")
                    if self.force_refresh:
                        cached_games = self.api._load_autoinstall_cache()
                        if cached_games is not None:
                            self.finished.emit(cached_games)
                            return
                    self.finished.emit(games)
                    return

                lang_code = self.api._get_autoinstall_lang_code()
                for game in api_games:
                    if not isinstance(game, dict):
                        continue
                    game_tuple = self.api._create_autoinstall_game_tuple(game, lang_code)
                    if game_tuple is not None:
                        games.append(game_tuple)

                self.api._save_autoinstall_cache(games)
                self.api._autoinstall_cache = games
                self.finished.emit(games)

        worker = AutoinstallWorker()
        worker.api = self
        worker.portproton_location = self.portproton_location
        worker.force_refresh = force_refresh
        worker.finished.connect(lambda games: callback(games))
        worker.start()
        logger.info("Started background load of autoinstall games")
        return worker

    def get_ppdb_url(self, game_name: str, exe_name: str) -> str:
        """Get the PPDB URL for a given game.

        Makes an API call to linux-gaming.ru to look up the game by exe name.
        If the returned name matches the game name, returns the direct URL.
        Otherwise returns a search URL to avoid false positives (e.g., launcher.exe matches many games).

        Args:
            game_name: Display name of the game
            exe_name: Executable name (with or without .exe extension)

        Returns:
            Full URL to the PPDB page or search page
        """
        base_url = "https://linux-gaming.ru"

        # Ensure exe_name has .exe extension
        if not exe_name.lower().endswith(".exe"):
            exe_name = f"{exe_name}.exe"

        api_url = f"{base_url}/api/lookup/exe/{urllib.parse.quote(exe_name)}"

        try:
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                api_name = data.get("name", "")
                api_url_result = data.get("url", "")

                # Compare normalized names to avoid false positives
                if api_name and api_url_result:
                    normalized_game = normalize_name(game_name)
                    normalized_api = normalize_name(api_name)

                    if normalized_game == normalized_api:
                        logger.debug("PPDB exact match for %s: %s", game_name, api_url_result)
                        return api_url_result

                    logger.debug(
                        "PPDB name mismatch for %s (exe: %s): API returned '%s', redirecting to search",
                        game_name, exe_name, api_name
                    )
        except requests.RequestException as e:
            logger.debug("PPDB API request failed for %s: %s", exe_name, e)
        except (ValueError, KeyError) as e:
            logger.debug("PPDB API response parsing failed for %s: %s", exe_name, e)

        # Fallback to search URL
        encoded_name = urllib.parse.quote(game_name)
        return f"{base_url}/browse?search={encoded_name}"

    def open_ppdb_page(self, game_name: str, exec_line: str) -> None:
        """Open the PPDB page for a game in the default browser.

        Args:
            game_name: Display name of the game
            exec_line: Exec line from which to extract the exe name
        """
        exe_name = extract_exe_name(exec_line)
        url = self.get_ppdb_url(game_name, exe_name)
        QDesktopServices.openUrl(QUrl(url))

    def download_ppdb_from_url(self, download_url: str) -> bool:
        """Download PPDB file from the given URL and place it next to the selected .exe file.

        Args:
            download_url: The full URL to download the PPDB file from

        Returns:
            True if download was successful, False otherwise
        """
        try:
            # Get the .exe file path directly from FileExplorer
            exe_path = self.ask_user_for_exe_location()
            if not exe_path:
                logger.error("User did not provide .exe file location")
                return False

            # Determine the destination directory for the PPDB file (next to the .exe file)
            exe_dir = os.path.dirname(exe_path)

            # Generate the PPDB filename based on the .exe filename
            exe_basename = os.path.basename(exe_path)
            if exe_basename.lower().endswith('.exe'):
                ppdb_filename = f"{os.path.splitext(exe_basename)[0]}.ppdb"
            else:
                ppdb_filename = f"{exe_basename}.ppdb"

            destination_path = os.path.join(exe_dir, ppdb_filename)

            logger.info(f"Downloading PPDB from {download_url} to {destination_path}")

            # Use the existing downloader synchronously
            try:
                # Download to a temporary file first
                temp_path = destination_path + ".tmp"
                response = requests.get(download_url, timeout=30)
                if response.status_code == 200:
                    with open(temp_path, 'wb') as f:
                        f.write(response.content)

                    # Move the file to its final location
                    shutil.move(temp_path, destination_path)
                    logger.info(f"Successfully downloaded PPDB to {destination_path}")

                    return True
                else:
                    logger.error(f"Failed to download PPDB: HTTP {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"Error during download: {e}")
                # Clean up temp file if it exists
                if os.path.exists(destination_path + ".tmp"):
                    os.remove(destination_path + ".tmp")
                return False

        except requests.RequestException as e:
            logger.error(f"Request error downloading PPDB: {e}")
            return False
        except Exception as e:
            logger.error(f"Error downloading PPDB: {e}")
            return False


    def ask_user_for_exe_location(self) -> str | None:
        """Ask the user for the location of the .exe file.

        Returns:
            Path to the .exe file if provided by user, None otherwise
        """
        # Check if we're running in GUI mode
        app = QApplication.instance()
        if app is None:
            logger.info("No GUI application instance available for FileExplorer")
            return None

        result_queue = queue.Queue()
        parent, bootstrap_input_manager = _create_bootstrap_file_explorer_parent()

        def on_file_selected(file_path):
            result_queue.put(file_path)

        file_explorer = FileExplorer(
            parent=parent,
            file_filter=".exe",
            initial_path=os.path.expanduser("~")
        )
        file_explorer.setWindowTitle(_("Select file for PPDB download"))
        file_explorer.file_signal.file_selected.connect(on_file_selected)

        try:
            file_explorer.exec()
        finally:
            if bootstrap_input_manager:
                bootstrap_input_manager.cleanup()
            if parent and bootstrap_input_manager:
                parent.deleteLater()

        try:
            selected_file = result_queue.get(timeout=0.1)  # Small timeout to get result
            if selected_file and os.path.exists(selected_file) and selected_file.lower().endswith('.exe'):
                logger.info(f"User selected .exe file: {selected_file}")
                return selected_file
            logger.info("No valid .exe file selected by user")
            return None
        except queue.Empty:
            logger.info("No file selected in FileExplorer")
            return None




def get_user_conf_setting(variable_name):
    """
    Gets the value of a specific variable from user.conf.

    Args:
        variable_name: Name of the variable to get

    Returns:
        Value of the variable or None if not set
    """

    start_cmd = get_portproton_start_command()
    if not start_cmd:
        logger.error("Could not determine PortProton start command")
        return None
    try:
        result = subprocess.run(
            start_cmd + ["cli", "--get-user-conf", variable_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Failed to get user.conf value for %s: %s", variable_name, e)
        return None

    if result.returncode != 0:
        logger.debug("PortProton CLI returned %s for --get-user-conf %s", result.returncode, variable_name)
        return None

    clean_lines = []
    for line in result.stdout.splitlines():
        stripped_line = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line).strip()
        if not stripped_line:
            continue
        if any(char in stripped_line for char in "█░▄▀╔╗╚╝║"):
            continue
        if re.match(r'^\[?[0-9;]*m?\s*(Info|Warning|Error|OK):', stripped_line):
            continue
        if "must use subscript when assigning associative array" in stripped_line:
            continue
        if " '" in stripped_line and stripped_line.endswith("'"):
            line_start, quoted_path = stripped_line.rsplit(" '", 1)
            if line_start and quoted_path.startswith("/"):
                continue
        clean_lines.append(stripped_line)

    if not clean_lines:
        return None

    return clean_lines[-1]


def set_user_conf_setting(variable_name, value):
    """
    Sets or deletes a specific variable in user.conf via PortProton CLI.

    Args:
        variable_name: Name of the variable to set or delete
        value: Value to set, or None/empty to delete the variable
    """
    start_cmd = get_portproton_start_command()
    if not start_cmd:
        logger.error("Could not determine PortProton start command")
        return False

    if value is None or value == "":
        cli_args = ["cli", "--delete-user-conf", variable_name]
    else:
        cli_args = ["cli", "--set-user-conf", variable_name, str(value)]

    try:
        result = subprocess.run(
            start_cmd + cli_args,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Failed to update user.conf value for %s: %s", variable_name, e)
        return False

    if result.returncode != 0:
        logger.warning(
            "PortProton CLI failed for %s (code %s): %s",
            variable_name,
            result.returncode,
            result.stderr.strip(),
        )
        return False

    return True
