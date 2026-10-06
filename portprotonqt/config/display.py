"""Display configuration settings."""
import os
from pathlib import Path
from portprotonqt.config.base import BaseConfig
from portprotonqt.config.validators import validate_bool, validate_string
from portprotonqt.logger import get_logger

logger = get_logger(__name__)
AUTOSTART_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "ru.linux_gaming.PortProtonQt.desktop"


class DisplayConfig(BaseConfig):
    """Display configuration settings."""

    _section = "Display"

    def get_fullscreen(self) -> bool:
        """Get fullscreen mode setting."""
        return self._get_bool("fullscreen", False)

    def set_fullscreen(self, fullscreen: bool):
        """Set fullscreen mode."""
        validate_bool(fullscreen, "fullscreen")
        self._save_value("fullscreen", fullscreen, "bool")

    def get_auto_fullscreen_gamepad(self) -> bool:
        """Get auto-fullscreen for gamepad setting."""
        return self._get_bool("auto_fullscreen_gamepad", False)

    def set_auto_fullscreen_gamepad(self, auto: bool):
        """Set auto-fullscreen for gamepad."""
        validate_bool(auto, "auto_fullscreen_gamepad")
        self._save_value("auto_fullscreen_gamepad", auto, "bool")

    def get_boot_animation_enabled(self) -> bool:
        """Return whether fullscreen boot videos are enabled."""
        return self._get_bool("boot_animation_enabled", True)

    def set_boot_animation_enabled(self, enabled: bool) -> None:
        """Enable or disable fullscreen boot videos."""
        validate_bool(enabled, "boot_animation_enabled")
        self._save_value("boot_animation_enabled", enabled, "bool")

    def get_minimize_to_tray(self) -> bool:
        """Get minimize-to-tray setting."""
        return self._get_bool("minimize_to_tray", False)

    def set_minimize_to_tray(self, minimize: bool):
        """Set minimize-to-tray setting."""
        validate_bool(minimize, "minimize_to_tray")
        self._save_value("minimize_to_tray", minimize, "bool")

    def get_autostart_enabled(self) -> bool:
        """Get autostart on login setting."""
        enabled = self._get_bool("autostart_enabled", False)
        if enabled and not AUTOSTART_FILE.exists():
            self.set_autostart_enabled(False)
            return False
        return enabled

    def set_autostart_enabled(self, enabled: bool):
        """Set autostart on login setting."""
        validate_bool(enabled, "autostart_enabled")
        self._save_value("autostart_enabled", enabled, "bool")

    def get_start_minimized(self) -> bool:
        """Get start minimized setting."""
        return self._get_bool("start_minimized", False)

    def set_start_minimized(self, minimized: bool):
        """Set start minimized setting."""
        validate_bool(minimized, "start_minimized")
        self._save_value("start_minimized", minimized, "bool")

    def get_tray_menu_mode(self) -> str:
        """Get tray menu mode."""
        mode = self._get_str("tray_menu_mode", "compact")
        return mode if mode in ("detailed", "compact") else "compact"

    def set_tray_menu_mode(self, mode: str) -> None:
        """Set tray menu mode."""
        validate_string(mode, "tray_menu_mode", min_len=1, max_len=20)
        self._save_value("tray_menu_mode", mode, "str")


def apply_xdg_autostart(enabled: bool) -> bool:
    """Create or remove xdg-autostart desktop entry."""
    try:
        if enabled:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            exec_command = "portprotonqt"
            repo_root = Path(__file__).resolve().parent.parent.parent
            venv_portprotonqt = repo_root / ".venv" / "bin" / "portprotonqt"
            if repo_root.joinpath(".git").exists() and venv_portprotonqt.exists():
                exec_command = f'"{venv_portprotonqt}"'

            desktop_entry = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=PortProtonQt\n"
                f"Exec={exec_command}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            AUTOSTART_FILE.write_text(desktop_entry, encoding="utf-8")
            logger.info("Enabled xdg-autostart at %s", AUTOSTART_FILE)
            return True

        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
            logger.info("Disabled xdg-autostart at %s", AUTOSTART_FILE)
        return True
    except OSError as error:
        logger.error("Failed to update xdg-autostart: %s", error)
        return False
