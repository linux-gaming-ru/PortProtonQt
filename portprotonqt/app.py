import argparse
import sys
import os
import subprocess
import threading
import urllib.error
import urllib.request
from urllib.parse import quote, unquote
from logging import Logger

__app_id__ = "ru.linux_gaming.PortProtonQt"
__app_name__ = "PortProtonQt"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)
from PySide6.QtGui import QAction, QIcon

from portprotonqt.config import (
    consume_download_counter_skip,
    display_config,
    get_portproton_start_command,
    get_portproton_location,
    save_portdata_path_to_config,
    ui_config,
    update_app_version,
    window_config,
)
from portprotonqt.logger import get_logger, setup_logger
from portprotonqt.cli import (
    parse_args,
    is_portproton_url,
    parse_portproton_url,
    parse_portprotonqt_theme_url,
    is_autoinstall_file,
    is_launch_file,
    is_prefix_backup_file,
    normalize_launch_path,
    add_steam_compat_tool,
    reinstall_steam_compat_tool,
    remove_steam_compat_tool,
    clear_cache,
    reset_settings,
    parse_resolution,
)
from portprotonqt.localization import _, get_steam_language

APP_VERSION = "@APP_VERSION@"
APP_COMMIT = "@APP_COMMIT@"
if APP_VERSION == "@APP" "_VERSION@":
    APP_VERSION = "1.4.1"
    try:
        APP_COMMIT = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        APP_COMMIT = ""

__app_version__ = APP_VERSION

COUNTER_DOWNLOAD_URL = "http://cloud.linux-gaming.ru:8081/api/download/{version}"

def get_version():
    if APP_COMMIT:
        return f"{__app_version__} ({APP_COMMIT})"

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        return f"{__app_version__} ({commit})"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return __app_version__


def stop_portproton_game(start_sh: list[str], logger: Logger) -> None:
    try:
        subprocess.run(
            start_sh + ["cli", "--stop"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Failed to execute PortProton stop command: %s", e)


def get_portproton_tray_icon() -> QIcon:
    from portprotonqt.theme_manager import ThemeManager

    icon = ThemeManager().get_icon("tray_portproton", ui_config.get_theme())
    if isinstance(icon, QIcon):
        return icon
    return QIcon()


def run_silent_tray(app: QApplication, start_sh: list[str], exe_path: str) -> None:
    """Launch a game with a minimal tray stop action."""
    logger = get_logger(__name__)
    app.setQuitOnLastWindowClosed(False)
    tray_icon = QSystemTrayIcon(get_portproton_tray_icon(), app)
    tray_icon.setToolTip(__app_name__)

    from datetime import datetime
    from portprotonqt.time_utils import save_last_launch, save_playtime
    save_last_launch(os.path.splitext(os.path.basename(exe_path))[0], datetime.now())
    start_time = datetime.now()

    process = subprocess.Popen(start_sh + [exe_path], env=os.environ.copy(), shell=False)
    tray_menu = QMenu()

    def end_silent_run():
        monitor_timer.stop()
        elapsed = int((datetime.now() - start_time).total_seconds())
        if elapsed > 0:
            save_playtime(exe_path, elapsed)
        tray_icon.hide()
        app.quit()

    def stop_game() -> None:
        stop_portproton_game(start_sh, logger)
        end_silent_run()

    def close_when_game_exits(_tray_menu: QMenu = tray_menu) -> None:
        if process.poll() is not None:
            end_silent_run()

    stop_action = QAction(_("Stop Game"), tray_menu)
    stop_action.triggered.connect(stop_game)
    tray_menu.addAction(stop_action)
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    monitor_timer = QTimer(app)
    monitor_timer.timeout.connect(close_when_game_exits)
    monitor_timer.start(1000)


def restore_prefix_backup(start_sh: list[str], backup_path: str) -> int:
    """Restore a PortProton prefix backup."""
    logger = get_logger(__name__)
    path = normalize_launch_path(backup_path)
    cmd = start_sh + ["--restore-prefix", path]
    try:
        process = subprocess.Popen(
            cmd,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return process.wait()
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Failed to restore prefix backup %s: %s", path, e)
        return 1


def notify_download_counter(app_version: str, logger: Logger) -> None:
    url = COUNTER_DOWNLOAD_URL.format(version=quote(app_version, safe=""))

    def send_request() -> None:
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=10):
                pass
        except urllib.error.URLError as e:
            logger.debug("Failed to notify download counter: %s", e)
        except OSError as e:
            logger.debug("Failed to notify download counter: %s", e)

    threading.Thread(target=send_request, daemon=True).start()


def create_prefix_backup(start_sh: list[str], prefix_name: str, backup_dir: str) -> int:
    """Create a PortProton prefix backup."""
    logger = get_logger(__name__)
    path = os.path.abspath(os.path.expanduser(backup_dir))
    cmd = start_sh + ["--backup-prefix", prefix_name, path]
    try:
        process = subprocess.run(cmd, env=os.environ.copy(), check=False)
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Failed to create prefix backup %s: %s", prefix_name, e)
        return 1
    return process.returncode


def is_restore_prefix_request(args: argparse.Namespace) -> bool:
    if args.restore_prefix:
        return bool(args.file_or_url)
    return bool(args.file_or_url and is_prefix_backup_file(args.file_or_url))


def main():
    parsed_args = parse_args()

    if os.environ.get("PORTPROTONQT_INTEGRATE_APPIMAGE") == "1":
        from portprotonqt.appimage_integration import integrate_appimage

        setup_logger(parsed_args.debug_level)
        try:
            destination = integrate_appimage()
            restart_env = os.environ.copy()
            restart_env.pop("PORTPROTONQT_INTEGRATE_APPIMAGE", None)
            subprocess.Popen(
                [str(destination), *sys.argv[1:]],
                env=restart_env,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError, KeyError) as error:
            get_logger(__name__).error("Failed to integrate AppImage: %s", error)
            return 1
        return 0

    # Handle --reinstall-steam-compat-tool flag
    if parsed_args.reinstall_steam_compat_tool:
        success = reinstall_steam_compat_tool()
        sys.exit(0 if success else 1)

    # Handle --add-steam-compat-tool flag
    if parsed_args.add_steam_compat_tool:
        success = add_steam_compat_tool()
        sys.exit(0 if success else 1)

    # Handle --remove-steam-compat-tool flag
    if parsed_args.remove_steam_compat_tool:
        success = remove_steam_compat_tool()
        sys.exit(0 if success else 1)

    if parsed_args.clear_cache:
        success = clear_cache()
        sys.exit(0 if success else 1)

    if parsed_args.reset_settings:
        success = reset_settings()
        sys.exit(0 if success else 1)

    os.environ["FULL_LN"] = get_steam_language()
    portproton_location = get_portproton_location()
    if portproton_location:
        os.environ["PORT_DATA_PATH"] = portproton_location
    ui_config.get_disable_runtime_download()

    # Check if running as Steam compatibility tool (STEAM_COMPAT=1).
    is_steam_compat = os.environ.get("STEAM_COMPAT") == "1"
    is_silent_launch = parsed_args.silent

    # Get the PortProton start command
    start_sh = get_portproton_start_command()

    if start_sh is None:
        return

    if parsed_args.restore_prefix and not parsed_args.file_or_url:
        setup_logger(parsed_args.debug_level)
        sys.exit(1)

    # Handle Steam compatibility mode - launch game directly without GUI.
    if is_steam_compat:
        exe_path = parsed_args.file_or_url if parsed_args.file_or_url else None
        can_launch_without_gui = bool(exe_path and is_launch_file(exe_path))

        if can_launch_without_gui and isinstance(exe_path, str):
            exe_path = normalize_launch_path(exe_path)
            logger = get_logger(__name__)
            setup_logger(parsed_args.debug_level)
            logger.info("Running in Steam compatibility mode, launching: %s", exe_path)
            logger.info("Steam compatibility launch arguments: %s", parsed_args.launch_args)

            # Launch game via PortProton without GUI
            env_vars = os.environ.copy()
            cmd = start_sh + [exe_path] + parsed_args.launch_args
            try:
                subprocess.run(cmd, env=env_vars)
            except Exception as e:
                logger.error("Failed to launch game in Steam compatibility mode: %s", e)
                sys.exit(1)
            sys.exit(0)
        else:
            # No launch file provided, fall back to GUI mode
            is_steam_compat = False

    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon.fromTheme(__app_id__))
    app.setDesktopFileName(__app_id__)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__app_version__)

    args = parsed_args
    setup_logger(args.debug_level)
    logger = get_logger(__name__)
    if consume_download_counter_skip():
        update_app_version(__app_version__)
    elif update_app_version(__app_version__):
        notify_download_counter(__app_version__, logger)

    fullscreen = args.fullscreen or display_config.get_fullscreen()
    ipc_message = "show:fullscreen" if fullscreen else "show"
    backup_request = None
    restore_prefix_path = None
    autoinstall_path = None
    theme_store_id = None
    gog_launch_uri = None
    egs_launch_uri = None
    resolution_from_args = None
    if args.resolution:
        resolution_from_args = parse_resolution(args.resolution)
        if resolution_from_args is None:
            logger.warning(f"Invalid resolution format: {args.resolution}, expected WIDTHxHEIGHT (e.g., 1920x1080)")
        else:
            window_config.set_geometry(resolution_from_args[0], resolution_from_args[1])
            logger.info("Saved window resolution: %sx%s", resolution_from_args[0], resolution_from_args[1])
            ipc_message = "noop"
    if args.create_backup:
        prefix_name, backup_dir = args.create_backup
        backup_request = (prefix_name, os.path.abspath(os.path.expanduser(backup_dir)))
        ipc_message = "backup:{}:{}".format(quote(prefix_name, safe=""), quote(backup_request[1], safe=""))
    elif is_restore_prefix_request(args):
        restore_prefix_path = normalize_launch_path(args.file_or_url)
        ipc_message = f"restore:{quote(restore_prefix_path, safe='')}"
    elif args.file_or_url and is_launch_file(args.file_or_url):
        launch_action = "silent" if is_silent_launch and not args.log else "log" if args.log else "open"
        ipc_message = f"{launch_action}:{normalize_launch_path(args.file_or_url)}"
    elif args.file_or_url and is_autoinstall_file(args.file_or_url):
        autoinstall_path = normalize_launch_path(args.file_or_url)
        ipc_message = f"autoinstall:{quote(autoinstall_path, safe='')}"
    elif args.file_or_url and args.file_or_url.startswith("gog://launch/"):
        app_id = args.file_or_url.removeprefix("gog://launch/")
        if app_id.isdigit():
            gog_launch_uri = args.file_or_url
            if args.log:
                ipc_message = f"log:{quote(args.file_or_url, safe='')}"
            else:
                ipc_message = f"silent:{quote(args.file_or_url, safe='')}" if is_silent_launch else f"gog:{app_id}"
    elif args.file_or_url and args.file_or_url.startswith("egs://launch/"):
        app_id = args.file_or_url.removeprefix("egs://launch/")
        if app_id and "/" not in app_id:
            egs_launch_uri = args.file_or_url
            if args.log:
                ipc_message = f"log:{quote(args.file_or_url, safe='')}"
            else:
                ipc_message = f"silent:{quote(args.file_or_url, safe='')}" if is_silent_launch else f"egs:{app_id}"
    elif args.file_or_url:
        theme_store_id = parse_portprotonqt_theme_url(args.file_or_url)
        if theme_store_id is not None:
            ipc_message = f"theme:{theme_store_id}"

    from PySide6.QtCore import QThread, Signal
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from requests import RequestException
    from portprotonqt.appimage_updater import (
        APPIMAGE_UPDATE_START_DELAY_MS,
        AppImageUpdateWorker,
    )
    from portprotonqt.main_window import MainWindow
    from portprotonqt.gog_api import GOGAPI
    from portprotonqt.port_data_path_selector import ask_portdata_path, is_portdata_path_read_write
    from portprotonqt.portproton_api import (
        PortProtonAPI,
        get_user_conf_setting,
        set_user_conf_setting,
    )
    from portprotonqt.downloader import Downloader
    from portprotonqt.dialogs.appimage_update import (
        AppImageUpdateDialog,
        AppImageUpdateProgressDialog,
    )
    from portprotonqt.debug_utils import (
        get_selectable_gpu_entries,
    )
    from portprotonqt.qt_utils import get_screen_info, get_system_dpi_for_wine

    # --- Single-instance logic ---
    server_name = __app_id__
    socket = QLocalSocket()
    socket.connectToServer(server_name)

    if socket.waitForConnected(200):
        # Second instance — send command to the first one
        socket.write(ipc_message.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        logger.info("Restored existing instance from tray")
        return

    # Remove old socket if it exists
    QLocalServer.removeServer(server_name)

    local_server = QLocalServer()
    if not local_server.listen(server_name):
        logger.warning(f"Failed to start local server: {local_server.errorString()}")
        return

    portdata_warning = None
    if portproton_location and not is_portdata_path_read_write(portproton_location):
        logger.warning("PORT_DATA_PATH is not readable/writable: %s", portproton_location)
        portdata_warning = _("PortProton data folder is not readable and writable. Choose another folder for PortProton data.")
        portproton_location = None

    if not portproton_location:
        portproton_location = ask_portdata_path(portdata_warning, bool(portdata_warning))
        if not portproton_location:
            logger.error("PORT_DATA_PATH is not configured, startup aborted")
            return
        os.environ["PORT_DATA_PATH"] = portproton_location
        if not save_portdata_path_to_config(portproton_location):
            logger.warning("Failed to persist PORT_DATA_PATH in PortProtonQt config")

    # Check if we have a portproton:// URL or launch file to handle
    if args.file_or_url and not restore_prefix_path and not gog_launch_uri and not egs_launch_uri:
        if is_portproton_url(args.file_or_url):
            # Parse the portproton:// URL to get the full download URL
            download_url = parse_portproton_url(args.file_or_url)
            if download_url:

                # Create PortProtonAPI instance to handle the download
                downloader = Downloader(max_workers=4)
                api = PortProtonAPI(downloader=downloader)

                # Perform the PPDB download - user will select the .exe file via FileExplorer
                success = api.download_ppdb_from_url(download_url)
                if success:
                    logger.info(f"Successfully downloaded PPDB from {download_url}")
                else:
                    logger.error(f"Failed to download PPDB from {download_url}")

                # Exit after handling the URL
                return
            else:
                logger.error(f"Failed to parse portproton:// URL: {args.file_or_url}")
                return
        elif is_launch_file(args.file_or_url):
            # Store launch file path for later processing after window is created
            exe_path = normalize_launch_path(args.file_or_url)
        elif is_autoinstall_file(args.file_or_url):
            autoinstall_path = normalize_launch_path(args.file_or_url)
            exe_path = None
        elif theme_store_id is not None:
            exe_path = None
        else:
            logger.warning(f"Unknown file or URL format: {args.file_or_url}")
            exe_path = None
    else:
        exe_path = None

    # Install theme from store URL before creating MainWindow
    if theme_store_id is not None:
        try:
            import tempfile
            import requests
            from portprotonqt.tabs.theme_store_workers import (
                _theme_store_download_url,
                _install_theme_archive,
            )
            from portprotonqt.theme_manager import ThemeManager

            url = _theme_store_download_url(theme_store_id)
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as archive:
                archive_path = archive.name
            try:
                session = requests.Session()
                with session.get(url, stream=True, timeout=60) as response:
                    response.raise_for_status()
                    with open(archive_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                theme_names = _install_theme_archive(archive_path)
                if theme_names:
                    tm = ThemeManager()
                    theme_module = tm.apply_theme(theme_names[0])
                    if theme_module:
                        ui_config.set_theme(theme_names[0])
                        ui_config.set_theme_variant("dark")
                        logger.info("Theme %s installed and applied before window creation", theme_names[0])
            except Exception as e:
                logger.warning("Failed to pre-install theme %s: %s", theme_store_id, e)
            finally:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
        except Exception as e:
            logger.warning("Failed to handle theme store URL: %s", e)
        theme_store_id = None

    # --- Main Window ---
    version = get_version()

    # Parse resolution if provided
    window_resolution = None
    if args.resolution and resolution_from_args is None:
        logger.warning(f"Invalid resolution format: {args.resolution}, expected WIDTHxHEIGHT (e.g. 1920x1080)")

    launch_path = exe_path or autoinstall_path
    silent_game_request = is_silent_launch and not args.log and bool(
        exe_path or gog_launch_uri or egs_launch_uri
    )
    window = MainWindow(app_name=__app_name__, version=version, launch_exe=launch_path, resolution=window_resolution, show_system_tab=args.ppqtos)
    window.silent_launch_mode = silent_game_request
    if silent_game_request:
        window._initialize_tray(__app_name__)
        assert window.tray_manager is not None
        if exe_path:
            window.tray_manager.tray_icon.hide()
        else:
            window.tray_manager.set_minimal_mode()

    def open_store_game_card(source: str, app_id: str, log_mode: bool = False) -> None:
        exec_line = f"{source}://launch/{app_id}"
        if log_mode:
            window._pending_log_exe = getattr(window, f"{source}_api").get_launch_target(app_id)

        def open_card(games: list[tuple]) -> None:
            game = next((item for item in games if item[5] == exec_line), None)
            if game is None:
                return
            window.openGameDetailPage({
                "name": game[0], "description": game[1], "cover_path": game[2],
                "appid": game[3], "controller_support": game[4],
                "exec_line": game[5], "last_launch": game[6],
                "formatted_playtime": game[7], "protondb_tier": game[8],
                "anticheat_status": game[9], "playtime_seconds": game[11],
                "game_source": game[12], "anticheat_slug": game[13],
                "ppdb_id": game[14], "ppdb_rating": game[15],
                "protondb_appid": game[16],
            })

        loader = getattr(window, f"_load_{source}_games_async")
        loader(open_card)

    def handle_game_request(target: str, silent: bool, log_mode: bool = False) -> None:
        if is_launch_file(target):
            path = normalize_launch_path(target)
            if silent:
                run_silent_tray(app, start_sh, path)
                return
            window.handle_launch_exe(path, log_mode=log_mode)
            return
        source, app_id = target.split("://launch/", 1)
        if silent:
            window.toggleGame(target)
            return
        open_store_game_card(source, app_id, log_mode)

    # Handle launch file if provided
    if exe_path:
        # Defer the call until after the window is shown
        def handle_launch_exe() -> None:
            handle_game_request(exe_path, is_silent_launch and not args.log, args.log)
        QTimer.singleShot(0, handle_launch_exe)
    elif autoinstall_path:
        def handle_autoinstall():
            window.open_local_autoinstall_card(autoinstall_path)
        QTimer.singleShot(0, handle_autoinstall)
    elif backup_request:
        def handle_create_backup():
            window._perform_backup(backup_request[1], backup_request[0])
        QTimer.singleShot(0, handle_create_backup)
    elif restore_prefix_path:
        def handle_restore_prefix():
            window._perform_restore(restore_prefix_path)
        QTimer.singleShot(0, handle_restore_prefix)
    elif gog_launch_uri:
        def handle_gog_launch() -> None:
            handle_game_request(gog_launch_uri, is_silent_launch, args.log)
        QTimer.singleShot(0, handle_gog_launch)
    elif egs_launch_uri:
        def handle_egs_launch() -> None:
            handle_game_request(egs_launch_uri, is_silent_launch, args.log)
        QTimer.singleShot(0, handle_egs_launch)

    # --- Handle incoming connections ---
    def handle_new_connection():
        conn = local_server.nextPendingConnection()
        if not conn:
            return

        if conn.waitForReadyRead(1000):
            data = conn.readAll().data()
            msg = bytes(data).decode("utf-8", errors="ignore")
            logger.info(f"IPC message received: {msg}")

            def restore_window():
                try:
                    if (
                        msg.startswith("show")
                        or msg.startswith("open:")
                        or msg.startswith("log:")
                        or msg.startswith("silent:")
                        or msg.startswith("restore:")
                        or msg.startswith("backup:")
                        or msg.startswith("theme:")
                        or msg.startswith("autoinstall:")
                        or msg.startswith("gog:")
                        or msg.startswith("egs:")
                    ):
                        if not msg.startswith("silent:"):
                            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
                            window.show()
                            window.raise_()
                            window.activateWindow()

                            # Ensure active state for strict focus policies
                            window.setWindowState(
                                window.windowState() | Qt.WindowState.WindowActive
                            )

                        if ":fullscreen" in msg:
                            logger.info("Switching to fullscreen via IPC")
                            display_config.set_fullscreen(True)
                            window.showFullScreen()
                        else:
                            if msg.startswith("show"):
                                logger.info("Switching to normal window via IPC")
                                display_config.set_fullscreen(False)
                                window.showNormal()

                        if msg.startswith("silent:"):
                            target = unquote(msg[7:].strip())
                            handle_game_request(target, True)
                        elif msg.startswith("open:") or msg.startswith("log:"):
                            log_mode = msg.startswith("log:")
                            launch_path = unquote(msg.split(":", 1)[1].strip())
                            if launch_path and is_launch_file(launch_path):
                                logger.info("Opening launch file via IPC: %s", launch_path)
                                handle_game_request(launch_path, False, log_mode)
                            elif log_mode and launch_path.startswith(("gog://launch/", "egs://launch/")):
                                handle_game_request(unquote(launch_path), False, True)
                            else:
                                logger.warning("Invalid launch file via IPC: %s", launch_path)
                        elif msg.startswith("restore:"):
                            backup_path = unquote(msg[8:].strip())
                            if backup_path and is_prefix_backup_file(backup_path):
                                logger.info("Restoring prefix backup via IPC: %s", backup_path)
                                window._perform_restore(backup_path)
                            else:
                                logger.warning("Invalid prefix backup via IPC: %s", backup_path)
                        elif msg.startswith("gog:"):
                            app_id = msg[4:].strip()
                            if app_id.isdigit():
                                handle_game_request(f"gog://launch/{app_id}", False)
                            else:
                                logger.warning("Invalid GOG app id via IPC: %s", app_id)
                        elif msg.startswith("egs:"):
                            app_id = msg[4:].strip()
                            if app_id and "/" not in app_id:
                                handle_game_request(f"egs://launch/{app_id}", False)
                            else:
                                logger.warning("Invalid Epic app id via IPC: %s", app_id)
                        elif msg.startswith("backup:"):
                            parts = msg.split(":", 2)
                            if len(parts) == 3:
                                prefix_name = unquote(parts[1])
                                backup_dir = unquote(parts[2])
                                logger.info("Creating prefix backup via IPC: %s", prefix_name)
                                window._perform_backup(backup_dir, prefix_name)
                            else:
                                logger.warning("Invalid prefix backup request via IPC: %s", msg)
                        elif msg.startswith("theme:"):
                            try:
                                theme_id = int(msg[6:].strip())
                            except ValueError:
                                logger.warning("Invalid theme store request via IPC: %s", msg)
                            else:
                                logger.info("Installing theme from store via IPC: %s", theme_id)
                                window._download_store_theme({"id": theme_id})
                        elif msg.startswith("autoinstall:"):
                            script_path = unquote(msg[12:].strip())
                            if script_path and is_autoinstall_file(script_path):
                                logger.info("Opening autoinstall file via IPC: %s", script_path)
                                window.open_local_autoinstall_card(script_path)
                            else:
                                logger.warning("Invalid autoinstall file via IPC: %s", script_path)
                except Exception as e:
                    logger.warning(f"Failed to restore window: {e}")

            # Execute in the main thread
            QTimer.singleShot(0, restore_window)

        conn.disconnectFromServer()

    local_server.newConnection.connect(handle_new_connection)

    # --- Initial fullscreen state ---
    launch_fullscreen = args.fullscreen or display_config.get_fullscreen()
    launch_auto_fullscreen = (
        display_config.get_auto_fullscreen_gamepad()
        and not launch_fullscreen
        and getattr(window.input_manager, "gamepad", None) is not None
    )
    launch_minimized = (
        silent_game_request
        or (
            display_config.get_start_minimized()
            and not args.fullscreen
            and not launch_auto_fullscreen
            and window_resolution is None
            and exe_path is None
            and backup_request is None
            and restore_prefix_path is None
            and autoinstall_path is None
            and theme_store_id is None
            and gog_launch_uri is None
            and egs_launch_uri is None
        )
    )
    if launch_minimized:
        logger.info("Launching in tray")
        window.hide()
    elif launch_fullscreen:
        logger.info(
            f"Launching in fullscreen mode ({'--fullscreen' if args.fullscreen else 'config'})"
        )
        display_config.set_fullscreen(True)
        window.showFullScreen()
    elif launch_auto_fullscreen:
        logger.info("Launching in fullscreen mode (gamepad)")
        window.input_manager.handle_fullscreen_slot(True)
        window.updateControlHints("force")
    elif window_resolution:
        logger.info(f"Launching with resolution: {window_resolution[0]}x{window_resolution[1]}")
        window.resize(window_resolution[0], window_resolution[1])
        window.showNormal()
    else:
        logger.info("Launching in normal mode")
        display_config.set_fullscreen(False)
        window.showNormal()

    appimage_update_progress: AppImageUpdateProgressDialog | None = None

    def start_appimage_update(update_info: str) -> None:
        nonlocal appimage_update_progress
        appimage_update_progress = AppImageUpdateProgressDialog(window, update_info)
        appimage_update_progress.update_finished.connect(show_appimage_update_result)
        appimage_update_progress.finished.connect(
            lambda _result: clear_appimage_update_progress()
        )
        appimage_update_progress.start_update()

    def clear_appimage_update_progress() -> None:
        nonlocal appimage_update_progress
        appimage_update_progress = None

    def show_appimage_update_prompt(changelog: str, update_info: str) -> None:
        dialog = AppImageUpdateDialog(window, window.theme, changelog)
        result = dialog.exec()
        if result == AppImageUpdateDialog.UPDATE:
            start_appimage_update(update_info)
        elif result == AppImageUpdateDialog.DISABLE:
            ui_config.set_auto_appimage_updates(False)

    def show_appimage_update_result(success: bool) -> None:
        if success:
            QMessageBox.information(
                window,
                _("Update complete"),
                _("AppImage updated. Restart the application to use the new version."),
            )
            return
        QMessageBox.warning(window, _("Error"), _("Failed to update AppImage."))

    window.appimageUpdateWorker = AppImageUpdateWorker("check")
    window.appimageUpdateWorker.update_available.connect(show_appimage_update_prompt)
    window.appimageUpdateWorker.finished.connect(
        lambda: setattr(window, "appimageUpdateWorker", None)
    )
    window.appimageUpdateWorker.finished.connect(window.appimageUpdateWorker.deleteLater)
    QTimer.singleShot(APPIMAGE_UPDATE_START_DELAY_MS, window.appimageUpdateWorker.start)

    class GOGDLUpdateWorker(QThread):
        """Update gogdl without blocking the UI thread."""

        def __init__(self, api: GOGAPI) -> None:
            super().__init__()
            self.api = api

        def run(self) -> None:
            try:
                self.api.update_gogdl()
            except (OSError, RequestException):
                logger.exception("Failed to update gogdl")

    gogdl_update_worker = GOGDLUpdateWorker(window.gog_api)
    window.gogdlUpdateWorker = gogdl_update_worker
    gogdl_update_worker.finished.connect(
        lambda: setattr(window, "gogdlUpdateWorker", None)
    )
    gogdl_update_worker.finished.connect(gogdl_update_worker.deleteLater)
    gogdl_update_worker.start()

    # Execute the initial PortProton command after the UI is set up
    class InitialCommandWorker(QThread):
        """Worker thread to run initial PortProton command without blocking UI."""
        finished = Signal()

        def __init__(self, start_cmd: list[str]):
            super().__init__()
            self.start_cmd = start_cmd

        def run(self):
            try:
                wine_dpi_value = "96"
                # Get screen information before running the initial command
                from portprotonqt.config import get_portproton_location
                portproton_path = get_portproton_location()

                if portproton_path:
                    screen_resolution, screen_primary = get_screen_info()

                    if screen_resolution and '=' in screen_resolution:
                        var_name, var_value = screen_resolution.split('=', 1)
                        if var_value:
                            set_user_conf_setting(var_name, var_value)
                            wine_dpi_value = get_system_dpi_for_wine()

                    if screen_primary and '=' in screen_primary:
                        var_name, var_value = screen_primary.split('=', 1)
                        if var_value:
                            set_user_conf_setting(var_name, var_value)

                set_user_conf_setting("PW_WINE_DPI_VALUE", wine_dpi_value)

                current_gpu_use = get_user_conf_setting("PW_GPU_USE")
                selectable_gpu_entries = get_selectable_gpu_entries()
                if len(selectable_gpu_entries) > 1:
                    selected_entry = None
                    for entry in selectable_gpu_entries:
                        if entry["device_name"] == current_gpu_use:
                            selected_entry = entry
                            break
                    if selected_entry is None:
                        selected_entry = selectable_gpu_entries[0]
                    if selected_entry is not None:
                        selected_gpu = selected_entry["device_name"]
                        if set_user_conf_setting("PW_GPU_USE", selected_gpu):
                            logger.info("Set PW_GPU_USE in user.conf via vk_gpu_info: %s", selected_gpu)
                        if selected_entry["vendor_id"]:
                            set_user_conf_setting("PW_vendorID", selected_entry["vendor_id"])
                        if selected_entry["device_id"]:
                            set_user_conf_setting("PW_deviceID", selected_entry["device_id"])
                elif current_gpu_use and current_gpu_use != "disabled":
                    set_user_conf_setting("PW_GPU_USE", None)
                    set_user_conf_setting("PW_vendorID", None)
                    set_user_conf_setting("PW_deviceID", None)

                # Run the initial PortProton command
                subprocess.run(self.start_cmd + ["cli", "--initial"], timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Initial PortProton command timed out")
            except Exception as e:
                logger.error(f"Error running initial PortProton command: {e}")
            finally:
                self.finished.emit()

    if start_sh:
        worker = InitialCommandWorker(start_sh)
        worker.start()
    else:
        logger.warning("PortProton start command not available, skipping initial command")

    # --- Cleanup ---
    def cleanup_on_exit():
        try:
            local_server.close()
            QLocalServer.removeServer(server_name)
            if window:
                window.close()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

    app.aboutToQuit.connect(cleanup_on_exit)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
