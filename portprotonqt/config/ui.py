"""UI configuration settings."""
import asyncio
import os
import subprocess
from typing import Any, cast

from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from portprotonqt.config.base import BaseConfig, configparser, THEMES_DIRS
from portprotonqt.config.validators import validate_string, validate_int, validate_bool
from portprotonqt.localization import get_theme_translations
from portprotonqt.logger import get_logger


logger = get_logger(__name__)
THEME_VARIANTS = ("dark", "light", "auto")
DOWNLOADS_SECTION = "Downloads"


def _read_theme_variants(theme_name: str) -> dict[str, str]:
    variants = {}
    for themes_dir in THEMES_DIRS:
        metainfo_file = os.path.join(themes_dir, theme_name, "metainfo.ini")
        if not os.path.exists(metainfo_file):
            continue
        cp = configparser.ConfigParser()
        cp.read(metainfo_file, encoding="utf-8")
        if "Metainfo" not in cp:
            return variants
        dark_name = cp.get("Metainfo", "dark_variant", fallback="")
        light_name = cp.get("Metainfo", "light_variant", fallback="")
        if dark_name and _theme_exists(dark_name):
            variants["dark"] = dark_name
        if light_name and _theme_exists(light_name):
            variants["light"] = light_name
        return variants
    return variants


def _get_theme_base_name(theme_name: str) -> str:
    variants = _read_theme_variants(theme_name)
    if variants.get("dark"):
        return variants["dark"]
    return theme_name


def _get_theme_variant_name(theme_name: str) -> str:
    variants = _read_theme_variants(theme_name)
    if variants.get("light") == theme_name:
        return "light"
    return "auto"


def _theme_exists(theme_name: str) -> bool:
    for themes_dir in THEMES_DIRS:
        theme_folder = os.path.join(themes_dir, theme_name)
        if os.path.exists(os.path.join(theme_folder, "styles.py")):
            return True
    return False


def _get_theme_base_names(theme_names: list[str]) -> list[str]:
    base_names = []
    for theme_name in theme_names:
        base_name = _get_theme_base_name(theme_name)
        if base_name not in base_names:
            base_names.append(base_name)
    return base_names


def _unwrap_variant(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 1:
        value = value[0]
    while not isinstance(value, tuple) and hasattr(value, "value"):
        value = cast(Any, value).value
    return value


async def _read_portal_color_scheme() -> int | None:
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    try:
        introspection = await bus.introspect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        proxy = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            introspection,
        )
        iface = cast(Any, proxy.get_interface("org.freedesktop.portal.Settings"))
        value = await iface.call_read("org.freedesktop.appearance", "color-scheme")
        return int(_unwrap_variant(value))
    finally:
        bus.disconnect()


def _is_portal_dark_theme() -> bool | None:
    try:
        color_scheme = asyncio.run(_read_portal_color_scheme())
    except Exception as e:
        logger.debug("Failed to read portal color scheme: %s", e)
        return None
    if color_scheme is None:
        return None
    return color_scheme == 1


def _is_gsettings_dark_theme() -> bool | None:
    session = os.environ.get("XDG_SESSION_DESKTOP", "").lower()

    # XFCE
    if session.startswith("xfce"):
        try:
            result = subprocess.run(
                ["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"],
                capture_output=True, text=True, check=False, timeout=1,
            )
            if result.returncode == 0 and (gtk_theme := result.stdout.strip()):
                return "-dark" in gtk_theme.lower()
        except (OSError, subprocess.SubprocessError):
            pass

    # MATE
    if session.startswith("mate"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.mate.interface", "gtk-theme"],
                capture_output=True, text=True, check=False, timeout=1,
            )
            if result.returncode == 0 and (gtk_theme := result.stdout.strip().strip("'\"")):
                return "-dark" in gtk_theme.lower()
        except (OSError, subprocess.SubprocessError):
            pass

    # Cinnamon
    if session.startswith("cinnamon"):
        for schema, key in [
            ("org.x.apps.portal", "color-scheme"),
            ("org.cinnamon.desktop.interface", "gtk-theme"),
        ]:
            try:
                result = subprocess.run(
                    ["gsettings", "get", schema, key],
                    capture_output=True, text=True, check=False, timeout=1,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode != 0:
                continue
            value = result.stdout.strip().strip("'\"")
            if key == "color-scheme":
                if value == "prefer-dark":
                    return True
                if value in ("default", "prefer-light"):
                    return False
            else:
                return "-dark" in value.lower()

    # GNOME
    for schema, key in [
        ("org.gnome.desktop.interface", "color-scheme"),
        ("org.gnome.desktop.interface", "gtk-theme"),
    ]:
        try:
            result = subprocess.run(
                ["gsettings", "get", schema, key],
                capture_output=True, text=True, check=False, timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue

        value = result.stdout.strip().strip("'\"")
        if key == "color-scheme":
            if value == "prefer-dark":
                return True
            if value in ("default", "prefer-light"):
                return False
        else:
            return "-dark" in value.lower()

    return None


def _is_qt_light_theme() -> bool:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return False

    app = cast(QApplication | None, QApplication.instance())
    if app is None:
        return False

    try:
        color_scheme = app.styleHints().colorScheme()
    except AttributeError:
        return False
    return color_scheme == Qt.ColorScheme.Light


def _is_system_light_theme() -> bool:
    is_dark = _is_portal_dark_theme()
    if is_dark is None:
        is_dark = _is_gsettings_dark_theme()
    if is_dark is not None:
        return not is_dark
    return _is_qt_light_theme()


def _resolve_theme_name(theme_name: str, variant: str) -> str:
    base_name = _get_theme_base_name(theme_name)
    resolved_variant = "light" if variant == "auto" and _is_system_light_theme() else variant
    variants = _read_theme_variants(base_name)
    resolved_name = variants.get(resolved_variant, base_name)
    if _theme_exists(resolved_name):
        return resolved_name
    if _theme_exists(base_name):
        return base_name
    light_name = variants.get("light", "")
    if _theme_exists(light_name):
        return light_name
    return base_name


class UIConfig(BaseConfig):
    """UI configuration settings."""

    _section = "Appearance"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._resolved_theme_cache: tuple[str, str, str] | None = None

    def _clear_resolved_theme_cache(self) -> None:
        self._resolved_theme_cache = None

    def get_theme(self) -> str:
        """Get the current theme name."""
        theme_name = self._get_str("theme", "standart")
        variant = self.get_theme_variant()
        cache = self._resolved_theme_cache
        if cache is not None and cache[:2] == (theme_name, variant):
            return cache[2]
        resolved_name = _resolve_theme_name(theme_name, variant)
        self._resolved_theme_cache = (theme_name, variant, resolved_name)
        return resolved_name

    def set_theme(self, theme_name: str):
        """Set the theme name."""
        validate_string(theme_name, "theme", min_len=1, max_len=50)
        self._clear_resolved_theme_cache()
        self._save_value("theme", theme_name, "str")

    def get_theme_base(self) -> str:
        """Get the selected base theme name."""
        return _get_theme_base_name(self._get_str("theme", "standart"))

    def get_theme_bases(self, theme_names: list[str]) -> list[str]:
        """Get unique base theme names."""
        return _get_theme_base_names(theme_names)

    def get_theme_variant(self) -> str:
        """Get theme variant."""
        theme_name = self._get_str("theme", "standart")
        variant = self._get_str("theme_variant", _get_theme_variant_name(theme_name))
        return variant if variant in THEME_VARIANTS else _get_theme_variant_name(theme_name)

    def set_theme_variant(self, variant: str) -> None:
        """Set theme variant."""
        validate_string(variant, "theme_variant", min_len=1, max_len=10)
        if variant not in THEME_VARIANTS:
            variant = "auto"
        self._clear_resolved_theme_cache()
        self._save_value("theme_variant", variant, "str")

    def resolve_theme(self, theme_name: str, variant: str) -> str:
        """Resolve base theme and variant to an installed theme name."""
        return _resolve_theme_name(theme_name, variant)

    def get_terminal_scheme(self) -> str:
        """Get the current terminal scheme name."""
        return self._get_str("terminal_scheme", "default")

    def set_terminal_scheme(self, scheme_name: str):
        """Set the terminal scheme name."""
        validate_string(scheme_name, "terminal_scheme", min_len=1, max_len=50)
        self._save_value("terminal_scheme", scheme_name, "str")

    def get_time_detail_level(self) -> str:
        """Get time detail level."""
        cp = self._read_config()
        if cp is None or not cp.has_section("Time"):
            return self._save_time_detail("detailed")
        return cp.get("Time", "detail_level", fallback="detailed").lower()

    def _save_time_detail(self, detail_level: str) -> str:
        """Save time detail level."""
        validate_string(detail_level, "detail_level", min_len=1, max_len=20)
        cp = self._read_config() or configparser.ConfigParser()
        if "Time" not in cp:
            cp["Time"] = {}
        cp["Time"]["detail_level"] = detail_level
        self._save_config(cp)
        return detail_level

    def set_time_detail_level(self, detail_level: str):
        """Set time detail level."""
        self._save_time_detail(detail_level)

    def get_card_width(self) -> int:
        """Get card width for game cards."""
        return self._get_int("card_width", 250)

    def set_card_width(self, width: int):
        """Set card width."""
        validate_int(width, "card_width", min_val=100, max_val=1000)
        self._save_value("card_width", width, "int")

    def get_auto_card_width(self) -> int:
        """Get card width for auto-install."""
        return self._get_int("auto_card_width", 250)

    def set_auto_card_width(self, width: int):
        """Set card width for auto-install."""
        validate_int(width, "auto_card_width", min_val=100, max_val=1000)
        self._save_value("auto_card_width", width, "int")

    def get_theme_store_card_width(self) -> int:
        """Get card width for theme store."""
        return self._get_int("theme_store_card_width", 350)

    def set_theme_store_card_width(self, width: int):
        """Set card width for theme store."""
        validate_int(width, "theme_store_card_width", min_val=150, max_val=600)
        self._save_value("theme_store_card_width", width, "int")

    def get_hide_autoinstall_tab(self) -> bool:
        """Get hide auto-install tab setting."""
        return self._get_bool("hide_autoinstall_tab", False)

    def set_hide_autoinstall_tab(self, hide: bool):
        """Set hide auto-install tab setting."""
        validate_bool(hide, "hide_autoinstall_tab")
        self._save_value("hide_autoinstall_tab", hide, "bool")

    def get_hide_control_hints(self) -> bool:
        """Get hide control hints setting."""
        return self._get_bool("hide_control_hints", False)

    def set_hide_control_hints(self, hide: bool) -> None:
        """Set hide control hints setting."""
        validate_bool(hide, "hide_control_hints")
        self._save_value("hide_control_hints", hide, "bool")

    def get_force_english(self) -> bool:
        """Get forced English language setting."""
        cp = self._read_config()
        if cp is None:
            return False
        try:
            return cp.getboolean(self._section, "force_english", fallback=False)
        except (configparser.Error, ValueError) as e:
            logger.warning("Error reading force_english: %s", e)
            return False

    def set_force_english(self, enabled: bool) -> None:
        """Set forced English language setting."""
        validate_bool(enabled, "force_english")
        self._save_value("force_english", enabled, "bool")

    def get_badge_view_mode(self) -> str:
        """Get badge view mode ('detailed' or 'compact')."""
        mode = self._get_str("badge_view_mode", "detailed")
        return mode if mode in ("detailed", "compact", "hidden") else "detailed"

    def set_badge_view_mode(self, mode: str):
        """Set badge view mode."""
        validate_string(mode, "badge_view_mode", min_len=1, max_len=20)
        self._save_value("badge_view_mode", mode, "str")

    def get_library_layout_mode(self, theme_mode: str = "grid") -> str:
        """Get the selected library layout or the theme default."""
        modes = {"grid", "list", "vertical", "horizontal", "horizontal_top"}
        mode = self._get_str("library_layout_mode", "theme")
        return mode if mode in modes else theme_mode.lower()

    def set_library_layout_mode(self, mode: str) -> None:
        """Set the library layout mode."""
        validate_string(mode, "library_layout_mode", min_len=1, max_len=20)
        self._save_value("library_layout_mode", mode, "str")

    def get_horizontal_card_orientation(self, theme_mode: str) -> str:
        """Get the horizontal card orientation or the theme default."""
        mode = self._get_str("horizontal_card_orientation", "theme")
        return mode if mode in {"horizontal", "vertical"} else theme_mode

    def set_horizontal_card_orientation(self, mode: str) -> None:
        """Set the horizontal card orientation."""
        validate_string(mode, "horizontal_card_orientation", min_len=1, max_len=20)
        self._save_value("horizontal_card_orientation", mode, "str")

    def get_economy_mode(self) -> bool:
        """Get economy mode setting."""
        return self._get_download_bool("economy_mode", False)

    def set_economy_mode(self, enabled: bool):
        """Set economy mode setting."""
        validate_bool(enabled, "economy_mode")
        self._save_download_value("economy_mode", enabled)

    def _get_download_bool(self, option: str, default: bool) -> bool:
        cp = self._read_config()
        if cp is None:
            return self._save_download_value(option, default)

        try:
            if cp.has_option(DOWNLOADS_SECTION, option):
                return cp.getboolean(DOWNLOADS_SECTION, option, fallback=default)
            if cp.has_option(self._section, option):
                return cp.getboolean(self._section, option, fallback=default)
        except ValueError as e:
            logger.warning("Error reading %s: %s", option, e)
            return self._save_download_value(option, default)
        except configparser.Error as e:
            logger.warning("Error reading %s: %s", option, e)
            return self._save_download_value(option, default)

        return self._save_download_value(option, default)

    def _save_download_value(self, option: str, value: bool) -> bool:
        validate_bool(value, option)
        cp = self._read_config() or configparser.ConfigParser()
        if DOWNLOADS_SECTION not in cp:
            cp[DOWNLOADS_SECTION] = {}

        cp[DOWNLOADS_SECTION][option] = str(value)
        if cp.has_section(self._section):
            cp.remove_option(self._section, option)
        self._save_config(cp)
        return value

    def get_download_wine_to_steam(self) -> bool:
        """Get Steam compatibility tools download setting."""
        return self._get_download_bool("download_wine_to_steam", False)

    def set_download_wine_to_steam(self, enabled: bool) -> None:
        """Set Steam compatibility tools download setting."""
        validate_bool(enabled, "download_wine_to_steam")
        self._save_download_value("download_wine_to_steam", enabled)

    def get_disable_runtime_download(self) -> bool:
        """Get PortProton runtime download setting."""
        default = bool(os.getenv("FLATPAK_ID"))
        return self._get_download_bool("disable_runtime_download", default)

    def set_disable_runtime_download(self, enabled: bool) -> None:
        """Set PortProton runtime download setting."""
        if os.getenv("FLATPAK_ID"):
            enabled = True
        validate_bool(enabled, "disable_runtime_download")
        self._save_download_value("disable_runtime_download", enabled)

    def get_auto_download_ppdb(self) -> bool:
        """Get PPDB auto-download setting."""
        return self._get_download_bool("auto_download_ppdb", False)

    def set_auto_download_ppdb(self, enabled: bool) -> None:
        """Set PPDB auto-download setting."""
        validate_bool(enabled, "auto_download_ppdb")
        self._save_download_value("auto_download_ppdb", enabled)

    def get_auto_appimage_updates(self) -> bool:
        """Get AppImage self-update setting."""
        return self._get_download_bool("auto_appimage_updates", True)

    def set_auto_appimage_updates(self, enabled: bool) -> None:
        """Set AppImage self-update setting."""
        validate_bool(enabled, "auto_appimage_updates")
        self._save_download_value("auto_appimage_updates", enabled)

    def get_enable_theme_store(self) -> bool:
        """Get theme store visibility setting."""
        return self._get_bool("enable_theme_store", False)

    def set_enable_theme_store(self, enabled: bool):
        """Set theme store visibility setting."""
        validate_bool(enabled, "enable_theme_store")
        self._save_value("enable_theme_store", enabled, "bool")

    def get_sounds_enabled(self) -> bool:
        """Get UI sounds enabled setting."""
        return self._get_bool("sounds_enabled", True)

    def set_sounds_enabled(self, enabled: bool):
        """Set UI sounds enabled setting."""
        validate_bool(enabled, "sounds_enabled")
        self._save_value("sounds_enabled", enabled, "bool")

    def get_crash_reports_enabled(self) -> bool:
        """Get compatibility reports after game crashes setting."""
        return self._get_bool("crash_reports_enabled", True)

    def set_crash_reports_enabled(self, enabled: bool) -> None:
        """Set compatibility reports after game crashes setting."""
        validate_bool(enabled, "crash_reports_enabled")
        self._save_value("crash_reports_enabled", enabled, "bool")


def load_theme_metainfo(theme_name: str) -> dict:
    """Load theme metadata from metainfo.ini."""
    meta: dict[str, str] = {}
    for themes_dir in THEMES_DIRS:
        theme_folder = os.path.join(themes_dir, theme_name)
        metainfo_file = os.path.join(theme_folder, "metainfo.ini")
        if os.path.exists(metainfo_file):
            theme_translations = get_theme_translations(metainfo_file)
            cp = configparser.ConfigParser()
            cp.read(metainfo_file, encoding="utf-8")
            if "Metainfo" in cp:
                meta["author"] = cp.get("Metainfo", "author", fallback="Unknown")
                meta["author_link"] = cp.get("Metainfo", "author_link", fallback="")
                meta["dark_variant"] = cp.get("Metainfo", "dark_variant", fallback="")
                meta["light_variant"] = cp.get("Metainfo", "light_variant", fallback="")
                meta["name"] = theme_translations.get("name", theme_name)
                meta["description"] = theme_translations.get("description", "")
            break
    return meta
