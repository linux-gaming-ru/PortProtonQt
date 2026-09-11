"""GOG authentication, library and gogdl process helpers."""

import hashlib
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import orjson
import requests

from portprotonqt.localization import get_metadata_language
from portprotonqt.logger import get_logger

logger = get_logger(__name__)
GOG_LOGIN_URL = (
    "https://auth.gog.com/auth?client_id=46899977096215655&"
    "redirect_uri=https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient&"
    "response_type=code&layout=galaxy"
)
GOGDL_RELEASE_URL = "https://api.github.com/repos/Heroic-Games-Launcher/heroic-gogdl/releases/latest"
GOGDL_AUTH_TIMEOUT = 60
GOGDL_UPDATE_INTERVAL = 30 * 24 * 60 * 60
GOG_USER_TIMEOUT = 15
GOG_METADATA_WORKERS = 4
GOG_SETUP_MARKER_VERSION = 1
GOG_SETUP_TIMEOUT = 600
GOG_PRODUCT_LOCALES = {
    "bg": "bg-BG", "cs": "cs-CZ", "da": "da-DK", "de": "de-DE",
    "el": "el-GR", "en": "en-US", "es": "es-ES", "fi": "fi-FI",
    "fr": "fr-FR", "hu": "hu-HU", "it": "it-IT", "ja": "ja-JP",
    "ko": "ko-KR", "nl": "nl-NL", "no": "no-NO", "pl": "pl-PL",
    "pt": "pt-BR", "ro": "ro-RO", "ru": "ru-RU", "sv": "sv-SE",
    "th": "th-TH", "tr": "tr-TR", "uk": "uk-UA", "zh": "zh-Hans",
    "zh_hant": "zh-Hant",
}


class GOGAPI:
    """Provide the local GOG backend used by the Qt UI."""

    def __init__(self) -> None:
        data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))
        self.data_dir = data_home / "PortProtonQt" / "launcher" / "gog"
        self.bin_dir = data_home / "PortProtonQt" / "bin"
        legacy_dir = data_home / "PortProtonQt" / "gog"
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
        self.auth_path = self.data_dir / "auth.json"
        self.account_path = self.data_dir / "account.json"
        self.config_dir = self.data_dir / "gogdl"
        self.gogdl_version_path = self.bin_dir / "gogdl.version"
        self.library_path = self.data_dir / "library.json"
        self.installed_path = self.data_dir / "installed.json"
        self.sizes_path = self.data_dir / "sizes.json"
        self.games_dir = Path.home() / "Games"

    def get_gogdl_path(self) -> str | None:
        """Return an available gogdl executable."""
        bundled = self.bin_dir / "gogdl"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
        return shutil.which("gogdl")

    def build_command(self, arguments: list[str]) -> list[str]:
        """Build a gogdl command with private configuration paths."""
        gogdl = self.get_gogdl_path()
        if not gogdl:
            raise FileNotFoundError("gogdl executable not found")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        return [gogdl, "--auth-config-path", str(self.auth_path), *arguments]

    def ensure_gogdl(self) -> str:
        """Download and verify the latest official Heroic gogdl binary."""
        existing = self.get_gogdl_path()
        if existing:
            return existing
        asset, release_tag = self._get_latest_gogdl_release()
        return self._install_gogdl_release(asset, release_tag)

    def update_gogdl(self) -> str:
        """Update the bundled gogdl binary to the latest official release."""
        bundled = self.bin_dir / "gogdl"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            try:
                last_check = self.gogdl_version_path.stat().st_mtime
            except OSError:
                last_check = 0
            if time.time() - last_check < GOGDL_UPDATE_INTERVAL:
                return str(bundled)
            self.gogdl_version_path.touch()
        asset, release_tag = self._get_latest_gogdl_release()
        if (
            bundled.is_file()
            and os.access(bundled, os.X_OK)
            and self._get_gogdl_release_tag() == release_tag
        ):
            return str(bundled)
        return self._install_gogdl_release(asset, release_tag)

    def _get_latest_gogdl_release(self) -> tuple[dict, str]:
        """Return the matching asset and tag from the latest gogdl release."""
        architecture = {"x86_64": "x86_64", "aarch64": "arm64"}.get(platform.machine())
        if not architecture:
            raise OSError(f"Unsupported gogdl architecture: {platform.machine()}")
        response = requests.get(GOGDL_RELEASE_URL, timeout=15)
        response.raise_for_status()
        release = response.json()
        asset_name = f"gogdl_linux_{architecture}"
        asset = next(
            (item for item in release.get("assets", []) if item.get("name") == asset_name),
            None,
        )
        if not asset:
            raise OSError(f"gogdl release asset not found: {asset_name}")
        release_tag = str(release.get("tag_name", ""))
        if not release_tag:
            raise OSError("gogdl release tag not found")
        return asset, release_tag

    def _get_gogdl_release_tag(self) -> str:
        try:
            return self.gogdl_version_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _install_gogdl_release(self, asset: dict, release_tag: str) -> str:
        path = self._download_gogdl_asset(asset)
        self.gogdl_version_path.write_text(release_tag, encoding="utf-8")
        return path

    def _download_gogdl_asset(self, asset: dict) -> str:
        target = self.bin_dir / "gogdl"
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
                raise OSError("gogdl checksum verification failed")
            temporary.chmod(0o755)
            temporary.replace(target)
            return str(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def get_environment(self) -> dict[str, str]:
        """Return the environment required by gogdl."""
        environment = os.environ.copy()
        environment["GOGDL_CONFIG_PATH"] = str(self.config_dir)
        return environment

    def authenticate(self, code: str) -> tuple[bool, str]:
        """Exchange an OAuth code through gogdl."""
        self.ensure_gogdl()
        result = subprocess.run(
            self.build_command(["auth", "--code", code]),
            env=self.get_environment(), capture_output=True, check=False,
            timeout=GOGDL_AUTH_TIMEOUT,
        )
        if result.returncode != 0:
            error = result.stderr.decode(errors="replace").strip()
            logger.error("gogdl authentication failed: %s", error)
            return False, error or f"gogdl exited with code {result.returncode}"
        try:
            data = orjson.loads(result.stdout)
        except orjson.JSONDecodeError:
            return False, "gogdl returned an invalid authentication response"
        if not isinstance(data, dict) or data.get("error"):
            return False, "GOG rejected the authorization code"
        self._cache_account(data)
        if self.auth_path.is_file():
            self.auth_path.chmod(0o600)
        return True, ""

    def get_credentials(self) -> dict:
        """Return refreshed GOG credentials through gogdl."""
        try:
            self.ensure_gogdl()
            result = subprocess.run(
                self.build_command(["auth"]), env=self.get_environment(),
                capture_output=True, check=False,
            )
            data = orjson.loads(result.stdout) if result.returncode == 0 else {}
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, orjson.JSONDecodeError):
            return {}

    def is_authenticated(self) -> bool:
        """Return whether gogdl provides usable account credentials."""
        credentials = self.get_credentials()
        return bool(credentials.get("access_token") and credentials.get("user_id"))

    def get_account_name(self) -> str:
        """Return cached GOG account name or user ID."""
        account = self._load_json(self.account_path, {})
        if isinstance(account, dict) and account.get("username"):
            return str(account["username"])
        credentials = self._load_json(self.auth_path, {})
        if isinstance(credentials, dict) and credentials.get("user_id"):
            return str(credentials["user_id"])
        return ""

    def refresh_account_name(self) -> str:
        """Fetch and cache the current GOG account name."""
        return self._cache_account(self.get_credentials())

    def _cache_account(self, credentials: dict) -> str:
        """Fetch GOG account data for credentials and return its username."""
        user_id = credentials.get("user_id")
        access_token = credentials.get("access_token")
        if not user_id or not access_token:
            return ""
        try:
            response = requests.get(
                f"https://users.gog.com/users/{user_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=GOG_USER_TIMEOUT,
            )
            response.raise_for_status()
            account = response.json()
        except requests.RequestException as error:
            logger.warning("Failed to load GOG account name: %s", error)
            return ""
        if not isinstance(account, dict) or not account.get("username"):
            return ""
        self._save_json(self.account_path, account)
        return str(account["username"])

    def logout(self) -> bool:
        """Remove local GOG credentials and account library cache."""
        try:
            self.auth_path.unlink(missing_ok=True)
        except OSError as error:
            logger.error("Failed to remove GOG credentials: %s", error)
            return False
        try:
            self.account_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Failed to remove cached GOG account name: %s", error)
        self.clear_library_cache()
        logger.info("GOG account disconnected")
        return True

    def refresh_library(
        self, progress_callback: Callable[[int, int], None] | None = None
    ) -> list[dict]:
        """Fetch and cache the user's GOG library."""
        credentials = self.get_credentials()
        token = credentials.get("access_token")
        user_id = credentials.get("user_id")
        if not token or not user_id:
            return []
        entries = self._get_library_entries(str(user_id), str(token))
        gog_entries = [entry for entry in entries if entry.get("platform_id") == "gog"]
        games = self._get_games_parallel(gog_entries, str(token), progress_callback)
        self._save_json(self.library_path, games)
        return games

    def _get_games_parallel(
        self, entries: list[dict], token: str,
        progress_callback: Callable[[int, int], None] | None,
    ) -> list[dict]:
        cached = {str(game.get("app_id")): game for game in self.load_library()}
        games = []
        worker_count = min(GOG_METADATA_WORKERS, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(self._get_game, entry, token): entry for entry in entries}
            for completed, future in enumerate(as_completed(futures), 1):
                entry = futures[future]
                app_id = str(entry.get("external_id", ""))
                try:
                    game = future.result()
                except requests.RequestException as error:
                    logger.warning("Failed to load GOG metadata for %s: %s", app_id, error)
                    game = cached.get(app_id, {})
                if game:
                    game.setdefault("steam_appid", "")
                    games.append(game)
                if progress_callback:
                    progress_callback(completed, len(entries))
        return games

    def load_library(self) -> list[dict]:
        """Load the cached GOG library."""
        data = self._load_json(self.library_path, [])
        return data if isinstance(data, list) else []

    def clear_library_cache(self) -> None:
        """Remove cached GOG covers and descriptions."""
        try:
            self.library_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Failed to clear GOG library cache: %s", error)

    def load_installed(self) -> dict[str, dict]:
        """Load installed GOG game records."""
        data = self._load_json(self.installed_path, {})
        return data if isinstance(data, dict) else {}

    def save_installed_game(self, app_id: str, game: dict) -> None:
        """Persist one installed GOG game record."""
        installed = self.load_installed()
        installed[app_id] = game
        self._save_json(self.installed_path, installed)

    def remove_installed_game(self, app_id: str) -> None:
        """Remove one installed GOG game record."""
        installed = self.load_installed()
        installed.pop(app_id, None)
        self._save_json(self.installed_path, installed)

    def get_cached_download_sizes(self, app_id: str) -> tuple[int, int] | None:
        """Return cached download and disk sizes for a game."""
        cache = self._load_json(self.sizes_path, {})
        if not isinstance(cache, dict):
            return None
        cached = cache.get(app_id)
        if not isinstance(cached, list) or len(cached) != 2:
            return None
        return int(cached[0]), int(cached[1])

    def save_download_sizes(self, app_id: str, sizes: tuple[int, int]) -> None:
        """Cache download and disk sizes for a game."""
        cached = self._load_json(self.sizes_path, {})
        if not isinstance(cached, dict):
            cached = {}
        cached[app_id] = list(sizes)
        self._save_json(self.sizes_path, cached)

    def is_game_installed(
        self, app_id: str, installed_games: dict[str, dict] | None = None
    ) -> bool:
        """Return whether a complete gogdl installation is available."""
        return self.get_installed_path(app_id, installed_games) is not None

    def get_installed_path(
        self, app_id: str, installed_games: dict[str, dict] | None = None
    ) -> Path | None:
        """Return a recorded or discoverable gogdl installation path."""
        records = installed_games if installed_games is not None else self.load_installed()
        installed = records.get(app_id, {})
        install_path = Path(str(installed.get("install_path", "")))
        if (install_path / f"goggame-{app_id}.info").is_file():
            return install_path
        return self.find_install_path(app_id, self.games_dir)

    def get_install_path(self, app_id: str, title: str) -> Path:
        """Return the default parent directory for GOG installations."""
        return self.games_dir

    def find_install_path(self, app_id: str, parent: Path) -> Path | None:
        """Find the directory created by gogdl for an installed game."""
        metadata_name = f"goggame-{app_id}.info"
        if (parent / metadata_name).is_file():
            return parent
        try:
            return next(
                (path.parent for path in parent.glob(f"*/{metadata_name}")),
                None,
            )
        except OSError as error:
            logger.warning("Failed to inspect GOG installation path %s: %s", parent, error)
            return None

    def get_launch_target(self, app_id: str) -> str | None:
        """Return the primary executable from gogdl installation metadata."""
        primary, install_path = self._get_primary_task(app_id)
        if primary is None or install_path is None:
            return None
        target = install_path
        parts = str(primary.get("path", "")).replace("\\", "/").split("/")
        for part in parts:
            exact_path = target / part
            if exact_path.exists():
                target = exact_path
                continue
            try:
                target = next(
                    child for child in target.iterdir()
                    if child.name.casefold() == part.casefold()
                )
            except (OSError, StopIteration):
                return None
        return str(target) if target.is_file() else None

    def ensure_launch_parameters(self, app_id: str) -> None:
        """Add GOG task arguments to the executable PPDB when absent."""
        primary, install_path = self._get_primary_task(app_id)
        target = self.get_launch_target(app_id)
        if primary is None or install_path is None or not target:
            return
        arguments = str(primary.get("arguments", "")).replace("\r", " ").replace("\n", " ").strip()
        if not arguments:
            return
        ppdb_path = Path(f"{target}.ppdb")
        try:
            current = ppdb_path.read_text(encoding="utf-8") if ppdb_path.exists() else ""
            base_value = arguments.replace('"', "").replace("\\", "/")
            safe_value = base_value.replace("$", "\\$").replace("`", "\\`")
            launch_line = f'export LAUNCH_PARAMETERS="{safe_value}"'
            lines = current.splitlines()
            existing = next(
                (line for line in lines if line.startswith("export LAUNCH_PARAMETERS=")),
                "",
            )
            if existing:
                value = existing.removeprefix('export LAUNCH_PARAMETERS="').removesuffix('"')
                comparable = re.sub(r"\\+", "/", value.replace('\\"', "").replace('"', ""))
                if comparable != base_value:
                    return
                lines[lines.index(existing)] = launch_line
                ppdb_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return
            separator = "" if not current or current.endswith("\n") else "\n"
            ppdb_path.write_text(
                f"{current}{separator}{launch_line}\n",
                encoding="utf-8",
            )
        except OSError as error:
            logger.warning("Failed to add GOG launch parameters to %s: %s", ppdb_path, error)

    def install_support(
        self, app_id: str, start_command: list[str],
        process_callback: Callable[[subprocess.Popen], None] | None = None,
    ) -> None:
        """Install GOG support instructions through the common ISI redist."""
        manifest = self._load_json(
            self.config_dir / "heroic_gogdl" / "manifests" / app_id, {}
        )
        install_path = self.get_installed_path(app_id)
        if not isinstance(manifest, dict) or not manifest.get("scriptInterpreter"):
            return
        if install_path is None:
            return
        setup_marker = install_path / (
            f".gogsetup-v{GOG_SETUP_MARKER_VERSION}-{app_id}"
        )
        if setup_marker.is_file():
            return
        redist_path = self.data_dir / "redist" / "gog"
        interpreter = redist_path / "__redist" / "ISI" / "scriptinterpreter.exe"
        if not interpreter.is_file():
            result = subprocess.run(
                self.build_command([
                    "redist", "--ids", "ISI", "--path", str(redist_path),
                ]),
                env=self.get_environment(), capture_output=True, check=False,
                timeout=GOG_SETUP_TIMEOUT,
            )
            if result.returncode != 0:
                error = result.stderr.decode(errors="replace").strip()
                raise OSError(error or "Failed to download GOG ISI redist")
        if not interpreter.is_file():
            raise FileNotFoundError(f"GOG script interpreter not found: {interpreter}")
        support_path = self.config_dir / "heroic_gogdl" / "gog-support" / app_id
        setup_path = self.data_dir / "setup" / app_id
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        if setup_path.is_symlink() and setup_path.resolve() != install_path.resolve():
            setup_path.unlink()
        if not setup_path.exists():
            setup_path.symlink_to(install_path, target_is_directory=True)
        if not setup_path.is_symlink():
            raise OSError(f"GOG setup path is not a symbolic link: {setup_path}")
        arguments = self._get_support_arguments(
            app_id, manifest, setup_path, support_path
        )
        target = self.get_launch_target(app_id)
        if not target:
            raise FileNotFoundError(f"GOG launch target not found: {app_id}")
        launch_parameters = " ".join(arguments).replace("$", "\\$").replace("`", "\\`")
        self._write_support_ppdb(interpreter, target, launch_parameters)
        self._run_support_process(
            [*start_command, str(interpreter)], install_path, process_callback
        )
        setup_marker.touch()

    @staticmethod
    def _run_support_process(
        command: list[str], install_path: Path,
        process_callback: Callable[[subprocess.Popen], None] | None,
    ) -> None:
        """Run GOG setup and expose its process for UI cancellation."""
        process = subprocess.Popen(
            command, cwd=install_path, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
        )
        if process_callback:
            process_callback(process)
        try:
            return_code = process.wait(timeout=GOG_SETUP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)

    @staticmethod
    def _write_support_ppdb(
        interpreter: Path, target: str, launch_parameters: str,
    ) -> None:
        """Inherit game settings while replacing support launch commands."""
        target_ppdb = Path(f"{target}.ppdb")
        ppdb_lines = (
            target_ppdb.read_text(encoding="utf-8").splitlines()
            if target_ppdb.is_file() else []
        )
        replaced_keys = (
            "export LAUNCH_PARAMETERS=", "export PW_RUN_AFTER_EXE=",
            "export FILE_SHA256SUM=",
        )
        inherited = [
            line for line in ppdb_lines
            if not line.startswith(replaced_keys)
        ]
        inherited.extend([
            f'export LAUNCH_PARAMETERS="{launch_parameters}"',
        ])
        Path(f"{interpreter}.ppdb").write_text(
            "\n".join(inherited) + "\n",
            encoding="utf-8",
        )

    def needs_support_setup(self, app_id: str) -> bool:
        """Return whether GOG setup instructions still need to run."""
        install_path = self.get_installed_path(app_id)
        if install_path is None:
            return False
        manifest = self._load_json(
            self.config_dir / "heroic_gogdl" / "manifests" / app_id, {}
        )
        marker = install_path / f".gogsetup-v{GOG_SETUP_MARKER_VERSION}-{app_id}"
        return bool(
            isinstance(manifest, dict)
            and manifest.get("scriptInterpreter")
            and not marker.is_file()
        )

    @staticmethod
    def _get_support_arguments(
        app_id: str, manifest: dict, install_path: Path, support_path: Path
    ) -> list[str]:
        product = next(
            (
                item for item in manifest.get("products", [])
                if str(item.get("productId", "")) == app_id
            ),
            {},
        )
        product_id = str(product.get("productId", app_id))
        wine_install_path = "Z:" + str(install_path).replace("/", "\\")
        wine_support_path = "Z:" + str(support_path).replace("/", "\\")
        return [
            "/VERYSILENT", f"/DIR={wine_install_path}", "/Language=English",
            "/LANG=English", f"/ProductId={product_id}", "/galaxyclient",
            f"/buildId={manifest.get('buildId', '')}",
            f"/versionName={manifest.get('versionName', '')}",
            "/lang-code=en-US", f"/supportDir={wine_support_path}",
            "/nodesktopshorctut", "/nodesktopshortcut",
        ]

    def _get_primary_task(self, app_id: str) -> tuple[dict | None, Path | None]:
        """Return the primary GOG launch task and installation path."""
        install_path = self.get_installed_path(app_id)
        if install_path is None:
            return None, None
        info = self._load_json(install_path / f"goggame-{app_id}.info", {})
        tasks = info.get("playTasks", []) if isinstance(info, dict) else []
        primary = next((task for task in tasks if task.get("isPrimary")), None)
        if primary is None and tasks:
            primary = tasks[0]
        if not isinstance(primary, dict) or primary.get("type") != "FileTask":
            return None, install_path
        return primary, install_path

    def _get_library_entries(self, user_id: str, token: str) -> list[dict]:
        entries = []
        page_token = ""
        headers = {"Authorization": f"Bearer {token}"}
        while True:
            url = f"https://galaxy-library.gog.com/users/{user_id}/releases"
            response = requests.get(url, headers=headers, params={"page_token": page_token} if page_token else {}, timeout=15)
            response.raise_for_status()
            data = response.json()
            entries.extend(data.get("items", []))
            page_token = data.get("next_page_token", "")
            if not page_token:
                return entries

    def _get_game(self, entry: dict, token: str) -> dict:
        if entry.get("platform_id") != "gog" or not entry.get("external_id"):
            return {}
        app_id = str(entry["external_id"])
        headers = {"Authorization": f"Bearer {token}"}
        if entry.get("certificate"):
            headers["X-GOG-Library-Cert"] = str(entry["certificate"])
        response = requests.get(
            f"https://gamesdb.gog.com/platforms/gog/external_releases/{app_id}",
            headers=headers, timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        game = data.get("game", {})
        if not game.get("visible_in_library", True):
            return {}
        steam_release = next(
            (
                release for release in game.get("releases", [])
                if release.get("platform_id") == "steam"
            ),
            {},
        )
        description = self._localized_value(data.get("summary"))
        language = get_metadata_language().lower()
        try:
            product_response = requests.get(
                f"https://api.gog.com/products/{app_id}",
                params={
                    "expand": "description",
                    "locale": GOG_PRODUCT_LOCALES.get(language, language),
                },
                timeout=15,
            )
            product_response.raise_for_status()
            product_description = product_response.json().get("description", {})
            localized_lead = str(product_description.get("lead") or "")
            if localized_lead:
                paragraphs = re.split(
                    r"(?:<br\s*/?>\s*){2,}", localized_lead, flags=re.IGNORECASE
                )
                paragraph_count = (
                    2 if re.match(r"\s*<(?:b|strong)>", paragraphs[0], re.IGNORECASE)
                    else 1
                )
                description = "<br><br>".join(
                    paragraph.strip() for paragraph in paragraphs[:paragraph_count]
                )
        except requests.RequestException as error:
            logger.warning(
                "Failed to load localized GOG description for %s: %s",
                app_id, error,
            )
        return {
            "app_id": app_id,
            "title": (
                self._localized_value(data.get("title"))
                or self._localized_value(game.get("title"))
                or app_id
            ).strip(),
            "description": description,
            "cover": self._format_image(game.get("vertical_cover") or game.get("logo") or game.get("background")),
            "steam_appid": str(steam_release.get("external_id", "")),
        }

    @staticmethod
    def _localized_value(values: dict | None) -> str:
        if not isinstance(values, dict):
            return ""
        language = get_metadata_language().lower()
        for key in (language, language.replace("_", "-")):
            if values.get(key):
                return str(values[key])
        localized = next(
            (value for key, value in values.items() if key.lower().startswith(language)),
            None,
        )
        return str(localized or values.get("*", ""))

    @staticmethod
    def _format_image(image: dict | None) -> str:
        template = image.get("url_format", "") if isinstance(image, dict) else ""
        return template.replace("{formatter}", "").replace("{ext}", "jpg")

    @staticmethod
    def parse_download_sizes(output: bytes) -> tuple[int, int]:
        """Return download and disk sizes from gogdl info output."""
        data = orjson.loads(output)
        sizes = data.get("size", {}) if isinstance(data, dict) else {}
        languages = data.get("languages", []) if isinstance(data, dict) else []
        selected = [sizes.get("*", {})]
        if languages:
            selected.append(sizes.get(str(languages[0]), {}))
        download_size = sum(int(item.get("download_size", 0)) for item in selected)
        disk_size = sum(int(item.get("disk_size", 0)) for item in selected)
        return download_size, disk_size

    @staticmethod
    def extract_auth_code(url: str) -> str:
        """Extract the OAuth code from GOG's redirect URL."""
        parsed = urlparse(url)
        if parsed.netloc != "embed.gog.com" or parsed.path != "/on_login_success":
            return ""
        values = parse_qs(parsed.query)
        return values.get("code", [""])[0]

    @staticmethod
    def _load_json(path: Path, fallback):
        try:
            return orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return fallback

    @staticmethod
    def _save_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
