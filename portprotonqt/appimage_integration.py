"""User-level AppImage desktop integration."""
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QThread, Signal

from portprotonqt.config import get_portproton_location, migrate_legacy_shortcut
from portprotonqt.localization import _
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

APP_ID = "ru.linux_gaming.PortProtonQt"
MIME_PACKAGE_NAME = f"{APP_ID}.xml"
DESKTOP_DATABASE_TIMEOUT = 10
EXECUTABLE_MODE = 0o755
WINDOWS_MIME_TYPES = (
    "application/x-ms-dos-executable;application/x-msdos-program;"
    "application/x-ms-dos-exec;"
    "application/x-dosexec;application/vnd.microsoft.portable-executable;"
)
INTEGRATION_MODES = ("log", "silent")


def _find_appimage_asset(appdir: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = appdir / name
        if path.is_file():
            return path
    return None


def _copy_appimage(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    temporary = destination.with_suffix(".appimage.part")
    shutil.copy2(source, temporary)
    temporary.chmod(EXECUTABLE_MODE)
    temporary.replace(destination)


def _remove_existing_integration(applications_dir: Path, icon_dir: Path) -> None:
    desktop_names = (
        f"{APP_ID}.desktop",
        f"{APP_ID}.log.desktop",
        f"{APP_ID}.silent.desktop",
    )
    for name in desktop_names:
        (applications_dir / name).unlink(missing_ok=True)
    for suffix in (".svg", ".png"):
        (icon_dir / f"{APP_ID}{suffix}").unlink(missing_ok=True)


def _rewrite_main_desktop(content: str, appimage: Path) -> str:
    exec_line = f"Exec={shlex.join([str(appimage), '%u'])}"
    content = re.sub(r"^Exec=.*$", exec_line, content, count=1, flags=re.MULTILINE)
    content = re.sub(r"^Icon=.*$", f"Icon={APP_ID}", content, flags=re.MULTILINE)
    if re.search(r"^TryExec=", content, flags=re.MULTILINE):
        return re.sub(
            r"^TryExec=.*$",
            f"TryExec={appimage}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
    return content.replace("Type=Application\n", f"Type=Application\nTryExec={appimage}\n", 1)


def _mode_desktop(mode: str, appimage: Path) -> str:
    action = _("Run in logging mode") if mode == "log" else _("Run in silent mode")
    exec_line = shlex.join([str(appimage), f"--{mode}", "%u"])
    return (
        "[Desktop Entry]\n"
        f"Name=PortProtonQt — {action}\n"
        f"Exec={exec_line}\n"
        f"TryExec={appimage}\n"
        "Type=Application\n"
        f"Comment={action}\n"
        "Terminal=false\n"
        f"Icon={APP_ID}\n"
        f"StartupWMClass={APP_ID}\n"
        "Categories=Game;\n"
        "NoDisplay=true\n"
        f"MimeType={WINDOWS_MIME_TYPES}\n"
        "StartupNotify=true\n"
    )


def _install_desktop_files(
    source: Path,
    applications_dir: Path,
    appimage: Path,
) -> None:
    content = source.read_text(encoding="utf-8")
    rewritten_content = _rewrite_main_desktop(content, appimage)
    main_path = applications_dir / f"{APP_ID}.desktop"
    main_path.write_text(rewritten_content, encoding="utf-8")
    desktop_dir = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    )
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = desktop_dir / f"{APP_ID}.desktop"
    desktop_path.write_text(rewritten_content, encoding="utf-8")
    desktop_path.chmod(EXECUTABLE_MODE)
    for mode in INTEGRATION_MODES:
        path = applications_dir / f"{APP_ID}.{mode}.desktop"
        path.write_text(_mode_desktop(mode, appimage), encoding="utf-8")


def _set_default_mime_handlers() -> None:
    desktop_id = f"{APP_ID}.desktop"
    for mime_type in WINDOWS_MIME_TYPES.rstrip(";").split(";"):
        try:
            subprocess.run(
                ["xdg-mime", "default", desktop_id, mime_type],
                check=True,
                timeout=DESKTOP_DATABASE_TIMEOUT,
            )
        except FileNotFoundError as error:
            logger.warning("Failed to set default MIME handler: %s", error)
            return
        except subprocess.SubprocessError as error:
            logger.warning("Failed to set default handler for %s: %s", mime_type, error)


def _get_appimage_metadata(appdir: Path) -> tuple[Path, Path]:
    desktop = _find_appimage_asset(
        appdir,
        (
            f"{APP_ID}.desktop",
            f"usr/share/applications/{APP_ID}.desktop",
            f"share/applications/{APP_ID}.desktop",
        ),
    )
    icon = appdir / f"{APP_ID}.svg"
    if not desktop or not icon.is_file():
        raise FileNotFoundError("AppImage desktop metadata is incomplete")
    return desktop, icon


def _install_mime_package(appdir: Path, data_home: Path) -> None:
    source = _find_appimage_asset(
        appdir,
        (
            f"share/mime/packages/{MIME_PACKAGE_NAME}",
            f"usr/share/mime/packages/{MIME_PACKAGE_NAME}",
        ),
    )
    if not source:
        raise FileNotFoundError("AppImage MIME metadata is incomplete")
    mime_dir = data_home / "mime"
    packages_dir = mime_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, packages_dir / MIME_PACKAGE_NAME)
    subprocess.run(
        ["update-mime-database", str(mime_dir)],
        check=True,
        timeout=DESKTOP_DATABASE_TIMEOUT,
    )


def integrate_appimage() -> Path:
    """Install the running AppImage and its desktop handlers for this user."""
    source = Path(os.environ["APPIMAGE"]).expanduser()
    appdir = Path(os.environ["APPDIR"]).expanduser()
    if not source.is_file():
        raise FileNotFoundError("AppImage desktop metadata is incomplete")
    desktop_source, icon_source = _get_appimage_metadata(appdir)

    appimages_dir = Path.home() / "AppImages"
    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))
    applications_dir = data_home / "applications"
    icon_dir = data_home / "icons"
    appimages_dir.mkdir(parents=True, exist_ok=True)
    applications_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)

    destination = appimages_dir / "portprotonqt.appimage"
    resolved_icon = icon_source.resolve()
    icon = icon_dir / f"{APP_ID}.svg"
    _copy_appimage(source, destination)
    # Remove after the legacy AppImage migration period.
    legacy_appimage = Path.home() / "Applications/PortProtonQt.AppImage"
    if legacy_appimage.resolve() != destination.resolve():
        portproton_location = get_portproton_location()
        migrate_legacy_shortcut(
            portproton_location or "",
            launcher_command=[str(destination), "--silent"],
        )
    _remove_existing_integration(applications_dir, icon_dir)
    shutil.copy2(resolved_icon, icon)
    _install_desktop_files(desktop_source, applications_dir, destination)
    _install_mime_package(appdir, data_home)
    _set_default_mime_handlers()
    try:
        subprocess.run(
            ["update-desktop-database", str(applications_dir)],
            check=False,
            timeout=DESKTOP_DATABASE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        logger.warning("Failed to update desktop database: %s", error)
    if legacy_appimage.resolve() != destination.resolve():
        legacy_appimage.unlink(missing_ok=True)
    return destination


class AppImageIntegrationWorker(QThread):
    """Install AppImage integration outside the UI thread."""

    completed = Signal(bool, str)

    def run(self) -> None:
        try:
            destination = integrate_appimage()
            self.completed.emit(True, str(destination))
        except (OSError, subprocess.SubprocessError, KeyError) as error:
            logger.error("Failed to integrate AppImage: %s", error)
            self.completed.emit(False, str(error))
