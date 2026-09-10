import ast
import asyncio
import hashlib
import importlib.util
import os
import re
import shutil
import stat
import xml.etree.ElementTree as ET
from typing import Any, cast
import orjson
from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from portprotonqt.logger import get_logger
from portprotonqt.theme_security import (
    check_theme_directory_safety,
    is_safe_font_file,
    is_safe_image_file,
)
from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QFontDatabase, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from portprotonqt.config import CACHE_DIR, ui_config, load_theme_metainfo
from portprotonqt.config.ui import _is_system_light_theme, _unwrap_variant
from portprotonqt.qt_utils import get_device_pixel_ratio

# Icon caching for performance optimization
_icon_cache = {}
# Directory structure cache for performance optimization
_icon_dirs_cache = {}

logger = get_logger(__name__)
SUPPORTED_IMAGE_EXTENSIONS = ('.svg', '.png', '.jpg', '.jpeg', '.webp', '.jxl')
DMS_COLOR_FILE_MAX_SIZE = 128 * 1024
DMS_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
DMS_COLOR_ROLES = (
    "background",
    "error",
    "on_background",
    "on_primary",
    "on_primary_container",
    "on_surface",
    "on_surface_variant",
    "outline",
    "outline_variant",
    "primary",
    "primary_container",
    "secondary",
    "shadow",
    "surface",
    "surface_bright",
    "surface_container",
    "surface_container_high",
    "surface_container_highest",
    "surface_container_low",
    "surface_container_lowest",
    "tertiary",
)
SVG_COLOR_PATTERN = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|[A-Za-z][A-Za-z0-9_-]{0,31}|"
    r"(rgba?|hsla?)\([0-9A-Za-z.,% /+-]+\))$"
)
SVG_STYLE_DECL_PATTERN = re.compile(
    r"(?P<prefix>(^|;)\s*(fill|stroke|color|stop-color|flood-color|lighting-color)\s*:\s*)"
    r"(?P<value>[^;]+)",
    re.IGNORECASE,
)
SVG_PAINT_ATTR_PATTERN = re.compile(
    r"(?P<prefix>\b(fill|stroke|color|stop-color|flood-color|lighting-color)\s*=\s*)"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
SVG_PAINT_ATTRIBUTES = {"fill", "stroke", "color", "stop-color", "flood-color", "lighting-color"}
SVG_ANIMATION_TAGS = {"animate", "animateMotion", "animateTransform", "set"}
SVG_KEEP_PAINT_VALUES = {"none", "transparent", "inherit", "initial", "unset", "freeze", "remove"}
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SVG_CACHE_VERSION = 2
NON_INHERITED_THEME_CONSTANTS = {"ICON_COLORS"}
SYSTEM_THEME_POLL_INTERVAL_MS = 200
SYSTEM_THEME_POLL_STEP_MS = 200
PORTAL_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
PORTAL_COLOR_SCHEME_KEY = "color-scheme"

ET.register_namespace("", SVG_NAMESPACE)

# Folder where all custom themes are located
xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
THEMES_DIRS = [
    os.path.join(xdg_data_home, "PortProtonQt", "themes"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")
]
_loaded_theme = None
_loaded_font_signature = None


def _read_dms_color_file(colors_file: str) -> bytes | None:
    """Read a stable, user-owned regular DMS color file."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        file_descriptor = os.open(colors_file, flags)
    except OSError as e:
        logger.warning("Cannot open DMS color palette: %s", e)
        return None
    try:
        before = os.fstat(file_descriptor)
        unsafe_mode = before.st_mode & 0o022
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or unsafe_mode
            or not 0 < before.st_size <= DMS_COLOR_FILE_MAX_SIZE
        ):
            logger.warning("Unsafe DMS color palette file: %s", colors_file)
            return None
        with os.fdopen(file_descriptor, "rb", closefd=False) as source_file:
            content = source_file.read(DMS_COLOR_FILE_MAX_SIZE + 1)
        after = os.fstat(file_descriptor)
    except OSError as e:
        logger.warning("Cannot read DMS color palette: %s", e)
        return None
    finally:
        os.close(file_descriptor)
    if (
        len(content) != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        logger.warning("DMS color palette changed while being read")
        return None
    return content


def _is_valid_dms_document(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    palettes = document.get("colors")
    if not isinstance(palettes, dict):
        return False
    for variant in ("dark", "light"):
        colors = palettes.get(variant)
        if not isinstance(colors, dict):
            return False
        if any(
            not isinstance(colors.get(role), str)
            or not DMS_COLOR_PATTERN.fullmatch(colors[role])
            for role in DMS_COLOR_ROLES
        ):
            return False
    return True


def load_dms_palette(variant: str) -> dict[str, str]:
    """Load a validated Material palette generated by Dank Material Shell."""
    if variant not in ("dark", "light"):
        raise ValueError(f"Unsupported DMS palette variant: {variant}")
    cache_home = os.getenv(
        "XDG_CACHE_HOME",
        os.path.join(os.path.expanduser("~"), ".cache"),
    )
    if not os.path.isabs(cache_home):
        logger.warning("XDG_CACHE_HOME is not an absolute path")
        return {}
    colors_file = os.path.join(
        cache_home,
        "DankMaterialShell",
        "dms-colors.json",
    )
    content = _read_dms_color_file(colors_file)
    if content is None:
        return {}
    try:
        document = orjson.loads(content)
    except orjson.JSONDecodeError as e:
        logger.warning("Cannot parse DMS color palette: %s", e)
        return {}
    if not _is_valid_dms_document(document):
        logger.warning("Invalid DMS color palette schema")
        return {}
    return {role: document["colors"][variant][role] for role in DMS_COLOR_ROLES}

def _load_icon(icon_path: str) -> QIcon:
    """Load theme icon with device pixel ratio for crisp raster icons."""
    if icon_path.lower().endswith(".svg"):
        return _load_svg_icon(icon_path)

    pixmap = QPixmap(icon_path)
    if pixmap.isNull():
        return QIcon(icon_path)

    device_pixel_ratio = get_device_pixel_ratio()
    if device_pixel_ratio > 1.0:
        pixmap.setDevicePixelRatio(device_pixel_ratio)
    return QIcon(pixmap)


def _load_svg_icon(icon_path: str) -> QIcon:
    """Render SVG icon into high-DPI pixmaps for Qt icon users."""
    renderer = QSvgRenderer(icon_path)
    if not renderer.isValid():
        return QIcon(icon_path)

    icon = QIcon()
    device_pixel_ratio = get_device_pixel_ratio()
    for size in (16, 20, 22, 24, 32, 48, 64):
        target_size = max(1, int(size * device_pixel_ratio))
        pixmap = QPixmap(target_size, target_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(device_pixel_ratio)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _safe_svg_color(color: str | None) -> str | None:
    if not isinstance(color, str):
        return None
    value = color.strip()
    if not SVG_COLOR_PATTERN.match(value):
        logger.warning("Unsafe SVG icon color skipped: %s", color)
        return None
    return value


def _colored_svg_cache_path(icon_path: str, color: str) -> str | None:
    try:
        stat = os.stat(icon_path)
    except OSError as e:
        logger.warning("Cannot stat SVG icon '%s': %s", icon_path, e)
        return None
    digest_source = f"{SVG_CACHE_VERSION}:{icon_path}:{stat.st_mtime_ns}:{color}".encode()
    digest = hashlib.sha256(digest_source).hexdigest()[:16]
    return str(CACHE_DIR / "icons" / f"{digest}.svg")


def _svg_local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1] if "}" in name else name


def _is_recolorable_paint(value: str) -> bool:
    paint = value.strip()
    paint_lower = paint.lower()
    if not paint or paint_lower in SVG_KEEP_PAINT_VALUES:
        return False
    if paint_lower.startswith(("url(", "context-fill", "context-stroke")):
        return False
    return True


def _replace_style_paints(style: str | None, color: str) -> str | None:
    if style is None:
        return None

    def replace_match(match: re.Match) -> str:
        value = match.group("value")
        if not _is_recolorable_paint(value):
            return match.group(0)
        return f"{match.group('prefix')}{color}"

    return SVG_STYLE_DECL_PATTERN.sub(replace_match, style)


def _replace_svg_paints_text(source: str, color: str) -> str:
    def replace_match(match: re.Match) -> str:
        if not _is_recolorable_paint(match.group("value")):
            return match.group(0)
        return f"{match.group('prefix')}{match.group('quote')}{color}{match.group('quote')}"

    source = SVG_PAINT_ATTR_PATTERN.sub(replace_match, source)
    return _replace_style_paints(source, color) or source


def _recolor_svg_element(element: ET.Element, color: str) -> None:
    local_name = _svg_local_name(element.tag)
    if local_name != "style":
        style = _replace_style_paints(element.attrib.get("style"), color)
        if style is not None:
            element.set("style", style)
    elif element.text:
        element.text = _replace_style_paints(element.text, color)

    if local_name not in SVG_ANIMATION_TAGS:
        for attr_name, attr_value in list(element.attrib.items()):
            if _svg_local_name(attr_name) not in SVG_PAINT_ATTRIBUTES:
                continue
            if _is_recolorable_paint(attr_value):
                element.set(attr_name, color)

    for child in list(element):
        _recolor_svg_element(child, color)


def _recolor_svg_source(source: str, color: str) -> str:
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return _replace_svg_paints_text(source, color)
    _recolor_svg_element(root, color)
    return ET.tostring(root, encoding="unicode")


def _write_colored_svg(icon_path: str, target_path: str, color: str) -> bool:
    try:
        with open(icon_path, encoding="utf-8") as source_file:
            source = source_file.read()
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        temp_path = f"{target_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as target_file:
            target_file.write(_recolor_svg_source(source, color))
        os.replace(temp_path, target_path)
    except OSError as e:
        logger.warning("Cannot write colored SVG icon '%s': %s", icon_path, e)
        return False
    return True


def _is_valid_theme_name(theme_name: str) -> bool:
    """Return True when theme name is safe to use in filesystem paths."""
    if not isinstance(theme_name, str) or not theme_name or len(theme_name) > 50:
        return False
    if os.path.isabs(theme_name):
        return False
    if os.sep in theme_name or (os.altsep and os.altsep in theme_name):
        return False
    if theme_name in (".", ".."):
        return False
    normalized = os.path.normpath(theme_name)
    return normalized == theme_name and normalized not in (".", "..")


def _get_parent_theme_name(theme_name: str, parent_name: str | None = None) -> str | None:
    """Return parent theme name, preserving standard fallback by default."""
    if theme_name == "standart":
        return None

    parent_name = parent_name or "standart"
    if not parent_name:
        return "standart"
    if not _is_valid_theme_name(parent_name) or parent_name == theme_name:
        logger.warning("Invalid parent theme '%s' for '%s', using 'standart'", parent_name, theme_name)
        return "standart"
    return parent_name


def _inject_parent_theme_constants(module, styles_file: str):
    visited = set()
    current_name = module.__name__.split(".")[-1]
    while current_name and current_name not in visited:
        visited.add(current_name)
        parent_name = _read_theme_parent_name(current_name)
        if not parent_name:
            break
        parent_folder = _find_theme_folder(parent_name)
        if not parent_folder:
            break
        sources = []
        styles_dir = os.path.join(parent_folder, "styles")
        if os.path.isdir(styles_dir):
            constants_path = os.path.join(styles_dir, "constants.py")
            if os.path.exists(constants_path):
                sources.append(constants_path)
        parent_styles = os.path.join(parent_folder, "styles.py")
        if os.path.exists(parent_styles):
            sources.append(parent_styles)
        for fpath in sources:
            _inject_ast_constants(fpath, module, NON_INHERITED_THEME_CONSTANTS)
        current_name = parent_name


def _inject_ast_constants(source_path: str, module, excluded_names: set | None = None):
    excluded_names = excluded_names or set()
    try:
        with open(source_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=source_path)
    except (OSError, SyntaxError) as e:
        logger.debug("Cannot parse '%s': %s", source_path, e)
        return
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id.startswith("_") or target.id in excluded_names:
                continue
            if target.id in module.__dict__:
                continue
            try:
                module.__dict__[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue


def _is_overridden_assignment(node: ast.AST, custom_constants: dict) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    for target in node.targets:
        if isinstance(target, ast.Name) and target.id in custom_constants:
            return True
    return False


def _find_theme_folder(theme_name: str) -> str | None:
    if theme_name == "standart":
        themes_dirs_to_check = [THEMES_DIRS[1]]
    else:
        themes_dirs_to_check = THEMES_DIRS

    for themes_dir in themes_dirs_to_check:
        theme_folder = os.path.join(themes_dir, theme_name)
        styles_file = os.path.join(theme_folder, "styles.py")
        if os.path.exists(styles_file):
            return theme_folder
    return None


def _read_theme_parent_name(theme_name: str) -> str | None:
    theme_folder = _find_theme_folder(theme_name)
    if not theme_folder:
        return _get_parent_theme_name(theme_name)

    styles_file = os.path.join(theme_folder, "styles.py")
    try:
        with open(styles_file, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read(), filename=styles_file)
    except (OSError, SyntaxError) as e:
        logger.warning("Cannot read parent theme for '%s': %s", theme_name, e)
        return _get_parent_theme_name(theme_name)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "THEME_INHERITS" for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return _get_parent_theme_name(theme_name, node.value.value)
        logger.warning("Invalid THEME_INHERITS value for '%s', using 'standart'", theme_name)
        return _get_parent_theme_name(theme_name)
    return _get_parent_theme_name(theme_name)


def _get_theme_resource_chain(theme_name: str) -> list[str]:
    if not _is_valid_theme_name(theme_name):
        logger.warning("Unsafe theme name for resources: %s", theme_name)
        return []

    chain = []
    seen = set()
    current_name = theme_name
    while current_name:
        if current_name in seen:
            logger.warning("Theme resource inheritance cycle for '%s'", current_name)
            break
        seen.add(current_name)
        chain.append(current_name)
        current_name = _read_theme_parent_name(current_name)

    if "standart" not in chain:
        chain.append("standart")
    return chain


def list_themes():
    """
    Return list of available themes (folder names) from THEMES_DIRS directories.
    """
    themes = []
    for themes_dir in THEMES_DIRS:
        if os.path.exists(themes_dir):
            for entry in os.listdir(themes_dir):
                theme_path = os.path.join(themes_dir, entry)
                if os.path.isdir(theme_path) and os.path.exists(os.path.join(theme_path, "styles.py")):
                    themes.append(entry)
    return themes

def load_theme_screenshots(theme_name):
    """
    Load all screenshots from "screenshots" folder in theme directory.
    Return list of tuples (pixmap, "").
    If folder missing or empty, return empty list.
    """
    screenshots = []
    if not _is_valid_theme_name(theme_name):
        logger.warning("Unsafe theme name for screenshots: %s", theme_name)
        return screenshots

    for themes_dir in THEMES_DIRS:
        theme_folder = os.path.join(themes_dir, theme_name)
        screenshots_folder = os.path.join(theme_folder, "images", "screenshots")
        if os.path.exists(screenshots_folder) and os.path.isdir(screenshots_folder):
            for file in os.listdir(screenshots_folder):
                screenshot_path = os.path.join(screenshots_folder, file)
                if os.path.isfile(screenshot_path) and is_safe_image_file(screenshot_path):
                    pixmap = QPixmap(screenshot_path)
                    if not pixmap.isNull():
                        screenshots.append((pixmap, ""))
    return screenshots

def build_icon_cache(theme_name):
    """
    Builds a cache of all image files in the theme for fast lookup.
    """
    global _icon_dirs_cache
    if not _is_valid_theme_name(theme_name):
        logger.warning("Unsafe theme name for icon cache: %s", theme_name)
        return {}

    # Check if cache already exists for this theme
    if theme_name in _icon_dirs_cache:
        return _icon_dirs_cache[theme_name]

    image_map = {}

    for resource_theme_name in _get_theme_resource_chain(theme_name):
        theme_folder = _find_theme_folder(resource_theme_name)
        if not theme_folder:
            logger.warning(
                "Resource theme '%s' not found for '%s'",
                resource_theme_name,
                theme_name,
            )
            continue
        images_folder = os.path.join(theme_folder, "images")

        if not os.path.exists(images_folder):
            continue

        for root, _dirs, files in os.walk(images_folder):
            for file in files:
                if file.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                    image_name = os.path.splitext(file)[0]
                    if image_name not in image_map:
                        image_path = os.path.join(root, file)
                        image_map[image_name] = image_path

    _icon_dirs_cache[theme_name] = image_map
    return image_map

def _resolve_sound_dirs(theme_name: str) -> list[str]:
    """Return ordered list of sound directories from theme inheritance chain."""
    dirs = []
    for resource_theme_name in _get_theme_resource_chain(theme_name):
        theme_folder = _find_theme_folder(resource_theme_name)
        if not theme_folder:
            continue
        sounds_dir = os.path.join(theme_folder, "sounds")
        if os.path.isdir(sounds_dir):
            dirs.append(sounds_dir)
    return dirs


def load_theme_fonts(theme_name):
    """
    Load all fonts from selected theme if not already loaded.
    """
    global _loaded_theme, _loaded_font_signature
    if _loaded_theme == theme_name:
        logger.debug(f"Fonts for theme '{theme_name}' already loaded, skipping")
        return

    def load_fonts_delayed():
        global _loaded_theme, _loaded_font_signature
        try:
            import time
            import os
            start_time = time.time()
            timeout = 3  # Reduced timeout to 3 seconds for faster loading

            fonts_folder = None
            for resource_theme_name in _get_theme_resource_chain(theme_name):
                theme_folder = _find_theme_folder(resource_theme_name)
                if not theme_folder:
                    continue
                possible_fonts_folder = os.path.join(theme_folder, "fonts")
                if os.path.exists(possible_fonts_folder):
                    fonts_folder = possible_fonts_folder
                    break

            if not fonts_folder or not os.path.exists(fonts_folder):
                logger.error(f"Fonts folder not found for theme '{theme_name}'")
                return

            font_files = []
            for filename in os.listdir(fonts_folder):
                if filename.lower().endswith((".ttf", ".otf")):
                    font_path = os.path.join(fonts_folder, filename)
                    if is_safe_font_file(font_path):
                        font_files.append(filename)
                    else:
                        logger.warning("Skipping unsafe font file: %s", font_path)

            # Limit number of fonts loaded to prevent too much blocking
            font_files = sorted(font_files)[:10]
            font_signature_parts = []
            for filename in font_files:
                with open(os.path.join(fonts_folder, filename), "rb") as font_file:
                    digest = hashlib.sha256(font_file.read()).hexdigest()
                font_signature_parts.append((filename, digest))
            font_signature = tuple(font_signature_parts)
            if _loaded_font_signature == font_signature:
                _loaded_theme = theme_name
                logger.debug("Fonts for theme '%s' already loaded, skipping", theme_name)
                return

            # Remove fonts only when the selected files changed.
            if _loaded_theme is not None:
                QFontDatabase.removeAllApplicationFonts()

            for filename in font_files:
                if time.time() - start_time > timeout:
                    logger.warning(f"Font loading timed out for theme '{theme_name}' after loading {len(font_files)} fonts")
                    break

                font_path = os.path.join(fonts_folder, filename)
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    logger.info(f"Font {filename} successfully loaded: {families}")
                else:
                    logger.error(f"Error loading font: {filename}")

            # Update the global variable in the main thread
            _loaded_theme = theme_name
            _loaded_font_signature = font_signature
        except Exception as e:
            logger.error(f"Error loading fonts for theme '{theme_name}': {e}")

    # Use QTimer to delay font loading until after the UI is rendered
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, load_fonts_delayed)  # Delay font loading by 100ms

class ThemeWrapper:
    """
    Wrapper for custom theme with metainfo support.
    When accessing attribute, first look for it in custom theme,
    if attribute missing, value taken from inherited theme.
    """
    def __init__(self, custom_theme, metainfo=None, inherit_chain=None):
        self.custom_theme = custom_theme
        self.metainfo = metainfo or {}
        self._theme_name = custom_theme.__name__.split(".")[-1]
        self._screenshots = None
        parent_name = getattr(custom_theme, "THEME_INHERITS", "standart")
        self.parent_theme_name = _get_parent_theme_name(custom_theme.__name__.split(".")[-1], parent_name)
        self._inherit_chain = inherit_chain or []
        self._default_theme = None  # Lazy-loaded default theme
        self._generated_styles = None  # Lazy-generated standard styles with custom constants

    @property
    def screenshots(self) -> list[tuple[QPixmap, str]]:
        """Load theme preview screenshots on first access."""
        if self._screenshots is None:
            self._screenshots = load_theme_screenshots(self._theme_name)
        return self._screenshots

    def __getattr__(self, name):
        if hasattr(self.custom_theme, name):
            return getattr(self.custom_theme, name)
        if name in NON_INHERITED_THEME_CONSTANTS:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        generated = self._get_generated_style(name)
        if generated is not None:
            return generated
        if self._default_theme is None:
            if self.parent_theme_name in self._inherit_chain:
                raise AttributeError(f"Theme inheritance cycle for '{self.parent_theme_name}'")
            try:
                self._default_theme = load_theme(self.parent_theme_name, self._inherit_chain)
            except FileNotFoundError:
                logger.warning("Parent theme '%s' unavailable, using 'standart'", self.parent_theme_name)
                self._default_theme = load_theme("standart")
        try:
            return getattr(self._default_theme, name)
        except AttributeError:
            pass
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _get_generated_style(self, name):
        parent_styles_dir = self._find_parent_styles_dir()
        parent_styles_file = self._find_parent_styles_file()
        if parent_styles_dir is None and parent_styles_file is None:
            return None
        if self._generated_styles is None:
            if parent_styles_dir is not None:
                self._generated_styles = self._build_generated_styles(parent_styles_dir)
            else:
                if parent_styles_file is None:
                    return None
                self._generated_styles = self._build_generated_styles_file(parent_styles_file)
        return self._generated_styles.get(name)

    def _find_parent_styles_dir(self):
        parent_name = self.parent_theme_name
        if not parent_name:
            return None
        folder = _find_theme_folder(parent_name)
        if not folder:
            return None
        styles_dir = os.path.join(folder, "styles")
        if os.path.isdir(styles_dir):
            return styles_dir
        return None

    def _find_parent_styles_file(self):
        parent_name = self.parent_theme_name
        if not parent_name:
            return None
        folder = _find_theme_folder(parent_name)
        if not folder:
            return None
        styles_file = os.path.join(folder, "styles.py")
        if os.path.exists(styles_file):
            return styles_file
        return None

    def _build_generated_styles_file(self, styles_file: str):
        custom_constants = {
            key: value
            for key, value in vars(self.custom_theme).items()
            if not key.startswith("_") and not callable(value)
        }
        try:
            with open(styles_file, encoding="utf-8") as source_file:
                tree = ast.parse(source_file.read(), filename=styles_file)
        except (OSError, SyntaxError):
            return {}

        tree.body = [
            node for node in tree.body
            if not _is_overridden_assignment(node, custom_constants)
        ]
        module_globals = {"__builtins__": __builtins__, **custom_constants}
        try:
            exec(compile(ast.fix_missing_locations(tree), styles_file, "exec"), module_globals, module_globals)
        except Exception:
            return {}
        return {
            key: value
            for key, value in module_globals.items()
            if not key.startswith("_")
        }

    def _build_generated_styles(self, styles_dir: str):
        generated = {}
        constants_path = os.path.join(styles_dir, "constants.py")
        base_constants: dict = {}
        try:
            with open(constants_path, encoding="utf-8") as f:
                exec(compile(f.read(), constants_path, "exec"), base_constants, base_constants)
            base_constants = {
                k: v for k, v in base_constants.items()
                if not k.startswith("_") and not callable(v)
            }
        except Exception:
            base_constants = {}
        custom_constants = {
            key: value
            for key, value in vars(self.custom_theme).items()
            if not key.startswith("_") and not callable(value)
        }
        constants = {**base_constants, **custom_constants}
        for style_file in (
            "base.py",
            "game_card.py",
            "detail_page.py",
            "settings.py",
            "winetricks.py",
            "get_wine.py",
            "file_explorer.py",
            "theme_utils.py",
        ):
            style_path = os.path.join(styles_dir, style_file)
            try:
                with open(style_path, encoding="utf-8") as source_file:
                    source = source_file.read()
            except OSError:
                continue

            source = source.replace("from .constants import *\n", "")
            module_globals = {"__builtins__": __builtins__, **constants}
            try:
                exec(compile(source, style_path, "exec"), module_globals, module_globals)
            except Exception:
                continue
            for key, value in module_globals.items():
                if key.startswith("_"):
                    continue
                generated[key] = value
        return generated

def load_theme(theme_name, inherit_chain=None):
    """
    Dynamically load style module of selected theme and metainfo.
    All themes, including standard, pass security check.
    For custom themes, return wrapper that supplies missing attributes.
    """
    import sys
    import types
    import os

    inherit_chain = inherit_chain or []
    if theme_name in inherit_chain:
        raise FileNotFoundError(f"Theme inheritance cycle for '{theme_name}'")
    next_inherit_chain = [*inherit_chain, theme_name]

    if not _is_valid_theme_name(theme_name):
        raise FileNotFoundError(f"Invalid theme name '{theme_name}'")

    if theme_name == "standart":
        themes_dirs_to_check = [THEMES_DIRS[1]]
    else:
        themes_dirs_to_check = THEMES_DIRS

    for themes_dir in themes_dirs_to_check:
        theme_folder = os.path.join(themes_dir, theme_name)
        styles_file = os.path.join(theme_folder, "styles.py")
        if os.path.exists(styles_file):
            # Check theme security before loading
            allow_absolute_imports = themes_dir == THEMES_DIRS[1]
            if not check_theme_directory_safety(
                theme_folder,
                allow_absolute_imports=allow_absolute_imports,
            ):
                logger.error(f"Theme '{theme_name}' is unsafe, falling back to 'standart'")
                raise FileNotFoundError(f"Theme '{theme_name}' contains forbidden modules or functions")

            # Determine the appropriate module name based on theme location
            # For standard theme, use the full module name to match existing imports
            # For custom themes, we need to support various import styles
            if themes_dir == THEMES_DIRS[1]:  # Standard theme location (second in list)
                module_name = f"portprotonqt.themes.{theme_name}"
            else:  # Custom theme location (user's local directory - first in list)
                # For custom themes, we'll use the simple name but need to set up proper package structure
                module_name = theme_name

            spec = importlib.util.spec_from_file_location(module_name, styles_file)
            if spec is None or spec.loader is None:
                continue
            custom_theme = importlib.util.module_from_spec(spec)

            # Temporarily add the theme directory to sys.path to support relative imports
            theme_dir = os.path.dirname(styles_file)
            if theme_dir not in sys.path:
                sys.path.insert(0, theme_dir)
                path_added = True
            else:
                path_added = False

            # Register parent packages for the standard theme to support its imports
            if themes_dir == THEMES_DIRS[1]:  # Standard theme location (second in list)
                # Register the parent packages to support imports like 'portprotonqt.themes.standart.styles.constants'
                theme_parts = module_name.split('.')
                for i in range(1, len(theme_parts)):
                    pkg_name = '.'.join(theme_parts[:i])
                    if pkg_name not in sys.modules:
                        pkg_module = types.ModuleType(pkg_name)
                        if pkg_name == 'portprotonqt':
                            pkg_module.__path__ = [os.path.dirname(os.path.dirname(__file__))]
                        elif pkg_name == 'portprotonqt.themes':
                            pkg_module.__path__ = [os.path.join(os.path.dirname(os.path.dirname(__file__)), 'themes')]
                        elif pkg_name == f'portprotonqt.themes.{theme_name}':
                            pkg_module.__path__ = [theme_dir]
                        sys.modules[pkg_name] = pkg_module

                # Also register the 'styles' subpackage for the standard theme
                styles_subdir = os.path.join(theme_dir, 'styles')
                if os.path.isdir(styles_subdir):
                    styles_module_name = f"{module_name}.styles"
                    if styles_module_name not in sys.modules:
                        styles_pkg_module = types.ModuleType(styles_module_name)
                        styles_pkg_module.__path__ = [styles_subdir]
                        styles_pkg_module.__file__ = os.path.join(styles_subdir, '__init__.py')
                        sys.modules[styles_module_name] = styles_pkg_module

            # For custom themes, register the package structure to support various import styles
            if themes_dir == THEMES_DIRS[0] and theme_name != "standart":  # Custom theme (first in list) but not standard
                # Register the theme as a package to support relative imports
                theme_pkg_module = types.ModuleType(module_name)
                theme_pkg_module.__path__ = [theme_dir]
                theme_pkg_module.__file__ = os.path.join(theme_dir, '__init__.py')
                sys.modules[module_name] = theme_pkg_module

                # Also register the subpackages like 'themename.styles'
                styles_subdir = os.path.join(theme_dir, 'styles')
                if os.path.isdir(styles_subdir):
                    styles_module_name = f"{module_name}.styles"
                    styles_pkg_module = types.ModuleType(styles_module_name)
                    styles_pkg_module.__path__ = [styles_subdir]
                    styles_pkg_module.__file__ = os.path.join(styles_subdir, '__init__.py')
                    sys.modules[styles_module_name] = styles_pkg_module

            # Register the actual theme module and set its package if it's a custom theme
            sys.modules[module_name] = custom_theme
            if themes_dir == THEMES_DIRS[0] and theme_name != "standart":  # Custom theme (first in list) but not standard
                custom_theme.__package__ = module_name  # This enables relative imports

            _inject_parent_theme_constants(custom_theme, styles_file)

            try:
                spec.loader.exec_module(custom_theme)
            finally:
                # Remove the theme directory from sys.path if we added it
                if path_added:
                    sys.path.remove(theme_dir)

            if theme_name == "standart":
                return custom_theme
            meta = load_theme_metainfo(theme_name)
            return ThemeWrapper(custom_theme, metainfo=meta, inherit_chain=next_inherit_chain)
    raise FileNotFoundError(f"Styles file not found for theme '{theme_name}'")

class SystemThemeWatcher(QThread):
    """Watch desktop color scheme without blocking the UI thread."""

    theme_changed = Signal(bool)

    def __init__(self, initial_light: bool, parent=None) -> None:
        super().__init__(parent)
        self._last_light = initial_light

    def run(self) -> None:
        try:
            asyncio.run(self._watch_portal())
            return
        except Exception as e:
            logger.debug("Portal theme watcher unavailable: %s", e)
        self._poll_system_theme()

    async def _watch_portal(self) -> None:
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
            interface = cast(Any, proxy.get_interface("org.freedesktop.portal.Settings"))
            value = await interface.call_read(
                PORTAL_APPEARANCE_NAMESPACE,
                PORTAL_COLOR_SCHEME_KEY,
            )
            if int(_unwrap_variant(value)) == 0:
                raise RuntimeError("Portal does not provide a color scheme")
            self._emit_portal_theme(value)
            interface.on_setting_changed(self._on_portal_setting_changed)
            while not self.isInterruptionRequested():
                await asyncio.sleep(SYSTEM_THEME_POLL_STEP_MS / 1000)
        finally:
            bus.disconnect()

    def _on_portal_setting_changed(self, namespace: str, key: str, value: object) -> None:
        if namespace == PORTAL_APPEARANCE_NAMESPACE and key == PORTAL_COLOR_SCHEME_KEY:
            self._emit_portal_theme(value)

    def _emit_portal_theme(self, value: object) -> None:
        color_scheme = int(_unwrap_variant(value))
        if color_scheme not in (1, 2):
            return
        is_light = color_scheme == 2
        if is_light != self._last_light:
            self._last_light = is_light
            self.theme_changed.emit(is_light)

    def _poll_system_theme(self) -> None:
        elapsed_ms = SYSTEM_THEME_POLL_INTERVAL_MS
        while not self.isInterruptionRequested():
            if elapsed_ms >= SYSTEM_THEME_POLL_INTERVAL_MS:
                is_light = _is_system_light_theme()
                if is_light != self._last_light:
                    self._last_light = is_light
                    self.theme_changed.emit(is_light)
                elapsed_ms = 0
            self.msleep(SYSTEM_THEME_POLL_STEP_MS)
            elapsed_ms += SYSTEM_THEME_POLL_STEP_MS


class ThemeManager:
    """
    Class for managing application themes.
    Implement Singleton pattern for single instance.
    """
    _instance = None
    current_theme_name: str | None
    current_theme_module: Any | None
    _theme_module_cache: dict[str, Any]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.current_theme_name = None
            cls._instance.current_theme_module = None
            cls._instance._theme_module_cache = {}
        return cls._instance

    def get_available_themes(self) -> list:
        """Return list of available themes."""
        return list_themes()

    def is_custom_theme(self, theme_name: str) -> bool:
        """Return whether a theme is installed in the user theme directory."""
        if not _is_valid_theme_name(theme_name):
            return False
        theme_path = os.path.join(THEMES_DIRS[0], theme_name)
        return os.path.isdir(theme_path) and not os.path.islink(theme_path)

    def remove_custom_theme(self, theme_name: str) -> bool:
        """Remove a theme from the user theme directory."""
        if not self.is_custom_theme(theme_name):
            return False
        theme_path = os.path.join(THEMES_DIRS[0], theme_name)
        try:
            shutil.rmtree(theme_path)
        except OSError as e:
            logger.warning("Failed to remove custom theme '%s': %s", theme_name, e)
            return False
        self.invalidate_theme(theme_name)
        return True

    def invalidate_theme(self, theme_name: str) -> None:
        """Discard a cached theme after its files change."""
        self._theme_module_cache.pop(theme_name, None)
        _icon_dirs_cache.pop(theme_name, None)
        marker = f"_{theme_name}_"
        for cache_key in list(_icon_cache):
            if marker in cache_key:
                _icon_cache.pop(cache_key, None)
        if self.current_theme_name == theme_name:
            self.current_theme_name = None
            self.current_theme_module = None

    def get_cached_icon_names(self, theme_name: str) -> tuple[dict[int, str], dict[str, str]]:
        """Return cached icon identifiers before a live theme change."""
        marker = f"_{theme_name}_"
        qicons = {}
        paths = {}
        for cache_key, icon in _icon_cache.items():
            marker_index = cache_key.rfind(marker)
            if marker_index < 0:
                continue
            icon_name = cache_key[:marker_index]
            if isinstance(icon, QIcon) and not icon.isNull():
                qicons[icon.cacheKey()] = icon_name
            elif isinstance(icon, str):
                paths[icon] = icon_name
        return qicons, paths

    def apply_theme(self, theme_name: str):
        """
        Apply selected theme if not already applied.
        Return theme module or wrapper.
        """
        if self.current_theme_name == theme_name and self.current_theme_module is not None:
            return self.current_theme_module

        theme_module = self._theme_module_cache.get(theme_name)
        if theme_module is None:
            try:
                theme_module = load_theme(theme_name)
            except FileNotFoundError:
                logger.warning(f"Theme '{theme_name}' not found or unsafe, applying standard theme 'standart'")
                theme_name = "standart"
                theme_module = self._theme_module_cache.get(theme_name)
                if theme_module is None:
                    theme_module = load_theme(theme_name)
                ui_config.set_theme(theme_name)
            self._theme_module_cache[theme_name] = theme_module

        load_theme_fonts(theme_name)

        self.current_theme_name = theme_name
        self.current_theme_module = theme_module
        ui_config.set_theme(theme_name)

        from portprotonqt.sound_manager import SoundManager
        SoundManager().set_sounds_dirs(_resolve_sound_dirs(theme_name))

        logger.info("Theme '%s' successfully applied", theme_name)
        return theme_module

    def _get_theme_icon_colors(self, theme: object) -> dict:
        if isinstance(theme, ThemeWrapper):
            colors = vars(theme.custom_theme).get("ICON_COLORS", {})
        else:
            colors = vars(theme).get("ICON_COLORS", {})
        return colors if isinstance(colors, dict) else {}

    def _get_icon_color(self, icon_name: str, theme_name: str | None) -> str | None:
        if not theme_name:
            return None
        theme = self.current_theme_module if theme_name == self.current_theme_name else None
        if theme is None:
            import sys
            theme = sys.modules.get(f"portprotonqt.themes.{theme_name}") or sys.modules.get(theme_name)
        if theme is None:
            return None
        colors = self._get_theme_icon_colors(theme)
        color = colors.get(icon_name)
        return color if isinstance(color, str) else None

    def _colored_icon_path(self, icon_path: str, color: str) -> str | None:
        if not is_safe_image_file(icon_path):
            return None
        if not icon_path.lower().endswith(".svg"):
            return icon_path
        safe_color = _safe_svg_color(color)
        if safe_color is None:
            return icon_path
        target_path = _colored_svg_cache_path(icon_path, safe_color)
        if target_path is None:
            return icon_path
        if os.path.exists(target_path):
            return target_path
        if _write_colored_svg(icon_path, target_path, safe_color):
            return target_path
        return icon_path

    def get_icon(self, icon_name, theme_name=None, as_path=False):
        """
        Return QIcon from icons folder of current theme (including subdirectories),
        if file not found, from standard theme.
        If as_path=True, return icon path instead of QIcon.
        """
        theme_name = theme_name or self.current_theme_name
        supported_extensions = SUPPORTED_IMAGE_EXTENSIONS
        has_extension = any(icon_name.lower().endswith(ext) for ext in supported_extensions)
        base_name = os.path.splitext(icon_name)[0] if has_extension else icon_name
        icon_color = self._get_icon_color(base_name, theme_name)

        device_pixel_ratio = 1.0 if as_path else get_device_pixel_ratio()
        cache_key = f"{icon_name}_{theme_name}_{as_path}_{device_pixel_ratio}_{icon_color}"

        if cache_key in _icon_cache:
            return _icon_cache[cache_key]

        icon_path = None

        icon_map = build_icon_cache(theme_name)

        if base_name in icon_map:
            icon_path = icon_map[base_name]
            if not is_safe_image_file(icon_path):
                icon_path = None

        if not icon_path or not os.path.exists(icon_path):
            logger.error(f"Warning: icon '{icon_name}' not found")
            result = QIcon() if not as_path else None
            _icon_cache[cache_key] = result
            return result

        if icon_color:
            icon_path = self._colored_icon_path(icon_path, icon_color) or icon_path

        if as_path:
            _icon_cache[cache_key] = icon_path
            return icon_path

        icon = _load_icon(icon_path)
        _icon_cache[cache_key] = icon
        return icon

    def get_colored_icon_path(self, icon_name: str, color: str, theme_name: str | None = None) -> str | None:
        """
        Return a cached SVG path with currentColor replaced by color.
        Non-SVG icons and unsafe colors fall back to the original icon path.
        """
        has_extension = any(icon_name.lower().endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)
        if has_extension and os.path.exists(icon_name):
            icon_path = icon_name
        else:
            icon_path = self.get_icon(icon_name, theme_name, as_path=True)
        if not isinstance(icon_path, str):
            return None
        return self._colored_icon_path(icon_path, color)

    def get_theme_image(self, image_name, theme_name=None):
        """
        Return path to image from current theme folder.
        If not found, check standard theme.
        Accept icon name without extension and find matching file
        with supported extension (.svg, .png, .jpg, .webp, .jxl, etc.).
        """
        image_path = None
        theme_name = theme_name or self.current_theme_name

        # Extract base name without extension if present
        supported_extensions = SUPPORTED_IMAGE_EXTENSIONS
        has_extension = any(image_name.lower().endswith(ext) for ext in supported_extensions)
        base_name = os.path.splitext(image_name)[0] if has_extension else image_name

        # Build icon cache for this theme if not already done
        # Note: We reuse the same cache mechanism for all images in the theme
        icon_map = build_icon_cache(theme_name)

        # Look up the image in the cache
        if base_name in icon_map:
            image_path = icon_map[base_name]
            if not is_safe_image_file(image_path):
                image_path = None

        return image_path
