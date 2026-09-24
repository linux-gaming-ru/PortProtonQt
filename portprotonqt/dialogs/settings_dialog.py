"""Settings dialog for PortProtonQt."""

import os
import re
import subprocess
from typing import cast, TYPE_CHECKING

from PySide6.QtCore import Qt, QObject, QEvent, QPoint, QProcess, QTimer, QUrl
from PySide6.QtGui import QColor, QContextMenuEvent, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from portprotonqt.main_window import MainWindow

from portprotonqt.config import (
    get_portproton_location,
    get_portproton_scripts_path,
    get_portproton_start_command,
    exe_settings_favorites_config,
    ui_config,
)
from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox
from portprotonqt.dialogs.base import DraggableDialog
from portprotonqt.dialogs.dialog_utils import create_dialog_hints_widget, update_dialog_hints
from portprotonqt.dialogs.settings_mangohud import MANGOHUD_ENV_KEYS, MangoHudSettingsMixin
from portprotonqt.dialogs.settings_gamescope import GAMESCOPE_ENV_KEYS, GamescopeSettingsMixin
from portprotonqt.dialogs.settings_vkbasalt import VKBASALT_ENV_KEYS, VkBasaltSettingsMixin
from portprotonqt.localization import _, format_setting_name_for_display
from portprotonqt.logger import get_logger
from portprotonqt.preloader import Preloader
from portprotonqt.qt_utils import get_screen_info, get_system_dpi_for_wine
from portprotonqt.settings_manager import (
    ADVANCED_SETTING_KEYS,
    get_available_prefix_options,
    get_available_wine_options,
    get_advanced_settings,
    get_toggle_settings,
    read_lg_dist_versions_from_var,
)
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.virtual_keyboard import VirtualKeyboard

logger = get_logger(__name__)
theme_manager = ThemeManager()
TOGGLE_BOOL_KEYS = {
    'PW_MANGOHUD',
    'PW_MANGOHUD_USER_CONF',
    'PW_GAMESCOPE',
    'PW_VKBASALT',
    'PW_VKBASALT_USER_CONF',
}
def _normalize_prefix_directories(prefixes_dir):
    if not os.path.isdir(prefixes_dir):
        return

    for prefix_name in os.listdir(prefixes_dir):
        current_path = os.path.join(prefixes_dir, prefix_name)
        if not os.path.isdir(current_path):
            continue

        normalized_name = re.sub(r"[ \t]", "_", prefix_name).upper()
        if normalized_name == prefix_name:
            continue

        normalized_path = os.path.join(prefixes_dir, normalized_name)
        if os.path.isdir(normalized_path):
            logger.warning(
                "Cannot rename prefix %s to %s: target already exists",
                prefix_name,
                normalized_name
            )
            continue

        try:
            os.rename(current_path, normalized_path)
        except OSError as exc:
            logger.warning("Failed to rename prefix %s: %s", prefix_name, exc)


def _format_setting_value_for_display(value: str) -> str:
    """Hide shell-escaped quotes in GUI fields."""
    return value.replace('\\"', '"')


def _get_numa_nodes() -> dict[str, str]:
    """Read NUMA nodes from lscpu output."""
    try:
        result = subprocess.run(
            ["lscpu"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    if result.returncode != 0:
        return {}

    numa_nodes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"NUMA node(\d+) CPU\(s\):\s*(.+)$", line.strip())
        if not match:
            continue
        node_id, node_cpus = match.groups()
        if node_cpus:
            numa_nodes[node_id] = node_cpus
    return numa_nodes


class ExeSettingsDialog(
    DraggableDialog,
    MangoHudSettingsMixin,
    GamescopeSettingsMixin,
    VkBasaltSettingsMixin,
):
    """Dialog for configuring executable-specific settings."""

    def __init__(self, parent=None, theme=None, exe_path=None, appid=None, game_source=None,
                 user_conf=False):
        super().__init__(parent)
        self.theme = theme if theme else theme_manager.apply_theme(ui_config.get_theme())
        self.exe_path = exe_path
        self.appid = appid
        self.game_source = str(game_source).lower() if game_source else ""
        self.user_conf = user_conf
        if not self.user_conf and not self.exe_path and not self.appid:
            return
        self.portproton_path = get_portproton_location()
        if self.portproton_path is None:
            logger.error("PortProton location not found")
            return
        self.start_sh = get_portproton_start_command()
        if self.start_sh is None:
            logger.error("PortProton start command not found")
            return

        self.dist_options = []
        self.lg_dist_aliases = {}
        self.plugins_ver = ""
        self.prefix_options = []
        if self.portproton_path:
            scripts_path = get_portproton_scripts_path()
            if scripts_path:
                var_path = os.path.join(scripts_path, "var")
                self.lg_dist_aliases = read_lg_dist_versions_from_var(var_path)
                try:
                    with open(var_path, encoding="utf-8") as var_file:
                        for line in var_file:
                            if line.startswith('export PW_PLUGINS_VER='):
                                self.plugins_ver = line.split('=', 1)[1].strip().strip('"\'')
                                break
                except OSError as exc:
                    logger.warning("Failed to read PW_PLUGINS_VER: %s", exc)
            system_wine_label = "" if self.game_source == "steam" else _('System WINE')
            self.dist_options = get_available_wine_options(
                self.portproton_path, system_wine_label, self.game_source == "steam"
            )
            prefixes_dir = os.path.join(self.portproton_path, 'prefixes')
            if os.path.exists(prefixes_dir):
                _normalize_prefix_directories(prefixes_dir)
            self.prefix_options = get_available_prefix_options(self.portproton_path)

        self.current_settings = {}
        self.value_widgets = {}
        self.original_values = {}
        self.advanced_widgets = {}
        self.original_display_values = {}
        self.exe_setting_favorites = exe_settings_favorites_config.get_keys()
        self.advanced_settings_by_key = {}
        self.init_mangohud_state()
        self.init_gamescope_state()
        self.init_vkbasalt_state()
        self.blocked_keys = set()
        self.numa_nodes = {}
        self.locale_options = []
        self.logical_core_options = []
        self._gamepad_tooltip_map = {}

        self.setWindowTitle(_("Global Game Settings") if self.user_conf else _("Exe Settings"))
        self.setModal(True)
        self.resize(1100, 720)
        self.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.toggle_settings = get_toggle_settings()

        self.setup_ui()
        if self.user_conf:
            self.open_ppdb_button.clicked.disconnect()
            self.open_ppdb_button.setText(_("Edit user.conf"))
            self.open_ppdb_button.clicked.connect(self.open_user_conf)
            self.clear_ppdb_button.clicked.disconnect()
            self.clear_ppdb_button.setText(_("Clear All"))
            self.clear_ppdb_button.clicked.connect(self.clear_user_conf)
            self.settings_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._on_focus_changed)

        self.input_manager = None
        self.main_window = None
        parent_obj = self.parent()
        while parent_obj:
            if hasattr(parent_obj, 'input_manager'):
                self.input_manager = cast("MainWindow", parent_obj).input_manager
                self.main_window = parent_obj
            parent_obj = parent_obj.parent()

        self.current_theme_name = ui_config.get_theme()

        if self.input_manager:
            self.input_manager.enable_settings_mode(self)
            self.input_manager.connect_surface_signal(
                'settings_dialog',
                self.input_manager.gamepad_hotplug,
                self._update_vkbasalt_toggle_key_visibility,
            )

        self.hints_widget, self.hints_labels = create_dialog_hints_widget(
            self.theme, self.main_window, self.input_manager, context='settings'
        )
        self.main_layout.addWidget(self.hints_widget)

        if self.input_manager:
            def update_hints(*_args: object) -> None:
                update_dialog_hints(
                    self.hints_labels, self.main_window, self.input_manager,
                    theme_manager, self.current_theme_name,
                )
            self.input_manager.connect_surface_updates('settings_dialog', update_hints)
            update_dialog_hints(self.hints_labels, self.main_window, self.input_manager, theme_manager, self.current_theme_name)

        self.init_virtual_keyboard()
        self.load_current_settings()

    def _get_process_args(self, subcommand_args):
        """Get the full arguments for QProcess.start."""
        return self.start_sh + subcommand_args

    def _resolve_run_after_exe_path(self, exe_path: str) -> str:
        """Resolve run-after executable relative to the main executable."""
        if not exe_path:
            return exe_path
        normalized = os.path.normpath(os.path.expanduser(exe_path))
        if os.path.isabs(normalized):
            return normalized
        if " " in exe_path:
            return exe_path
        game_dir = os.path.dirname(self.exe_path or "")
        if not game_dir:
            return normalized
        return os.path.normpath(os.path.join(game_dir, normalized))

    def _get_setting_file_selector_path(self, current_path: str) -> str:
        """Get initial path for setting file selectors."""
        initial_path = os.path.expanduser("~")
        if not current_path:
            return initial_path
        normalized = self._resolve_run_after_exe_path(current_path)
        if os.path.isfile(normalized):
            return os.path.dirname(normalized)
        if os.path.isdir(normalized):
            return normalized
        return initial_path

    def setup_ui(self):
        """Set up the user interface."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        self.search_edit.setPlaceholderText(_("Search settings…"))
        self.search_edit.textChanged.connect(self.filter_settings)
        self.search_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.search_edit.installEventFilter(self)
        search_layout.addWidget(self.search_edit)
        self.main_layout.addLayout(search_layout)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(self.theme.TAB_STYLE)
        self.favorites_tab = QWidget()
        self.favorites_tab_layout = QVBoxLayout(self.favorites_tab)
        self.main_tab = QWidget()
        self.main_tab_layout = QVBoxLayout(self.main_tab)
        self.advanced_tab = QWidget()
        self.advanced_tab_layout = QVBoxLayout(self.advanced_tab)
        self.mangohud_tab = QWidget()
        self.mangohud_tab_layout = QVBoxLayout(self.mangohud_tab)
        self.vkbasalt_tab = QWidget()
        self.vkbasalt_tab_layout = QVBoxLayout(self.vkbasalt_tab)
        self.gamescope_tab = QWidget()
        self.gamescope_tab_layout = QVBoxLayout(self.gamescope_tab)

        self.tab_widget.addTab(self.main_tab, _("Main"))
        self.tab_widget.addTab(self.advanced_tab, _("Advanced"))
        self.tab_widget.addTab(self.mangohud_tab, "MangoHud")
        self.tab_widget.addTab(self.vkbasalt_tab, "vkBasalt")
        if self.gamescope_available:
            self.tab_widget.addTab(self.gamescope_tab, "Gamescope")
        self.tab_widget.currentChanged.connect(self.on_table_selection_changed)

        self.settings_table = QTableWidget()
        self.settings_table.setAlternatingRowColors(True)
        self.settings_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.settings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.settings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.settings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.settings_table.setColumnCount(3)
        self.settings_table.setHorizontalHeaderLabels([_("Setting"), _("Value"), _("Description")])
        self.settings_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.settings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.settings_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.settings_table.horizontalHeader().resizeSection(1, 100)
        self.settings_table.setWordWrap(True)
        self.settings_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.settings_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        settings_combo_style = getattr(self.theme, "SETTINGS_TABLE_COMBOBOX_STYLE", "")
        self.settings_table.setStyleSheet(self.theme.WINETRICKS_TABBLE_STYLE + self.theme.COMBOBOX_STYLE + settings_combo_style + self.theme.LINE_EDIT_STYLE + self.theme.SCROLL_STYLE)
        self.settings_table.setMouseTracking(True)
        self.settings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.settings_table.customContextMenuRequested.connect(
            lambda pos: self.show_setting_context_menu(self.settings_table, pos)
        )

        self.settings_preloader = Preloader()
        settings_preloader_container = QWidget()
        settings_preloader_layout = QVBoxLayout(settings_preloader_container)
        settings_preloader_layout.addStretch()
        settings_preloader_hlayout = QHBoxLayout()
        settings_preloader_hlayout.addStretch()
        settings_preloader_hlayout.addWidget(self.settings_preloader)
        settings_preloader_hlayout.addStretch()
        settings_preloader_layout.addLayout(settings_preloader_hlayout)
        settings_preloader_layout.addStretch()
        settings_preloader_layout.setContentsMargins(0, 0, 0, 0)
        settings_preloader_layout.setSpacing(0)

        self.settings_container = QStackedWidget()
        self.settings_container.addWidget(settings_preloader_container)
        self.settings_container.addWidget(self.settings_table)
        self.main_tab_layout.addWidget(self.settings_container)
        self.settings_table.currentCellChanged.connect(self.on_table_selection_changed)
        self.settings_table.cellEntered.connect(self.on_table_cell_hovered)
        self.settings_table.installEventFilter(self)

        self.advanced_table = QTableWidget()
        self.advanced_table.setAlternatingRowColors(True)
        self.advanced_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.advanced_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.advanced_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.advanced_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.advanced_table.setColumnCount(3)
        self.advanced_table.setHorizontalHeaderLabels([_("Setting"), _("Value"), _("Description")])
        self.advanced_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.advanced_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.advanced_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.advanced_table.horizontalHeader().resizeSection(1, 230)
        self.advanced_table.setWordWrap(True)
        self.advanced_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.advanced_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.advanced_table.setStyleSheet(self.theme.WINETRICKS_TABBLE_STYLE + self.theme.COMBOBOX_STYLE + settings_combo_style + self.theme.LINE_EDIT_STYLE + self.theme.SCROLL_STYLE)
        self.advanced_table.setMouseTracking(True)
        self.advanced_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.advanced_table.customContextMenuRequested.connect(
            lambda pos: self.show_setting_context_menu(self.advanced_table, pos)
        )

        self.favorites_table = QTableWidget()
        self.favorites_table.setAlternatingRowColors(True)
        self.favorites_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.favorites_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.favorites_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.favorites_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.favorites_table.setColumnCount(3)
        self.favorites_table.setHorizontalHeaderLabels([_("Setting"), _("Value"), _("Description")])
        self.favorites_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.favorites_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.favorites_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.favorites_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.favorites_table.setWordWrap(True)
        self.favorites_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.favorites_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.favorites_table.setStyleSheet(
            self.theme.WINETRICKS_TABBLE_STYLE
            + self.theme.COMBOBOX_STYLE
            + settings_combo_style
            + self.theme.LINE_EDIT_STYLE
            + self.theme.SCROLL_STYLE
        )
        self.favorites_table.setMouseTracking(True)
        self.favorites_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_table.customContextMenuRequested.connect(
            lambda pos: self.show_setting_context_menu(self.favorites_table, pos)
        )
        self.favorites_tab_layout.addWidget(self.favorites_table)
        self.favorites_table.currentCellChanged.connect(self.on_table_selection_changed)
        self.favorites_table.cellEntered.connect(self.on_table_cell_hovered)

        self.advanced_preloader = Preloader()
        advanced_preloader_container = QWidget()
        advanced_preloader_layout = QVBoxLayout(advanced_preloader_container)
        advanced_preloader_layout.addStretch()
        advanced_preloader_hlayout = QHBoxLayout()
        advanced_preloader_hlayout.addStretch()
        advanced_preloader_hlayout.addWidget(self.advanced_preloader)
        advanced_preloader_hlayout.addStretch()
        advanced_preloader_layout.addLayout(advanced_preloader_hlayout)
        advanced_preloader_layout.addStretch()
        advanced_preloader_layout.setContentsMargins(0, 0, 0, 0)
        advanced_preloader_layout.setSpacing(0)

        self.advanced_container = QStackedWidget()
        self.advanced_container.addWidget(advanced_preloader_container)
        self.advanced_container.addWidget(self.advanced_table)
        self.advanced_tab_layout.addWidget(self.advanced_container)
        self.advanced_table.currentCellChanged.connect(self.on_table_selection_changed)
        self.advanced_table.cellEntered.connect(self.on_table_cell_hovered)
        self.advanced_table.installEventFilter(self)

        self.setup_mangohud_tab()
        self.setup_vkbasalt_tab()
        if self.gamescope_available:
            self.setup_gamescope_tab()

        self.main_layout.addWidget(self.tab_widget)

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

        button_layout = QHBoxLayout()
        self.apply_button = AutoSizeButton(_("Apply"), icon=ThemeManager().get_icon("apply", as_path=True))
        self.cancel_button = AutoSizeButton(_("Cancel"), icon=ThemeManager().get_icon("cancel", as_path=True))
        self.open_ppdb_button = AutoSizeButton(_("Edit PPDB"), icon=ThemeManager().get_icon("folder", as_path=True))
        self.clear_ppdb_button = AutoSizeButton(_("Clear PPDB"), icon=ThemeManager().get_icon("delete", as_path=True))
        self.apply_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.open_ppdb_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.clear_ppdb_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.apply_button.installEventFilter(self)
        self.cancel_button.installEventFilter(self)
        self.open_ppdb_button.installEventFilter(self)
        self.clear_ppdb_button.installEventFilter(self)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.open_ppdb_button)
        button_layout.addWidget(self.clear_ppdb_button)
        self.main_layout.addLayout(button_layout)

        self.apply_button.clicked.connect(self.apply_changes)
        self.cancel_button.clicked.connect(self.reject)
        self.open_ppdb_button.clicked.connect(self.open_ppdb_file)
        self.clear_ppdb_button.clicked.connect(self.clear_ppdb_file)
        self._install_line_edit_event_filters()

    def load_current_settings(self):
        """Load available toggles and current settings."""
        self.settings_container.setCurrentIndex(0)
        self.advanced_container.setCurrentIndex(0)

        process = QProcess(self)
        process.finished.connect(self.on_show_ppdb_finished)
        command = ["cli", "--get-user-conf"] if self.user_conf else [
            "cli", "--show-ppdb", f"{self.exe_path}"
        ]
        args = self._get_process_args(command)
        process.start(args[0], args[1:])

    def on_show_ppdb_finished(self, exit_code, exit_status):
        """Handle --show-ppdb output."""
        process = cast(QProcess, self.sender())
        self.current_settings = {}
        self.blocked_keys = set()
        self.numa_nodes = _get_numa_nodes()
        self.logical_core_options = []
        self.locale_options = []

        if self.user_conf and (
            exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit
        ):
            QMessageBox.warning(self, _("Error"), _("Failed to load global game settings."))
            self.reject()
            return

        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            output = bytes(process.readAllStandardOutput().data()).decode('utf-8', 'ignore')
            for line in output.splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                if line_stripped.startswith('PW_') and '=' not in line_stripped:
                    parts = line_stripped.split(maxsplit=1)
                    key = parts[0]
                    if len(parts) > 1 and 'blocked' in parts[1]:
                        self.blocked_keys.add(key)
                    continue

                if '=' in line_stripped:
                    try:
                        key, val = line_stripped.split('=', 1)
                        if (
                            key in self.toggle_settings
                            or key in ADVANCED_SETTING_KEYS
                            or key in MANGOHUD_ENV_KEYS
                            or key in GAMESCOPE_ENV_KEYS
                            or key in VKBASALT_ENV_KEYS
                            or key in TOGGLE_BOOL_KEYS
                        ):
                            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                                val = val[1:-1]
                            val = _format_setting_value_for_display(val)
                            self.current_settings[key] = val
                    except ValueError:
                        continue
        if self.user_conf and self.plugins_ver:
            self.current_settings['PW_PLUGINS_VER'] = self.plugins_ver

        if self.game_source == "steam":
            self.blocked_keys.update({
                "PW_USE_GSTREAMER",
                "PW_USE_RUNTIME",
                "PW_DGVOODOO2",
                "PW_USE_D3D_EXTRAS",
                "PW_USE_GALLIUM_NINE",
                "PW_USE_SUPPLIED_DXVK_VKD3D",
                "PW_USE_INHIBIT_SLEEP",
            })
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            for key in self.toggle_settings:
                self.current_settings[key] = '0'
            for adv_key in ADVANCED_SETTING_KEYS:
                self.current_settings[adv_key] = 'disabled' if any(
                    x in adv_key for x in ['TOPOLOGY', 'SELECT', 'MODE', 'LEVEL', 'GL_VERSION', 'NUMA', 'DRIVER']
                ) else ''
            for key in MANGOHUD_ENV_KEYS:
                self.current_settings[key] = ''
            for key in GAMESCOPE_ENV_KEYS:
                self.current_settings[key] = ''
            for key in VKBASALT_ENV_KEYS:
                self.current_settings[key] = ''
        elif not self.user_conf:
            self.current_settings.setdefault('PW_MANGOHUD', '0')
            self.current_settings.setdefault('PW_VKBASALT', '0')

        for key in self.blocked_keys:
            self.current_settings[key] = '0'

        current_wine_version = self.current_settings.get('PW_WINE_USE')
        if current_wine_version in self.lg_dist_aliases:
            self.current_settings['PW_WINE_USE'] = self.lg_dist_aliases[current_wine_version]
            current_wine_version = self.current_settings['PW_WINE_USE']
        if (
            current_wine_version
            and current_wine_version not in self.dist_options
            and self.game_source != "steam"
            and current_wine_version != 'USE_SYSTEM_WINE'
        ):
            self.dist_options.append(current_wine_version)

        self.original_values = self.current_settings.copy()
        for key in set(self.toggle_settings.keys()):
            self.original_values.setdefault(key, '' if self.user_conf else '0')

        self.populate_table()
        self.populate_advanced()
        self.populate_mangohud()
        self.populate_vkbasalt()
        if self.gamescope_available:
            self.populate_gamescope()
        self.populate_favorites(select_tab=True)

        self.settings_container.setCurrentIndex(1)
        self.advanced_container.setCurrentIndex(1)

    def open_ppdb_file(self):
        """Open the PPDB file for the current executable."""
        if not self.exe_path:
            QMessageBox.critical(self, _("Error"), _("Executable path is not available."))
            return

        db_path = self.exe_path + ".ppdb"

        if not os.path.exists(db_path):
            QMessageBox.critical(self, _("Error"), _("PPDB file does not exist at: ") + db_path)
            return

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(db_path)):
            QMessageBox.critical(self, _("Error"), _("Failed to open PPDB file:\n") + db_path)

    def open_user_conf(self) -> None:
        user_conf = os.path.join(cast(str, self.portproton_path), "data", "user.conf")
        if not os.path.exists(user_conf):
            QMessageBox.critical(self, _("Error"), _("Failed to open file:\n") + user_conf)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(user_conf)):
            QMessageBox.critical(self, _("Error"), _("Failed to open file:\n") + user_conf)

    def clear_ppdb_file(self):
        """Remove the PPDB file and reload settings."""
        if not self.exe_path:
            QMessageBox.critical(self, _("Error"), _("Executable path is not available."))
            return

        db_path = self.exe_path + ".ppdb"
        if not os.path.exists(db_path):
            QMessageBox.information(self, _("Information"), _("PPDB file does not exist at: ") + db_path)
            self.load_current_settings()
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm PPDB Clear"))
        msg_box.setText(_("Are you sure you want to clear settings? This action cannot be undone."))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        try:
            os.remove(db_path)
        except OSError as exc:
            logger.warning("Failed to remove PPDB file %s: %s", db_path, exc)
            QMessageBox.warning(self, _("Error"), _("Failed to remove PPDB file:\n") + db_path)
            return

        self.load_current_settings()

    def clear_user_conf(self) -> None:
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Clear"))
        msg_box.setText(_("Are you sure you want to clear settings? This action cannot be undone."))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return

        user_conf = os.path.join(cast(str, self.portproton_path), "data", "user.conf")
        try:
            os.remove(user_conf)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Failed to remove user.conf: %s", exc)
            QMessageBox.warning(self, _("Error"), _("Failed to apply changes. Check logs."))
            return
        screen_resolution, screen_primary = get_screen_info()
        self.user_conf_changes = [
            screen_resolution,
            screen_primary,
            f"PW_WINE_DPI_VALUE={get_system_dpi_for_wine()}",
        ]
        self.user_conf_changes = [
            change for change in self.user_conf_changes if change.split('=', 1)[1]
        ]
        self.close_after_user_conf_changes = False
        self.apply_button.setEnabled(False)
        self._apply_next_user_conf_change()

    def populate_table(self):
        """Populate the table with settings."""
        self.settings_table.setRowCount(0)
        self.value_widgets.clear()
        self.settings_table.verticalHeader().setVisible(False)

        visible_keys = list(self.toggle_settings.keys())

        for toggle in visible_keys:
            description = self.toggle_settings.get(toggle)
            if not description:
                continue

            row = self.settings_table.rowCount()
            self.settings_table.insertRow(row)

            name_item = QTableWidgetItem(format_setting_name_for_display(toggle))
            name_item.setData(Qt.ItemDataRole.UserRole, toggle)
            name_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

            current_val = self.current_settings.get(toggle, '') if self.user_conf else (
                self.current_settings.get(toggle, '0')
            )
            is_blocked = toggle in self.blocked_keys
            if self.user_conf:
                value_widget = CustomComboBox(theme=self.theme)
                value_widget.setObjectName("settingsTableCombo")
                value_widget.view().window().setWindowFlags(
                    Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                )
                value_widget.view().window().setAttribute(
                    Qt.WidgetAttribute.WA_TranslucentBackground
                )
                value_widget.addItem(_("Default"), "")
                value_widget.addItem(_("Yes"), "1")
                value_widget.addItem(_("No"), "0")
                value_widget.setCurrentIndex(max(0, value_widget.findData(current_val)))
            else:
                value_widget = QCheckBox()
                value_widget.setStyleSheet(self.theme.CHECKBOX_STYLE)
                value_widget.setChecked(current_val == '1' and not is_blocked)
            value_widget.setEnabled(not is_blocked)
            value_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            value_widget.installEventFilter(self)
            if is_blocked:
                name_item.setForeground(QColor(self.theme.color_disabled_text))
            if self.user_conf:
                self.settings_table.setCellWidget(row, 1, value_widget)
            else:
                checkbox_container = QWidget()
                checkbox_container.setStyleSheet(self.theme.CHECKBOX_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE)
                checkbox_layout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.addWidget(value_widget)
                checkbox_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self.settings_table.setItem(row, 1, checkbox_item)
                self.settings_table.setCellWidget(row, 1, checkbox_container)

            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if is_blocked:
                desc_item.setForeground(QColor(self.theme.color_disabled_text))
            self.settings_table.setItem(row, 2, desc_item)

            self.settings_table.setItem(row, 0, name_item)
            self.value_widgets[(row, 1)] = value_widget

        self.settings_table.resizeRowsToContents()
        if self.settings_table.rowCount() > 0:
            self.settings_table.setCurrentCell(0, 1)
            self.settings_table.selectRow(0)
            first_widget = self.value_widgets.get((0, 1))
            if isinstance(first_widget, QCheckBox):
                first_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                self.settings_table.setFocus(Qt.FocusReason.OtherFocusReason)

        self.on_table_selection_changed()

    def populate_advanced(self):
        """Populate the advanced tab with table format."""
        self.advanced_table.setRowCount(0)
        self.advanced_widgets.clear()
        self.original_display_values = {}
        self.value_mapping = {}
        self.advanced_table.verticalHeader().setVisible(False)

        current = self.current_settings
        disabled_text = _('disabled')

        advanced_settings = get_advanced_settings(
            disabled_text=disabled_text,
            logical_core_options=self.logical_core_options,
            numa_nodes=self.numa_nodes,
            dist_options=self.dist_options,
            prefix_options=self.prefix_options
        )
        if self.user_conf:
            advanced_settings = [
                setting for setting in advanced_settings
                if setting['key'] not in ('PW_WINE_USE', 'PW_PREFIX_NAME', 'PW_VULKAN_USE')
            ]
            for setting in advanced_settings:
                if setting['type'] == 'combo':
                    setting['options'] = [_('Default')] + setting['options']
        self.advanced_settings_by_key = {
            setting['key']: setting for setting in advanced_settings
        }

        for setting in advanced_settings:
            row = self.advanced_table.rowCount()
            self.advanced_table.insertRow(row)
            is_blocked = setting.get("type") == "combo" and len(setting.get("options", [])) == 1

            name_item = QTableWidgetItem(setting['name'])
            name_item.setData(Qt.ItemDataRole.UserRole, setting['key'])
            name_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.advanced_table.setItem(row, 0, name_item)

            if setting['type'] == 'combo':
                combo = CustomComboBox(theme=self.theme)
                combo.setObjectName("settingsTableCombo")
                combo.view().window().setWindowFlags(
                    Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                )
                combo.view().window().setAttribute(
                    Qt.WidgetAttribute.WA_TranslucentBackground
                )
                combo.addItems(setting['options'])
                if setting['key'] == 'PW_PREFIX_NAME':
                    combo.setEditable(True)
                    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                    prefix_line_edit = combo.lineEdit()
                    if prefix_line_edit is not None:
                        prefix_line_edit.setPlaceholderText(_("Enter prefix name"))
                    combo.highlighted.connect(
                        lambda row, c=combo: self._on_combo_highlighted(row, c),
                    )
                elif setting['key'] == 'PW_WINE_USE':
                    combo.highlighted.connect(
                        lambda row, c=combo: self._on_combo_highlighted(row, c),
                    )

                current_raw = current.get(setting['key'], '') if self.user_conf else (
                    current.get(setting['key'], setting['default'])
                )
                if self.user_conf and not current_raw:
                    current_val = _('Default')
                elif setting['key'] == 'PW_WINE_CPU_TOPOLOGY':
                    current_val = disabled_text if current_raw == 'disabled' else (
                        current_raw.split(':')[0] if isinstance(current_raw, str) and ':' in current_raw else current_raw
                    )
                elif setting['key'] == 'PW_WINE_USE':
                    current_val = _('System WINE') if current_raw == 'USE_SYSTEM_WINE' else current_raw
                else:
                    current_val = disabled_text if current_raw == 'disabled' else current_raw

                if '_value_map' in setting:
                    reverse_map = {v: k for k, v in setting['_value_map'].items()}
                    if current_raw in reverse_map:
                        current_val = reverse_map[current_raw]

                current_val_text = current_val if isinstance(current_val, str) else ''
                if current_val_text and current_val_text not in setting['options']:
                    combo.addItem(current_val_text)
                combo.setCurrentText(current_val_text)

                if setting['key'] in ('PW_PREFIX_NAME', 'PW_VULKAN_USE') and self.game_source == "steam":
                    combo.setEnabled(False)
                    name_item.setForeground(QColor(self.theme.color_disabled_text))
                elif is_blocked:
                    combo.setEnabled(False)
                    name_item.setForeground(QColor(self.theme.color_disabled_text))

                combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                self.advanced_table.setCellWidget(row, 1, combo)
                self.advanced_widgets[setting['key']] = combo

                if '_value_map' in setting:
                    reverse_map = {v: k for k, v in setting['_value_map'].items()}
                    if current_raw in reverse_map:
                        self.original_display_values[setting['key']] = reverse_map[current_raw]
                    else:
                        self.original_display_values[setting['key']] = current_val_text
                else:
                    self.original_display_values[setting['key']] = current_val_text

                if self.user_conf and not current_raw:
                    self.original_display_values[setting['key']] = ''

                if '_value_map' in setting:
                    reverse_map = {v: k for k, v in setting['_value_map'].items()}
                    self.value_mapping[setting['key']] = {
                        'forward': setting['_value_map'],
                        'reverse': reverse_map
                    }

            elif setting['type'] == 'text':
                line_edit = QLineEdit()
                current_val = current.get(setting['key'], '') if self.user_conf else (
                    current.get(setting['key'], setting['default'])
                )
                line_edit.setText(current_val)
                if not current_val and not setting['default']:
                    line_edit.setPlaceholderText(_("Default value"))

                if is_blocked:
                    line_edit.setEnabled(False)
                    line_edit.setStyleSheet(self.theme.SETTINGS_DISABLED_INPUT_STYLE)

                if setting['key'] == 'PW_RUN_AFTER_EXE':
                    text_container = QWidget()
                    text_container.setProperty("ppqt_run_after_exe_widget", True)
                    text_layout = QHBoxLayout(text_container)
                    text_layout.setContentsMargins(0, 0, 0, 0)
                    text_layout.setSpacing(6)
                    text_layout.addWidget(line_edit)

                    browse_button = AutoSizeButton("...", icon=ThemeManager().get_icon("folder", as_path=True))
                    browse_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
                    browse_button.setFixedWidth(56)
                    browse_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    if is_blocked:
                        browse_button.setEnabled(False)

                    def open_run_after_exe_selector(
                        _checked: bool = False,
                        target_line_edit=line_edit,
                        file_filter="",
                    ):
                        from portprotonqt.dialogs.file_explorer import FileExplorer

                        initial_path = self._get_setting_file_selector_path(
                            target_line_edit.text().strip()
                        )

                        file_explorer = FileExplorer(
                            self,
                            theme=self.theme,
                            file_filter=file_filter,
                            initial_path=initial_path,
                        )
                        file_explorer.file_signal.file_selected.connect(
                            lambda file_path, target=target_line_edit: target.setText(os.path.normpath(file_path))
                        )
                        file_explorer.exec()

                    browse_button.clicked.connect(open_run_after_exe_selector)
                    text_layout.addWidget(browse_button)
                    self.advanced_table.setCellWidget(row, 1, text_container)
                else:
                    self.advanced_table.setCellWidget(row, 1, line_edit)
                self.advanced_widgets[setting['key']] = line_edit
                self.original_display_values[setting['key']] = current_val

            desc_item = QTableWidgetItem(setting['description'])
            desc_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if is_blocked:
                desc_item.setForeground(QColor(self.theme.color_disabled_text))
            self.advanced_table.setItem(row, 2, desc_item)

        if self.advanced_table.rowCount() > 0:
            self.on_table_selection_changed()
        self._install_line_edit_event_filters()

    def _get_current_settings_table(self) -> QTableWidget | None:
        current_widget = self.tab_widget.currentWidget()
        if current_widget == self.favorites_tab:
            return self.favorites_table
        if current_widget == self.main_tab:
            return self.settings_table
        if current_widget == self.advanced_tab:
            return self.advanced_table
        return None

    def show_setting_context_menu(self, table: QTableWidget, pos: QPoint) -> None:
        """Show favorite actions for a settings row."""
        row = table.rowAt(pos.y())
        if row < 0:
            return

        item = table.item(row, 0)
        if item is None:
            return

        key = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(key, str) or not key:
            return

        is_favorite = key in self.exe_setting_favorites
        icon_name = "star" if is_favorite else "star_full"
        raw_icon = theme_manager.get_icon(icon_name)
        if isinstance(raw_icon, QIcon):
            icon = raw_icon
        elif isinstance(raw_icon, str):
            icon = QIcon(raw_icon)
        else:
            icon = QIcon()
        menu = QMenu(table)
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(self.theme.CONTEXT_MENU_STYLE)
        menu.setParent(table, Qt.WindowType.Popup)
        text = _("Remove from Favorites") if is_favorite else _("Add to Favorites")
        action = menu.addAction(icon, text)
        action.triggered.connect(lambda: self.toggle_setting_favorite(key, not is_favorite))
        menu.setActiveAction(action)
        menu.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, lambda: menu.setActiveAction(action))
        menu.exec(table.viewport().mapToGlobal(pos))

    def handle_settings_context_menu(self) -> bool:
        """Open favorite context menu for the current settings row."""
        table = self._get_current_settings_table()
        if table is None or table.currentRow() < 0:
            return False

        column = table.currentColumn()
        if column < 0:
            column = 0
        index = table.model().index(table.currentRow(), column)
        if not index.isValid():
            return False

        point = table.visualRect(index).center()
        self.show_setting_context_menu(table, point)
        return True

    def toggle_setting_favorite(self, key: str, add: bool) -> None:
        """Toggle favorite state for an executable setting."""
        favorites = list(self.exe_setting_favorites)
        if add and key not in favorites:
            favorites.append(key)
        elif not add and key in favorites:
            favorites.remove(key)
        else:
            return

        self.exe_setting_favorites = favorites
        exe_settings_favorites_config.set_keys(favorites)
        self.populate_favorites()

    def populate_favorites(self, select_tab: bool = False) -> None:
        """Populate the favorites tab with selected settings."""
        self.favorites_table.setRowCount(0)
        self.favorites_table.verticalHeader().setVisible(False)
        for key in self.exe_setting_favorites:
            if key in self.toggle_settings:
                self._add_favorite_toggle_row(key)
            elif key in self.advanced_widgets:
                self._add_favorite_advanced_row(key)
        self.favorites_table.resizeRowsToContents()
        self._sync_favorites_table_columns()
        self._sync_favorites_tab_visibility(select_tab)
        if self.search_edit.text():
            self.filter_settings(self.search_edit.text())

    def _sync_favorites_table_columns(self) -> None:
        source_table = self.settings_table
        for key in self.exe_setting_favorites:
            if key in self.advanced_widgets and key not in self.toggle_settings:
                source_table = self.advanced_table
                break

        source_header = source_table.horizontalHeader()
        target_header = self.favorites_table.horizontalHeader()
        target_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        target_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        target_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        target_header.resizeSection(0, source_header.sectionSize(0))
        target_header.resizeSection(1, source_header.sectionSize(1))

    def _sync_favorites_tab_visibility(self, select_tab: bool) -> None:
        favorites_index = self.tab_widget.indexOf(self.favorites_tab)
        has_favorites = self.favorites_table.rowCount() > 0
        if has_favorites and favorites_index < 0:
            self.tab_widget.insertTab(0, self.favorites_tab, _("Favorites"))
            if not select_tab:
                return
            self.tab_widget.setCurrentIndex(0)
            self.favorites_table.setCurrentCell(0, 1)
            self.favorites_table.setFocus(Qt.FocusReason.OtherFocusReason)
        elif has_favorites and select_tab:
            self.tab_widget.setCurrentIndex(0)
            self.favorites_table.setCurrentCell(0, 1)
            self.favorites_table.setFocus(Qt.FocusReason.OtherFocusReason)
        elif not has_favorites and favorites_index >= 0:
            self.tab_widget.removeTab(favorites_index)

    def _add_favorite_toggle_row(self, key: str) -> None:
        row = self.favorites_table.rowCount()
        self.favorites_table.insertRow(row)
        self._set_favorite_text_cells(
            row,
            key,
            format_setting_name_for_display(key),
            self.toggle_settings[key],
        )

        source_widget = self._find_toggle_widget(key)
        checkbox = QCheckBox()
        checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        if isinstance(source_widget, QComboBox):
            self.favorites_table.removeCellWidget(row, 1)
            self._add_favorite_combo(row, source_widget)
            return
        checkbox.setChecked(source_widget.isChecked() if source_widget else False)
        checkbox.setEnabled(source_widget.isEnabled() if source_widget else False)
        checkbox.stateChanged.connect(
            lambda _state, widget=source_widget, cb=checkbox: self._sync_checkbox(widget, cb)
        )
        checkbox_container = QWidget()
        checkbox_container.setStyleSheet(
            self.theme.CHECKBOX_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE
        )
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox_layout.addWidget(checkbox)
        checkbox_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.favorites_table.setItem(row, 1, checkbox_item)
        self.favorites_table.setCellWidget(row, 1, checkbox_container)

    def _add_favorite_advanced_row(self, key: str) -> None:
        setting = self.advanced_settings_by_key.get(key)
        source_widget = self.advanced_widgets.get(key)
        if setting is None or source_widget is None:
            return

        row = self.favorites_table.rowCount()
        self.favorites_table.insertRow(row)
        self._set_favorite_text_cells(row, key, setting['name'], setting['description'])
        if isinstance(source_widget, QComboBox):
            self._add_favorite_combo(row, source_widget)
        elif isinstance(source_widget, QLineEdit):
            self._add_favorite_line_edit(row, source_widget)

    def _set_favorite_text_cells(self, row: int, key: str, name: str, description: str) -> None:
        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.ItemDataRole.UserRole, key)
        name_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        desc_item = QTableWidgetItem(description)
        desc_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.favorites_table.setItem(row, 0, name_item)
        self.favorites_table.setItem(row, 2, desc_item)

    def _find_toggle_widget(self, key: str) -> QCheckBox | QComboBox | None:
        for (row, _column), widget in self.value_widgets.items():
            item = self.settings_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == key:
                return widget
        return None

    def _sync_checkbox(self, source_widget: QCheckBox | None, checkbox: QCheckBox) -> None:
        if source_widget is not None and source_widget.checkState() != checkbox.checkState():
            source_widget.setCheckState(checkbox.checkState())

    def _add_favorite_combo(self, row: int, source_widget: QComboBox) -> None:
        combo = CustomComboBox(theme=self.theme)
        combo.setObjectName("settingsTableCombo")
        combo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        combo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        combo.setEditable(source_widget.isEditable())
        for index in range(source_widget.count()):
            combo.addItem(source_widget.itemText(index), source_widget.itemData(index))
        combo.setCurrentText(source_widget.currentText())
        combo.setEnabled(source_widget.isEnabled())
        settings_combo_style = getattr(self.theme, "SETTINGS_TABLE_COMBOBOX_STYLE", "")
        combo.setStyleSheet(
            self.theme.COMBOBOX_STYLE
            + settings_combo_style
            + self.theme.SCROLL_STYLE
        )
        combo.currentTextChanged.connect(source_widget.setCurrentText)
        combo.highlighted.connect(
            lambda row_idx, c=combo: self._on_combo_highlighted(row_idx, c),
        )
        self.favorites_table.setCellWidget(row, 1, combo)

    def _add_favorite_line_edit(self, row: int, source_widget: QLineEdit) -> None:
        line_edit = QLineEdit()
        line_edit.setText(source_widget.text())
        line_edit.setPlaceholderText(source_widget.placeholderText())
        line_edit.setEnabled(source_widget.isEnabled())
        line_edit.setStyleSheet(source_widget.styleSheet() or self.theme.ADDGAME_INPUT_STYLE)
        line_edit.textChanged.connect(source_widget.setText)
        line_edit.installEventFilter(self)
        self.favorites_table.setCellWidget(row, 1, line_edit)

    def init_virtual_keyboard(self):
        """Initialize virtual keyboard."""
        self.keyboard = VirtualKeyboard(self, theme=self.theme, button_width=50)
        self.keyboard.hide()
        self.keyboard.current_input_widget = None

    def show_virtual_keyboard(self, widget=None):
        """Show virtual keyboard for search or text input."""
        if not widget:
            widget = self.search_edit

        if not widget or not widget.isVisible():
            return

        self.keyboard.show_for_widget(widget)

    def register_gamepad_tooltip(self, widget: QWidget, text: str) -> None:
        """Register tooltip text for a focusable widget."""
        if text:
            self._gamepad_tooltip_map[widget] = text

    def _on_combo_highlighted(self, row: int, combo: QComboBox) -> None:
        view = combo.view()
        index = view.model().index(row, 0)
        if not index.isValid():
            self.gamepad_tooltip.hide()
            return
        text = view.model().data(index, Qt.ItemDataRole.DisplayRole) or ''
        if not text:
            self.gamepad_tooltip.hide()
            return
        fm = view.fontMetrics()
        text_rect = fm.boundingRect(0, 0, 480, 1000, Qt.TextFlag.TextWordWrap, text)
        w = min(500, text_rect.width() + 25)
        h = min(300, text_rect.height() + 25)
        item_rect = view.visualRect(index)
        item_center_y = view.viewport().mapToGlobal(item_rect.center()).y()
        combo_right_x = combo.mapToGlobal(combo.rect().topRight()).x()
        pos = QPoint(combo_right_x + 4, item_center_y - h // 2)
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen:
            ar = screen.availableGeometry()
            if pos.x() + w > ar.right():
                pos.setX(ar.right() - w)
            if pos.y() + h > ar.bottom():
                pos.setY(ar.bottom() - h)
            if pos.y() < ar.top():
                pos.setY(ar.top())
        self.gamepad_tooltip.setText(text)
        self.gamepad_tooltip.setFixedSize(w, h)
        self.gamepad_tooltip.move(pos)
        self.gamepad_tooltip.setVisible(True)
        self.gamepad_tooltip_timer.start(max(2500, min(12000, 1500 + len(text) * 30)))

    def _select_checkbox_row(self, widget: QCheckBox) -> bool:
        for (row, column), checkbox in self.value_widgets.items():
            if checkbox != widget:
                continue
            self.settings_table.setCurrentCell(row, column)
            self.settings_table.selectRow(row)
            return True
        return False

    def show_registered_gamepad_tooltip(self, widget: QWidget) -> bool:
        """Show registered tooltip for the provided widget."""
        text = self._gamepad_tooltip_map.get(widget, "")
        if not text:
            return False
        self.show_gamepad_tooltip(show=True, text=text, anchor_widget=widget)
        return True

    def _install_line_edit_event_filters(self) -> None:
        """Install event filter for all line edits in the dialog."""
        for line_edit in self.findChildren(QLineEdit):
            if line_edit.property("ppqt_ctx_menu_filter_installed"):
                continue
            line_edit.setProperty("ppqt_ctx_menu_filter_installed", True)
            line_edit.installEventFilter(self)

    def filter_settings(self, text):
        """Filter settings based on search text."""
        search_text = text.lower()
        for row in range(self.favorites_table.rowCount()):
            name_item = self.favorites_table.item(row, 0)
            desc_item = self.favorites_table.item(row, 2)
            should_show = False

            if name_item and search_text in name_item.text().lower():
                should_show = True
            elif desc_item and search_text in desc_item.text().lower():
                should_show = True

            self.favorites_table.setRowHidden(row, not should_show)

        for row in range(self.settings_table.rowCount()):
            name_item = self.settings_table.item(row, 0)
            desc_item = self.settings_table.item(row, 2)
            should_show = False

            if name_item and search_text in name_item.text().lower():
                should_show = True
            elif desc_item and search_text in desc_item.text().lower():
                should_show = True

            self.settings_table.setRowHidden(row, not should_show)

        for row in range(self.advanced_table.rowCount()):
            name_item = self.advanced_table.item(row, 0)
            desc_item = self.advanced_table.item(row, 2)
            should_show = False

            if name_item and search_text in name_item.text().lower():
                should_show = True
            elif desc_item and search_text in desc_item.text().lower():
                should_show = True

            self.advanced_table.setRowHidden(row, not should_show)

        self._filter_mangohud_settings(search_text)
        self._filter_vkbasalt_settings(search_text)
        self._filter_gamescope_settings(search_text)

    def apply_changes(self):
        """Apply changes by collecting diffs from both main and advanced tabs."""
        changes = []
        mangohud_enabled = False

        for key, orig_val in self.original_values.items():
            if key in self.blocked_keys:
                continue
            row = -1
            for r in range(self.settings_table.rowCount()):
                item0 = self.settings_table.item(r, 0)
                if item0 and item0.data(Qt.ItemDataRole.UserRole) == key:
                    row = r
                    break
            if row == -1:
                continue

            widget = self.value_widgets.get((row, 1))
            if isinstance(widget, QComboBox) and self.user_conf:
                new_val = str(widget.currentData() or '')
            elif isinstance(widget, QCheckBox):
                new_val = '1' if widget.isChecked() else '0'
            else:
                continue
            if new_val != orig_val:
                changes.append(f"{key}={new_val}")
                # Track if PW_MANGOHUD is being enabled
                if key == 'PW_MANGOHUD' and new_val == '1':
                    mangohud_enabled = True

        for key, widget in self.advanced_widgets.items():
            orig_val = self.original_display_values.get(key, '')
            if isinstance(widget, QComboBox):
                new_val = widget.currentText()
                if self.user_conf and new_val == _('Default'):
                    new_val = ''
                if key in ('PW_PREFIX_NAME', 'PW_VULKAN_USE') and self.game_source == "steam":
                    continue
                if key == 'PW_PREFIX_NAME':
                    new_val = re.sub(r"[ \t]", "_", new_val.strip()).upper()

                if key in self.value_mapping and 'forward' in self.value_mapping[key]:
                    value_map = self.value_mapping[key]['forward']
                    has_changed = (new_val != orig_val)
                    if new_val in value_map:
                        new_val = value_map[new_val]
                else:
                    has_changed = (new_val != orig_val)

                if key == 'PW_WINE_USE' and new_val == _('System WINE'):
                    new_val = 'USE_SYSTEM_WINE'

                if new_val.lower() == _('disabled').lower():
                    new_val = 'disabled'

                if has_changed:
                    changes.append(f"{key}={new_val}")

            elif isinstance(widget, QLineEdit):
                new_val = widget.text().strip()
                if key == 'PW_RUN_AFTER_EXE':
                    new_val = self._resolve_run_after_exe_path(new_val)
                if new_val != orig_val:
                    changes.append(f"{key}={new_val}")
            else:
                continue

        mangohud_changes = self._collect_mangohud_changes()
        gamescope_changes = []
        if self.gamescope_available:
            gamescope_changes = self._collect_gamescope_changes()
        vkbasalt_changes = self._collect_vkbasalt_changes()
        if self.user_conf:
            if self.current_settings.get('PW_MANGOHUD') != '1':
                mangohud_changes = [
                    change for change in mangohud_changes
                    if change.startswith(('PW_MANGOHUD=', 'PW_MANGOHUD_USER_CONF='))
                ]
            if self.current_settings.get('PW_VKBASALT') != '1':
                vkbasalt_changes = [
                    change for change in vkbasalt_changes
                    if change.startswith(('PW_VKBASALT=', 'PW_VKBASALT_USER_CONF='))
                ]
            if self.current_settings.get('PW_GAMESCOPE') != '1':
                gamescope_changes = [
                    change for change in gamescope_changes
                    if change.startswith('PW_GAMESCOPE=')
                ]
        specialized_changes = mangohud_changes + vkbasalt_changes + gamescope_changes
        if self.user_conf:
            defaults = ('', '0', '0.00', 'Home')
            specialized_changes = [
                change for change in specialized_changes
                if change.split('=', 1)[0] in self.original_values
                or change.split('=', 1)[1] not in defaults
            ]
        changes.extend(specialized_changes)

        # Check if PW_GAMESCOPE toggle changes are already in the list
        has_gamescope_toggle = any(change.startswith("PW_GAMESCOPE=") for change in gamescope_changes)

        if gamescope_changes and not has_gamescope_toggle:
            changes = [change for change in changes if not change.startswith("PW_GAMESCOPE=")]
            changes.append("PW_GAMESCOPE=1")

        # If PW_MANGOHUD is being enabled and MANGOHUD_CONFIG is not in current settings,
        # add it from the var file
        has_mangohud_config_change = any(change.startswith("MANGOHUD_CONFIG=") for change in changes)
        if mangohud_enabled and 'MANGOHUD_CONFIG' not in self.current_settings and not has_mangohud_config_change:
            default_config = self._get_default_mangohud_config()
            if default_config:
                changes.append(f"MANGOHUD_CONFIG={default_config}")
                logger.info("Added MANGOHUD_CONFIG from var file: %s", default_config)

        if not changes:
            return

        if self.user_conf:
            self.user_conf_changes = changes
            self.close_after_user_conf_changes = True
            self.apply_button.setEnabled(False)
            self._apply_next_user_conf_change()
            return

        process = QProcess(self)
        process.finished.connect(self.on_edit_db_finished)
        process_args = ["cli", "--edit-db", self.exe_path] + changes
        args = self._get_process_args(process_args)
        process.start(args[0], args[1:])
        self.apply_button.setEnabled(False)

    def _apply_next_user_conf_change(self) -> None:
        if not self.user_conf_changes:
            self.apply_button.setEnabled(True)
            if self.close_after_user_conf_changes:
                self.close()
            else:
                self.load_current_settings()
            return

        key, value = self.user_conf_changes.pop(0).split('=', 1)
        action = "--set-user-conf" if value else "--delete-user-conf"
        command = ["cli", action, key]
        if value:
            command.append(value)
        self.user_conf_process = QProcess(self)
        self.user_conf_process.finished.connect(self._on_user_conf_change_finished)
        args = self._get_process_args(command)
        self.user_conf_process.start(args[0], args[1:])

    def _on_user_conf_change_finished(self, exit_code, exit_status) -> None:
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            error_output = bytes(self.user_conf_process.readAllStandardError().data()).decode(
                'utf-8', 'ignore'
            )
            self.apply_button.setEnabled(True)
            QMessageBox.warning(self, _("Error"), _("Failed to apply changes. Check logs."))
            logger.error("Failed to update user.conf: %s", error_output)
            return
        self._apply_next_user_conf_change()

    def on_edit_db_finished(self, exit_code, exit_status):
        """Handle --edit-db output."""
        process = cast(QProcess, self.sender())
        self.apply_button.setEnabled(True)
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            error_output = bytes(process.readAllStandardError().data()).decode('utf-8', 'ignore')
            QMessageBox.warning(self, _("Error"), _("Failed to apply changes. Check logs."))
            logger.error(f"Failed to apply changes: {error_output}")
        else:
            self.load_current_settings()
            self.close()

    def closeEvent(self, event):
        if hasattr(self, 'keyboard') and self.keyboard.isVisible():
            self.keyboard.hide()
        if self.input_manager:
            self.input_manager.disable_settings_mode()
        super().closeEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QWidget) and self._handle_vkbasalt_key_button_event(obj, event):
            return True

        action_buttons = (
            getattr(self, "apply_button", None),
            getattr(self, "cancel_button", None),
            getattr(self, "open_ppdb_button", None),
            getattr(self, "clear_ppdb_button", None),
        )
        if obj in action_buttons:
            if event.type() in (
                QEvent.Type.Enter,
                QEvent.Type.FocusIn,
                QEvent.Type.MouseButtonPress,
            ):
                self.show_gamepad_tooltip(show=False)

        if isinstance(obj, QLineEdit) and event.type() == QEvent.Type.ContextMenu:
            context_event = cast(QContextMenuEvent, event)
            from portprotonqt.context_menu_manager import show_themed_line_edit_context_menu

            show_themed_line_edit_context_menu(obj, context_event.globalPos(), self.theme)
            return True

        if isinstance(obj, QCheckBox) and obj in self._gamepad_tooltip_map:
            if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                self.show_registered_gamepad_tooltip(obj)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                focused_widget = QApplication.focusWidget()
                if focused_widget not in self._gamepad_tooltip_map:
                    self.show_gamepad_tooltip(show=False)

        if isinstance(obj, QCheckBox) and event.type() == QEvent.Type.FocusIn:
            self._select_checkbox_row(obj)

        return super().eventFilter(obj, event)

    def show_gamepad_tooltip(self, show=True, text="", anchor_widget=None, anchor_global_pos=None):
        """Show or hide the gamepad tooltip with the provided text."""
        if show and text:
            tooltip_x_offset = self.theme.settings_tooltip_offset_x
            tooltip_y_offset = self.theme.settings_tooltip_offset_y
            tooltip_timeout_ms = max(2500, min(12000, 1500 + len(text) * 30))
            self.gamepad_tooltip.setText(text)
            self.gamepad_tooltip.setFixedSize(500, 300)

            font_metrics = self.gamepad_tooltip.fontMetrics()
            max_width = 500

            text_rect = font_metrics.boundingRect(
                0, 0, max_width - 20, 1000,
                Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs,
                text
            )

            required_width = min(max_width, text_rect.width() + 25)
            required_height = min(300, text_rect.height() + 25)

            def _show_tooltip_at(anchor_pos):
                x = anchor_pos.x() + tooltip_x_offset
                y_below = anchor_pos.y() + tooltip_y_offset
                y = y_below

                screen = QGuiApplication.screenAt(anchor_pos) or QGuiApplication.primaryScreen()
                if screen:
                    available_rect = screen.availableGeometry()
                    y_above = anchor_pos.y() - required_height - tooltip_y_offset
                    fits_below = y_below + required_height <= available_rect.bottom()
                    fits_above = y_above >= available_rect.top()
                    if not fits_below and fits_above:
                        y = y_above

                    if x + required_width > available_rect.right():
                        x = max(available_rect.left(), available_rect.right() - required_width)
                    if x < available_rect.left():
                        x = available_rect.left()
                    if y + required_height > available_rect.bottom():
                        y = max(available_rect.top(), available_rect.bottom() - required_height)
                    if y < available_rect.top():
                        y = available_rect.top()

                self.gamepad_tooltip.setFixedSize(required_width, required_height)
                self.gamepad_tooltip.move(x, y)
                self.gamepad_tooltip.setVisible(True)
                self.gamepad_tooltip_timer.start(tooltip_timeout_ms)

            if anchor_global_pos is not None:
                _show_tooltip_at(anchor_global_pos)
                return

            if anchor_widget and anchor_widget.isVisible():
                widget_rect = anchor_widget.rect()
                _show_tooltip_at(anchor_widget.mapToGlobal(widget_rect.bottomLeft()))
                return

            current_table = self._get_current_settings_table()
            if current_table and current_table.currentRow() >= 0 and current_table.currentColumn() >= 0:
                row = current_table.currentRow()
                col = current_table.currentColumn()
                item_rect = current_table.visualRect(current_table.model().index(row, col))
                _show_tooltip_at(current_table.mapToGlobal(item_rect.bottomLeft()))
            else:
                self.gamepad_tooltip_timer.stop()
                self.gamepad_tooltip.setVisible(False)
        else:
            self.gamepad_tooltip_timer.stop()
            self.gamepad_tooltip.setVisible(False)

    def get_current_description(self):
        """Get the description text for the currently selected row."""
        current_table = self._get_current_settings_table()
        if current_table is None:
            return ""
        current_row = current_table.currentRow()
        if current_row >= 0:
            desc_item = current_table.item(current_row, 2)
            if desc_item:
                return desc_item.text()
        return ""

    def _is_description_clipped(self, table: QTableWidget, row: int) -> bool:
        """Check whether description text is clipped in the table cell."""
        if row < 0:
            return False

        desc_item = table.item(row, 2)
        if not desc_item:
            return False

        description = desc_item.text()
        if not description:
            return False

        item_rect = table.visualRect(table.model().index(row, 2))
        if not item_rect.isValid() or item_rect.width() <= 0 or item_rect.height() <= 0:
            return False

        wrap_rect = table.fontMetrics().boundingRect(
            0,
            0,
            max(1, item_rect.width() - 12),
            10000,
            Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs,
            description
        )
        if wrap_rect.height() > (item_rect.height() - 6):
            return True

        single_line_width = table.fontMetrics().horizontalAdvance(description)
        return single_line_width > (item_rect.width() - 12)

    def on_table_selection_changed(self):
        """Called when table selection changes to update the gamepad tooltip."""
        current_table = self._get_current_settings_table()
        if current_table is None:
            self.show_gamepad_tooltip(show=False)
            return

        current_column = current_table.currentColumn() if current_table else -1
        if current_column != 2:
            self.show_gamepad_tooltip(show=False)
            return

        current_row = current_table.currentRow()
        if not self._is_description_clipped(current_table, current_row):
            self.show_gamepad_tooltip(show=False)
            return

        description = self.get_current_description()
        if description:
            self.show_gamepad_tooltip(show=True, text=description)
        else:
            self.show_gamepad_tooltip(show=False)

    def on_table_cell_hovered(self, row, column):
        """Show custom tooltip on hover for description cells."""
        if column != 2:
            self.show_gamepad_tooltip(show=False)
            return

        table = cast(QTableWidget | None, self.sender())
        if table is None:
            self.show_gamepad_tooltip(show=False)
            return

        desc_item = table.item(row, 2)
        description = desc_item.text() if desc_item else ""
        should_show_tooltip = self._is_description_clipped(table, row) or len(description) > 80
        if description and should_show_tooltip:
            item_rect = table.visualRect(table.model().index(row, 2))
            cell_pos = table.mapToGlobal(item_rect.bottomLeft())
            self.show_gamepad_tooltip(show=True, text=description, anchor_global_pos=cell_pos)
        else:
            self.show_gamepad_tooltip(show=False)

    def reject(self):
        if hasattr(self, 'keyboard') and self.keyboard.isVisible():
            self.keyboard.hide()
        self.gamepad_tooltip.setVisible(False)
        if self.input_manager:
            self.input_manager.disable_settings_mode()
        super().reject()

    def accept(self):
        if hasattr(self, 'keyboard') and self.keyboard.isVisible():
            self.keyboard.hide()
        self.gamepad_tooltip.setVisible(False)
        if self.input_manager:
            self.input_manager.disable_settings_mode()
        super().accept()
