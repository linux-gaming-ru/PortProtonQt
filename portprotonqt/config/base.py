"""Base configuration class for PortProtonQt."""
import os
import configparser
from pathlib import Path
from portprotonqt.logger import get_logger
from portprotonqt.config.validators import validate_string, validate_int, validate_bool, ValidationError

logger = get_logger(__name__)

# Export configparser for use in other modules
__all__ = ["configparser"]

# Configuration file paths
CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_FILE = CONFIG_DIR / "PortProtonQt.conf"
COUNTER_SKIP_FILE = CONFIG_DIR / "PortProtonQt.counter.skip"
PORTPROTON_CONFIG_FILE = CONFIG_DIR / "PortProton.conf"

# Theme directories
XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
THEMES_DIRS = [
    XDG_DATA_HOME / "PortProtonQt" / "themes",
    Path(__file__).parent.parent / "themes",
]

# Cache paths
CACHE_DIR = XDG_DATA_HOME / "PortProtonQt" / "cache"

# Module-level cache storage
_config_cache: dict[str, configparser.ConfigParser] = {}
_config_mtime: dict[str, float] = {}


def reset_main_config() -> None:
    """Delete main config file and invalidate cache."""
    _mark_download_counter_skip()
    if not CONFIG_FILE.exists():
        return
    try:
        CONFIG_FILE.unlink()
        logger.info("Configuration file %s deleted", CONFIG_FILE)
    except OSError as error:
        logger.warning("Failed to delete configuration file: %s", error)
        return

    config_path = str(CONFIG_FILE)
    _config_cache.pop(config_path, None)
    _config_mtime.pop(config_path, None)


def _mark_download_counter_skip() -> None:
    """Skip the next download counter request."""
    try:
        COUNTER_SKIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        COUNTER_SKIP_FILE.write_text("1", encoding="utf-8")
    except OSError as error:
        logger.warning("Failed to save counter skip marker: %s", error)


def consume_download_counter_skip() -> bool:
    """Return True once after settings reset."""
    if not COUNTER_SKIP_FILE.exists():
        return False
    try:
        COUNTER_SKIP_FILE.unlink()
    except OSError as error:
        logger.warning("Failed to delete counter skip marker: %s", error)
    return True


def update_app_version(app_version: str) -> bool:
    """Store current app version and report whether it changed."""
    cp = configparser.ConfigParser()
    config_existed = CONFIG_FILE.exists()
    if config_existed:
        try:
            cp.read(CONFIG_FILE, encoding="utf-8")
        except configparser.Error as e:
            logger.warning("Invalid configuration file format: %s", e)
            return False

    section = "Application"
    old_version = cp.get(section, "version", fallback="")
    if config_existed and old_version == app_version:
        return False

    if section not in cp:
        cp[section] = {}
    cp[section]["version"] = app_version

    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
            cp.write(config_file)
    except OSError as error:
        logger.warning("Failed to save application version: %s", error)
        return False

    config_path = str(CONFIG_FILE)
    _config_cache.pop(config_path, None)
    _config_mtime.pop(config_path, None)
    return True


class BaseConfig:
    """Base configuration class providing common functionality."""

    _section: str = ""

    def __init__(self, config_file: Path = CONFIG_FILE):
        self._config_file = config_file

    def _read_config(self) -> configparser.ConfigParser | None:
        """Read configuration file with caching."""
        config_path = str(self._config_file)

        if not self._config_file.exists():
            try:
                self._config_file.parent.mkdir(parents=True, exist_ok=True)
                self._config_file.touch()
            except OSError as error:
                logger.warning("Failed to create configuration file %s: %s", config_path, error)
                return None

        try:
            current_mtime = self._config_file.stat().st_mtime
        except OSError:
            logger.warning("Failed to get modification time for %s", config_path)
            return None

        if config_path in _config_cache and config_path in _config_mtime:
            if _config_mtime[config_path] == current_mtime:
                return _config_cache[config_path]

        cp = configparser.ConfigParser()
        try:
            cp.read(config_path, encoding="utf-8")
            _config_cache[config_path] = cp
            _config_mtime[config_path] = current_mtime
            return cp
        except (configparser.DuplicateSectionError, configparser.DuplicateOptionError) as e:
            logger.warning("Invalid configuration file format: %s", e)
            return None
        except Exception as e:
            logger.warning("Failed to read configuration file: %s", e)
            return None

    def _save_config(self, cp: configparser.ConfigParser):
        """Save configuration to file."""
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_file, "w", encoding="utf-8") as f:
            cp.write(f)
        self._invalidate_cache()

    def _invalidate_cache(self):
        """Invalidate configuration cache."""
        config_path = str(self._config_file)
        if config_path in _config_cache:
            del _config_cache[config_path]
        if config_path in _config_mtime:
            del _config_mtime[config_path]

    def _get_value(self, option: str, default, value_type: str = "str"):
        """Get a configuration value with type conversion."""
        cp = self._read_config()
        if cp is None or not cp.has_section(self._section):
            return self._save_value(option, default, value_type)
        if not cp.has_option(self._section, option):
            return self._save_value(option, default, value_type)

        try:
            if value_type == "int":
                return cp.getint(self._section, option, fallback=default)
            elif value_type == "bool":
                return cp.getboolean(self._section, option, fallback=default)
            else:
                return cp.get(self._section, option, fallback=default)
        except (ValueError, configparser.Error) as e:
            logger.warning("Error reading %s: %s", option, e)
            return self._save_value(option, default, value_type)

    def _get_str(self, option: str, default: str) -> str:
        """Get a string configuration value."""
        return str(self._get_value(option, default, "str"))

    def _get_int(self, option: str, default: int) -> int:
        """Get an integer configuration value."""
        return int(self._get_value(option, default, "int"))

    def _get_bool(self, option: str, default: bool) -> bool:
        """Get a boolean configuration value."""
        return bool(self._get_value(option, default, "bool"))

    def _save_value(self, option: str, value, value_type: str = "str"):
        """Save a configuration value with validation."""
        try:
            if value_type == "int":
                validate_int(value, option)
            elif value_type == "bool":
                validate_bool(value, option)
            else:
                validate_string(value, option)
        except ValidationError as e:
            logger.warning("Validation failed for %s: %s", option, e)
            raise

        cp = self._read_config() or configparser.ConfigParser()
        if self._section not in cp:
            cp[self._section] = {}

        cp[self._section][option] = str(value)
        self._save_config(cp)
        return value
