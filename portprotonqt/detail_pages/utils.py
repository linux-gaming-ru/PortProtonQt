"""Detail page utilities for PortProtonQt."""

import os
import re
from weakref import WeakKeyDictionary
from collections.abc import Callable
from PySide6.QtWidgets import QWidget, QApplication, QLabel, QGraphicsBlurEffect, QGraphicsOpacityEffect, QGraphicsPixmapItem, QGraphicsScene
from PySide6.QtCore import QTimer, Qt, QObject, Signal, QPropertyAnimation, QByteArray
from PySide6.QtGui import QBrush, QImage, QPainter, QPalette, QPixmap

from portprotonqt.image_utils import get_animated_cover_pixmap
from portprotonqt.image_utils import load_pixmap_async, round_corners, set_animated_cover
from portprotonqt.config import (
    extract_exec_target_path,
    favorites_config,
    parse_desktop_entry,
)
from portprotonqt.logger import get_logger
from portprotonqt.animations.detail_background import DetailBackgroundAnimations

logger = get_logger(__name__)
_pixmap_relays: WeakKeyDictionary[QWidget, "_PixmapReadyRelay"] = WeakKeyDictionary()
_cover_reveal_animations: WeakKeyDictionary[QLabel, QPropertyAnimation] = WeakKeyDictionary()
_detail_backgrounds = DetailBackgroundAnimations()


class _PixmapReadyRelay(QObject):
    """Relay pixmap updates to GUI thread safely."""

    pixmap_ready = Signal(object)


class _AutoinstallCheckRelay(QObject):
    """Relay autoinstall check results to GUI thread safely."""

    result_ready = Signal(bool)


def setup_image_loading(
    detail_page: QWidget,
    image_label: QLabel,
    cover_path: str | None,
    main_window,
    cover_width: int = 300,
    cover_height: int = 450,
) -> None:
    """Setup async image loading with palette-based stylesheet."""
    relay = _PixmapReadyRelay(detail_page)
    relay.pixmap_ready.connect(
        lambda pixmap: _on_pixmap_ready(pixmap, detail_page, image_label, main_window),
        Qt.ConnectionType.QueuedConnection,
    )
    _pixmap_relays[detail_page] = relay

    fallback_exe = detail_page.property("fallbackExe") or ""
    fallback_icon_path = detail_page.property("fallbackIconPath") or ""
    if cover_path:
        _prepare_cover_reveal(image_label)
        if _set_animated_cover((detail_page, image_label), cover_path, (cover_width, cover_height), main_window):
            return
    if cover_path or fallback_exe:
        if not cover_path:
            _prepare_cover_reveal(image_label)
        load_pixmap_async(
            cover_path or "",
            cover_width,
            cover_height,
            lambda pixmap: relay.pixmap_ready.emit(pixmap),
            app_name=str(detail_page.property("coverCacheKey") or ""),
            fallback_exe=fallback_exe,
            fallback_icon_path=fallback_icon_path,
        )
    else:
        _apply_no_cover_style(detail_page, main_window.theme)

def _set_animated_cover(
    cover_widgets: tuple[QWidget, QLabel],
    cover_path: str,
    cover_size: tuple[int, int],
    main_window,
) -> bool:
    """Set animated cover on detail page."""
    if not os.path.isfile(cover_path):
        return False
    detail_page, image_label = cover_widgets
    if not set_animated_cover(image_label, cover_path, cover_size[0], cover_size[1], 10):
        return False
    setup_cover_background(detail_page, get_animated_cover_pixmap(image_label), main_window)
    _reveal_cover(image_label, main_window.theme)
    return True


def _on_pixmap_ready(pixmap: QPixmap, detail_page: QWidget, image_label: QLabel, main_window) -> None:
    """Handle pixmap loaded callback."""
    if not _is_detail_page_valid(detail_page):
        return
    try:
        rounded = round_corners(pixmap, 10)
        image_label.setPixmap(rounded)
        _reveal_cover(image_label, main_window.theme)
        logger.debug("Pixmap set for imageLabel")
        setup_cover_background(detail_page, pixmap, main_window)
    except RuntimeError:
        logger.warning("Detail page already deleted, skipping pixmap update")


def _prepare_cover_reveal(image_label: QLabel) -> None:
    """Hide cover until the loaded pixmap is ready."""
    effect = QGraphicsOpacityEffect(image_label)
    effect.setOpacity(0.0)
    image_label.setGraphicsEffect(effect)


def _reveal_cover(image_label: QLabel, theme) -> None:
    """Show cover smoothly after async loading finishes."""
    effect = image_label.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(image_label)
        image_label.setGraphicsEffect(effect)

    animation_type = theme.GAME_CARD_ANIMATION.get("detail_page_animation_type", "fade")
    duration_key = "detail_page_fade_duration"
    default_duration = 350
    if animation_type.startswith("slide_"):
        duration_key = "detail_page_slide_duration"
        default_duration = 500
    elif animation_type == "bounce":
        duration_key = "detail_page_bounce_duration"
        default_duration = 400
    duration = theme.GAME_CARD_ANIMATION.get(duration_key, default_duration)
    animation = QPropertyAnimation(effect, QByteArray(b"opacity"), image_label)
    animation.setDuration(duration)
    animation.setStartValue(effect.opacity())
    animation.setEndValue(1.0)
    animation.finished.connect(effect.deleteLater)
    animation.finished.connect(lambda: _cover_reveal_animations.pop(image_label, None))
    _cover_reveal_animations[image_label] = animation
    animation.start()


def setup_cover_background(
    detail_page: QWidget, pixmap: QPixmap | None, main_window, theme=None
) -> None:
    """Setup palette-based stylesheet after image load."""
    if pixmap is None:
        return
    active_theme = theme or main_window.theme
    if getattr(active_theme, "DETAIL_PAGE_BG_MODE", "gradient") == "blur":
        _apply_blurred_cover(detail_page, pixmap, active_theme)
        return

    def on_palette_ready(palette: list) -> None:
        _on_palette_ready(palette, detail_page, main_window, active_theme)

    num_colors = getattr(active_theme, 'DETAIL_PAGE_PALETTE_COLORS', 5)
    if num_colors < 2:
        num_colors = 2
    main_window.getColorPalette_from_pixmap(pixmap, num_colors=num_colors, callback=on_palette_ready)


def remove_cover_background(widget: QWidget) -> None:
    """Remove a shared cover-driven background and stop its animation."""
    _remove_wave_background(widget)
    _detail_backgrounds.remove(widget)
    widget.setStyleSheet("")
    widget.setAutoFillBackground(False)
    if isinstance(widget, QLabel):
        widget.clear()


def _on_palette_ready(
    palette: list, detail_page: QWidget, main_window, theme
) -> None:
    """Handle palette ready callback."""
    if not _is_detail_page_valid(detail_page):
        return
    _apply_palette_stylesheet(detail_page, palette, main_window, theme)


def _apply_blurred_cover(widget: QWidget, pixmap: QPixmap, theme) -> None:
    config = theme.DETAIL_PAGE_BACKGROUNDS.get("blur", {})
    width, height = config.get("render_resolution", (1280, 720))
    scaled = pixmap.scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    source = scaled.copy(
        (scaled.width() - width) // 2, (scaled.height() - height) // 2,
        width, height,
    )
    item = QGraphicsPixmapItem(source)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(config.get("radius", 64))
    item.setGraphicsEffect(effect)
    scene = QGraphicsScene()
    scene.addItem(item)
    image = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()
    background = QPixmap.fromImage(image).scaled(widget.size())
    if isinstance(widget, QLabel):
        widget.setPixmap(background)
        return
    palette = widget.palette()
    palette.setBrush(QPalette.ColorRole.Window, QBrush(background))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


def _build_palette_stops(dark_palette: list) -> str:
    """Build gradient stops from palette with even positions."""
    count = len(dark_palette)
    if count == 0:
        return ""
    if count == 1:
        return f"stop:0 {dark_palette[0].name()}"
    n = count - 1
    return ",\n".join(
        f"stop:{i/n:.2f} {dark_palette[i].name()}" for i in range(count)
    )


def _resolve_gradient_stops(theme, dark_palette: list) -> str:
    """Resolve gradient stops from DETAIL_PAGE_GRADIENT or palette.

    DETAIL_PAGE_GRADIENT accepts:
    - None: palette colors at even positions
    - str: raw QSS stop string (full override)
    - list of float: palette colors at specified positions
    - list of dict/tuple/str: custom stops with position+color
    """
    gradient_stops = _resolve_gradient_config(theme).get("stops")
    if gradient_stops is None:
        return _build_palette_stops(dark_palette)
    if isinstance(gradient_stops, str):
        return gradient_stops
    if isinstance(gradient_stops, list) and gradient_stops and isinstance(
        gradient_stops[0], (int, float)
    ):
        n = len(dark_palette)
        return ",\n".join(
            f"stop:{pos} {dark_palette[min(i, n - 1)].name()}"
            for i, pos in enumerate(gradient_stops)
        )
    stop_parts = []
    for item in gradient_stops:
        if isinstance(item, str):
            stop_parts.append(item)
        elif isinstance(item, dict):
            stop_parts.append(f"stop:{item['position']} {item['color']}")
        else:
            stop_parts.append(f"stop:{item[0]} {item[1]}")
    return ",\n".join(stop_parts)


def _resolve_gradient_config(theme: object) -> dict:
    """Resolve nested gradient settings with legacy theme compatibility."""
    backgrounds = getattr(theme, "DETAIL_PAGE_BACKGROUNDS", {})
    config = dict(backgrounds.get("gradient", {})) if isinstance(backgrounds, dict) else {}
    legacy_names = {
        "stops": "DETAIL_PAGE_GRADIENT",
        "type": "DETAIL_PAGE_GRADIENT_TYPE",
        "x1": "DETAIL_PAGE_GRADIENT_X1",
        "y1": "DETAIL_PAGE_GRADIENT_Y1",
        "x2": "DETAIL_PAGE_GRADIENT_X2",
        "y2": "DETAIL_PAGE_GRADIENT_Y2",
        "cx": "DETAIL_PAGE_GRADIENT_CX",
        "cy": "DETAIL_PAGE_GRADIENT_CY",
        "radius": "DETAIL_PAGE_GRADIENT_RADIUS",
        "fx": "DETAIL_PAGE_GRADIENT_FX",
        "fy": "DETAIL_PAGE_GRADIENT_FY",
    }
    for key, legacy_name in legacy_names.items():
        if hasattr(theme, legacy_name):
            config[key] = getattr(theme, legacy_name)
    return config


def _apply_palette_stylesheet(
    detail_page: QWidget, palette: list, main_window, theme
) -> None:
    """Apply palette-based stylesheet to detail page."""
    try:
        dark_palette = [
            main_window.darkenColor(color, factor=200) for color in palette
        ]
        gradient_config = _resolve_gradient_config(theme)
        stops = _resolve_gradient_stops(theme, dark_palette)
        gradient_type = gradient_config.get("type", "linear")

        if gradient_type == 'radial':
            cx = gradient_config.get("cx", 0.5)
            cy = gradient_config.get("cy", 0.5)
            radius = gradient_config.get("radius", 0.5)
            fx = gradient_config.get("fx", 0.5)
            fy = gradient_config.get("fy", 0.5)

            stylesheet = f"""
            QWidget {{
                background: qradialgradient(cx:{cx}, cy:{cy}, radius:{radius},
                                            fx:{fx}, fy:{fy},
                                            {stops});
                border-radius: 0px;
            }}
            """
        else:
            x1 = gradient_config.get("x1", 0)
            y1 = gradient_config.get("y1", 0)
            x2 = gradient_config.get("x2", 1)
            y2 = gradient_config.get("y2", 1)

            stylesheet = f"""
            QWidget {{
                background: qlineargradient(x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2},
                                            {stops});
                border-radius: 0px;
            }}
            """

        detail_page.setStyleSheet(stylesheet)
        _setup_wave_background(detail_page, dark_palette, theme)
        detail_page.update()
        logger.debug("Stylesheet updated with palette")
    except RuntimeError:
        logger.warning("Detail page already deleted, skipping palette update")


_wave_states: WeakKeyDictionary[QWidget, dict] = WeakKeyDictionary()


def _setup_wave_background(detail_page: QWidget, dark_palette: list, theme) -> None:
    """Setup wave background overlay based on theme DETAIL_PAGE_BG_MODE."""
    bg_mode = getattr(theme, "DETAIL_PAGE_BG_MODE", "gradient")

    if _detail_backgrounds.setup(detail_page, dark_palette, theme):
        _remove_wave_background(detail_page)
        return
    _detail_backgrounds.remove(detail_page)

    if bg_mode not in {"waves", "static_waves"}:
        _remove_wave_background(detail_page)
        return

    backgrounds = getattr(theme, "DETAIL_PAGE_BACKGROUNDS", {})
    wave_config = backgrounds.get("waves", {}) if isinstance(backgrounds, dict) else {}
    if hasattr(theme, "DETAIL_PAGE_WAVES"):
        wave_config = theme.DETAIL_PAGE_WAVES
    state = _wave_states.get(detail_page)
    if state is None:
        state = {
            "palette": dark_palette,
            "config": wave_config,
            "phase": 0.0,
            "timer": None,
            "original_paint": None,
        }
        _wave_states[detail_page] = state
    else:
        state["palette"] = dark_palette
        state["config"] = wave_config

    if state["original_paint"] is not None:
        return

    state["original_paint"] = detail_page.paintEvent

    def _wave_paint_event(event) -> None:
        paint_fn = state["original_paint"]
        if paint_fn is not None:
            paint_fn(event)
        _paint_waves(detail_page, state)

    detail_page.paintEvent = _wave_paint_event

    if bg_mode == "waves" and state["timer"] is None:
        speed = wave_config.get("animation_speed", 0.03)
        interval = wave_config.get("animation_interval_ms", 30)
        timer = QTimer(detail_page)
        timer.setInterval(interval)

        def _tick() -> None:
            if not _is_detail_page_valid(detail_page):
                timer.stop()
                return
            state["phase"] += speed
            detail_page.update()

        timer.timeout.connect(_tick)
        timer.start()
        state["timer"] = timer


def _remove_wave_background(detail_page: QWidget) -> None:
    """Remove wave background overlay if present."""
    state = _wave_states.pop(detail_page, None)
    if state is None:
        return
    timer = state.get("timer")
    if timer is not None:
        timer.stop()
        timer.deleteLater()
    original = state.get("original_paint")
    if original is not None:
        detail_page.paintEvent = original


def _paint_waves(detail_page: QWidget, state: dict) -> None:
    """Paint wave shapes on the detail page background."""
    import math
    from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush

    palette = state.get("palette", [])
    config = state.get("config", {})
    phase = state.get("phase", 0.0)
    if not palette:
        return

    painter = QPainter(detail_page)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    w = float(detail_page.width())
    h = float(detail_page.height())

    layer_count = config.get("layer_count", 4)
    amplitude = h * config.get("wave_amplitude_ratio", 0.06)
    frequency = config.get("wave_frequency", 2.0)
    spacing = h * config.get("layer_spacing_ratio", 0.04)
    base_opacity = config.get("base_opacity", 0.45)
    decay = config.get("opacity_decay", 0.85)

    palette_len = len(palette)
    for i in range(layer_count):
        base_color = palette[i % palette_len]
        opacity = base_opacity * (decay ** i)
        color = QColor(base_color)
        color.setAlphaF(min(opacity, 1.0))
        y_offset = h - (i + 1) * spacing - amplitude

        path = QPainterPath()
        path.moveTo(0.0, h)
        steps = max(int(w / 4), 20)
        for s in range(steps + 1):
            x = w * s / steps
            wave = math.sin(frequency * math.pi * s / steps + phase + i * 0.8)
            y = y_offset + amplitude * wave
            path.lineTo(x, y)
        path.lineTo(w, h)
        path.closeSubpath()

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

    painter.end()


def _apply_no_cover_style(detail_page: QWidget, theme) -> None:
    """Apply no-cover stylesheet to detail page."""
    try:
        detail_page.setStyleSheet(theme.DETAIL_PAGE_NO_COVER_STYLE)
        _remove_wave_background(detail_page)
        _detail_backgrounds.remove(detail_page)
        detail_page.update()
    except RuntimeError:
        logger.warning("Detail page already deleted, skipping no-cover stylesheet update")


def _is_detail_page_valid(detail_page: QWidget) -> bool:
    """Check if detail page is still valid and visible."""
    return (
        detail_page is not None
        and not detail_page.isHidden()
        and detail_page.parent() is not None
    )


def validate_detail_page(detail_page: QWidget) -> bool:
    """Validate detail page before operations."""
    if not _is_detail_page_valid(detail_page):
        logger.warning("Detail page is None, hidden, or no longer valid")
        return False
    return True


def set_opacity_safe(detail_page: QWidget) -> bool:
    """Safely set window opacity on detail page."""
    try:
        detail_page.setWindowOpacity(1.0)
        return True
    except RuntimeError:
        logger.warning("Detail page is None, hidden, or no longer valid, skipping opacity set")
        return False


def create_focus_helper(
    detail_page: QWidget,
    main_window,
    button: QWidget,
    stacked_widget,
) -> Callable[[], None]:
    """Create focus helper function for detail page buttons."""

    def can_focus_detail_page() -> bool:
        return stacked_widget.indexOf(detail_page) >= 0

    def try_set_focus() -> None:
        try:
            if not can_focus_detail_page():
                return
            if not (button and not button.isHidden()):
                return

            stacked_widget.setCurrentWidget(detail_page)
            detail_page.setFocus(Qt.FocusReason.OtherFocusReason)
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            button.update()
            detail_page.raise_()
            main_window.activateWindow()

            if button.hasFocus():
                logger.debug("Button successfully received focus")
            else:
                logger.debug("Retrying focus...")
                QTimer.singleShot(20, retry_focus)
        except RuntimeError:
            logger.debug("Detail focus target was deleted")

    def retry_focus() -> None:
        try:
            if not can_focus_detail_page():
                return
            if not (button and not button.isHidden() and not button.hasFocus()):
                return

            QApplication.processEvents()
            main_window.activateWindow()
            stacked_widget.setCurrentWidget(detail_page)
            detail_page.raise_()
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            button.update()

            if not button.hasFocus():
                logger.debug("Final retry...")
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.setFocus(Qt.FocusReason.OtherFocusReason)
                QApplication.processEvents()

                if button.hasFocus():
                    logger.debug("Button received focus after final retry")
                else:
                    logger.debug("Button still doesn't have focus")
        except RuntimeError:
            logger.debug("Detail focus target was deleted")

    return try_set_focus


def toggle_favorite(game_name: str, main_window) -> str:
    """Toggle favorite status for a game."""
    favorites = favorites_config.get_games()
    if game_name in favorites:
        favorites.remove(game_name)
        favorite_icon_name = "star_fav"
    else:
        favorites.append(game_name)
        favorite_icon_name = "star_fav_full"
    favorites_config.set_games(favorites)

    if hasattr(main_window, "game_library_manager"):
        main_window.game_library_manager.update_game_grid()

    return favorite_icon_name


def check_autoinstall_installed(
    script_name: str,
    game_name: str,
    portproton_location: str | None,
    callback: Callable[..., None] | None = None,
) -> bool | None:
    """Check if auto-install game is already installed.

    If callback is provided, runs asynchronously and calls callback with result.
    If callback is None, runs synchronously and returns result.
    """
    if not portproton_location:
        if callback:
            callback(False)
            return None
        return False

    if callback:
        _check_autoinstall_installed_async(
            script_name, game_name, portproton_location, callback
        )
        return None

    return _check_autoinstall_installed_sync(
        script_name, game_name, portproton_location
    )


def _check_autoinstall_installed_sync(
    script_name: str,
    game_name: str,
    portproton_location: str,
) -> bool:
    """Synchronous check for installed autoinstall game."""
    try:
        desktop_files = os.listdir(portproton_location)
    except (OSError, AttributeError):
        return False

    autoinstall_exe, autoinstall_path = _get_autoinstall_exe_target(script_name)
    if not autoinstall_exe:
        return False

    for file in desktop_files:
        if _check_desktop_file(file, portproton_location, autoinstall_exe, autoinstall_path):
            return True

    return False


def find_autoinstall_entry_path(
    script_name: str,
    portproton_location: str | None,
) -> str | None:
    """Find installed autoinstall desktop entry path."""
    if not portproton_location:
        return None

    try:
        desktop_files = os.listdir(portproton_location)
    except (OSError, AttributeError):
        return None

    autoinstall_exe, autoinstall_path = _get_autoinstall_exe_target(script_name)
    if not autoinstall_exe:
        return None

    for filename in desktop_files:
        if not _check_desktop_file(filename, portproton_location, autoinstall_exe, autoinstall_path):
            continue
        return os.path.join(portproton_location, filename)

    return None


def _check_autoinstall_installed_async(
    script_name: str,
    game_name: str,
    portproton_location: str,
    callback: Callable[[bool], None],
) -> None:
    """Asynchronous check for installed autoinstall game."""
    from threading import Thread

    relay = _AutoinstallCheckRelay(QApplication.instance())

    def on_result(result: bool) -> None:
        callback(result)
        relay.deleteLater()

    relay.result_ready.connect(on_result, Qt.ConnectionType.QueuedConnection)

    def worker() -> None:
        result = _check_autoinstall_installed_sync(
            script_name, game_name, portproton_location
        )
        relay.result_ready.emit(result)

    thread = Thread(target=worker, daemon=True)
    thread.start()


def _check_desktop_file(
    filename: str,
    location: str,
    autoinstall_exe: str,
    autoinstall_path: str,
) -> bool:
    """Check if desktop file targets autoinstall exe."""
    if not filename.endswith(".desktop"):
        return False

    desktop_entry = parse_desktop_entry(os.path.join(location, filename))
    if not desktop_entry:
        return False

    exec_path = extract_exec_target_path(desktop_entry.get("Exec", ""))
    if not exec_path:
        return False
    if not os.path.isfile(exec_path):
        return False

    exec_name = os.path.basename(exec_path).lower()
    real_exec_name = os.path.basename(os.path.realpath(exec_path)).lower()
    if autoinstall_path:
        return (
            _path_matches_autoinstall(exec_path, autoinstall_path)
            or _path_matches_autoinstall(os.path.realpath(exec_path), autoinstall_path)
        )
    return autoinstall_exe.lower() in (exec_name, real_exec_name)


def _get_autoinstall_exe_target(script_name: str) -> tuple[str, str]:
    script_path = script_name
    if not os.path.isfile(script_path):
        return "", ""

    install_exe = ""
    install_path = ""
    try:
        with open(script_path, encoding="utf-8") as script_file:
            for line in script_file:
                if line.lstrip().startswith("#"):
                    continue
                if "PW_EXE_FILE" in line:
                    exe_name = _extract_exe_name(line)
                    if exe_name:
                        return exe_name, _extract_exe_path(line)
                if "PW_AUTOINSTALL_EXE" not in line:
                    continue
                exe_name = _extract_exe_name(line)
                if exe_name:
                    install_exe = exe_name
                    install_path = _extract_exe_path(line)
    except OSError:
        return "", ""

    return install_exe, install_path


def _extract_exe_name(line: str) -> str:
    quoted_exe = re.search(r"['\"]([^/'\"]+\.exe)['\"]", line, re.IGNORECASE)
    if quoted_exe:
        return quoted_exe.group(1)
    for part in line.replace("\\", "/").split("/"):
        clean_part = part.strip().strip('"\' }')
        if clean_part.lower().endswith(".exe"):
            return clean_part
    return ""


def _extract_exe_path(line: str) -> str:
    paths = re.findall(r"['\"]([^'\"]+\.exe)['\"]", line.replace("\\", "/"), re.IGNORECASE)
    for path in paths:
        drive_index = path.lower().find("drive_c/")
        if drive_index >= 0:
            return path[drive_index:].lower()
        if "/" in path and not path.startswith("$"):
            return path.lower()
    return ""


def _path_matches_autoinstall(exec_path: str, autoinstall_path: str) -> bool:
    normalized_path = exec_path.replace("\\", "/").lower()
    pattern_parts = []
    for part in autoinstall_path.split("/"):
        if part.startswith("$"):
            pattern_parts.append("[^/]+")
        else:
            pattern_parts.append(re.escape(part))
    pattern = r"(^|.*/)" + "/".join(pattern_parts) + r"$"
    return re.search(pattern, normalized_path) is not None
