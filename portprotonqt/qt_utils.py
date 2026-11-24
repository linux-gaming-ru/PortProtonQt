from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def get_device_pixel_ratio() -> float:
    """Return current device pixel ratio with a safe fallback."""
    app = QApplication.instance()
    return app.devicePixelRatio() if isinstance(app, QApplication) else 1.0


def get_system_dpi_for_wine() -> str:
    """Return Wine LogPixels value calculated from system scale."""
    app_instance = QApplication.instance()
    if isinstance(app_instance, QGuiApplication):
        window = app_instance.focusWindow()
        if window is None:
            for widget in QApplication.topLevelWidgets():
                if widget.isVisible() and widget.windowHandle() is not None:
                    window = widget.windowHandle()
                    break
        if window is not None:
            dpi_value = int(round(96.0 * window.devicePixelRatio()))
            if dpi_value > 96:
                return str(dpi_value)

    return "96"


def get_screen_info() -> tuple[str, str, str]:
    """Get screen resolution, output name and refresh rate in Hz."""
    app_instance = QApplication.instance()
    default_resolution = "1920x1080"
    default_primary = ""
    default_refresh_rate = 60.0
    if not isinstance(app_instance, QGuiApplication):
        return (
            f"PW_SCREEN_RESOLUTION={default_resolution}",
            f"PW_SCREEN_PRIMARY={default_primary}",
            f"PW_SCREEN_REFRESH_RATE={default_refresh_rate:.2f}",
        )

    screen = app_instance.primaryScreen()
    if screen is None:
        screens = app_instance.screens()
        if screens:
            screen = screens[0]

    if screen is None:
        return (
            f"PW_SCREEN_RESOLUTION={default_resolution}",
            f"PW_SCREEN_PRIMARY={default_primary}",
            f"PW_SCREEN_REFRESH_RATE={default_refresh_rate:.2f}",
        )

    geometry = screen.geometry()
    if geometry.width() > 0 and geometry.height() > 0:
        resolution = f"{geometry.width()}x{geometry.height()}"
    else:
        resolution = default_resolution

    primary = screen.name() or default_primary
    return (
        f"PW_SCREEN_RESOLUTION={resolution}",
        f"PW_SCREEN_PRIMARY={primary}",
        f"PW_SCREEN_REFRESH_RATE={screen.refreshRate():.2f}",
    )
