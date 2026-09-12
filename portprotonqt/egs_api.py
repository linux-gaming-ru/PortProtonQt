"""Epic Games Store integration through Legendary."""

import hashlib
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import orjson
import requests

from portprotonqt.localization import get_store_content_languages
from portprotonqt.logger import get_logger

logger = get_logger(__name__)
EGS_LOGIN_URL = "https://legendary.gl/epiclogin"
LEGENDARY_RELEASE_URL = (
    "https://api.github.com/repos/Heroic-Games-Launcher/legendary/releases/latest"
)
LEGENDARY_TIMEOUT = 120
EGS_METADATA_WORKERS = 4
EGS_METADATA_TIMEOUT = 15
EGS_DESCRIPTION_CACHE_VERSION = 2
LEGENDARY_UPDATE_INTERVAL = 30 * 24 * 60 * 60
EGS_API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 EpicGamesLauncher"
)


class EGSAPI:
    """Provide EGS authentication, library and installation helpers."""

    def __init__(self) -> None:
        data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))
        self.data_dir = data_home / "PortProtonQt" / "launcher" / "egs"
        self.bin_dir = data_home / "PortProtonQt" / "bin"
        # Remove after the legacy launcher storage migration period.
        legacy_dir = data_home / "PortProtonQt" / "egs"
        if legacy_dir.exists() and not self.data_dir.exists():
            self.data_dir.parent.mkdir(parents=True, exist_ok=True)
            legacy_dir.rename(self.data_dir)
        legacy_bin = self.data_dir / "bin"
        if legacy_bin.is_dir():
            self.bin_dir.mkdir(parents=True, exist_ok=True)
            for legacy_binary in legacy_bin.iterdir():
                target = self.bin_dir / legacy_binary.name
                if not target.exists():
                    legacy_binary.rename(target)
            if not any(legacy_bin.iterdir()):
                legacy_bin.rmdir()
        self.config_dir = self.data_dir / "legendary"
        self.user_path = self.config_dir / "user.json"
        self.library_path = self.data_dir / "library.json"
        self.sizes_path = self.data_dir / "sizes.json"
        self.version_path = self.bin_dir / "legendary.version"
        self.games_dir = Path.home() / "Games"

    def get_legendary_path(self) -> str | None:
        """Return an available Legendary executable."""
        bundled = self.bin_dir / "legendary"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
        return shutil.which("legendary")

    def ensure_legendary(self) -> str:
        """Download the current official Heroic Legendary binary if needed."""
        existing = self.get_legendary_path()
        if existing:
            return existing
        asset, release_tag = self._get_latest_legendary_release()
        return self._download_legendary(asset, release_tag)

    def update_legendary(self) -> str:
        """Update the bundled Legendary binary when a newer release exists."""
        bundled = self.bin_dir / "legendary"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            try:
                last_check = self.version_path.stat().st_mtime
            except OSError:
                last_check = 0
            if time.time() - last_check < LEGENDARY_UPDATE_INTERVAL:
                return str(bundled)
        asset, release_tag = self._get_latest_legendary_release()
        if (
            bundled.is_file()
            and self._get_legendary_release_tag() == release_tag
        ):
            self.version_path.touch()
            return str(bundled)
        return self._download_legendary(asset, release_tag)

    def _get_latest_legendary_release(self) -> tuple[dict, str]:
        """Return the matching Legendary asset and release tag."""
        architecture = {"x86_64": "x86_64", "aarch64": "arm64"}.get(
            platform.machine()
        )
        if not architecture:
            raise OSError(f"Unsupported Legendary architecture: {platform.machine()}")
        response = requests.get(LEGENDARY_RELEASE_URL, timeout=15)
        response.raise_for_status()
        release = response.json()
        asset_name = f"legendary_linux_{architecture}"
        asset = next(
            (item for item in release.get("assets", []) if item.get("name") == asset_name),
            None,
        )
        if not asset:
            raise OSError(f"Legendary release asset not found: {asset_name}")
        release_tag = str(release.get("tag_name", ""))
        if not release_tag:
            raise OSError("Legendary release tag not found")
        return asset, release_tag

    def _get_legendary_release_tag(self) -> str:
        try:
            return self.version_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _download_legendary(self, asset: dict, release_tag: str) -> str:
        target = self.bin_dir / "legendary"
        temporary = target.with_suffix(".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        try:
            with requests.get(asset["browser_download_url"], stream=True, timeout=30) as response:
                response.raise_for_status()
                with open(temporary, "wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
                            digest.update(chunk)
            expected = str(asset.get("digest", "")).removeprefix("sha256:")
            if not expected or digest.hexdigest() != expected:
                raise OSError("Legendary checksum verification failed")
            temporary.chmod(0o755)
            temporary.replace(target)
            self.version_path.write_text(release_tag, encoding="utf-8")
            return str(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def build_command(self, arguments: list[str]) -> list[str]:
        """Build a Legendary command using private configuration paths."""
        executable = self.get_legendary_path()
        if not executable:
            raise FileNotFoundError("Legendary executable not found")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)
        command_arguments = list(arguments)
        if "-y" in command_arguments:
            command_arguments.remove("-y")
            command_arguments.insert(0, "-y")
        return [executable, *command_arguments]

    def get_environment(self) -> dict[str, str]:
        """Return the environment required by Legendary."""
        environment = os.environ.copy()
        environment["LEGENDARY_CONFIG_PATH"] = str(self.config_dir)
        return environment

    def authenticate(self, code: str) -> tuple[bool, str]:
        """Authenticate an Epic account with an authorization code."""
        self.ensure_legendary()
        result = subprocess.run(
            self.build_command(["auth", "--code", code]),
            env=self.get_environment(), capture_output=True, check=False,
            timeout=LEGENDARY_TIMEOUT,
        )
        if result.returncode == 0 and self.user_path.is_file():
            self.user_path.chmod(0o600)
            return True, ""
        error = result.stderr.decode(errors="replace").strip()
        logger.error("Legendary authentication failed: %s", error)
        return False, error or f"Legendary exited with code {result.returncode}"

    @staticmethod
    def extract_auth_code(text: str) -> str:
        """Extract an Epic authorization code from copied text or JSON."""
        value = text.strip()
        try:
            data = orjson.loads(value)
        except orjson.JSONDecodeError:
            return value if "://" not in value else ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("authorizationCode", "")).strip()

    def logout(self) -> bool:
        """Remove the Epic login and cached library."""
        try:
            if self.get_legendary_path() and self.user_path.is_file():
                subprocess.run(
                    self.build_command(["auth", "--delete"]),
                    env=self.get_environment(), capture_output=True, check=False,
                    timeout=LEGENDARY_TIMEOUT,
                )
            self.user_path.unlink(missing_ok=True)
            self.library_path.unlink(missing_ok=True)
            return True
        except (OSError, subprocess.SubprocessError) as error:
            logger.error("Failed to disconnect Epic account: %s", error)
            return False

    def get_account_name(self) -> str:
        """Return the Epic display name from Legendary state."""
        user = self._load_json(self.user_path, {})
        return str(user.get("displayName", "")) if isinstance(user, dict) else ""

    def refresh_library(
        self, progress_callback: Callable[[int, int], None] | None = None
    ) -> list[dict]:
        """Refresh and cache the Epic library through Legendary."""
        self.update_legendary()
        result = subprocess.run(
            self.build_command(["list", "--json", "--third-party"]),
            env=self.get_environment(), capture_output=True, check=False,
            timeout=LEGENDARY_TIMEOUT,
        )
        if result.returncode != 0:
            error = result.stderr.decode(errors="replace").strip()
            raise OSError(error or "Failed to refresh Epic library")
        raw_games = orjson.loads(result.stdout)
        if not isinstance(raw_games, list):
            raise OSError("Legendary returned an invalid Epic library")
        games = []
        for game in raw_games:
            metadata = game.get("metadata", {})
            release_info = metadata.get("releaseInfo", [])
            mobile_only = bool(release_info) and all(
                info.get("platform")
                and all(platform in {"Android", "iOS"}
                        for platform in info["platform"])
                for info in release_info
            )
            if not mobile_only:
                games.append(self._normalize_game(game))
        games = [game for game in games if game.get("app_id")]
        self._enrich_descriptions(games, progress_callback)
        self._save_json(self.library_path, games)
        return games

    def load_library(self) -> list[dict]:
        """Load the cached Epic library."""
        data = self._load_json(self.library_path, [])
        return data if isinstance(data, list) else []

    def clear_library_cache(self) -> None:
        """Remove cached Epic library metadata."""
        try:
            self.library_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Failed to clear Epic library cache: %s", error)

    def load_installed(self) -> dict[str, dict]:
        """Load Legendary installed game records."""
        data = self._load_json(self.config_dir / "installed.json", {})
        return data if isinstance(data, dict) else {}

    def is_game_installed(self, app_id: str) -> bool:
        """Return whether Legendary records a usable installation."""
        return self.get_launch_target(app_id) is not None

    @staticmethod
    def is_eos_overlay_enabled(prefix_path: Path) -> bool:
        """Return whether the EOS overlay is enabled in a Wine prefix."""
        try:
            registry = (prefix_path / "user.reg").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return False
        for section in registry.casefold().split("\n["):
            if section.startswith(r"software\\epic games\\eos]"):
                if '"overlaypath"=' in section:
                    return True
        return False

    def get_launch_target(self, app_id: str) -> str | None:
        """Return the installed game's Windows executable."""
        installed = self.load_installed().get(app_id, {})
        install_path = Path(str(installed.get("install_path", "")))
        executable = str(installed.get("executable", "")).replace("\\", "/")
        target = install_path.joinpath(*executable.split("/"))
        return str(target) if executable and target.is_file() else None

    def get_cached_download_sizes(self, app_id: str) -> tuple[int, int] | None:
        """Return cached EGS download and disk sizes."""
        cache = self._load_json(self.sizes_path, {})
        value = cache.get(app_id) if isinstance(cache, dict) else None
        if not isinstance(value, list) or len(value) != 2:
            return None
        sizes = int(value[0]), int(value[1])
        return None if sizes[0] > 0 and sizes[1] <= 0 else sizes

    def save_download_sizes(self, app_id: str, sizes: tuple[int, int]) -> None:
        """Cache EGS download and disk sizes."""
        cache = self._load_json(self.sizes_path, {})
        if not isinstance(cache, dict):
            cache = {}
        cache[app_id] = list(sizes)
        self._save_json(self.sizes_path, cache)

    @staticmethod
    def parse_download_sizes(output: bytes) -> tuple[int, int]:
        """Extract download and install sizes from Legendary JSON."""
        data = orjson.loads(output)
        values: dict[str, int] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"download_size", "install_size", "disk_size"}:
                        try:
                            values[key] = max(values.get(key, 0), int(item))
                        except (TypeError, ValueError):
                            continue
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(data)
        install_size = values.get("install_size") or values.get("disk_size", 0)
        return values.get("download_size", 0), install_size

    def _enrich_descriptions(
        self, games: list[dict],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        cached = {str(game.get("app_id")): game for game in self.load_library()}
        pending = []
        completed = 0
        total = len(games)
        preferred_locale = get_store_content_languages()[0]
        for game in games:
            old_game = cached.get(game["app_id"], {})
            old_description = str(old_game.get("description", ""))
            if (
                old_description
                and old_description != game["title"]
                and old_game.get("description_preference") == preferred_locale
                and old_game.get("description_cache_version")
                == EGS_DESCRIPTION_CACHE_VERSION
            ):
                game["description"] = old_description
                game["description_locale"] = str(old_game.get("description_locale", ""))
                game["description_preference"] = preferred_locale
                game["description_cache_version"] = EGS_DESCRIPTION_CACHE_VERSION
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
            else:
                pending.append(game)
        if not pending:
            return
        worker_count = min(EGS_METADATA_WORKERS, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            descriptions = executor.map(self._get_store_description, pending)
            for game, result in zip(pending, descriptions, strict=True):
                description, description_locale = result
                if description:
                    game["description"] = description
                    game["description_locale"] = description_locale
                    game["description_preference"] = preferred_locale
                    game["description_cache_version"] = EGS_DESCRIPTION_CACHE_VERSION
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

    def _get_store_description(self, game: dict) -> tuple[str, str]:
        slug = self._get_product_slug(str(game.get("namespace", "")), game["title"])
        for language in get_store_content_languages():
            try:
                response = requests.get(
                    "https://store-content.ak.epicgames.com/api/"
                    f"{language}/content/products/{slug}",
                    headers={"User-Agent": EGS_API_USER_AGENT},
                    timeout=EGS_METADATA_TIMEOUT,
                )
                if response.status_code == requests.codes.not_found:
                    continue
                response.raise_for_status()
                description = self._parse_store_description(response.json())
                if description:
                    return description, language
            except requests.RequestException as error:
                logger.debug(
                    "Epic description unavailable for %s: %s", game["app_id"], error
                )
                return "", ""
        return "", ""

    @staticmethod
    def _parse_store_description(data: Any) -> str:
        if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
            return ""
        page = next(
            (item for item in data["pages"]
             if isinstance(item, dict) and item.get("type") == "productHome"),
            {},
        )
        about = page.get("data", {}).get("about", {})
        short_description = str(about.get("shortDescription") or "").strip()
        if short_description:
            return short_description
        description = str(about.get("description") or "").strip()
        return description.split("\n\n", 1)[0].strip()

    def _get_product_slug(self, namespace: str, title: str) -> str:
        fallback = "-".join("".join(
            character if character.isascii() and character.isalnum() else " "
            for character in title.lower()
        ).split())
        if not namespace:
            return fallback
        query = {
            "query": "query ProductSlug($namespace: String!) { Catalog { "
                     "catalogNs(namespace: $namespace) { mappings(pageType: "
                     "\"productHome\") { pageSlug pageType } } } }",
            "variables": {"namespace": namespace},
        }
        try:
            response = requests.post(
                "https://launcher.store.epicgames.com/graphql",
                json=query,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": EGS_API_USER_AGENT,
                },
                timeout=EGS_METADATA_TIMEOUT,
            )
            response.raise_for_status()
            mappings = response.json()["data"]["Catalog"]["catalogNs"]["mappings"]
            return str(mappings[0].get("pageSlug") or fallback) if mappings else fallback
        except (KeyError, IndexError, TypeError, requests.RequestException) as error:
            logger.debug("Epic product slug unavailable for %s: %s", namespace, error)
            return fallback

    @staticmethod
    def _normalize_game(game: dict) -> dict:
        metadata = game.get("metadata", {})
        images = metadata.get("keyImages", []) if isinstance(metadata, dict) else []
        cover = next(
            (str(image.get("url", "")) for image in images
             if image.get("type") in ("DieselGameBoxTall", "OfferImageTall")),
            "",
        )
        return {
            "app_id": str(game.get("app_name") or game.get("appName") or ""),
            "title": str(game.get("app_title") or metadata.get("title") or ""),
            "description": str(metadata.get("description", "")),
            "cover": cover,
            "namespace": str(metadata.get("namespace", "")),
            "description_locale": "",
            "description_preference": "",
            "description_cache_version": 0,
        }

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        try:
            return orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return default

    @staticmethod
    def _save_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
