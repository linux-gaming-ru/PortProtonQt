from __future__ import annotations

import os
import sys
import signal
import shlex
import subprocess
import re
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import TYPE_CHECKING

import psutil
import orjson

from portprotonqt.logger import get_logger
from portprotonqt.icon_extractor import generate_thumbnail, get_exe_icon_cache_path
from portprotonqt.dialogs import FileExplorer, ExeSettingsDialog
from portprotonqt.dialogs.compatibility_report import CompatibilityReportDialog
from portprotonqt.game_card import GameCard
from portprotonqt.animations import DetailPageAnimations
from portprotonqt.custom_widgets import ClickableLabel, AutoSizeButton, NavLabel
from portprotonqt.detail_pages import DetailPageManager
from portprotonqt.portproton_api import PortProtonAPI, remove_empty_custom_data_dirs
from portprotonqt.gog_api import GOGAPI
from portprotonqt.egs_api import EGSAPI
from portprotonqt.debug_utils import get_prefix_name
from portprotonqt.input_manager import InputManager, MainWindowProtocol
from portprotonqt.context_menu_manager import ContextMenuManager

from portprotonqt.image_utils import (
    COVER_IMAGE_EXTENSIONS,
    ImageCarousel,
    load_pixmap_async,
    set_all_animated_covers_suspended,
)
from portprotonqt.steam_api import get_steam_game_info_async, get_full_steam_game_info_async, get_cached_steam_game_info, get_steam_installed_games, fetch_sgdb_cover_async, get_steam_launch_commands
from portprotonqt.theme_manager import SystemThemeWatcher, ThemeManager
from portprotonqt.time_utils import save_last_launch, get_last_launch, get_playtime_for_exe, format_playtime, get_last_launch_timestamp, format_last_launch
from portprotonqt.config import (
    get_portproton_location,
    ui_config,
    parse_desktop_entry,
    game_config,
    favorites_config,
    display_config,
    THEMED_LAUNCH_ICON_NAMES,
    WINDOWS_LAUNCH_EXTENSIONS,
    extract_exec_target_path,
    window_config,
    get_portproton_start_command,
    get_portproton_scripts_path,
    find_game_by_exe,
    resolve_custom_data_dir,
)

from portprotonqt.localization import _, get_metadata_language, read_metadata_translations
from portprotonqt.downloader import Downloader
from portprotonqt.tray_manager import TrayManager
from portprotonqt.game_library_manager import GameLibraryManager
from portprotonqt.virtual_keyboard import VirtualKeyboard
from portprotonqt.disc_image_utils import DiscImageManager
from portprotonqt.compatibility_report import (
    CompatibilityLaunch,
    analyze_launch,
    has_dxvk_vulkan_incompatibility,
    is_suspected_crash,
)
from portprotonqt.sound_manager import SoundManager
from portprotonqt.tabs.control_hints import MainWindowControlHintsMixin
from portprotonqt.tabs.autoinstall_tab import MainWindowAutoInstallTabMixin
from portprotonqt.tabs.library_tab import MainWindowLibraryTabMixin
from portprotonqt.tabs.download_tab import GOGLibraryWorker, MainWindowDownloadTabMixin
from portprotonqt.tabs.settings_tab import MainWindowSettingsTabMixin
from portprotonqt.tabs.system_tab import MainWindowSystemTabMixin
from portprotonqt.tabs.theme_tab import MainWindowThemeTabMixin
from portprotonqt.tabs.wine_tab import MainWindowWineTabMixin
from portprotonqt.tabs.workers import MainWindowWorkersMixin

from PySide6.QtWidgets import (QLineEdit, QMainWindow, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QStackedWidget, QComboBox,
                               QMessageBox, QApplication, QPushButton, QCheckBox)
from PySide6.QtCore import Qt, QEvent, QEventLoop, QUrl, Signal, QTimer, Slot, QProcess, QProcessEnvironment, QThread, QFileSystemWatcher, QObject
from PySide6.QtGui import QColor, QDesktopServices, QHideEvent, QShowEvent, QGuiApplication
from typing import cast
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

STORE_LAUNCH_GRACE_SECONDS = 10

if TYPE_CHECKING:
    from portprotonqt.appimage_updater import AppImageUpdateWorker

logger = get_logger(__name__)
DISC_IMAGE_EXTENSIONS = (".iso", ".mdf", ".nrg")
ALT_BIARCH_REPO = "x86_64-i586"
ALT_BIARCH_URL = "https://www.altlinux.org/Biarch"
GAME_LAUNCH_MARKER = "PORTPROTONQT_GAME_LAUNCH_STARTED"

class MainWindow(
    MainWindowControlHintsMixin,
    MainWindowAutoInstallTabMixin,
    MainWindowLibraryTabMixin,
    MainWindowDownloadTabMixin,
    MainWindowSettingsTabMixin,
    MainWindowSystemTabMixin,
    MainWindowThemeTabMixin,
    MainWindowWineTabMixin,
    MainWindowWorkersMixin,
    QMainWindow,
):
    games_loaded = Signal(list)
    compatibility_report_ready = Signal(str)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            corner_size = 20
            width = self.width()
            height = self.height()
            click_pos = event.pos()

            if click_pos.x() >= width - corner_size and click_pos.y() >= height - corner_size:
                self.window().windowHandle().startSystemResize(
                    Qt.Edge.BottomEdge | Qt.Edge.RightEdge  # type: ignore
                )
            else:
                self.window().windowHandle().startSystemMove()
            event.accept()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange):
            self._update_animated_covers_activity()

    def hideEvent(self, event: QHideEvent) -> None:
        self._set_animated_covers_suspended(True)
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_animated_covers_activity()

    def _on_application_state_changed(self, _state: Qt.ApplicationState) -> None:
        self._update_animated_covers_activity()

    def _update_animated_covers_activity(self) -> None:
        should_suspend = (
            not self.isVisible() or
            self.isMinimized() or
            not self.isActiveWindow()
        )
        self._set_animated_covers_suspended(should_suspend)

    def _set_animated_covers_suspended(self, suspended: bool) -> None:
        if getattr(self, "_animated_covers_suspended", False) == suspended:
            return
        self._animated_covers_suspended = suspended
        set_all_animated_covers_suspended(suspended)
        self._set_inactive_background_suspended(suspended)
        if not suspended and hasattr(self, "game_library_manager"):
            QTimer.singleShot(0, self.game_library_manager.load_visible_images)
        if not suspended and hasattr(self, "input_manager") and not self._has_running_game_process():
            self.input_manager.resume_gamepad_polling()

    def _set_inactive_background_suspended(self, suspended: bool) -> None:
        if hasattr(self, "game_library_manager") and suspended:
            self.game_library_manager.stop_background_activity()

    def _init_gamepad_tooltip(self) -> None:
        self._gamepad_tooltip_map: dict[QWidget, str] = {}
        self.gamepad_tooltip = QLabel()
        self.gamepad_tooltip.setWordWrap(True)
        self.gamepad_tooltip.setStyleSheet(self.theme.TOOLTIP_STYLE)
        self.gamepad_tooltip.setVisible(False)
        self.gamepad_tooltip.setParent(self)
        self.gamepad_tooltip.setWindowFlags(Qt.WindowType.ToolTip)
        self.gamepad_tooltip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.gamepad_tooltip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.gamepad_tooltip_timer = QTimer(self)
        self.gamepad_tooltip_timer.setSingleShot(True)
        self.gamepad_tooltip_timer.timeout.connect(lambda: self.gamepad_tooltip.setVisible(False))

    def _register_gamepad_tooltip(self, widget: QWidget, text: str) -> None:
        self._gamepad_tooltip_map[widget] = text
        widget.installEventFilter(self)

    def _show_gamepad_tooltip(self, show: bool, text: str = "", anchor_widget: QWidget | None = None) -> None:
        if not show or not text or anchor_widget is None or not anchor_widget.isVisible():
            self.gamepad_tooltip_timer.stop()
            self.gamepad_tooltip.setVisible(False)
            return

        self.gamepad_tooltip.setText(text)
        self.gamepad_tooltip.setFixedSize(500, 300)
        font_metrics = self.gamepad_tooltip.fontMetrics()
        text_rect = font_metrics.boundingRect(
            0, 0, 480, 1000,
            Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs,
            text,
        )
        required_width = min(500, text_rect.width() + 25)
        required_height = min(300, text_rect.height() + 25)
        anchor_pos = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        x = anchor_pos.x() + self.theme.settings_tooltip_offset_x
        y = anchor_pos.y() + self.theme.settings_tooltip_offset_y
        screen = QGuiApplication.screenAt(anchor_pos) or QGuiApplication.primaryScreen()
        if screen:
            available_rect = screen.availableGeometry()
            x = max(available_rect.left(), min(x, available_rect.right() - required_width))
            y = max(available_rect.top(), min(y, available_rect.bottom() - required_height))
        self.gamepad_tooltip.setFixedSize(required_width, required_height)
        self.gamepad_tooltip.move(x, y)
        self.gamepad_tooltip.setVisible(True)
        self.gamepad_tooltip_timer.start(max(2500, min(12000, 1500 + len(text) * 30)))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QWidget) and obj in getattr(self, "_gamepad_tooltip_map", {}):
            if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                self._show_gamepad_tooltip(True, self._gamepad_tooltip_map[obj], obj)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.FocusOut, QEvent.Type.MouseButtonPress):
                self._show_gamepad_tooltip(False)
        return super().eventFilter(obj, event)

    def _get_var_default_setting(self, key: str, fallback: str) -> str:
        scripts_path = get_portproton_scripts_path()
        if not scripts_path:
            return fallback

        var_path = os.path.join(scripts_path, "var")
        if not os.path.exists(var_path):
            return fallback

        try:
            with open(var_path, encoding="utf-8") as var_file:
                for line in var_file:
                    match = re.match(rf'^\s*check_variables\s+{key}\s+["\']?([^"\']+)', line)
                    if match:
                        return match.group(1)
        except OSError as exc:
            logger.warning("Failed to read default %s from %s: %s", key, var_path, exc)
        return fallback

    def _set_combo_current_data(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        if value:
            combo.addItem(value, value)
            combo.setCurrentIndex(combo.count() - 1)

    def __init__(self, app_name: str, version: str, launch_exe: str | None = None, resolution: tuple[int, int] | None = None, show_system_tab: bool = False):
        super().__init__()
        self.theme_manager = ThemeManager()
        selected_theme = ui_config.get_theme()
        self.current_theme_name = selected_theme
        # Apply theme but defer heavy font loading
        self.theme = self.theme_manager.apply_theme(selected_theme)
        self.tray_manager = None
        QTimer.singleShot(0, lambda: self._initialize_tray(app_name))
        self.card_width = ui_config.get_card_width()
        self.auto_card_width = ui_config.get_auto_card_width()
        self.setWindowTitle(f"{app_name} {version}")
        self.setMinimumSize(890, 600)
        self._pending_resolution = resolution  # Store resolution for later application
        self._show_system_tab = show_system_tab
        self.system_tab_index = -1  # Default, set when system tab is created
        self._animated_covers_suspended = False

        self.games = []
        self.game_processes = []
        self.target_exe = None
        self.game_start_time = None
        self.game_start_exe = None
        self.game_launch_monotonic = None
        self.game_stopped_by_user = False
        self.current_running_button = None
        self.disc_image_manager = DiscImageManager()
        self.portproton_location = get_portproton_location()
        self.start_sh = get_portproton_start_command()
        self.launch_exe = launch_exe  # Store launch_exe path
        self._pending_log_exe: str | None = None
        self.appimageUpdateWorker: AppImageUpdateWorker | None = None
        self.gogdlUpdateWorker: QThread | None = None
        self.compatibility_report_ready.connect(self._show_compatibility_report)

        self.game_library_manager = GameLibraryManager(self, self.theme, None)

        # Initialize detail page manager
        self.detail_page_manager = DetailPageManager(self)

        self.context_menu_manager = ContextMenuManager(
            self,
            self.portproton_location,
            self.theme,
            self.game_library_manager
        )

        self.game_library_manager.context_menu_manager = self.context_menu_manager

        QApplication.setStyle("Fusion")
        self.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE)
        self.setAcceptDrops(True)
        self._init_gamepad_tooltip()
        self.current_exec_line = None
        self.currentDetailPage = None
        self.current_play_button = None
        self.current_focused_card: GameCard | None = None
        self.current_hovered_card: GameCard | None = None
        self._library_controls_hover_close_delayed = False
        self.pending_games = []
        self.total_games = 0
        self._loading_games = False
        self._known_portproton_desktops: set[str] = set()
        self.games_load_timer = QTimer(self)
        self.games_load_timer.setSingleShot(True)
        self.games_load_timer.timeout.connect(self.finalize_game_loading)
        self.games_loaded.connect(self.on_games_loaded)
        self.current_add_game_dialog = None

        self.settingsDebounceTimer = QTimer(self)
        self.settingsDebounceTimer.setSingleShot(True)
        self.settingsDebounceTimer.setInterval(300)
        self.settingsDebounceTimer.timeout.connect(self.applySettingsDelayed)

        # Initialize file system watcher for dist and prefixes directories
        self.fs_watcher = QFileSystemWatcher(self)
        self.fs_watcher.directoryChanged.connect(self.on_directory_changed)

        ui_config.get_time_detail_level()

        # Start watching dist and prefixes directories if they exist
        QTimer.singleShot(0, self.start_watching_directories)  # Delay to ensure portproton_location is set
        self.downloader = Downloader(max_workers=4)
        self.gog_api = GOGAPI()
        self.egs_api = EGSAPI()
        self.portproton_api = PortProtonAPI(self.downloader)
        self.autoInstallCustomDataThread = None

        self.installing = False
        self.install_process = None
        self.install_stop_process = None
        self.install_stop_requested = False
        self.current_install_script = None
        self.current_install_button = None
        self.current_install_button_text = None
        self.current_install_button_icon = None
        self.current_install_status = None
        self.install_output_buffer = ""

        # Dependency setup monitoring during game launch
        self.launch_output_queue = Queue()
        self.launch_output_thread = None
        self.wine_download_percent = 0.0
        self.wine_download_seen = False
        self.wine_download_status = _("Downloading Wine…")
        self.game_launch_started = False
        self.game_process_exit_monotonic = None
        self.egs_launch_cancelled = False
        self.launcher_process_only = False
        self.silent_launch_mode = False

        # Central widget and main layout
        centralWidget = QWidget()
        self.setCentralWidget(centralWidget)
        mainLayout = QVBoxLayout(centralWidget)
        mainLayout.setSpacing(0)
        mainLayout.setContentsMargins(0, 0, 0, 0)

        # 1. HEADER
        self.header = QWidget()
        self.header.setFixedHeight(80)
        self.header.setStyleSheet(self.theme.MAIN_WINDOW_HEADER_STYLE)
        headerLayout = QVBoxLayout(self.header)
        headerLayout.setContentsMargins(0, 0, 0, 0)
        headerLayout.addStretch()

        self.input_manager = InputManager(cast(MainWindowProtocol, self))
        self.input_manager.button_event.connect(self.updateControlHints)
        self.input_manager.dpad_moved.connect(self.updateControlHints)
        self.input_manager.gamepad_hotplug.connect(self.updateControlHints)

        # 2. NAVIGATION (TAB BUTTONS)
        self.navWidget = QWidget()
        self.navWidget.setProperty("theme_style_name", "NAV_WIDGET_STYLE")
        self.navWidget.setStyleSheet(self.theme.NAV_WIDGET_STYLE)
        navLayout = QHBoxLayout(self.navWidget)
        navLayout.setContentsMargins(10, 0, 10, 0)
        navLayout.setSpacing(10)

         # Left navigation button (key_left or button_lb)
        self.leftNavButton = NavLabel()
        self.leftNavButton.setFixedSize(32, 32)
        self.leftNavButton.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.leftNavButton.setProperty("sound_event", False)
        self.leftNavButton.clicked.connect(lambda: self.switchVisibleTab(-1))
        navLayout.addWidget(self.leftNavButton)

        # Tabs
        self.tabButtons = {}
        tabs = [
            _("Library"),
            _("Auto Install"),
            _("Wine Settings"),
            _("PPQT Settings"),
            _("System"),
            _("Themes"),
            _("Downloads")
        ]
        for i, tabName in enumerate(tabs):
            btn = NavLabel(tabName)
            btn.setCheckable(True)
            btn.setProperty("sound_event", False)
            btn.clicked.connect(lambda index=i: self.switchTab(index))
            btn.setStyleSheet(self.theme.NAV_BUTTON_STYLE)
            navLayout.addWidget(btn)
            self.tabButtons[i] = btn

        self.tabButtons[0].setChecked(True)

        # Right navigation button (key_right or button_rb)
        self.rightNavButton = NavLabel()
        self.rightNavButton.setFixedSize(32, 32)
        self.rightNavButton.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rightNavButton.setProperty("sound_event", False)
        self.rightNavButton.clicked.connect(lambda: self.switchVisibleTab(1))
        navLayout.addWidget(self.rightNavButton)

        # Initial update of navigation buttons based on input device
        self.updateNavButtons()

        mainLayout.addWidget(self.navWidget)

        # 3. QStackedWidget (TABS)
        self.stackedWidget = QStackedWidget()
        self.stackedWidget.currentChanged.connect(self.updateControlHints)
        self.stackedWidget.currentChanged.connect(self._load_empty_library_on_tab_enter)
        self.stackedWidget.currentChanged.connect(self._log_stacked_widget_change)
        mainLayout.addWidget(self.stackedWidget)

        self.createInstalledTab()

        # Always create auto-install tab but set visibility based on settings
        self.createAutoInstallTab()
        self.auto_install_tab_index = 1  # Auto Install tab is always at index 1

        # Set visibility based on settings
        hide_autoinstall = ui_config.get_hide_autoinstall_tab()
        if hide_autoinstall:
            # Hide the tab button and page
            if hasattr(self, 'tabButtons') and self.auto_install_tab_index in self.tabButtons:
                tab_button = self.tabButtons[self.auto_install_tab_index]
                tab_button.setVisible(False)

            if hasattr(self, 'stackedWidget'):
                auto_install_page = self.stackedWidget.widget(self.auto_install_tab_index)
                if auto_install_page:
                    auto_install_page.setVisible(False)

        self.createWineTab()
        self.createPortProtonTab()
        if self._show_system_tab:
            self.createSystemTab()
        else:
            # Keep tab indexes stable when System tab is disabled.
            self.stackedWidget.addWidget(QWidget())
            if hasattr(self, 'tabButtons') and 4 in self.tabButtons:
                system_tab_button = self.tabButtons[4]
                system_tab_button.setVisible(False)
            hidden_system_page = self.stackedWidget.widget(4)
            if hidden_system_page:
                hidden_system_page.setVisible(False)
        self.createThemeTab()
        self.createGOGDownloadsTab()

        self.controlHintsWidget = self.createControlHintsWidget()
        self.controlHintsWidget.setProperty(
            "theme_style_name", "HINT_BAR_STYLE"
        )
        self.controlHintsWidget.setStyleSheet(self.theme.HINT_BAR_STYLE)
        mainLayout.addWidget(self.controlHintsWidget)

        self.updateControlHints("force")

        self.restore_state()

        self.keyboard = VirtualKeyboard(self, self.theme)

        self.detail_animations = DetailPageAnimations(self, self.theme)
        self._animations = {}
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.applicationStateChanged.connect(self._on_application_state_changed)
            is_light = app.styleHints().colorScheme() == Qt.ColorScheme.Light
            self.system_theme_watcher = SystemThemeWatcher(is_light, self)
            self.system_theme_watcher.theme_changed.connect(self._on_system_theme_detected)
            app.styleHints().colorSchemeChanged.connect(
                self._on_qt_color_scheme_changed
            )
            self.system_theme_watcher.start()

        auto_fullscreen_gamepad = (
            display_config.get_auto_fullscreen_gamepad()
            and self.input_manager.gamepad is not None
        )
        if display_config.get_fullscreen() or auto_fullscreen_gamepad:
            self.showFullScreen()
        elif self._pending_resolution:
            # Apply resolution from command line
            self.resize(self._pending_resolution[0], self._pending_resolution[1])
            self.showNormal()
        else:
            width, height = window_config.get_geometry()
            if width > 0 and height > 0:
                self.resize(width, height)
            else:
                self.showNormal()

        # Process events to ensure UI is responsive before starting heavy operations
        QApplication.processEvents()
        self.updateControlHints("force")

        # Delay game loading until after the UI is fully displayed to prevent blocking
        # Use a longer delay to ensure window is fully rendered and responsive
        # Use a custom event processing approach to make sure UI stays responsive
        QTimer.singleShot(500, self.loadGames)  # Reduced delay but ensure UI gets event processing

    def on_slider_released(self) -> None:
        """Delegate to game library manager."""
        if hasattr(self, 'game_library_manager'):
            self.game_library_manager.on_slider_released()

    def on_directory_changed(self, path: str):
        """Handle PortProton directory change events."""
        if not self.portproton_location:
            return

        dist_path = os.path.join(self.portproton_location, "data", "dist")
        prefixes_path = os.path.join(self.portproton_location, "data", "prefixes")

        if path == self.portproton_location:
            QTimer.singleShot(300, self._refresh_portproton_shortcuts)
        elif path == dist_path:
            # Wine/Proton directory changed, refresh wine combo
            QTimer.singleShot(100, self.refresh_wine_combo)  # Small delay to allow file operations to complete
        elif path == prefixes_path:
            # Prefixes directory changed, refresh prefix combo
            QTimer.singleShot(100, self.refresh_prefix_combo)  # Small delay to allow file operations to complete

    def _refresh_portproton_shortcuts(self) -> None:
        """Add newly created PortProton shortcuts to the library."""
        desktop_files = self._get_portproton_desktop_files()
        new_desktops = desktop_files - self._known_portproton_desktops
        self._known_portproton_desktops = desktop_files

        if not new_desktops or not self.game_library_manager.games:
            return

        existing_exec_lines = {game[5] for game in self.game_library_manager.games}

        def on_game_data(game_data: tuple | None) -> None:
            if not game_data:
                return
            exec_line = game_data[5]
            if exec_line in existing_exec_lines:
                return
            existing_exec_lines.add(exec_line)
            self.game_library_manager.add_game_incremental(game_data)
            QTimer.singleShot(200, self.game_library_manager.load_visible_images)

        for file_path in new_desktops:
            entry = parse_desktop_entry(file_path)
            if not entry or entry.get("Exec", "") in existing_exec_lines:
                continue
            self._process_desktop_file_async(file_path, on_game_data)

    def _get_portproton_desktop_files(self) -> set[str]:
        """Return current PortProton shortcut files."""
        if not self.portproton_location:
            return set()

        try:
            return {
                entry.path for entry in os.scandir(self.portproton_location)
                if entry.name.endswith(".desktop")
            }
        except OSError as e:
            logger.warning("Failed to scan PortProton shortcuts: %s", e)
            return set()

    def start_watching_directories(self):
        """Start watching PortProton directories for changes."""
        if not self.portproton_location:
            return

        dist_path = os.path.join(self.portproton_location, "data", "dist")
        prefixes_path = os.path.join(self.portproton_location, "data", "prefixes")

        # Create directories if they don't exist
        os.makedirs(dist_path, exist_ok=True)
        os.makedirs(prefixes_path, exist_ok=True)

        # Add dist directory to watcher
        self.fs_watcher.addPath(dist_path)

        # Add prefixes directory to watcher
        self.fs_watcher.addPath(prefixes_path)

        # Add shortcuts directory to watcher
        self.fs_watcher.addPath(self.portproton_location)
        self._known_portproton_desktops = self._get_portproton_desktop_files()

    def launch_autoinstall(
        self, script_name: str, button: AutoSizeButton | None = None
    ) -> None:
        """Launch auto-install script."""
        if self.installing:
            if script_name == self.current_install_script:
                self.stop_autoinstall()
                return
            QMessageBox.warning(self, _("Warning"), _("Installation already in progress."))
            return
        if not self._check_alt_i586_dependencies_before_launch():
            return
        self.installing = True
        self.install_stop_requested = False
        self.current_install_script = script_name
        self._set_install_button_stop(button)
        self._set_install_button_progress_text(_("Installing…"))
        self.seen_progress = False
        self.current_percent = 0.0
        start_sh = self.start_sh
        if not start_sh:
            self._reset_install_state()
            return
        cmd = start_sh + ["cli", "--autoinstall", script_name]
        self.install_process = QProcess(self)
        self.install_output_buffer = ""
        self.install_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.install_process.readyReadStandardOutput.connect(self._on_install_output_ready)
        self.install_process.finished.connect(self.on_install_finished)
        self.install_process.errorOccurred.connect(self.on_install_error)
        self.install_process.start(cmd[0], cmd[1:])
        if not self.install_process.waitForStarted(5000):
            self._reset_install_state()
            QMessageBox.warning(self, _("Error"), _("Failed to start installation."))
            return

    def _set_install_button_stop(self, button: AutoSizeButton | None = None) -> None:
        """Switch the active auto-install button to stop action."""
        self.current_install_button = button
        if button is None:
            return

        self.current_install_button_text = button.text()
        self.current_install_button_icon = button.rawIcon()
        icon = self.theme_manager.get_icon("stop", as_path=True)
        if icon:
            button.setIcon(icon)
        button.setText(_("Stop"))

    def detach_install_button(self, page: QWidget) -> None:
        """Detach install button before its detail page is deleted."""
        button = self.current_install_button
        if button is None:
            return
        try:
            if page.isAncestorOf(button):
                self.current_install_button = None
                self.current_install_button_text = None
                self.current_install_button_icon = None
        except RuntimeError:
            self.current_install_button = None
            self.current_install_button_text = None
            self.current_install_button_icon = None

    def _set_install_button_progress_text(
        self, status: str | None = None, percent: float | None = None
    ) -> None:
        """Update auto-install button text with current progress."""
        if self.current_install_button is None:
            return
        try:
            if percent is not None and percent > 0:
                progress_text = self._format_progress_percent(percent)
                button_text = f"{status} {progress_text}" if status else progress_text
                self.current_install_button.setText(button_text)
                return
            if status:
                self.current_install_button.setText(status)
                return
            self.current_install_button.setText(_("Stop"))
        except RuntimeError:
            self.current_install_button = None

    def _format_progress_percent(self, percent: float) -> str:
        """Format progress without hiding sub-percent values."""
        if 0 < percent < 1:
            return f"{percent:.1f}%"
        return f"{int(percent)}%"

    def _on_install_output_ready(self) -> None:
        """Update install progress from live PortProton output."""
        if self.install_process is None:
            return

        data = bytes(self.install_process.readAllStandardOutput().data()).decode(
            "utf-8", "ignore"
        )
        sys.stdout.write(data)
        sys.stdout.flush()
        self.install_output_buffer += data
        lines = self.install_output_buffer.splitlines(keepends=True)
        self.install_output_buffer = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.install_output_buffer = lines.pop()

        for line in lines:
            state = self._read_process_status_line(line)
            if state is None:
                continue
            status, percent, launch_started = state
            if launch_started:
                continue
            self._update_install_progress(status, percent)

    def _update_install_progress(
        self, status: str | None = None, percent: float | None = None
    ) -> None:
        """Apply parsed auto-install progress to the current button."""
        if status is not None:
            self.current_install_status = status
        elif percent is not None:
            status = self.current_install_status
        if percent is None:
            self._set_install_button_progress_text(status=status)
            return
        if percent > 0:
            self.seen_progress = True
            self.current_percent = percent
            self._set_install_button_progress_text(status=status, percent=percent)
            return
        if self.seen_progress and percent == 0:
            self.current_percent = 100.0
            self._set_install_button_progress_text(status=status, percent=100.0)
            return
        if status:
            self._set_install_button_progress_text(status=status)

    def _reset_install_state(self) -> None:
        """Reset auto-install process state and restore button."""
        self.installing = False
        self.install_stop_requested = False
        self.current_install_script = None
        if self.current_install_button is not None:
            try:
                if self.current_install_button_icon is not None:
                    self.current_install_button.setIcon(self.current_install_button_icon)
                if self.current_install_button_text is not None:
                    self.current_install_button.setText(self.current_install_button_text)
            except RuntimeError:
                pass
        self.current_install_button = None
        self.current_install_button_text = None
        self.current_install_button_icon = None
        self.current_install_status = None
        self.install_output_buffer = ""

    def stop_autoinstall(self) -> None:
        """Stop current auto-install process."""
        if not self.install_process:
            self._reset_install_state()
            return
        if (
            self.install_stop_process is not None
            and self.install_stop_process.state() != QProcess.ProcessState.NotRunning
        ):
            return

        self.install_stop_requested = True
        if not self.start_sh:
            logger.warning("PortProton start command is unavailable for stop")
            self.install_stop_requested = False
            return

        def on_stop_finished(exit_code: int, exit_status: QProcess.ExitStatus) -> None:
            if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                self.install_stop_requested = False
                QMessageBox.warning(self, _("Error"), _("Failed to stop installation."))
            if self.install_stop_process:
                self.install_stop_process.deleteLater()
                self.install_stop_process = None

        def on_stop_error(error: QProcess.ProcessError) -> None:
            logger.error("Failed to execute PortProton stop command: %s", error)
            self.install_stop_requested = False
            if self.install_stop_process:
                self.install_stop_process.deleteLater()
                self.install_stop_process = None

        self.install_stop_process = QProcess(self)
        self.install_stop_process.finished.connect(on_stop_finished)
        self.install_stop_process.errorOccurred.connect(on_stop_error)
        self.install_stop_process.start(self.start_sh[0], self.start_sh[1:] + ["cli", "--stop"])

    def _get_install_status_from_name(self, name: str, action: str) -> str:
        """Build install status text for a try_download target."""
        name_lower = name.lower()
        if "plugins" in name_lower:
            return _("{0} Plugins…").format(action)
        if "libs" in name_lower or "libraries" in name_lower:
            return _("{0} Libs…").format(action)
        if "wine" in name_lower or "proton" in name_lower:
            return f"{action} Wine…"
        return _("{0} components…").format(action)

    def _parse_process_status_line(
        self, line: str
    ) -> tuple[str | None, float | None, bool] | None:
        """Parse dependency setup status from one PortProton log line."""
        line_text = line.strip()
        line_lower = line.lower()
        status = percent = None
        launch_started = line_text == GAME_LAUNCH_MARKER
        progress_match = re.fullmatch(r'([0-9]*\.?[0-9]+)%', line_text)
        if progress_match:
            percent = float(progress_match.group(1))
        elif "download " in line_lower and " from " in line_lower:
            filename_match = re.search(r'download\s+(.+?)\s+from\s+', line, re.IGNORECASE)
            filename = filename_match.group(1) if filename_match else line
            status = self._get_install_status_from_name(filename, _("Downloading"))
        elif "unpacking file:" in line_lower:
            unpack_match = re.search(
                r'unpacking file:\s*(.+?)\s+please wait', line, re.IGNORECASE
            )
            filename = unpack_match.group(1) if unpack_match else line
            status = self._get_install_status_from_name(filename, _("Extracting"))
        elif "download and install" in line_lower:
            status = self._get_install_status_from_name(line, _("Downloading"))

        if status is None and percent is None and not launch_started:
            return None
        return status, percent, launch_started

    def _read_process_status_line(
        self, line: str
    ) -> tuple[str | None, float | None, bool] | None:
        """Log and parse one PortProton output line."""
        text = line.strip()
        if text:
            logger.info("%s", text)
        return self._parse_process_status_line(text)

    @Slot(int, int)
    def on_install_finished(self, exit_code: int, exit_status: int):
        """Handle installation finish."""
        script_name = self.current_install_script
        if self.install_stop_requested:
            if self.install_process:
                self.install_process.deleteLater()
                self.install_process = None
            self._reset_install_state()
            return
        if exit_code != 0:
            QMessageBox.warning(self, _("Error"), f"Installation failed (code: {exit_code}).")

        if self.install_process:
            self.install_process.deleteLater()
            self.install_process = None
        self._reset_install_state()
        if exit_code == 0:
            self.detail_page_manager.refresh_autoinstall_install_status(script_name)

    def on_install_error(self, error: QProcess.ProcessError):
        """Handle installation error."""
        if self.install_stop_requested:
            if self.install_process:
                self.install_process.deleteLater()
                self.install_process = None
            self._reset_install_state()
            return
        QMessageBox.warning(self, _("Error"), f"Process error: {error}")
        self._reset_install_state()

    @Slot(list)
    def on_games_loaded(self, games: list[tuple]):
        self._loading_games = False
        self.games = games
        if not game_config.get_only_installed():
            display_filter = game_config.get_display_filter()
            library_cache = getattr(self, "_loaded_library_cache", {})
            library_cache[display_filter] = games
            self._loaded_library_cache = library_cache
        focus_first_card = not getattr(self, "_preserve_library_focus_after_load", False)
        self._preserve_library_focus_after_load = False
        self.game_library_manager.set_games(games, focus_first_card=focus_first_card)
        self._known_portproton_desktops = self._get_portproton_desktop_files()

        # Clear the refresh in progress flag
        if hasattr(self, '_refresh_in_progress'):
            self._refresh_in_progress = False

        # Re-enable the refresh button if it exists
        if hasattr(self, 'refreshButton'):
            self.refreshButton.setEnabled(True)
            self._gamepad_tooltip_map[self.refreshButton] = _("Refresh Grid")

    def loadGames(self, force_load: bool = False):
        if self._loading_games:
            return

        # Skip loading library if launching a specific exe
        if self.launch_exe and not force_load:
            return

        if force_load:
            self.launch_exe = None

        self._loading_games = True
        display_filter = game_config.get_display_filter()
        favorites = favorites_config.get_games()
        self.pending_games = []
        self.games = []

        def start_loading():
            source_loader = getattr(
                self, f"_load_{display_filter}_games_async", None
            )
            if callable(source_loader):
                source_loader(lambda games: self.games_loaded.emit(games))
            elif display_filter == "favorites":
                def on_all_games_favorites():
                    games = [
                        game for source in results.values() for game in source
                        if game[0] in favorites
                    ]
                    self.games_loaded.emit(games)

                # Load games from different sources in parallel to prevent blocking
                results = {'portproton': [], 'steam': [], 'gog': [], 'egs': []}
                completed = dict.fromkeys(results, False)

                def check_completion():
                    if all(completed.values()):
                        QApplication.processEvents()  # Keep UI responsive
                        on_all_games_favorites()

                def portproton_callback(games):
                    results['portproton'] = games
                    completed['portproton'] = True
                    QApplication.processEvents()  # Keep UI responsive
                    check_completion()

                def steam_callback(games):
                    results['steam'] = games
                    completed['steam'] = True
                    QApplication.processEvents()  # Keep UI responsive
                    check_completion()

                def gog_callback(games):
                    results['gog'] = games
                    completed['gog'] = True
                    check_completion()

                def egs_callback(games):
                    results['egs'] = games
                    completed['egs'] = True
                    check_completion()

                self._load_portproton_games_async(portproton_callback)
                self._load_steam_games_async(steam_callback)
                self._load_gog_games_async(gog_callback)
                self._load_egs_games_async(egs_callback)
            else:
                # For 'all' filter - load games from different sources in parallel to prevent blocking
                results = {'portproton': [], 'steam': [], 'gog': [], 'egs': []}
                completed = dict.fromkeys(results, False)

                def on_all_games():
                    seen = set()
                    games = []
                    for source_games in results.values():
                        for game in source_games:
                        # Unique key: name + exec_line
                            key = (game[0], game[5])
                            if key not in seen:
                                seen.add(key)
                                games.append(game)
                    QApplication.processEvents()  # Keep UI responsive
                    self.games_loaded.emit(games)

                def check_completion():
                    if all(completed.values()):
                        QApplication.processEvents()  # Keep UI responsive
                        on_all_games()

                def portproton_callback(games):
                    results['portproton'] = games
                    completed['portproton'] = True
                    QApplication.processEvents()  # Keep UI responsive
                    check_completion()

                def steam_callback(games):
                    results['steam'] = games
                    completed['steam'] = True
                    QApplication.processEvents()  # Keep UI responsive
                    check_completion()

                def gog_callback(games):
                    results['gog'] = games
                    completed['gog'] = True
                    check_completion()

                def egs_callback(games):
                    results['egs'] = games
                    completed['egs'] = True
                    check_completion()

                # Load all sources in parallel
                self._load_portproton_games_async(portproton_callback)
                self._load_steam_games_async(steam_callback)
                self._load_gog_games_async(gog_callback)
                self._load_egs_games_async(egs_callback)

        # Run loading immediately to show status without delay
        start_loading()

    def _load_gog_games_async(self, callback: Callable[[list[tuple]], None]) -> None:
        api = getattr(self, "gog_api", None) or GOGAPI()
        installed = api.load_installed()
        only_installed = game_config.get_only_installed()
        library = [game for game in api.load_library() if game.get("app_id")]
        if self._upgrade_legacy_gog_library(api, library, callback):
            return
        games = []
        if not library:
            callback(games)
            return
        from portprotonqt.time_utils import get_statistics_path
        statistics_file = get_statistics_path()
        processed_count = 0

        def on_game_info(game: dict, steam_info: dict) -> None:
            nonlocal processed_count
            app_id = str(game.get("app_id", ""))
            is_installed = api.is_game_installed(app_id, installed)
            if not only_installed or is_installed:
                action = "launch" if is_installed else "install"
                target = api.get_launch_target(app_id) if is_installed else None
                playtime_seconds = get_playtime_for_exe(
                    statistics_file, target, exact_path=True
                ) if target else 0
                playtime_seconds = playtime_seconds or 0
                games.append((
                    str(game.get("title", app_id)),
                    str(game.get("description", "")), str(game.get("cover", "")),
                    app_id,
                    steam_info.get("controller_support", ""),
                    f"gog://{action}/{app_id}",
                    get_last_launch(f"gog-{app_id}") if target else _("Never"),
                    format_playtime(playtime_seconds),
                    steam_info.get("protondb_tier", ""),
                    steam_info.get("anticheat_status", ""),
                    get_last_launch_timestamp(f"gog-{app_id}") if target else 0,
                    playtime_seconds,
                    "gog",
                    steam_info.get("anticheat_slug", ""),
                    steam_info.get("ppdb_id", ""), steam_info.get("ppdb_rating", ""),
                    steam_info.get("appid", ""),
                ))
            processed_count += 1
            if processed_count == len(library):
                callback(games)

        for game in library:
            app_id = str(game.get("app_id", ""))
            steam_appid = str(game.get("steam_appid", ""))
            if steam_appid:
                get_full_steam_game_info_async(
                    int(steam_appid),
                    lambda info, current_game=game: on_game_info(current_game, info),
                    fallback_name=str(game.get("title", app_id)),
                )
                continue
            get_steam_game_info_async(
                str(game.get("title", app_id)),
                f"gog://launch/{app_id}",
                lambda info, current_game=game: on_game_info(current_game, info),
            )

    def _load_egs_games_async(self, callback: Callable[[list[tuple]], None]) -> None:
        library = [game for game in self.egs_api.load_library() if game.get("app_id")]
        only_installed = game_config.get_only_installed()
        games = []
        if not library:
            callback(games)
            return
        from portprotonqt.time_utils import get_statistics_path
        statistics_file = get_statistics_path()
        processed_count = 0

        def on_game_info(game: dict, steam_info: dict) -> None:
            nonlocal processed_count
            app_id = str(game["app_id"])
            installed = self.egs_api.is_game_installed(app_id)
            if not only_installed or installed:
                target = self.egs_api.get_launch_target(app_id) if installed else None
                description = str(game.get("description", ""))
                if not description or description == str(game.get("title", "")):
                    description = str(steam_info.get("description", ""))
                playtime = get_playtime_for_exe(
                    statistics_file, target, exact_path=True
                ) if target else 0
                playtime = playtime or 0
                games.append((
                    str(game.get("title", app_id)), description,
                    str(game.get("cover", "")), app_id,
                    steam_info.get("controller_support", ""),
                    f"egs://{'launch' if installed else 'install'}/{app_id}",
                    get_last_launch(f"egs-{app_id}") if target else _("Never"),
                    format_playtime(playtime), steam_info.get("protondb_tier", ""),
                    steam_info.get("anticheat_status", ""),
                    get_last_launch_timestamp(f"egs-{app_id}") if target else 0,
                    playtime, "egs", steam_info.get("anticheat_slug", ""),
                    steam_info.get("ppdb_id", ""), steam_info.get("ppdb_rating", ""),
                    steam_info.get("appid", ""),
                ))
            processed_count += 1
            if processed_count == len(library):
                callback(games)

        for game in library:
            get_steam_game_info_async(
                str(game.get("title", game["app_id"])),
                f"egs://launch/{game['app_id']}",
                lambda info, current_game=game: on_game_info(current_game, info),
            )

    def _upgrade_legacy_gog_library(
        self, api: GOGAPI, library: list[dict], callback: Callable[[list], None]
    ) -> bool:
        auth_path = getattr(api, "auth_path", None)
        needs_upgrade = any("steam_appid" not in game for game in library)
        if (
            not needs_upgrade
            or getattr(self, "_gog_metadata_upgrade_attempted", False)
            or auth_path is None
            or not auth_path.is_file()
        ):
            return False
        self._gog_metadata_upgrade_attempted = True
        worker = GOGLibraryWorker(api)
        worker.loaded.connect(lambda _games: self._load_gog_games_async(callback))
        worker.failed.connect(lambda _error: self._load_gog_games_async(callback))
        worker.finished.connect(lambda: setattr(self, "gog_metadata_worker", None))
        self.gog_metadata_worker = worker
        worker.start()
        return True

    def _load_steam_games_async(self, callback: Callable[[list[tuple]], None]):
        steam_games = []
        installed_games = get_steam_installed_games()
        logger.info("Found %d installed Steam games: %s", len(installed_games), [g[0] for g in installed_games])
        if not installed_games:
            callback(steam_games)
            return
        self.total_games = len(installed_games)
        processed_count = 0

        def on_game_info(info: dict, name, appid, last_played, playtime_seconds):
            nonlocal processed_count
            if not info:
                logger.warning("No info retrieved for game %s (appid %s)", name, appid)
                info = {
                    'description': '',
                    'cover': '',
                    'controller_support': '',
                    'protondb_tier': '',
                    'name': name,
                    'game_source': 'steam'
                }
            name, custom_cover = self._get_custom_steam_data(appid, name)
            last_launch = format_last_launch(datetime.fromtimestamp(last_played)) if last_played else _("Never")
            steam_games.append((
                name,
                info.get('description', ''),
                custom_cover or info.get('cover', ''),
                appid,
                info.get('controller_support', ''),
                f"steam://rungameid/{appid}",
                last_launch,
                format_playtime(playtime_seconds),
                info.get('protondb_tier', ''),
                info.get("anticheat_status", ""),
                last_played,
                playtime_seconds,
                "steam",
                info.get("anticheat_slug", ""),
                info.get("ppdb_id", ""),
                info.get("ppdb_rating", ""),
            ))
            processed_count += 1
            self.pending_games.append(None)
            if processed_count == len(installed_games):
                callback(steam_games)

        for name, appid, last_played, playtime_seconds in installed_games:
            get_full_steam_game_info_async(appid, lambda info, n=name, a=appid, lp=last_played, pt=playtime_seconds: on_game_info(info, n, a, lp, pt), fallback_name=name)

    @staticmethod
    def _get_custom_steam_data(
        appid: int | str, fallback_name: str
    ) -> tuple[str, str]:
        """Return custom Steam name and cover stored by AppID."""
        xdg_data_home = os.getenv(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        game_dir = os.path.join(
            xdg_data_home, "PortProtonQt", "custom_data", str(appid)
        )
        metadata_path = os.path.join(game_dir, "metadata.txt")
        custom_name = fallback_name
        if os.path.isfile(metadata_path):
            translations = read_metadata_translations(metadata_path, get_metadata_language())
            custom_name = translations.get("name", fallback_name).strip()
        for extension in COVER_IMAGE_EXTENSIONS:
            cover_path = os.path.join(game_dir, f"cover{extension}")
            if os.path.isfile(cover_path):
                return custom_name, cover_path
        return custom_name, ""

    def _load_portproton_games_async(self, callback: Callable[[list[tuple]], None]):
        games = []
        xdg_data_home = os.getenv(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "share"),
        )
        remove_empty_custom_data_dirs(
            os.path.join(xdg_data_home, "PortProtonQt", "custom_data")
        )
        if not self.portproton_location:
            callback(games)
            return
        desktop_files = [entry.path for entry in os.scandir(self.portproton_location)
                        if entry.name.endswith(".desktop")]
        if not desktop_files:
            callback(games)
            return
        self.total_games = len(desktop_files)
        processed_count = 0
        def on_desktop_processed(result: tuple | None, games=games):
            nonlocal processed_count
            if result:
                games.append(result)
            self.pending_games.append(None)
            processed_count += 1
            if processed_count == len(desktop_files):
                callback(games)
        with ThreadPoolExecutor() as executor:
            for file_path in desktop_files:
                executor.submit(self._process_desktop_file_async, file_path, on_desktop_processed)

    def _generate_missing_portproton_icon(self, game_exe: str, icon_path: str, desktop_name: str) -> str:
        if not self.portproton_location:
            return ""
        if not game_exe.lower().endswith(".exe") or not os.path.isfile(game_exe):
            return ""

        img_dir = os.path.join(self.portproton_location, "data", "img")
        os.makedirs(img_dir, exist_ok=True)
        target_path = ""

        if icon_path:
            expanded_icon = os.path.expanduser(icon_path)
            abs_icon = os.path.abspath(expanded_icon)
            abs_img_dir = os.path.abspath(img_dir)
            if abs_icon.startswith(abs_img_dir + os.sep):
                target_path = abs_icon
            elif not os.path.isabs(expanded_icon):
                icon_name = os.path.basename(expanded_icon)
                if not os.path.splitext(icon_name)[1]:
                    icon_name = f"{icon_name}.png"
                target_path = os.path.join(img_dir, icon_name)

        if not target_path:
            safe_name = os.path.basename(desktop_name) or os.path.splitext(os.path.basename(game_exe))[0]
            target_path = os.path.join(img_dir, f"{safe_name}.png")

        if os.path.isfile(target_path):
            return target_path
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if generate_thumbnail(game_exe, target_path, size=128):
            return target_path
        return ""

    def _process_desktop_file_async(
        self,
        file_path: str,
        callback: Callable[[tuple | None], None],
    ):
        entry = parse_desktop_entry(file_path)
        if not entry:
            callback(None)
            return
        desktop_name = entry.get("Name", _("Unknown Application"))
        if desktop_name.lower() in ["portproton", "readme"]:
            callback(None)
            return
        exec_line = entry.get("Exec", "")
        game_exe = ""
        exe_name = ""
        playtime_seconds = 0
        formatted_playtime = ""

        if exec_line:
            game_exe = extract_exec_target_path(exec_line) or ""

        xdg_data_home = os.getenv("XDG_DATA_HOME",
                                os.path.join(os.path.expanduser("~"), ".local", "share"))
        user_custom_folder = os.path.join(xdg_data_home, "PortProtonQt", "custom_data")

        user_cover = ""
        user_game_folder = ""
        generated_img_icon = ""
        themed_launch_icon = ""
        economy_mode = ui_config.get_economy_mode()
        if game_exe:
            exe_name = os.path.splitext(os.path.basename(game_exe))[0]
            user_game_folder = resolve_custom_data_dir(user_custom_folder, game_exe)
            themed_launch_icon = THEMED_LAUNCH_ICON_NAMES.get(os.path.splitext(game_exe)[1].lower(), "")
            generated_img_icon = self._generate_missing_portproton_icon(
                game_exe, entry.get("Icon", ""), desktop_name
            )

            user_files = set(os.listdir(user_game_folder)) if os.path.isdir(user_game_folder) else set()
            for ext in COVER_IMAGE_EXTENSIONS:
                candidate = f"cover{ext}"
                if candidate in user_files:
                    user_cover = os.path.join(user_game_folder, candidate)
                    break

            # Read statistics
            from portprotonqt.time_utils import get_statistics_path
            statistics_file = get_statistics_path()
            try:
                playtime_from_stats = get_playtime_for_exe(statistics_file, game_exe)
                if playtime_from_stats is not None:
                    playtime_seconds = playtime_from_stats
                    formatted_playtime = format_playtime(playtime_seconds)
            except Exception as e:
                logger.error(f"Failed to parse playtime data: {e}")

        def on_steam_info(steam_info: dict):
            # Get current language
            language_code = get_metadata_language()

            # Read translations from metadata.txt
            user_metadata_file = os.path.join(user_game_folder, "metadata.txt")

            translations = {'name': desktop_name, 'description': ''}
            if os.path.exists(user_metadata_file):
                translations = read_metadata_translations(user_metadata_file, language_code)

            final_name = translations['name']
            final_desc = translations['description'] or steam_info.get("description", "")
            final_cover = (
                user_cover if user_cover else
                steam_info.get("cover", "") or generated_img_icon or entry.get("Icon", "")
            )

            callback((
                final_name,
                final_desc,
                final_cover,
                steam_info.get("appid", ""),
                steam_info.get("controller_support", ""),
                exec_line,
                get_last_launch(exe_name) if exe_name else _("Never"),
                formatted_playtime,
                steam_info.get("protondb_tier", ""),
                steam_info.get("anticheat_status", ""),
                get_last_launch_timestamp(exe_name) if exe_name else 0,
                playtime_seconds,
                "portproton",
                steam_info.get("anticheat_slug", ""),
                steam_info.get("ppdb_id", ""),
                steam_info.get("ppdb_rating", ""),
            ))

        if economy_mode:
            language_code = get_metadata_language()
            user_metadata_file = os.path.join(user_game_folder, "metadata.txt")
            translations = {'name': desktop_name, 'description': ''}
            if os.path.exists(user_metadata_file):
                translations = read_metadata_translations(user_metadata_file, language_code)
            cached_steam_info = {} if themed_launch_icon else get_cached_steam_game_info(desktop_name, exec_line)
            final_name = translations['name'] or cached_steam_info.get("name", "")
            final_desc = translations['description'] or cached_steam_info.get("description", "")
            final_cover = (
                user_cover or cached_steam_info.get("cover", "") or
                generated_img_icon or entry.get("Icon", "")
            )
            if not final_cover and game_exe and game_exe.lower().endswith(".exe") and os.path.exists(game_exe):
                generated_cover_path = get_exe_icon_cache_path(game_exe)
                os.makedirs(os.path.dirname(generated_cover_path), exist_ok=True)
                if not os.path.exists(generated_cover_path):
                    if not generate_thumbnail(game_exe, generated_cover_path, size=128):
                        generated_cover_path = ""
                if generated_cover_path and os.path.exists(generated_cover_path):
                    final_cover = generated_cover_path
            callback((
                final_name,
                final_desc,
                final_cover,
                cached_steam_info.get("appid", ""),
                cached_steam_info.get("controller_support", ""),
                exec_line,
                get_last_launch(exe_name) if exe_name else _("Never"),
                formatted_playtime,
                "",
                "",
                get_last_launch_timestamp(exe_name) if exe_name else 0,
                playtime_seconds,
                "portproton",
                "",
            ))
            return

        get_steam_game_info_async(desktop_name, exec_line, on_steam_info)

    def _replace_game_from_desktop_file(self, file_path: str, old_name: str, old_exec_line: str):
        """Refresh one library card from its .desktop file."""
        def on_game_data(game_data: tuple | None):
            if not game_data:
                return
            self.game_library_manager.replace_game_incremental(old_name, old_exec_line, game_data)
            QTimer.singleShot(200, self.game_library_manager.load_visible_images)

        self._process_desktop_file_async(file_path, on_game_data)

    def finalize_game_loading(self):
        logger.info("Finalizing game loading, pending_games: %d", len(self.pending_games))
        if self.pending_games and all(x is None for x in self.pending_games):
            logger.info("All games processed, clearing pending_games")
            self.pending_games = []

    # TABS
    def switchVisibleTab(self, step: int) -> None:
        """Switch to the previous or next visible tab."""
        visible_indices = [
            i for i, btn in self.tabButtons.items()
            if btn.isVisible()
        ]
        visible_indices.sort()
        if not visible_indices:
            return

        current_index = self.stackedWidget.currentIndex()
        try:
            current_pos = visible_indices.index(current_index)
        except ValueError:
            current_pos = 0

        new_index = visible_indices[(current_pos + step) % len(visible_indices)]
        self.switchTab(new_index)

    def switchTab(self, index):
        """Set active tab by index."""
        SoundManager().play("tab_switch")
        # Check if the requested tab index is valid, exists, and is visible
        if (hasattr(self, 'tabButtons') and
            index in self.tabButtons and
            self.tabButtons[index].isVisible()):

            # Only allow switching to existing and visible tabs
            for i, btn in self.tabButtons.items():
                btn.setChecked(i == index)
            self.stackedWidget.setCurrentIndex(index)
            if index == self.auto_install_tab_index:
                QTimer.singleShot(0, self._start_autoinstall_load)
        else:
            # If trying to switch to a non-existent or hidden tab (like auto-install when it's hidden),
            # find the first visible tab to switch to
            visible_tab_found = False
            if hasattr(self, 'tabButtons'):
                for i, btn in self.tabButtons.items():
                    if btn.isVisible():
                        for j, other_btn in self.tabButtons.items():
                            other_btn.setChecked(j == i)
                        self.stackedWidget.setCurrentIndex(i)
                        visible_tab_found = True
                        break

            # If no visible tab found (shouldn't happen), default to the first tab
            if not visible_tab_found and hasattr(self, 'tabButtons') and 0 in self.tabButtons:
                for i, btn in self.tabButtons.items():
                    btn.setChecked(i == 0)
                self.stackedWidget.setCurrentIndex(0)

        current_index = self.stackedWidget.currentIndex()
        if current_index != 0:
            self._close_library_controls()
        if hasattr(self, "game_library_manager"):
            mgr = self.game_library_manager
            if current_index == 0 and mgr.gamesListWidget and mgr.gamesListLayout:
                self._load_empty_library_on_tab_enter(current_index)
                mgr.gamesListLayout.invalidate()
                mgr.gamesListWidget.adjustSize()
                mgr.gamesListWidget.updateGeometry()
        if current_index == self.auto_install_tab_index:
            if hasattr(self, "autoInstallContainer") and hasattr(self, "autoInstallContainerLayout"):
                self.autoInstallContainerLayout.invalidate()
                self.autoInstallContainer.adjustSize()
                self.autoInstallContainer.updateGeometry()

        if self.stackedWidget.currentIndex() == getattr(self, "system_tab_index", -1):
            QTimer.singleShot(0, self._focusSystemNetworkOnTabEnter)

    # GAME DETAIL PAGE LOGIC
    def getColorPalette_async(self, cover_path, num_colors=5, sample_step=10, callback=None):
        def on_pixmap(pixmap):
            if pixmap.isNull():
                if callback:
                    callback([QColor(self.theme.color_default_fallback)] * num_colors)
                    return

            image = pixmap.toImage()
            width, height = image.width(), image.height()
            histogram = {}
            for x in range(0, width, sample_step):
                for y in range(0, height, sample_step):
                    color = image.pixelColor(x, y)
                    key = (color.red() // 32, color.green() // 32, color.blue() // 32)
                    if key in histogram:
                        histogram[key][0] += color.red()
                        histogram[key][1] += color.green()
                        histogram[key][2] += color.blue()
                        histogram[key][3] += 1
                    else:
                        histogram[key] = [color.red(), color.green(), color.blue(), 1]
            avg_colors = []
            for _unused, (r_sum, g_sum, b_sum, count) in histogram.items():
                avg_r = r_sum // count
                avg_g = g_sum // count
                avg_b = b_sum // count
                avg_colors.append((count, QColor(avg_r, avg_g, avg_b)))
            avg_colors.sort(key=lambda x: x[0], reverse=True)
            palette = [color for count, color in avg_colors[:num_colors]]
            if len(palette) < num_colors:
                palette += [palette[-1]] * (num_colors - len(palette))
            if callback:
                callback(palette)

        load_pixmap_async(cover_path, 180, 250, on_pixmap)

    def getColorPalette_from_pixmap(self, pixmap, num_colors=5, sample_step=10, callback=None):
        """Extract color palette from a QPixmap directly."""
        if pixmap.isNull():
            if callback:
                callback([QColor(self.theme.color_default_fallback)] * num_colors)
                return

        image = pixmap.toImage()
        width, height = image.width(), image.height()
        histogram = {}
        for x in range(0, width, sample_step):
            for y in range(0, height, sample_step):
                color = image.pixelColor(x, y)
                key = (color.red() // 32, color.green() // 32, color.blue() // 32)
                if key in histogram:
                    histogram[key][0] += color.red()
                    histogram[key][1] += color.green()
                    histogram[key][2] += color.blue()
                    histogram[key][3] += 1
                else:
                    histogram[key] = [color.red(), color.green(), color.blue(), 1]
        avg_colors = []
        for _unused, (r_sum, g_sum, b_sum, count) in histogram.items():
            avg_r = r_sum // count
            avg_g = g_sum // count
            avg_b = b_sum // count
            avg_colors.append((count, QColor(avg_r, avg_g, avg_b)))
        avg_colors.sort(key=lambda x: x[0], reverse=True)
        palette = [color for count, color in avg_colors[:num_colors]]
        if len(palette) < num_colors:
            palette += [palette[-1]] * (num_colors - len(palette))
        if callback:
            callback(palette)

    def darkenColor(self, color, factor=200):
        return color.darker(factor)

    def resolve_launch_file_path(self, file_path: str | None) -> str | None:
        """Resolve launch path to actual executable path for settings/logs."""
        if not file_path:
            return None
        normalized = os.path.abspath(os.path.expanduser(file_path))
        if normalized.lower().endswith(DISC_IMAGE_EXTENSIONS):
            resolved = self._resolve_iso_executable(normalized)
            if resolved:
                return resolved
            return None
        return normalized

    def open_exe_settings(self, exe_path, appid=None, game_source=None):
        """Open the ExeSettingsDialog for the given executable."""
        resolved_exe_path = self.resolve_launch_file_path(exe_path)
        if not resolved_exe_path or not os.path.exists(resolved_exe_path):
            QMessageBox.warning(self, _("Error"), _("Executable not found: {0}").format(exe_path))
            return
        dialog = ExeSettingsDialog(
            self, self.theme, resolved_exe_path, appid=appid, game_source=game_source
        )
        dialog.exec()

    def openGameDetailPage(self, game_data: dict) -> None:
        """Open game detail page."""
        SoundManager().play("open")
        exec_line = str(game_data.get("exec_line", ""))
        if str(game_data.get("game_source", "")).lower() == "gog":
            app_id = str(game_data.get("appid", ""))
            if (
                exec_line.startswith("gog://install/")
                and self.gog_api.is_game_installed(app_id)
            ):
                game_data = dict(game_data)
                game_data["exec_line"] = f"gog://launch/{app_id}"
        if str(game_data.get("game_source", "")).lower() == "egs":
            app_id = str(game_data.get("appid", ""))
            if (
                exec_line.startswith("egs://install/")
                and self.egs_api.is_game_installed(app_id)
            ):
                game_data = dict(game_data)
                game_data["exec_line"] = f"egs://launch/{app_id}"
        logger.debug(
            "Opening detail page for %s from stacked index %d",
            game_data.get("name", ""),
            self.stackedWidget.currentIndex(),
        )
        self.detail_page_manager.openGameDetailPage(game_data)
        pending_log_exe = self._pending_log_exe
        detail_exe = extract_exec_target_path(game_data.get("exec_line", ""))
        if exec_line.startswith(("gog://launch/", "egs://launch/")):
            source, app_id = exec_line.split("://", 1)[0], exec_line.rsplit("/", 1)[-1]
            detail_exe = getattr(self, f"{source}_api").get_launch_target(app_id)
        if pending_log_exe and detail_exe:
            if os.path.abspath(detail_exe) == pending_log_exe:
                self._pending_log_exe = None
                log_button = self.detail_page_manager._debug_log_button
                if log_button:
                    self.detail_page_manager._start_debug_log(pending_log_exe, log_button)
        logger.debug(
            "Detail page opened at stacked index %d, current_detail=%s",
            self.stackedWidget.currentIndex(),
            self.stackedWidget.currentWidget() is self.currentDetailPage,
        )

    def _log_stacked_widget_change(self, index: int) -> None:
        current_widget = self.stackedWidget.currentWidget()
        logger.debug(
            "Stacked widget changed to index %d, detail=%s, widget=%s",
            index,
            current_widget is self.currentDetailPage,
            type(current_widget).__name__ if current_widget else "None",
        )

    def _write_desktop_file(self, desktop_entry: str, desktop_path: str) -> None:
        """Write desktop file with executable permissions."""
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop_entry)
        os.chmod(desktop_path, 0o755)
        logger.info("Created desktop file: %s", desktop_path)

    def open_local_autoinstall_card(self, script_path: str) -> None:
        """Open a temporary card for a local PPAI script."""
        if not os.path.isfile(script_path):
            QMessageBox.warning(self, _("Error"), _("File not found: {0}").format(script_path))
            return

        metadata = self.portproton_api.read_local_autoinstall_metadata(script_path)
        icon_path = self.theme_manager.get_icon("ppai", as_path=True)
        cover_path = icon_path if isinstance(icon_path, str) else ""
        name = metadata.get("name") or os.path.splitext(os.path.basename(script_path))[0]
        game_data = {
            "name": name,
            "description": metadata.get("description", ""),
            "cover_path": cover_path,
            "appid": "",
            "controller_support": "",
            "exec_line": f"autoinstall:{shlex.quote(script_path)}",
            "last_launch": _("Never"),
            "formatted_playtime": "0:00",
            "protondb_tier": "",
            "anticheat_status": "",
            "game_source": "portproton",
            "anticheat_slug": "",
            "ppdb_id": "",
            "ppdb_rating": "",
        }
        self.detail_page_manager.openAutoInstallDetailPage(game_data, return_tab_index=0)

    def handle_launch_exe(self, exe_path: str, log_mode: bool = False) -> None:
        """Handle launching a supported file from CLI.

        If the game exists in the library, open its detail page.
        If not, open detail page without creating a shortcut automatically.

        Args:
            exe_path: Full path to the launch file
            log_mode: Start UI logging after opening the detail page
        """
        # Normalize the exe path
        exe_path = os.path.abspath(exe_path)
        self._pending_log_exe = exe_path if log_mode else None
        economy_mode = ui_config.get_economy_mode()

        xdg_data_home = os.getenv(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        custom_data_root = os.path.join(xdg_data_home, "PortProtonQt", "custom_data")
        user_game_folder = resolve_custom_data_dir(custom_data_root, exe_path)

        local_cover_path = ""
        if os.path.isdir(user_game_folder):
            for ext in COVER_IMAGE_EXTENSIONS:
                candidate_cover = os.path.join(user_game_folder, f"cover{ext}")
                if os.path.exists(candidate_cover):
                    local_cover_path = candidate_cover
                    break

        generated_cover_path = ""
        themed_launch_icon = THEMED_LAUNCH_ICON_NAMES.get(os.path.splitext(exe_path)[1].lower(), "")
        themed_launch_cover = ""
        if themed_launch_icon:
            icon_path = self.theme_manager.get_icon(themed_launch_icon, as_path=True)
            themed_launch_cover = icon_path if isinstance(icon_path, str) else ""
        if not local_cover_path and os.path.isfile(exe_path) and exe_path.lower().endswith(".exe"):
            generated_cover_path = get_exe_icon_cache_path(exe_path)
            os.makedirs(os.path.dirname(generated_cover_path), exist_ok=True)
            if not os.path.exists(generated_cover_path):
                if not generate_thumbnail(exe_path, generated_cover_path, size=128):
                    generated_cover_path = ""
            if generated_cover_path and not os.path.exists(generated_cover_path):
                generated_cover_path = ""

        # Check if the game already exists in the library
        existing_entry = find_game_by_exe(exe_path)

        if existing_entry:
            # Game exists - open detail page
            game_name = existing_entry.get("Name", _("Unknown Game"))
            icon_path = existing_entry.get("Icon", "")
            exec_line = existing_entry.get("Exec", "")
            if economy_mode:
                cached_steam_info = {} if themed_launch_icon else get_cached_steam_game_info(game_name, exec_line)
                game_data = {
                    "name": game_name,
                    "description": cached_steam_info.get("description", ""),
                    "cover_path": local_cover_path or cached_steam_info.get("cover", "") or generated_cover_path or icon_path,
                    "appid": cached_steam_info.get("appid", ""),
                    "controller_support": cached_steam_info.get("controller_support", ""),
                    "exec_line": exec_line,
                    "last_launch": _("Never"),
                    "formatted_playtime": "0:00",
                    "protondb_tier": cached_steam_info.get("protondb_tier", ""),
                    "anticheat_status": cached_steam_info.get("anticheat_status", ""),
                    "game_source": "portproton",
                    "anticheat_slug": cached_steam_info.get("anticheat_slug", ""),
                    "ppdb_id": cached_steam_info.get("ppdb_id", ""),
                    "ppdb_rating": cached_steam_info.get("ppdb_rating", ""),
                }
                self.openGameDetailPage(game_data)
                return

            # Get Steam game info asynchronously to fetch appid, cover, etc.
            def on_steam_info(steam_info: dict):
                steam_cover_path = ""
                sgdb_cover_path = ""
                steam_info_cover = steam_info.get("cover", "")
                is_steam_game = steam_info.get("steam_game", "false") == "true"
                if is_steam_game:
                    steam_cover_path = steam_info_cover
                    appid = str(steam_info.get("appid", "")).strip()
                    if not steam_cover_path and appid:
                        steam_cover_path = f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900_2x.jpg"
                else:
                    sgdb_cover_path = steam_info_cover

                final_cover_path = (
                    local_cover_path or steam_cover_path or sgdb_cover_path or
                    themed_launch_cover or generated_cover_path or icon_path
                )

                if not (local_cover_path or steam_cover_path or sgdb_cover_path) and not themed_launch_icon:
                    def on_sgdb_cover(cover: str) -> None:
                        game_data = {
                            "name": game_name,
                            "description": steam_info.get("description", ""),
                            "cover_path": (
                                local_cover_path or steam_cover_path or cover or
                                themed_launch_cover or generated_cover_path or icon_path
                            ),
                            "appid": steam_info.get("appid", ""),
                            "controller_support": steam_info.get("controller_support", ""),
                            "exec_line": exec_line,
                            "last_launch": _("Never"),
                            "formatted_playtime": "0:00",
                            "protondb_tier": steam_info.get("protondb_tier", ""),
                            "anticheat_status": steam_info.get("anticheat_status", ""),
                            "game_source": "portproton",
                            "anticheat_slug": steam_info.get("anticheat_slug", ""),
                            "ppdb_id": steam_info.get("ppdb_id", ""),
                            "ppdb_rating": steam_info.get("ppdb_rating", ""),
                        }
                        self.openGameDetailPage(game_data)

                    fetch_sgdb_cover_async(game_name, on_sgdb_cover)
                    return

                game_data = {
                    "name": game_name,
                    "description": steam_info.get("description", ""),
                    "cover_path": final_cover_path,
                    "appid": steam_info.get("appid", ""),
                    "controller_support": steam_info.get("controller_support", ""),
                    "exec_line": exec_line,
                    "last_launch": _("Never"),
                    "formatted_playtime": "0:00",
                    "protondb_tier": steam_info.get("protondb_tier", ""),
                    "anticheat_status": steam_info.get("anticheat_status", ""),
                    "game_source": "portproton",
                    "anticheat_slug": steam_info.get("anticheat_slug", ""),
                    "ppdb_id": steam_info.get("ppdb_id", ""),
                    "ppdb_rating": steam_info.get("ppdb_rating", ""),
                }
                # Open detail page for the newly added game
                self.openGameDetailPage(game_data)

            get_steam_game_info_async(game_name, exec_line, on_steam_info)
        else:
            # Game not found in library: open detail page without creating .desktop file
            game_name_from_exe = os.path.splitext(os.path.basename(exe_path))[0]
            direct_exec_line = shlex.quote(exe_path)
            if economy_mode:
                cached_steam_info = {} if themed_launch_icon else get_cached_steam_game_info(game_name_from_exe, direct_exec_line)
                game_data = {
                    "name": game_name_from_exe,
                    "description": cached_steam_info.get("description", ""),
                    "cover_path": local_cover_path or cached_steam_info.get("cover", "") or themed_launch_cover or generated_cover_path,
                    "appid": cached_steam_info.get("appid", ""),
                    "controller_support": cached_steam_info.get("controller_support", ""),
                    "exec_line": direct_exec_line,
                    "last_launch": _("Never"),
                    "formatted_playtime": "0:00",
                    "protondb_tier": cached_steam_info.get("protondb_tier", ""),
                    "anticheat_status": cached_steam_info.get("anticheat_status", ""),
                    "game_source": "portproton",
                    "anticheat_slug": cached_steam_info.get("anticheat_slug", ""),
                    "ppdb_id": cached_steam_info.get("ppdb_id", ""),
                    "ppdb_rating": cached_steam_info.get("ppdb_rating", ""),
                }
                self.openGameDetailPage(game_data)
                return

            def on_steam_info_missing(steam_info: dict):
                steam_cover_path = ""
                sgdb_cover_path = ""
                steam_info_cover = steam_info.get("cover", "")
                is_steam_game = steam_info.get("steam_game", "false") == "true"
                if is_steam_game:
                    steam_cover_path = steam_info_cover
                    appid = str(steam_info.get("appid", "")).strip()
                    if not steam_cover_path and appid:
                        steam_cover_path = f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900_2x.jpg"
                else:
                    sgdb_cover_path = steam_info_cover

                final_cover_path = (
                    local_cover_path or steam_cover_path or sgdb_cover_path or
                    themed_launch_cover or generated_cover_path
                )

                if not (local_cover_path or steam_cover_path or sgdb_cover_path) and not themed_launch_icon:
                    def on_sgdb_cover(cover: str) -> None:
                        game_data = {
                            "name": game_name_from_exe,
                            "description": steam_info.get("description", ""),
                            "cover_path": (
                                local_cover_path or steam_cover_path or cover or
                                themed_launch_cover or generated_cover_path
                            ),
                            "appid": steam_info.get("appid", ""),
                            "controller_support": steam_info.get("controller_support", ""),
                            "exec_line": direct_exec_line,
                            "last_launch": _("Never"),
                            "formatted_playtime": "0:00",
                            "protondb_tier": steam_info.get("protondb_tier", ""),
                            "anticheat_status": steam_info.get("anticheat_status", ""),
                            "game_source": "portproton",
                            "anticheat_slug": steam_info.get("anticheat_slug", ""),
                            "ppdb_id": steam_info.get("ppdb_id", ""),
                            "ppdb_rating": steam_info.get("ppdb_rating", ""),
                        }
                        self.openGameDetailPage(game_data)

                    fetch_sgdb_cover_async(game_name_from_exe, on_sgdb_cover)
                    return

                game_data = {
                    "name": game_name_from_exe,
                    "description": steam_info.get("description", ""),
                    "cover_path": final_cover_path,
                    "appid": steam_info.get("appid", ""),
                    "controller_support": steam_info.get("controller_support", ""),
                    "exec_line": direct_exec_line,
                    "last_launch": _("Never"),
                    "formatted_playtime": "0:00",
                    "protondb_tier": steam_info.get("protondb_tier", ""),
                    "anticheat_status": steam_info.get("anticheat_status", ""),
                    "game_source": "portproton",
                    "anticheat_slug": steam_info.get("anticheat_slug", ""),
                    "ppdb_id": steam_info.get("ppdb_id", ""),
                    "ppdb_rating": steam_info.get("ppdb_rating", ""),
                }
                self.openGameDetailPage(game_data)

            get_steam_game_info_async(game_name_from_exe, direct_exec_line, on_steam_info_missing)


    def activateFocusedWidget(self):
        """Activate the currently focused widget."""
        focused_widget = QApplication.focusWidget()
        if not focused_widget:
            return
        if isinstance(focused_widget, ClickableLabel):
            focused_widget.clicked.emit()
        elif isinstance(focused_widget, AutoSizeButton):
            focused_widget.click()
        elif isinstance(focused_widget, QPushButton):
            focused_widget.click()
        elif callable(click := getattr(focused_widget, "click", None)):
            click()
        elif isinstance(focused_widget, NavLabel):
            focused_widget.clicked.emit()
        elif isinstance(focused_widget, ImageCarousel):
            if focused_widget.image_items:
                current_item = focused_widget.image_items[focused_widget.horizontalScrollBar().value() // 100]
                current_item.show_fullscreen()
        elif isinstance(focused_widget, QLineEdit):
            focused_widget.setFocus()
            focused_widget.selectAll()
        elif isinstance(focused_widget, QCheckBox):
            focused_widget.setChecked(not focused_widget.isChecked())
        parent = focused_widget.parent()
        while parent:
            if isinstance(parent, FileExplorer):
                parent.select_item()
                break
            parent = parent.parent()


    def checkTargetExe(self):
        """Update launch state from the marker and PortProton process."""
        child_running = self._has_running_game_process()
        dependency_active = self._drain_launch_output_progress()

        if dependency_active:
            # Dependencies are downloading/extracting - update button with progress
            self._set_running_button_progress()
        elif child_running:
            self._set_running_button_stop()
        else:
            # Game completed - reset flag, reset button and stop timer
            self._analyze_short_launch()
            if getattr(self, "launcher_process_only", False):
                self._terminate_game_processes()
            self.resetPlayButton()
            #self._uninhibit_screensaver()
            if hasattr(self, 'checkProcessTimer') and self.checkProcessTimer is not None:
                self.checkProcessTimer.stop()
                self.checkProcessTimer.deleteLater()
                self.checkProcessTimer = None
            self._finish_silent_launch()

    def _finish_silent_launch(self) -> None:
        if not getattr(self, "silent_launch_mode", False):
            return
        if self.tray_manager is not None:
            self.tray_manager.tray_icon.hide()
        QApplication.quit()

    def _set_running_button_stop(self) -> None:
        """Update current running button to stop state."""
        if self.current_running_button is None:
            return
        try:
            self.current_running_button.setText(_("Stop"))
            icon = self.theme_manager.get_icon("stop", as_path=True)
            self.current_running_button.setIcon(icon)
        except RuntimeError:
            self.current_running_button = None

    def _set_running_button_progress(self) -> None:
        """Update current running button with dependency setup progress."""
        if self.current_running_button is None:
            return
        try:
            status = self.wine_download_status
            if self.wine_download_percent > 0:
                status = f"{status} {self._format_progress_percent(self.wine_download_percent)}"
            self.current_running_button.setText(status)
            icon = self.theme_manager.get_icon("save", as_path=True)
            self.current_running_button.setIcon(icon)
        except RuntimeError:
            self.current_running_button = None

    def _drain_launch_output_progress(self) -> bool:
        """Apply pending launch dependency statuses from live process output."""
        while True:
            try:
                status, percent, launch_started = self.launch_output_queue.get_nowait()
            except Empty:
                break
            if launch_started:
                if not self.game_launch_started:
                    self.game_launch_monotonic = time.monotonic()
                    self.game_process_exit_monotonic = None
                self.game_launch_started = True
                continue
            if status is not None:
                logger.debug("Launch dependency progress: %s %s", status, percent)
                self.wine_download_status = status
                self.wine_download_seen = True
                self.wine_download_percent = percent or 0.0
            elif percent is not None:
                self.wine_download_seen = True
                self.wine_download_percent = percent
        return self.wine_download_seen and not self.game_launch_started

    def resetPlayButton(self):
        """
        Reset game launch button:
        change text to "Play", set icon and reset variables.
        Called when game completed (not by button press).
        """
        if self.current_running_button is not None:
            try:
                self.current_running_button.setText(_("Start"))
                icon = self.theme_manager.get_icon("play", as_path=True)
                self.current_running_button.setIcon(icon)
            except RuntimeError:
                pass
            self.current_running_button = None

        start_time = getattr(self, "game_start_time", None)
        start_exe = getattr(self, "game_start_exe", None)
        if start_time and start_exe:
            elapsed = int((datetime.now() - start_time).total_seconds())
            if elapsed > 0:
                from portprotonqt.time_utils import save_playtime
                exact_path = getattr(self, "game_start_exact_path", False)
                save_playtime(start_exe, elapsed, exact_path=exact_path)
                self._update_playtime_after_exit(start_exe, elapsed)
            self.game_start_time = None
            self.game_start_exe = None
            self.game_start_exact_path = False
            self.game_launch_monotonic = None
            self.game_process_exit_monotonic = None
            self.game_stopped_by_user = False

        self.target_exe = None
        # Reset dependency setup monitoring
        self.wine_download_seen = False
        self.wine_download_percent = 0.0
        self.wine_download_status = _("Downloading Wine…")
        self.game_launch_started = False
        launcher_only = getattr(self, "launcher_process_only", False)
        self.launcher_process_only = False
        self.game_processes = [] if launcher_only else [
            proc for proc in self.game_processes if proc.poll() is None
        ]
        if not getattr(self, "_animated_covers_suspended", False):
            self.input_manager.resume_gamepad_polling()
        self._refresh_portproton_shortcuts()

    def _update_game_list_playtime(
        self, games: list[tuple], exe_path: str, additional_seconds: int
    ) -> tuple[list[tuple], bool]:
        updated_games = []
        changed = False
        for game in games:
            game_exe = self._get_game_executable(game[5]) if len(game) > 5 else ""
            if (
                len(game) <= 11
                or not game_exe
                or os.path.normpath(game_exe) != exe_path
            ):
                updated_games.append(game)
                continue
            updated_game = list(game)
            updated_game[11] = (updated_game[11] or 0) + additional_seconds
            updated_game[7] = format_playtime(updated_game[11])
            updated_games.append(tuple(updated_game))
            changed = True
        return updated_games, changed

    def _update_playtime_after_exit(self, exe_path: str, additional_seconds: int) -> None:
        target_path = os.path.normpath(exe_path)
        self.games, changed = self._update_game_list_playtime(
            self.games, target_path, additional_seconds
        )
        if not changed:
            return

        self.game_library_manager.games = self.games
        self.game_library_manager.filtered_games, _ = self._update_game_list_playtime(
            self.game_library_manager.filtered_games, target_path, additional_seconds
        )

        for card in self.game_library_manager.game_card_cache.values():
            card_exe = self._get_game_executable(card.exec_line)
            if os.path.normpath(card_exe) != target_path:
                continue
            card.playtime_seconds = (card.playtime_seconds or 0) + additional_seconds
            card.formatted_playtime = format_playtime(card.playtime_seconds)

        self.game_library_manager.update_game_grid(focus_first_card=False)
        self._refresh_current_detail_time()

    def _update_game_list_last_launch(
        self, games: list[tuple], exe_path: str, launch_time: datetime
    ) -> tuple[list[tuple], bool]:
        updated_games = []
        changed = False
        for game in games:
            game_exe = self._get_game_executable(game[5]) if len(game) > 5 else ""
            if (
                len(game) <= 10
                or not game_exe
                or os.path.normpath(game_exe) != exe_path
            ):
                updated_games.append(game)
                continue
            updated_game = list(game)
            updated_game[6] = format_last_launch(launch_time)
            updated_game[10] = launch_time.timestamp()
            updated_games.append(tuple(updated_game))
            changed = True
        return updated_games, changed

    def _update_last_launch_after_start(self, exe_path: str, launch_time: datetime) -> None:
        target_path = os.path.normpath(exe_path)
        self.games, changed = self._update_game_list_last_launch(
            self.games, target_path, launch_time
        )
        if not changed:
            return

        self.game_library_manager.games = self.games
        self.game_library_manager.filtered_games, _ = self._update_game_list_last_launch(
            self.game_library_manager.filtered_games, target_path, launch_time
        )

        for card in self.game_library_manager.game_card_cache.values():
            card_exe = self._get_game_executable(card.exec_line)
            if os.path.normpath(card_exe) != target_path:
                continue
            card.last_launch = format_last_launch(launch_time)
            card.last_launch_ts = launch_time.timestamp()

        self.game_library_manager.update_game_grid(focus_first_card=False)
        self._refresh_current_detail_time()

    def _get_game_executable(self, exec_line: str) -> str:
        """Resolve a library launch entry to its tracked executable."""
        if exec_line.startswith("gog://launch/"):
            app_id = exec_line.rsplit("/", 1)[-1]
            return str(self.gog_api.get_launch_target(app_id) or "")
        if exec_line.startswith("egs://launch/"):
            app_id = exec_line.rsplit("/", 1)[-1]
            return str(self.egs_api.get_launch_target(app_id) or "")
        return extract_exec_target_path(exec_line) or ""

    def _has_running_game_process(self) -> bool:
        process_alive = any(proc.poll() is None for proc in self.game_processes)
        if process_alive and not (
            getattr(self, "launcher_process_only", False)
            and (
                self.game_launch_started
                or getattr(self, "game_stopped_by_user", False)
            )
        ):
            self.game_process_exit_monotonic = None
            return True
        target = str(self.target_exe or "").lower()
        if target:
            for process in psutil.process_iter(attrs=["name", "status"]):
                try:
                    if (
                        str(process.info.get("name") or "").lower() == target
                        and process.info.get("status") != psutil.STATUS_ZOMBIE
                    ):
                        self.game_process_exit_monotonic = None
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        if getattr(self, "game_stopped_by_user", False):
            return False
        launch_started = getattr(self, "game_launch_monotonic", None)
        if launch_started is not None:
            now = time.monotonic()
            if getattr(self, "game_process_exit_monotonic", None) is None:
                self.game_process_exit_monotonic = now
            return now - launch_started < STORE_LAUNCH_GRACE_SECONDS
        started = getattr(self, "game_start_time", None)
        if started is None:
            return False
        return (datetime.now() - started).total_seconds() < STORE_LAUNCH_GRACE_SECONDS

    def _start_launch_output_reader(self, process: subprocess.Popen[str]) -> None:
        """Start background reader for PortProton launch output."""
        self.launch_output_queue = Queue()
        self.launch_output_thread = Thread(
            target=self._read_launch_output,
            args=(process,),
            daemon=True,
        )
        self.launch_output_thread.start()

    def _read_launch_output(self, process: subprocess.Popen[str]) -> None:
        """Read launch output and queue parsed dependency statuses."""
        if process.stdout is None:
            return
        for line in process.stdout:
            state = self._read_process_status_line(line)
            if state is not None:
                self.launch_output_queue.put(state)

    def _read_egs_launch_output(self, process: subprocess.Popen[str]) -> None:
        """Resolve an EGS command before starting its controlled Wine process."""
        if process.stdout is None:
            return
        launch_data = None
        for line in process.stdout:
            text = line.strip()
            if text:
                logger.info("%s", text)
            if text.startswith("{"):
                try:
                    launch_data = orjson.loads(text)
                except orjson.JSONDecodeError:
                    logger.warning("Invalid Legendary launch response")
        process.wait()
        if process.returncode != 0 or launch_data is None or self.egs_launch_cancelled:
            return
        command = list(launch_data.get("launch_command", []))
        executable = os.path.join(
            launch_data.get("game_directory", ""),
            launch_data.get("game_executable", ""),
        )
        command.extend([executable, *launch_data.get("game_parameters", [])])
        command.extend(launch_data.get("egl_parameters", []))
        command.extend(launch_data.get("user_parameters", []))
        environment = os.environ.copy()
        environment.update(launch_data.get("environment", {}))
        try:
            game_process = subprocess.Popen(
                command, env=environment, shell=False, preexec_fn=os.setsid,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace",
            )
        except OSError as error:
            logger.error("Failed to start resolved Epic game: %s", error)
            return
        if self.egs_launch_cancelled:
            os.killpg(os.getpgid(game_process.pid), signal.SIGTERM)
            game_process.kill()
            return
        self.game_processes = [game_process]
        self._start_launch_output_reader(game_process)

    def _analyze_short_launch(self) -> None:
        if not ui_config.get_crash_reports_enabled():
            return
        executable = getattr(self, "game_start_exe", None) or ""
        started = getattr(self, "game_launch_monotonic", None)
        if started is None:
            return
        ended = getattr(self, "game_process_exit_monotonic", None)
        duration = (ended or time.monotonic()) - started
        stopped_by_user = getattr(self, "game_stopped_by_user", False)
        exit_code = next(
            (process.poll() for process in self.game_processes if process.poll() is not None),
            None,
        )
        launch = CompatibilityLaunch(
            executable=executable,
            exit_code=exit_code,
            duration=duration,
        )
        worker = Thread(
            target=self._build_compatibility_report,
            args=(launch, stopped_by_user),
            daemon=True,
        )
        worker.start()

    def _build_compatibility_report(
        self, launch: CompatibilityLaunch, stopped_by_user: bool
    ) -> None:
        try:
            incompatible_dxvk = has_dxvk_vulkan_incompatibility(launch.executable)
            if not incompatible_dxvk and not is_suspected_crash(
                launch.duration, stopped_by_user, launch.executable
            ):
                return
            report = analyze_launch(launch, self.portproton_location or "")
        except (OSError, ValueError, TypeError) as error:
            logger.error("Compatibility analysis failed for %s: %s", launch.executable, error)
            return
        self.compatibility_report_ready.emit(report)

    def _show_compatibility_report(self, report: str) -> None:
        dialog = CompatibilityReportDialog(self, self.theme, report)
        dialog.exec()

    def _terminate_game_processes(self) -> None:
        for proc in self.game_processes:
            if proc.poll() is not None:
                continue
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.kill()
            except ProcessLookupError:
                continue
            except OSError as e:
                logger.warning("Failed to terminate game process group %s: %s", proc.pid, e)

    def _run_portproton_stop_command(self) -> bool:
        """Run PortProton CLI stop command."""
        if not self.start_sh:
            logger.warning("PortProton start command is unavailable for stop")
            return False

        if not QProcess.startDetached(self.start_sh[0], self.start_sh[1:] + ["cli", "--stop"]):
            logger.error("Failed to execute PortProton stop command")
            return False

        return True

    def stop_running_game(self, button=None) -> bool:
        """Stop current game via PortProton CLI stop command."""
        if button is not None:
            self.current_running_button = button
        self.game_stopped_by_user = True
        self.egs_launch_cancelled = True
        if getattr(self, "launcher_process_only", False):
            if self._run_portproton_stop_command():
                return True

        self._analyze_short_launch()

        self._terminate_game_processes()
        self.game_processes = []
        stopped = self._run_portproton_stop_command()
        if hasattr(self, 'checkProcessTimer') and self.checkProcessTimer is not None:
            self.checkProcessTimer.stop()
            self.checkProcessTimer.deleteLater()
            self.checkProcessTimer = None
        self.resetPlayButton()
        return stopped

    def _check_missing_prefix_by_name_before_launch(self, prefix_name: str, env_vars: dict[str, str]) -> None:
        """Check prefix presence and optionally disable default recommended libs."""
        if not prefix_name or not self.portproton_location:
            return

        prefix_path = os.path.join(self.portproton_location, "data", "prefixes", prefix_name)
        if os.path.isdir(prefix_path):
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Prefix not found"))
        msg_box.setText(_("Prefix '{0}' was not found. Install recommended libraries?").format(prefix_name))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.No:
            env_vars["DISABLE_CP_DEFPFX"] = "1"

    def _check_missing_prefix_before_launch(self, game_exe_path: str, env_vars: dict[str, str]) -> None:
        """Check game prefix and optionally disable default recommended libs."""
        if not game_exe_path:
            return

        prefix_name = get_prefix_name(game_exe_path)
        self._check_missing_prefix_by_name_before_launch(prefix_name, env_vars)

    def _is_alt_x86_64(self) -> bool:
        if os.uname().machine != "x86_64":
            return False

        try:
            with open("/etc/os-release", encoding="utf-8") as os_release:
                lines = os_release.readlines()
        except OSError as e:
            logger.debug("Failed to read /etc/os-release: %s", e)
            return False

        return any(line.strip() == "ID=altlinux" for line in lines)

    def _has_alt_biarch_repo(self) -> bool:
        try:
            result = subprocess.run(
                ["apt-repo"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Failed to check ALT repositories: %s", e)
            return False

        return ALT_BIARCH_REPO in result.stdout

    def _has_missing_alt_i586_packages(self) -> bool:
        if not self.start_sh:
            return True

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                subprocess.run,
                self.start_sh + ["cli", "--alt-i586-dependencies"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            event_flags = QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            QApplication.processEvents(event_flags)
            while not future.done():
                QApplication.processEvents(event_flags)
                time.sleep(0.01)
            try:
                result = future.result()
            except (OSError, subprocess.SubprocessError) as e:
                logger.warning("Failed to check ALT i586 packages: %s", e)
                return True

        return result.returncode != 0

    def _install_alt_i586_dependencies(self) -> bool:
        if not self.start_sh:
            return False

        command = [
            "pkexec",
            *self.start_sh,
            "cli",
            "--alt-i586-dependencies",
            "install",
        ]
        process = QProcess(self)
        event_loop = QEventLoop()
        process.finished.connect(event_loop.quit)
        process.start(
            sys.executable,
            ["-m", "portprotonqt.scripts_utils.easyterm", "-e", shlex.join(command)],
        )
        if not process.waitForStarted(5000):
            logger.warning("Failed to start ALT i586 dependency installer")
            return False

        event_loop.exec()
        return not self._has_missing_alt_i586_packages()

    def _check_alt_i586_dependencies_before_launch(self) -> bool:
        if not self._is_alt_x86_64():
            return True

        if not self._has_alt_biarch_repo():
            QMessageBox.warning(
                self,
                _("Error"),
                _("Repository x86_64-i586 is not enabled. See: {0}").format(ALT_BIARCH_URL),
            )
            return False

        if not self._has_missing_alt_i586_packages():
            return True

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Install dependencies"))
        msg_box.setText(_("32-bit dependencies are missing. Install them now?"))
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        msg_box.setButtonText(QMessageBox.StandardButton.Ok, _("OK"))
        msg_box.setButtonText(QMessageBox.StandardButton.Cancel, _("Cancel"))
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.Ok:
            return self._install_alt_i586_dependencies()
        return False

    def _resolve_iso_launch_parts(self, iso_path: str) -> list[str] | None:
        """Resolve executable and launch arguments from disc image autorun.inf."""
        return self.disc_image_manager.resolve_iso_launch_parts(iso_path)

    def _resolve_iso_executable(self, iso_path: str) -> str | None:
        """Resolve executable for disc image by reading [autorun] open= in autorun.inf."""
        return self.disc_image_manager.resolve_iso_executable(iso_path)

    def _get_game_name_for_exec_line(self, exec_line: str) -> str:
        for game in self.games:
            if len(game) > 5 and game[5] == exec_line and game[0]:
                return str(game[0])
        return ""

    def _launch_steam_game(self, exec_line: str) -> None:
        appid = exec_line.rsplit("/", 1)[-1]
        if not appid.isdigit():
            logger.warning("Invalid Steam URI: %s", exec_line)
            return

        for command in get_steam_launch_commands(appid):
            try:
                subprocess.Popen(command)
                SoundManager().play("game_launch")
                return
            except OSError as e:
                logger.warning("Failed to launch Steam app %s with %s: %s", appid, command[0], e)

        if QDesktopServices.openUrl(QUrl(exec_line)):
            SoundManager().play("game_launch")
        else:
            logger.warning("Failed to open Steam URI: %s", exec_line)

    def _handle_gog_game(self, exec_line: str, button=None) -> None:
        action, app_id = exec_line.removeprefix("gog://").split("/", 1)
        if action == "install" and self.gog_api.is_game_installed(app_id):
            action = "launch"
        if action == "launch":
            self._launch_gog_game(app_id, button)
            return
        game = next(
            (item for item in self.gog_api.load_library()
             if str(item.get("app_id", "")) == app_id),
            None,
        )
        if game:
            self._install_gog_game(game)

    def _handle_egs_game(self, exec_line: str, button=None) -> None:
        action, app_id = exec_line.removeprefix("egs://").split("/", 1)
        if action == "install" and self.egs_api.is_game_installed(app_id):
            action = "launch"
        if action == "launch":
            self._launch_egs_game(app_id, button)
            return
        self._install_egs_game(app_id)

    def _install_egs_game(self, app_id: str) -> None:
        self._install_egs_download(app_id)

    def _repair_egs_game(self, app_id: str) -> None:
        self._start_egs_operation(
            app_id, ["repair", app_id, "--skip-sdl", "-y"], _("Repair")
        )

    def _update_egs_game(self, app_id: str) -> None:
        self._start_egs_operation(
            app_id, ["update", app_id, "--platform", "Windows", "--skip-sdl", "-y"],
            _("Update")
        )

    def _delete_egs_game(self, app_id: str) -> None:
        self._start_egs_operation(
            app_id, ["uninstall", app_id, "-y"], _("Delete")
        )

    def _import_egs_game(self, app_id: str) -> None:
        selected_paths: list[str] = []
        explorer = FileExplorer(
            self, theme=self.theme, initial_path=str(Path.home() / "Games"),
            directory_only=True,
        )
        explorer.setWindowTitle(_("Select Epic game folder"))
        explorer.file_signal.file_selected.connect(selected_paths.append)
        explorer.exec()
        if selected_paths:
            self._start_egs_operation(app_id, [
                "import", app_id, selected_paths[0], "--with-dlcs",
                "--platform", "Windows", "-y",
            ], _("Import"))

    def _start_egs_operation(
        self, app_id: str, arguments: list[str], action: str
    ) -> None:
        if getattr(self, "egs_process", None) is not None:
            QMessageBox.warning(self, _("Error"), _("Another Epic operation is running"))
            return
        try:
            command = self.egs_api.build_command(arguments)
        except OSError as error:
            QMessageBox.warning(self, _("Error"), str(error))
            return
        game = next(
            (item for item in self.egs_api.load_library()
             if str(item.get("app_id", "")) == app_id),
            {"app_id": app_id, "title": app_id, "cover": ""},
        )
        self._start_egs_visible_operation(game, command, action)

    def _egs_process_environment(self) -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("LEGENDARY_CONFIG_PATH", str(self.egs_api.config_dir))
        return environment

    def _on_egs_operation_finished(
        self, app_id: str, action: str, exit_code: int
    ) -> None:
        self._finish_egs_visible_operation(action, exit_code == 0)
        if exit_code != 0:
            logger.error(
                "Epic %s failed for %s with code %s", action, app_id, exit_code
            )
            return
        if action == "eos-install":
            self._enable_egs_overlay(app_id)
            return
        self.loadGames(force_load=True)

    def _enable_egs_overlay(self, app_id: str) -> None:
        overlay_path = self.egs_api.data_dir / "eos_overlay"
        install_record = self.egs_api.config_dir / "overlay_install.json"
        if not install_record.is_file():
            self._start_egs_operation(app_id, [
                "eos-overlay", "install", "--path", str(overlay_path), "-y",
            ], "eos-install")
            return
        target = self.egs_api.get_launch_target(app_id)
        prefix_name = get_prefix_name(target)
        if not self.portproton_location:
            QMessageBox.warning(self, _("Error"), _("PortProton directory not found"))
            return
        prefix_path = Path(self.portproton_location) / "data/prefixes" / prefix_name
        if not (prefix_path / "user.reg").is_file():
            QMessageBox.warning(self, _("Error"), _("Wine prefix not found"))
            return
        action = (
            "disable"
            if self.egs_api.is_eos_overlay_enabled(prefix_path)
            else "enable"
        )
        self._start_egs_operation(app_id, [
            "eos-overlay", action, "--prefix", str(prefix_path),
        ], f"eos-{action}")

    def _is_egs_overlay_enabled(self, app_id: str) -> bool:
        target = self.egs_api.get_launch_target(app_id)
        if not target or not self.portproton_location:
            return False
        prefix_name = get_prefix_name(target)
        prefix_path = Path(self.portproton_location) / "data/prefixes" / prefix_name
        return self.egs_api.is_eos_overlay_enabled(prefix_path)

    def _launch_egs_game(self, app_id: str, button=None) -> None:
        target = self.egs_api.get_launch_target(app_id)
        if not target:
            self._finish_silent_launch()
            QMessageBox.warning(self, _("Error"), _("Game not found."))
            return
        if not self.start_sh:
            self._finish_silent_launch()
            QMessageBox.warning(self, _("Error"), _("PortProton start script not found"))
            return
        target_name = os.path.basename(target)
        if self.game_processes and self.target_exe == target_name:
            self.stop_running_game(button)
            return
        if self.game_processes:
            QMessageBox.warning(
                self, _("Error"), _("Cannot launch game while another game is running")
            )
            return
        if not self._check_alt_i586_dependencies_before_launch():
            self._finish_silent_launch()
            return
        try:
            command = self.egs_api.build_command([
                "launch", app_id, "--json", "--wrapper", self.start_sh[0],
                "--no-wine", "--skip-version-check",
            ])
            process = subprocess.Popen(
                command, env=self.egs_api.get_environment(), shell=False,
                preexec_fn=os.setsid, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace",
            )
        except OSError as error:
            self._finish_silent_launch()
            logger.error("Failed to launch Epic game %s: %s", app_id, error)
            QMessageBox.warning(self, _("Error"), str(error))
            return
        SoundManager().play("game_launch")
        self.egs_launch_cancelled = False
        self.launcher_process_only = True
        self.game_processes.append(process)
        self.target_exe = target_name
        self.current_running_button = button
        launch_time = datetime.now()
        self.game_start_time = launch_time
        self.game_start_exe = target
        self.game_start_exact_path = True
        save_last_launch(f"egs-{app_id}", launch_time)
        self._update_last_launch_after_start(target, launch_time)
        self.launch_output_queue = Queue()
        self.launch_output_thread = Thread(
            target=self._read_egs_launch_output,
            args=(process,),
            daemon=True,
        )
        self.launch_output_thread.start()
        self.input_manager.suspend_gamepad_polling()
        self.checkProcessTimer = QTimer(self)
        self.checkProcessTimer.timeout.connect(self.checkTargetExe)
        self.checkProcessTimer.start(500)
        if button is not None:
            button.setText(_("Stop"))
            button.setIcon(self.theme_manager.get_icon("stop", as_path=True))

    def _launch_gog_game(
        self, app_id: str, button=None, play_sound: bool = True
    ) -> None:
        self.gog_api.ensure_launch_parameters(app_id)
        discovered_path = self.gog_api.get_installed_path(app_id)
        install_path = str(discovered_path) if discovered_path else ""
        if not install_path:
            self._finish_silent_launch()
            QMessageBox.warning(self, _("Error"), _("Game not found."))
            return
        if not self.start_sh:
            self._finish_silent_launch()
            QMessageBox.warning(self, _("Error"), _("PortProton start script not found"))
            return
        target = os.path.basename(self.gog_api.get_launch_target(app_id) or app_id)
        if self.game_processes and self.target_exe == target:
            self.stop_running_game(button)
            return
        if self.game_processes:
            QMessageBox.warning(self, _("Error"), _("Cannot launch game while another game is running"))
            return
        needs_setup = getattr(self.gog_api, "needs_support_setup", lambda _app_id: False)
        if needs_setup(app_id):
            self._start_gog_support_setup(app_id, button)
            return
        if not self._check_alt_i586_dependencies_before_launch():
            self._finish_silent_launch()
            return
        try:
            command = self.gog_api.build_command([
                "launch", install_path, app_id, "--platform", "windows",
                "--wine", self.start_sh[0],
            ])
            process = subprocess.Popen(
                command, env=self.gog_api.get_environment(), shell=False,
                preexec_fn=os.setsid, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace",
            )
        except (OSError, ValueError) as error:
            self._finish_silent_launch()
            logger.error("Failed to launch GOG game %s: %s", app_id, error)
            QMessageBox.warning(self, _("Error"), str(error))
            return
        if play_sound:
            SoundManager().play("game_launch")
        self.game_processes.append(process)
        self.launcher_process_only = True
        self.target_exe = target
        self.current_running_button = button
        launch_target = self.gog_api.get_launch_target(app_id)
        if launch_target:
            launch_time = datetime.now()
            self.game_start_time = launch_time
            self.game_start_exe = launch_target
            self.game_start_exact_path = True
            save_last_launch(f"gog-{app_id}", launch_time)
            self._update_last_launch_after_start(launch_target, launch_time)
        self._start_launch_output_reader(process)
        self.input_manager.suspend_gamepad_polling()
        self.checkProcessTimer = QTimer(self)
        self.checkProcessTimer.timeout.connect(self.checkTargetExe)
        self.checkProcessTimer.start(500)
        if button is not None:
            button.setText(_("Stop"))
            button.setIcon(self.theme_manager.get_icon("stop", as_path=True))

    def toggleGame(self, exec_line, button=None, game_name=None):
        # Handle Steam games
        if exec_line.startswith("steam://"):
            self._launch_steam_game(exec_line)
            return

        if exec_line.startswith("gog://"):
            self._handle_gog_game(exec_line, button)
            return

        if exec_line.startswith("egs://"):
            self._handle_egs_game(exec_line, button)
            return

        # Handle PortProton games
        entry_exec_split = shlex.split(exec_line)
        if not entry_exec_split:
            QMessageBox.warning(self, _("Error"), _("Invalid command format (empty exec line)"))
            return
        launch_cmd = entry_exec_split
        file_to_check = extract_exec_target_path(entry_exec_split)
        if not file_to_check:
            QMessageBox.warning(self, _("Error"), _("Invalid command format (native)"))
            return

        first_exec_part = os.path.expanduser(entry_exec_split[0])
        if file_to_check.lower().endswith(DISC_IMAGE_EXTENSIONS):
            resolved_iso_parts = self._resolve_iso_launch_parts(file_to_check)
            if not resolved_iso_parts:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("Failed to launch game: {0}").format("autorun.inf or open executable not found")
                )
                return
            file_to_check = resolved_iso_parts[0]
            if not self.start_sh:
                QMessageBox.warning(self, _("Error"), _("PortProton start script not found"))
                return
            launch_cmd = self.start_sh + resolved_iso_parts
        elif self.start_sh and file_to_check.lower().endswith(WINDOWS_LAUNCH_EXTENSIONS):
            launch_file_parts = entry_exec_split if file_to_check == first_exec_part else [file_to_check]
            launch_cmd = self.start_sh + launch_file_parts

        if not os.path.exists(file_to_check):
            QMessageBox.warning(self, _("Error"), _("File not found: {0}").format(file_to_check))
            return

        current_exe = os.path.basename(file_to_check)
        if self.game_processes and self.target_exe is not None and self.target_exe != current_exe:
            QMessageBox.warning(self, _("Error"), _("Cannot launch game while another game is running"))
            return

        # Update button
        update_button = button if button is not None else self.current_play_button

        # If game already running for this exe - stop it
        if self.game_processes and self.target_exe == current_exe:
            if not self.stop_running_game(update_button):
                QMessageBox.warning(self, _("Error"), _("Failed to stop game"))
        else:
            if not self._check_alt_i586_dependencies_before_launch():
                return

            if update_button:
                try:
                    update_button.setText(_("Stop"))
                    icon = self.theme_manager.get_icon("stop", as_path=True)
                    update_button.setIcon(icon)
                except RuntimeError:
                    update_button = None
            SoundManager().play("game_launch")

            # Save button reference for reset after game completion
            self.current_running_button = update_button
            self.target_exe = current_exe
            exe_name = os.path.splitext(current_exe)[0]
            env_vars = os.environ.copy()
            inhibit_game_name = game_name or self._get_game_name_for_exec_line(exec_line)
            if inhibit_game_name:
                env_vars["PW_INHIBIT_NAME"] = inhibit_game_name
            game_exe_for_prefix = file_to_check if file_to_check.lower().endswith(WINDOWS_LAUNCH_EXTENSIONS) else ""
            self._check_missing_prefix_before_launch(game_exe_for_prefix, env_vars)

            # Launch game
            try:
                self.game_stopped_by_user = False
                process = subprocess.Popen(
                    launch_cmd,
                    env=env_vars,
                    shell=False,
                    preexec_fn=os.setsid,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    bufsize=1,
                )
                self.game_processes.append(process)
                self.game_launch_monotonic = None
                self._start_launch_output_reader(process)
                self.input_manager.suspend_gamepad_polling()
                launch_time = datetime.now()
                self.game_start_time = launch_time
                self.game_start_exe = file_to_check
                save_last_launch(exe_name, launch_time)
                self._update_last_launch_after_start(file_to_check, launch_time)
                # Reset dependency setup monitoring
                self.wine_download_seen = False
                self.wine_download_percent = 0.0
                self.wine_download_status = _("Downloading Wine…")
                self.game_launch_started = False

                self.checkProcessTimer = QTimer(self)
                self.checkProcessTimer.timeout.connect(self.checkTargetExe)
                self.checkProcessTimer.start(500)
            except Exception as e:
                logger.error(f"Failed to launch game {exe_name}: {e}")
                QMessageBox.warning(self, _("Error"), _("Failed to launch game: {0}").format(str(e)))

    def _initialize_tray(self, app_name: str) -> None:
        """Create the tray item after the Qt event loop starts."""
        if self.tray_manager is None:
            self.tray_manager = TrayManager(self, app_name, self.current_theme_name)

    def closeEvent(self, event):
        """Handle window close: check minimize_to_tray setting.
        If True - minimize to tray. Otherwise - fully close.
        """
        minimize_to_tray = display_config.get_minimize_to_tray()

        if minimize_to_tray:
            # Just minimize to tray
            event.ignore()
            self.hide()
            return

        # Full application close
        event.accept()

        watcher = getattr(self, "system_theme_watcher", None)
        if watcher is not None:
            watcher.requestInterruption()
            watcher.wait()

        # Hide and remove tray icon
        if self.tray_manager is not None:
            self.tray_manager.shutdown()

        # Save card sizes only for grid layouts.
        layout_mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        size_slider = getattr(self.game_library_manager, 'sizeSlider', None)
        if size_slider is None or layout_mode not in {
            "list", "vertical", "horizontal", "horizontal_top"
        }:
            ui_config.set_card_width(self.card_width)
        if (
            hasattr(self, 'auto_size_slider')
            and layout_mode not in {"list", "vertical", "horizontal", "horizontal_top"}
        ):
            ui_config.set_auto_card_width(self.auto_card_width)

        # Save window sizes (if not in fullscreen mode)
        if not display_config.get_fullscreen():
            logger.debug(f"Saving window geometry: {self.width()}x{self.height()}")
            window_config.set_geometry(self.width(), self.height())

        if self.game_processes:
            if not self.stop_running_game():
                logger.warning("Failed to stop running game during application shutdown")

        if self.install_process and self.install_process.state() != QProcess.ProcessState.NotRunning:
            if not self._run_portproton_stop_command():
                logger.warning("Failed to stop installation during application shutdown")

        self.disc_image_manager.cleanup_iso_rw_paths()
        self._stopBackgroundWorkers()

        # Universal stop and delete timers
        timers = [
            "games_load_timer",
            "settingsDebounceTimer",
            "searchDebounceTimer",
            "checkProcessTimer",
            "wine_monitor_timer",
        ]

        for tname in timers:
            timer = getattr(self, tname, None)
            if timer and timer.isActive():
                timer.stop()
            if timer:
                timer.deleteLater()
                setattr(self, tname, None)

        # Clean up animations to prevent memory leaks
        if hasattr(self, 'detail_animations'):
            try:
                self.detail_animations.cleanup()
            except RuntimeError:
                # Object already deleted
                pass

        # Clean up debug log manager to ensure logs are properly saved if application closes
        if hasattr(self, 'detail_page_manager') and hasattr(self.detail_page_manager, 'debug_log_manager'):
            try:
                self.detail_page_manager.debug_log_manager.cleanup_on_exit()
            except Exception as e:
                logger.warning(f"Failed to cleanup debug log manager: {e}")

    def goBackDetailPage(self, page):
        """Bridge method to detail page manager."""
        SoundManager().play("back")
        result = self.detail_page_manager.goBackDetailPage(page)
        # The detail page manager will handle the navigation properly
        return result

    def toggleFavoriteInDetailPage(self, game_name, label):
        """Bridge method to detail page manager."""
        return self.detail_page_manager.toggleFavoriteInDetailPage(game_name, label)
