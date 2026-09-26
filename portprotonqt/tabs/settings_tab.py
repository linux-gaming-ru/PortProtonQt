import os
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QScroller,
    QSizePolicy,
    QTabBar,
    QTableWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.appimage_integration import AppImageIntegrationWorker
from portprotonqt.cli import (
    add_steam_compat_tool,
    is_steam_compat_tool_installed,
    remove_steam_compat_tool,
    reset_settings,
)
from portprotonqt.config import (
    apply_xdg_autostart,
    cache_config,
    display_config,
    game_config,
    gamepad_config,
    get_portproton_location,
    migrate_legacy_shortcut,
    proxy_config,
    ui_config,
)
from portprotonqt.context_menu_manager import CustomLineEdit
from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox, FlowLayout
from portprotonqt.debug_utils import get_selectable_gpu_list
from portprotonqt.localization import _, retranslate
from portprotonqt.logger import get_logger
from portprotonqt.portproton_api import get_user_conf_setting, set_user_conf_setting
from portprotonqt.qt_utils import get_system_dpi_for_wine
from portprotonqt.steam_api import (
    get_steam_compatibilitytools_dir,
    get_steam_home,
    get_steam_users,
)
from portprotonqt.time_utils import format_playtime

logger = get_logger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class MainWindowSettingsTabMixin(_MainWindowTypingBase):
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    def createPortProtonTab(self):
        """PortProton Settings tab."""
        self.portProtonWidget = QWidget()
        self.portProtonWidget.setProperty("theme_style_name", "OTHER_PAGES_WIDGET_STYLE")
        self.portProtonWidget.setStyleSheet(self.theme.OTHER_PAGES_WIDGET_STYLE)
        self.portProtonWidget.setObjectName("otherPage")
        layout = QVBoxLayout(self.portProtonWidget)
        layout.setContentsMargins(10, 18, 10, 10)

        # Title
        title = QLabel(_("PortProton Settings"))
        title.setStyleSheet(self.theme.TAB_TITLE_STYLE)
        title.setObjectName("tabTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(title)

        # --- New: Scroll Area for settings ---
        self.settingsScrollArea = QScrollArea()
        self.settingsScrollArea.setWidgetResizable(True)
        self.settingsScrollArea.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settingsScrollArea.setStyleSheet(self.theme.SCROLL_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE)
        self.settingsScrollArea.setFrameShape(QFrame.Shape.NoFrame)
        # Disable horizontal scroll
        self.settingsScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QScroller.grabGesture(self.settingsScrollArea.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

        scrollWidget = QWidget()
        scrollWidget.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)
        scrollLayout = QVBoxLayout(scrollWidget)
        scrollLayout.setContentsMargins(0, 0, 10, 0)
        scrollLayout.setSpacing(10)  # Uniform spacing between sections

        # Helper to create styled sections
        def create_section(title_text, theme):
            section_frame = QFrame()
            section_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            section_frame.setProperty("theme_style_name", "SETTINGS_FRAME_STYLE")
            section_frame.setStyleSheet(self.theme.SETTINGS_FRAME_STYLE)
            section_layout = QVBoxLayout(section_frame)
            section_layout.setContentsMargins(*theme.portProtonPageMargins)
            section_layout.setSpacing(theme.portProtonPageSectionHeaderSpacing)

            section_title = QLabel(title_text)
            section_title.setStyleSheet(self.theme.SETTINGS_FRAME_TITLE_STYLE)
            section_layout.addWidget(section_title)

            section_form = QFormLayout()
            section_form.setSpacing(10)
            section_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            section_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            section_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            section_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            section_form.setHorizontalSpacing(theme.portProtonPageHorizontalSpacing)
            section_form.setVerticalSpacing(theme.portProtonPageVerticalSpacing)
            section_layout.addLayout(section_form)
            return section_frame, section_form

        # 1. Library Settings Section
        genFrame, genForm = create_section(_("Library Settings"), self.theme)
        genForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(genFrame)

        gogFrame, gogForm = create_section(_("Accounts"), self.theme)
        gogForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(gogFrame)
        self.steamAccountCombo = CustomComboBox(theme=self.theme)
        self.steamAccountCombo.setStyleSheet(
            self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE
        )
        self.steamAccountCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.steamAccountCombo.addItem(_("Auto"), "auto")
        self.steamAccountCombo.addItem(_("All"), "all")
        steam_home = get_steam_home()
        steam_users = get_steam_users(steam_home) if steam_home else {}
        for user_id, user_info in steam_users.items():
            account_name = user_info.get("AccountName", user_id)
            persona_name = user_info.get("PersonaName", account_name)
            self.steamAccountCombo.addItem(
                f"{persona_name} ({account_name})", user_id
            )
        selected_account = game_config.get_steam_account_id()
        selected_index = self.steamAccountCombo.findData(selected_account)
        self.steamAccountCombo.setCurrentIndex(max(selected_index, 0))
        self.steamAccountTitle = QLabel(_("Account") + " Steam:")
        self.steamAccountTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        gogForm.addRow(self.steamAccountTitle, self.steamAccountCombo)
        self.gogAccountStatus = QLabel()
        self.gogAccountStatus.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.gogAccountStatus.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.gogLoginButton = AutoSizeButton(_("Open login page"))
        self.gogLoginButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.gogLoginButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.gogLoginButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.gogLoginButton.clicked.connect(self._handle_gog_account_action)
        gog_buttons = QHBoxLayout()
        gog_buttons.addWidget(self.gogAccountStatus)
        gog_buttons.addWidget(self.gogLoginButton)
        self.gogAccountTitle = QLabel(_("Account") + " GOG:")
        self.gogAccountTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        gogForm.addRow(self.gogAccountTitle, gog_buttons)
        self._update_gog_account_state()
        self.egsAccountStatus = QLabel()
        self.egsAccountStatus.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.egsAccountStatus.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.egsLoginButton = AutoSizeButton(_("Open login page"))
        self.egsLoginButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.egsLoginButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.egsLoginButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.egsLoginButton.clicked.connect(self._handle_egs_account_action)
        egs_buttons = QHBoxLayout()
        egs_buttons.addWidget(self.egsAccountStatus)
        egs_buttons.addWidget(self.egsLoginButton)
        self.egsAccountTitle = QLabel(_("Account") + " Epic Games:")
        self.egsAccountTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        gogForm.addRow(self.egsAccountTitle, egs_buttons)
        self._update_egs_account_state()

        self.timeDetailCombo = CustomComboBox(theme=self.theme)
        self.timeDetailCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.timeDetailCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.timeDetailCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.time_keys = ["detailed", "brief", "steam", "hidden"]
        self.time_labels = [_("Detailed"), _("Brief"), "Steam", _("Hidden")]
        self.timeDetailCombo.addItems(self.time_labels)
        self.timeDetailCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.timeDetailCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timeDetailTitle = QLabel(_("Time Detail Level:"))
        self.timeDetailTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.timeDetailTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.timeDetailTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current = ui_config.get_time_detail_level()
        try:
            idx = self.time_keys.index(current)
        except ValueError:
            idx = 0
        self.timeDetailCombo.setCurrentIndex(idx)
        genForm.addRow(self.timeDetailTitle, self.timeDetailCombo)

        # 2. Interface Settings Section
        uiFrame, uiForm = create_section(_("Interface Settings"), self.theme)
        uiForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(uiFrame)

        self.tray_menu_mode_keys = ["compact", "detailed"]
        self.tray_menu_mode_labels = [_("Compact"), _("Detailed")]
        self.trayMenuModeCombo = CustomComboBox(theme=self.theme)
        self.trayMenuModeCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.trayMenuModeCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.trayMenuModeCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.trayMenuModeCombo.addItems(self.tray_menu_mode_labels)
        self.trayMenuModeCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.trayMenuModeCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.trayMenuModeTitle = QLabel(_("Tray Menu Type:"))
        self.trayMenuModeTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.trayMenuModeTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.trayMenuModeTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current = display_config.get_tray_menu_mode()
        try:
            idx = self.tray_menu_mode_keys.index(current)
        except ValueError:
            idx = 0
        self.trayMenuModeCombo.setCurrentIndex(idx)
        uiForm.addRow(self.trayMenuModeTitle, self.trayMenuModeCombo)
        self.setTabOrder(self.timeDetailCombo, self.steamAccountCombo)
        self.setTabOrder(self.steamAccountCombo, self.gogLoginButton)
        self.setTabOrder(self.gogLoginButton, self.egsLoginButton)
        self.setTabOrder(self.egsLoginButton, self.trayMenuModeCombo)

        self.gamepad_type_keys = ["auto", "xbox", "playstation"]
        self.gamepad_type_labels = [_("Auto"), "Xbox", "PlayStation"]
        self.gamepadTypeCombo = CustomComboBox(theme=self.theme)
        self.gamepadTypeCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.gamepadTypeCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.gamepadTypeCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.gamepadTypeCombo.addItems(self.gamepad_type_labels)
        self.gamepadTypeCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.gamepadTypeCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.gamepadTypeTitle = QLabel(_("Gamepad Type:"))
        self.gamepadTypeTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.gamepadTypeTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.gamepadTypeTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_gamepad_type = gamepad_config.get_gamepad_type()
        try:
            idx = self.gamepad_type_keys.index(current_gamepad_type)
        except ValueError:
            idx = 0
        self.gamepadTypeCombo.setCurrentIndex(idx)
        uiForm.addRow(self.gamepadTypeTitle, self.gamepadTypeCombo)

        self.fullscreenCheckBox = QCheckBox()
        self.fullscreenCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.fullscreenCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.fullscreenTitle = QLabel(_("Launch Application in Fullscreen"))
        self.fullscreenTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.fullscreenTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.fullscreenTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_fullscreen = display_config.get_fullscreen()
        self.fullscreenCheckBox.setChecked(current_fullscreen)
        fullscreen_layout = QHBoxLayout()
        fullscreen_layout.setContentsMargins(0, 0, 0, 0)
        fullscreen_layout.addWidget(self.fullscreenCheckBox)
        fullscreen_layout.addWidget(self.fullscreenTitle)
        fullscreen_layout.addStretch()
        uiForm.addRow(fullscreen_layout)

        self.autoFullscreenGamepadCheckBox = QCheckBox()
        self.autoFullscreenGamepadCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.autoFullscreenGamepadCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autoFullscreenGamepadTitle = QLabel(_("Auto Fullscreen on Gamepad connected"))
        self.autoFullscreenGamepadTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.autoFullscreenGamepadTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.autoFullscreenGamepadTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_auto_fullscreen = display_config.get_auto_fullscreen_gamepad()
        self.autoFullscreenGamepadCheckBox.setChecked(current_auto_fullscreen)
        auto_fullscreen_layout = QHBoxLayout()
        auto_fullscreen_layout.setContentsMargins(0, 0, 0, 0)
        auto_fullscreen_layout.addWidget(self.autoFullscreenGamepadCheckBox)
        auto_fullscreen_layout.addWidget(self.autoFullscreenGamepadTitle)
        auto_fullscreen_layout.addStretch()
        uiForm.addRow(auto_fullscreen_layout)

        self.minimizeToTrayCheckBox = QCheckBox()
        self.minimizeToTrayCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.minimizeToTrayCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.minimizeToTrayTitle = QLabel(_("Minimize to tray on close"))
        self.minimizeToTrayTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.minimizeToTrayTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.minimizeToTrayTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_minimize_to_tray = display_config.get_minimize_to_tray()
        self.minimizeToTrayCheckBox.setChecked(current_minimize_to_tray)
        self.minimizeToTrayCheckBox.toggled.connect(lambda checked: display_config.set_minimize_to_tray(checked))
        minimize_layout = QHBoxLayout()
        minimize_layout.setContentsMargins(0, 0, 0, 0)
        minimize_layout.addWidget(self.minimizeToTrayCheckBox)
        minimize_layout.addWidget(self.minimizeToTrayTitle)
        minimize_layout.addStretch()
        uiForm.addRow(minimize_layout)

        self.autostartCheckBox = QCheckBox()
        self.autostartCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.autostartCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autostartTitle = QLabel(_("Run at system startup"))
        self.autostartTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.autostartTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.autostartTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.autostartCheckBox.setChecked(display_config.get_autostart_enabled())
        autostart_layout = QHBoxLayout()
        autostart_layout.setContentsMargins(0, 0, 0, 0)
        autostart_layout.addWidget(self.autostartCheckBox)
        autostart_layout.addWidget(self.autostartTitle)
        autostart_layout.addStretch()
        uiForm.addRow(autostart_layout)

        self.startMinimizedCheckBox = QCheckBox()
        self.startMinimizedCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.startMinimizedCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.startMinimizedTitle = QLabel(_("Start in tray"))
        self.startMinimizedTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.startMinimizedTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.startMinimizedTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.startMinimizedCheckBox.setChecked(display_config.get_start_minimized())
        start_minimized_layout = QHBoxLayout()
        start_minimized_layout.setContentsMargins(0, 0, 0, 0)
        start_minimized_layout.addWidget(self.startMinimizedCheckBox)
        start_minimized_layout.addWidget(self.startMinimizedTitle)
        start_minimized_layout.addStretch()
        uiForm.addRow(start_minimized_layout)

        self.hideAutoInstallTabCheckBox = QCheckBox()
        self.hideAutoInstallTabCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.hideAutoInstallTabCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hideAutoInstallTabTitle = QLabel(_("Hide Auto-Install Tab"))
        self.hideAutoInstallTabTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hideAutoInstallTabTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.hideAutoInstallTabTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_hide_autoinstall = ui_config.get_hide_autoinstall_tab()
        self.hideAutoInstallTabCheckBox.setChecked(current_hide_autoinstall)
        self.hideAutoInstallTabCheckBox.toggled.connect(lambda checked: ui_config.set_hide_autoinstall_tab(checked))
        hide_autoinstall_layout = QHBoxLayout()
        hide_autoinstall_layout.setContentsMargins(0, 0, 0, 0)
        hide_autoinstall_layout.addWidget(self.hideAutoInstallTabCheckBox)
        hide_autoinstall_layout.addWidget(self.hideAutoInstallTabTitle)
        hide_autoinstall_layout.addStretch()
        uiForm.addRow(hide_autoinstall_layout)

        self.hideControlHintsCheckBox = QCheckBox()
        self.hideControlHintsCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.hideControlHintsCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hideControlHintsTitle = QLabel(_("Hide Control Hints"))
        self.hideControlHintsTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hideControlHintsTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.hideControlHintsTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hideControlHintsCheckBox.setChecked(ui_config.get_hide_control_hints())
        hide_control_hints_layout = QHBoxLayout()
        hide_control_hints_layout.setContentsMargins(0, 0, 0, 0)
        hide_control_hints_layout.addWidget(self.hideControlHintsCheckBox)
        hide_control_hints_layout.addWidget(self.hideControlHintsTitle)
        hide_control_hints_layout.addStretch()
        uiForm.addRow(hide_control_hints_layout)

        self.forceEnglishCheckBox = QCheckBox()
        self.forceEnglishCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.forceEnglishCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.forceEnglishTitle = QLabel(_("Force English language"))
        self.forceEnglishTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.forceEnglishTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.forceEnglishTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.forceEnglishCheckBox.setChecked(ui_config.get_force_english())
        force_english_layout = QHBoxLayout()
        force_english_layout.setContentsMargins(0, 0, 0, 0)
        force_english_layout.addWidget(self.forceEnglishCheckBox)
        force_english_layout.addWidget(self.forceEnglishTitle)
        force_english_layout.addStretch()
        uiForm.addRow(force_english_layout)

        self.soundsEnabledCheckBox = QCheckBox()
        self.soundsEnabledCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.soundsEnabledCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.soundsEnabledTitle = QLabel(_("Enable UI Sounds"))
        self.soundsEnabledTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.soundsEnabledTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.soundsEnabledTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.soundsEnabledCheckBox.setChecked(ui_config.get_sounds_enabled())
        sounds_enabled_layout = QHBoxLayout()
        sounds_enabled_layout.setContentsMargins(0, 0, 0, 0)
        sounds_enabled_layout.addWidget(self.soundsEnabledCheckBox)
        sounds_enabled_layout.addWidget(self.soundsEnabledTitle)
        sounds_enabled_layout.addStretch()
        uiForm.addRow(sounds_enabled_layout)

        self.crashReportsEnabledCheckBox = QCheckBox()
        self.crashReportsEnabledCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.crashReportsEnabledCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.crashReportsEnabledTitle = QLabel(
            _("Show compatibility report after game crash")
        )
        self.crashReportsEnabledTitle.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.crashReportsEnabledTitle.setStyleSheet(
            self.theme.SETTINGS_TITLE_CHECKBOX_STYLE
        )
        self.crashReportsEnabledTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.crashReportsEnabledCheckBox.setChecked(
            ui_config.get_crash_reports_enabled()
        )
        crash_reports_enabled_layout = QHBoxLayout()
        crash_reports_enabled_layout.setContentsMargins(0, 0, 0, 0)
        crash_reports_enabled_layout.addWidget(self.crashReportsEnabledCheckBox)
        crash_reports_enabled_layout.addWidget(self.crashReportsEnabledTitle)
        crash_reports_enabled_layout.addStretch()
        uiForm.addRow(crash_reports_enabled_layout)

        self.disableAltDependencyCheckCheckBox: QCheckBox | None = None
        if self._is_alt_x86_64():
            self.disableAltDependencyCheckCheckBox = QCheckBox()
            self.disableAltDependencyCheckCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
            self.disableAltDependencyCheckCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            disable_alt_dependency_check_title = QLabel(
                _("Disable ALT Linux i586 dependency check")
            )
            disable_alt_dependency_check_title.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            disable_alt_dependency_check_title.setStyleSheet(
                self.theme.SETTINGS_TITLE_CHECKBOX_STYLE
            )
            disable_alt_dependency_check_title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.disableAltDependencyCheckCheckBox.setChecked(
                ui_config.get_disable_alt_i586_dependency_check()
            )
            disable_alt_dependency_check_layout = QHBoxLayout()
            disable_alt_dependency_check_layout.setContentsMargins(0, 0, 0, 0)
            disable_alt_dependency_check_layout.addWidget(
                self.disableAltDependencyCheckCheckBox
            )
            disable_alt_dependency_check_layout.addWidget(
                disable_alt_dependency_check_title
            )
            disable_alt_dependency_check_layout.addStretch()
            uiForm.addRow(disable_alt_dependency_check_layout)

        disable_runtime_download_layout = None
        if not os.getenv("FLATPAK_ID"):
            self.disableRuntimeDownloadCheckBox = QCheckBox()
            self.disableRuntimeDownloadCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
            self.disableRuntimeDownloadCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.disableRuntimeDownloadTitle = QLabel(_("Disable runtime download"))
            self.disableRuntimeDownloadTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.disableRuntimeDownloadTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
            self.disableRuntimeDownloadTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.disableRuntimeDownloadCheckBox.setChecked(ui_config.get_disable_runtime_download())
            disable_runtime_download_layout = QHBoxLayout()
            disable_runtime_download_layout.setContentsMargins(0, 0, 0, 0)
            disable_runtime_download_layout.addWidget(self.disableRuntimeDownloadCheckBox)
            disable_runtime_download_layout.addWidget(self.disableRuntimeDownloadTitle)
            disable_runtime_download_layout.addStretch()

        download_wine_to_steam_layout = None
        self.steamCompatCheckBox = QCheckBox()
        self.steamCompatCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.steamCompatCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.steamCompatTitle = QLabel(_("Add to Steam compatibility tools"))
        self.steamCompatTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.steamCompatTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.steamCompatTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_steam_compat = is_steam_compat_tool_installed()
        self.steamCompatCheckBox.setChecked(current_steam_compat)
        steam_compat_layout = QHBoxLayout()
        steam_compat_layout.setContentsMargins(0, 0, 0, 0)
        steam_compat_layout.addWidget(self.steamCompatCheckBox)
        steam_compat_layout.addWidget(self.steamCompatTitle)
        steam_compat_layout.addStretch()
        uiForm.addRow(steam_compat_layout)

        if get_steam_compatibilitytools_dir() is not None:
            self.downloadWineToSteamCheckBox = QCheckBox()
            self.downloadWineToSteamCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
            self.downloadWineToSteamCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.downloadWineToSteamTitle = QLabel(_("Download WINE/Proton to Steam"))
            self.downloadWineToSteamTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.downloadWineToSteamTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
            self.downloadWineToSteamTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.downloadWineToSteamCheckBox.setChecked(ui_config.get_download_wine_to_steam())
            download_wine_to_steam_layout = QHBoxLayout()
            download_wine_to_steam_layout.setContentsMargins(0, 0, 0, 0)
            download_wine_to_steam_layout.addWidget(self.downloadWineToSteamCheckBox)
            download_wine_to_steam_layout.addWidget(self.downloadWineToSteamTitle)
            download_wine_to_steam_layout.addStretch()

        self.economyModeCheckBox = QCheckBox()
        self.economyModeCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.economyModeCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.economyModeTitle = QLabel(_("Economy mode"))
        self.economyModeTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.economyModeTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.economyModeTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.economyModeCheckBox.setChecked(ui_config.get_economy_mode())
        def update_economy_controls(enabled: bool):
            if enabled:
                if hasattr(self, "gamesBadgeViewCombo"):
                    self.gamesBadgeViewCombo.setCurrentIndex(self.badge_view_keys.index("hidden"))
                    self.gamesBadgeViewCombo.setEnabled(False)
                return
            if hasattr(self, "gamesBadgeViewCombo"):
                self.gamesBadgeViewCombo.setEnabled(True)

        self.economyModeCheckBox.toggled.connect(update_economy_controls)
        update_economy_controls(self.economyModeCheckBox.isChecked())
        economy_mode_layout = QHBoxLayout()
        economy_mode_layout.setContentsMargins(0, 0, 0, 0)
        economy_mode_layout.addWidget(self.economyModeCheckBox)
        economy_mode_layout.addWidget(self.economyModeTitle)
        economy_mode_layout.addStretch()

        self.downloadMirrorCombo = CustomComboBox(theme=self.theme)
        self.downloadMirrorCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.downloadMirrorCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.downloadMirrorCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.downloadMirrorCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.downloadMirrorCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.downloadMirrorCombo.addItems(["CLOUD", "GITHUB"])
        current_download_mirror = get_user_conf_setting('MIRROR')
        if current_download_mirror and current_download_mirror not in ("CLOUD", "GITHUB"):
            self.downloadMirrorCombo.addItem(current_download_mirror)
        if current_download_mirror:
            self.downloadMirrorCombo.setCurrentText(current_download_mirror)
        self.downloadMirrorTitle = QLabel(_("Download mirror:"))
        self.downloadMirrorTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.downloadMirrorTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.downloadMirrorTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.autoDownloadPPDBCheckBox = QCheckBox()
        self.autoDownloadPPDBCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.autoDownloadPPDBCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autoDownloadPPDBTitle = QLabel(_("Auto download PPDB from") + " linux-gaming.ru")
        self.autoDownloadPPDBTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.autoDownloadPPDBTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.autoDownloadPPDBTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.autoDownloadPPDBCheckBox.setChecked(ui_config.get_auto_download_ppdb())
        auto_download_ppdb_layout = QHBoxLayout()
        auto_download_ppdb_layout.setContentsMargins(0, 0, 0, 0)
        auto_download_ppdb_layout.addWidget(self.autoDownloadPPDBCheckBox)
        auto_download_ppdb_layout.addWidget(self.autoDownloadPPDBTitle)
        auto_download_ppdb_layout.addStretch()

        auto_appimage_updates_layout = None
        if os.getenv("APPIMAGE"):
            self.autoAppImageUpdatesCheckBox = QCheckBox()
            self.autoAppImageUpdatesCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
            self.autoAppImageUpdatesCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.autoAppImageUpdatesTitle = QLabel(_("Auto update AppImage"))
            self.autoAppImageUpdatesTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.autoAppImageUpdatesTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
            self.autoAppImageUpdatesTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.autoAppImageUpdatesCheckBox.setChecked(ui_config.get_auto_appimage_updates())
            auto_appimage_updates_layout = QHBoxLayout()
            auto_appimage_updates_layout.setContentsMargins(0, 0, 0, 0)
            auto_appimage_updates_layout.addWidget(self.autoAppImageUpdatesCheckBox)
            auto_appimage_updates_layout.addWidget(self.autoAppImageUpdatesTitle)
            auto_appimage_updates_layout.addStretch()
            self.integrateAppImageButton = AutoSizeButton(
                _("Integrate AppImage"), icon=self.theme_manager.get_icon("desktop", as_path=True)
            )
            self.integrateAppImageButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
            self.integrateAppImageButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            self.integrateAppImageButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.integrateAppImageButton.clicked.connect(self.integrateAppImage)

        self.forceSystemDpiCheckBox = QCheckBox()
        self.forceSystemDpiCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.forceSystemDpiCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.forceSystemDpiTitle = QLabel(_("Force system DPI for Wine"))
        self.forceSystemDpiTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.forceSystemDpiTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.forceSystemDpiTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        current_force_dpi = get_user_conf_setting('PW_FORCE_SYSTEM_DPI')
        self.forceSystemDpiCheckBox.setChecked(str(current_force_dpi) == "1")
        force_system_dpi_layout = QHBoxLayout()
        force_system_dpi_layout.setContentsMargins(0, 0, 0, 0)
        force_system_dpi_layout.addWidget(self.forceSystemDpiCheckBox)
        force_system_dpi_layout.addWidget(self.forceSystemDpiTitle)
        force_system_dpi_layout.addStretch()
        uiForm.addRow(force_system_dpi_layout)

        # 3. Download Settings Section
        downloadFrame, downloadForm = create_section(_("Download Settings"), self.theme)
        downloadForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(downloadFrame)

        if disable_runtime_download_layout is not None:
            downloadForm.addRow(disable_runtime_download_layout)

        if download_wine_to_steam_layout is not None:
            downloadForm.addRow(download_wine_to_steam_layout)

        downloadForm.addRow(economy_mode_layout)
        downloadForm.addRow(auto_download_ppdb_layout)
        if auto_appimage_updates_layout is not None:
            downloadForm.addRow(auto_appimage_updates_layout)

        self.enableThemeStoreCheckBox = QCheckBox()
        self.enableThemeStoreCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.enableThemeStoreCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.enableThemeStoreTitle = QLabel(
            _("Enable Theme Store from %(source)s (%(warning)s)") % {
                "source": "linux-gaming.ru",
                "warning": _("third-party themes may be unsafe"),
            }
        )
        self.enableThemeStoreTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.enableThemeStoreTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        self.enableThemeStoreTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.enableThemeStoreCheckBox.setChecked(ui_config.get_enable_theme_store())
        enable_theme_store_layout = QHBoxLayout()
        enable_theme_store_layout.setContentsMargins(0, 0, 0, 0)
        enable_theme_store_layout.addWidget(self.enableThemeStoreCheckBox)
        enable_theme_store_layout.addWidget(self.enableThemeStoreTitle)
        enable_theme_store_layout.addStretch()
        downloadForm.addRow(enable_theme_store_layout)

        downloadForm.addRow(self.downloadMirrorTitle, self.downloadMirrorCombo)

        # 4. Hardware Settings Section
        hwFrame, hwForm = create_section(_("Hardware Settings"), self.theme)
        hwForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(hwFrame)

        filtered_gpu_list = get_selectable_gpu_list()
        hwFrame.setVisible(len(filtered_gpu_list) > 1)
        if len(filtered_gpu_list) > 1:
            self.gpuCombo = CustomComboBox(theme=self.theme)
            self.gpuCombo.view().window().setWindowFlags(
                Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
            )
            self.gpuCombo.view().window().setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground
            )
            self.gpuCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.gpuCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.gpuCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
            self.gpuCombo.addItems(filtered_gpu_list)
            current_gpu = get_user_conf_setting('PW_GPU_USE')
            if current_gpu and current_gpu != "disabled" and current_gpu in filtered_gpu_list:
                self.gpuCombo.setCurrentText(current_gpu)
            elif current_gpu and current_gpu != "disabled" and "Info:" not in current_gpu:
                if current_gpu not in filtered_gpu_list:
                    self.gpuCombo.addItem(current_gpu)
                self.gpuCombo.setCurrentText(current_gpu)
            else:
                self.gpuCombo.setCurrentIndex(0)
            self.gpuTitle = QLabel(_("GPU to use:"))
            self.gpuTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.gpuTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
            self.gpuTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            hwForm.addRow(self.gpuTitle, self.gpuCombo)

        # 5. Proxy Settings Section
        proxyFrame, proxyForm = create_section(_("Proxy Settings"), self.theme)
        proxyForm.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        scrollLayout.addWidget(proxyFrame)

        self.proxyUrlEdit = CustomLineEdit(self, theme=self.theme)
        self.proxyUrlEdit.setPlaceholderText(_("Proxy URL"))
        self.proxyUrlEdit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.proxyUrlEdit.setProperty("theme_style_name", "LINE_EDIT_STYLE")
        self.proxyUrlEdit.setStyleSheet(self.theme.LINE_EDIT_STYLE)
        self.proxyUrlEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.proxyUrlTitle = QLabel(_("Proxy URL:"))
        self.proxyUrlTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.proxyUrlTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.proxyUrlTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        proxy_cfg = proxy_config.get_proxy()
        if proxy_cfg.get("http", ""):
            self.proxyUrlEdit.setText(proxy_cfg["http"])
        proxyForm.addRow(self.proxyUrlTitle, self.proxyUrlEdit)

        self.proxyUserEdit = CustomLineEdit(self, theme=self.theme)
        self.proxyUserEdit.setPlaceholderText(_("Proxy Username"))
        self.proxyUserEdit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.proxyUserEdit.setProperty("theme_style_name", "LINE_EDIT_STYLE")
        self.proxyUserEdit.setStyleSheet(self.theme.LINE_EDIT_STYLE)
        self.proxyUserEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.proxyUserTitle = QLabel(_("Proxy Username:"))
        self.proxyUserTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.proxyUserTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.proxyUserTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        proxyForm.addRow(self.proxyUserTitle, self.proxyUserEdit)

        self.proxyPasswordEdit = CustomLineEdit(self, theme=self.theme)
        self.proxyPasswordEdit.setPlaceholderText(_("Proxy Password"))
        self.proxyPasswordEdit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.proxyPasswordEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxyPasswordEdit.setProperty("theme_style_name", "LINE_EDIT_STYLE")
        self.proxyPasswordEdit.setStyleSheet(self.theme.LINE_EDIT_STYLE)
        self.proxyPasswordEdit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.proxyPasswordTitle = QLabel(_("Proxy Password:"))
        self.proxyPasswordTitle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.proxyPasswordTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.proxyPasswordTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        proxyForm.addRow(self.proxyPasswordTitle, self.proxyPasswordEdit)

        scrollLayout.addStretch(1)
        self.settingsScrollArea.setWidget(scrollWidget)
        layout.addWidget(self.settingsScrollArea)

        # Buttons (outside scroll area, always visible)
        buttonsLayout = FlowLayout(center_rows=True)
        buttonsLayout.setContentsMargins(0, 0, 0, 0)
        buttonsLayout.setSpacing(self.theme.portProtonPageVerticalSpacing)

        self.saveButton = AutoSizeButton(_("Save Settings"), icon=self.theme_manager.get_icon("save", as_path=True))
        self.saveButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.saveButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.saveButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.saveButton.clicked.connect(self.savePortProtonSettings)
        buttonsLayout.addWidget(self.saveButton)

        self.resetSettingsButton = AutoSizeButton(_("Reset Settings"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.resetSettingsButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.resetSettingsButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.resetSettingsButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resetSettingsButton.clicked.connect(self.resetSettings)
        buttonsLayout.addWidget(self.resetSettingsButton)

        self.globalGameSettingsButton = AutoSizeButton(
            _("Global Game Settings"), icon=self.theme_manager.get_icon("settings", as_path=True)
        )
        self.globalGameSettingsButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.globalGameSettingsButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.globalGameSettingsButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.globalGameSettingsButton.clicked.connect(self.openGlobalGameSettings)
        buttonsLayout.addWidget(self.globalGameSettingsButton)

        self.migrateShortcutsButton = AutoSizeButton(_("Migrate legacy shortcuts"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.migrateShortcutsButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.migrateShortcutsButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.migrateShortcutsButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.migrateShortcutsButton.clicked.connect(self.migrateLegacyShortcuts)
        buttonsLayout.addWidget(self.migrateShortcutsButton)

        if os.getenv("APPIMAGE"):
            buttonsLayout.addWidget(self.integrateAppImageButton)

        self.clearCacheButton = AutoSizeButton(_("Clear Cache"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.clearCacheButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.clearCacheButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.clearCacheButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clearCacheButton.clicked.connect(self.clearCache)
        buttonsLayout.addWidget(self.clearCacheButton)

        layout.addLayout(buttonsLayout)
        self.stackedWidget.addWidget(self.portProtonWidget)

    def openGlobalGameSettings(self) -> None:
        from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

        ExeSettingsDialog(self, self.theme, user_conf=True).exec()

    def resetSettings(self):
        """Reset settings and restart application."""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Reset"))
        msg_box.setText(_("Are you sure you want to reset all settings? This action cannot be undone."))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            if reset_settings():
                QTimer.singleShot(1000, lambda: self.restart_application())

    def migrateLegacyShortcuts(self):
        """Migrate legacy shortcuts after user confirmation."""
        portproton_location = get_portproton_location()
        if not portproton_location:
            QMessageBox.warning(self, _("Error"), _("PortProton directory not found"))
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Migrate legacy shortcuts"))
        msg_box.setText(_("Migrate old PortProton shortcuts to PortProtonQt format?"))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        migrated = migrate_legacy_shortcut(portproton_location)
        logger.info("Migrated legacy shortcuts: %d", migrated)

    def clearCache(self):
        """Clear cache."""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Clear Cache"))
        msg_box.setText(_("Are you sure you want to clear the cache? This action cannot be undone."))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            cache_config.clear_cache()
            self.gog_api.clear_library_cache()
            self.egs_api.clear_library_cache()

    def integrateAppImage(self) -> None:
        """Install the running AppImage in the user application menu."""
        self.integrateAppImageButton.setEnabled(False)
        self.appImageIntegrationWorker = AppImageIntegrationWorker(self)
        self.appImageIntegrationWorker.completed.connect(
            self._onAppImageIntegrationCompleted
        )
        self.appImageIntegrationWorker.finished.connect(
            self.appImageIntegrationWorker.deleteLater
        )
        self.appImageIntegrationWorker.finished.connect(
            lambda: setattr(self, "appImageIntegrationWorker", None)
        )
        self.appImageIntegrationWorker.start()

    def _onAppImageIntegrationCompleted(self, success: bool, message: str) -> None:
        self.integrateAppImageButton.setEnabled(True)
        if success:
            QMessageBox.information(
                self,
                _("Success"),
                _("AppImage integrated at: {path}").format(path=message),
            )
            return
        QMessageBox.warning(
            self,
            _("Error"),
            _("Failed to integrate AppImage: {error}").format(error=message),
        )

    def applySettingsDelayed(self):
        ui_config.get_time_detail_level()
        self.games = []
        self.loadGames()
        display_filter = game_config.get_display_filter()
        for card in self.game_library_manager.game_card_cache.values():
            card.update_badge_visibility(display_filter)

    def _format_game_tuple_playtime(self, game: tuple) -> tuple:
        """Return game tuple with playtime formatted for current UI mode."""
        if len(game) <= 11:
            return game
        updated_game = list(game)
        updated_game[7] = format_playtime(updated_game[11] or 0)
        return tuple(updated_game)

    def _refresh_loaded_playtime_format(self) -> None:
        """Refresh cached playtime strings after changing display mode."""
        self.games = [self._format_game_tuple_playtime(game) for game in self.games]
        self.game_library_manager.games = [
            self._format_game_tuple_playtime(game)
            for game in self.game_library_manager.games
        ]
        self.game_library_manager.filtered_games = [
            self._format_game_tuple_playtime(game)
            for game in self.game_library_manager.filtered_games
        ]
        for card in self.game_library_manager.game_card_cache.values():
            card.formatted_playtime = format_playtime(card.playtime_seconds or 0)

    def _refresh_current_detail_time(self) -> None:
        """Refresh time labels on the current detail page."""
        if not self.currentDetailPage or not self.current_exec_line:
            return
        if self.stackedWidget.currentWidget() is not self.currentDetailPage:
            return
        current_game = next(
            (game for game in self.games if game[5] == self.current_exec_line),
            None,
        )
        if not current_game:
            return
        last_launch_value = self.currentDetailPage.findChild(QLabel, "detailLastLaunchValue")
        if last_launch_value is not None:
            last_launch_value.setText(current_game[6])
        playtime_value = self.currentDetailPage.findChild(QLabel, "detailPlaytimeValue")
        if playtime_value is not None:
            playtime_value.setText(current_game[7])
        visible = ui_config.get_time_detail_level() != "hidden"
        for object_name in (
            "detailLastLaunchTitle",
            "detailLastLaunchValue",
            "detailPlaytimeTitle",
            "detailPlaytimeValue",
        ):
            widget = self.currentDetailPage.findChild(QLabel, object_name)
            if widget is not None:
                widget.setVisible(visible)

    def savePortProtonSettings(self):
        previous_economy_mode = ui_config.get_economy_mode()
        previous_force_english = ui_config.get_force_english()
        game_config.set_steam_account_id(
            str(self.steamAccountCombo.currentData())
        )
        time_idx = self.timeDetailCombo.currentIndex()
        time_key = self.time_keys[time_idx]
        ui_config.set_time_detail_level(time_key)
        self._refresh_loaded_playtime_format()

        economy_mode = self.economyModeCheckBox.isChecked()
        ui_config.set_economy_mode(economy_mode)
        economy_mode_changed = previous_economy_mode != economy_mode
        badge_view_idx = self.gamesBadgeViewCombo.currentIndex()
        badge_view_mode = self.badge_view_keys[badge_view_idx]
        if economy_mode:
            badge_view_mode = "hidden"
        ui_config.set_badge_view_mode(badge_view_mode)
        library_badge_index = self.badge_view_keys.index(badge_view_mode)
        if self.gamesBadgeViewCombo.currentIndex() != library_badge_index:
            self.gamesBadgeViewCombo.blockSignals(True)
            self.gamesBadgeViewCombo.setCurrentIndex(library_badge_index)
            self.gamesBadgeViewCombo.blockSignals(False)

        proxy_url = self.proxyUrlEdit.text().strip()
        proxy_user = self.proxyUserEdit.text().strip()
        proxy_password = self.proxyPasswordEdit.text().strip()
        proxy_config.set_proxy(proxy_url, proxy_user, proxy_password)

        fullscreen = self.fullscreenCheckBox.isChecked()
        display_config.set_fullscreen(fullscreen)

        auto_fullscreen_gamepad = self.autoFullscreenGamepadCheckBox.isChecked()
        display_config.set_auto_fullscreen_gamepad(auto_fullscreen_gamepad)

        hide_control_hints = self.hideControlHintsCheckBox.isChecked()
        ui_config.set_hide_control_hints(hide_control_hints)
        force_english = self.forceEnglishCheckBox.isChecked()
        ui_config.set_force_english(force_english)
        if previous_force_english != force_english:
            self._retranslate_interface()

        gamepad_type_idx = self.gamepadTypeCombo.currentIndex()
        gamepad_type = self.gamepad_type_keys[gamepad_type_idx]
        gamepad_config.set_gamepad_type(gamepad_type)

        autostart_enabled = self.autostartCheckBox.isChecked()
        display_config.set_autostart_enabled(autostart_enabled)
        if not apply_xdg_autostart(autostart_enabled):
            QMessageBox.warning(self, _("Error"), _("Failed to update xdg-autostart entry."))

        start_minimized = self.startMinimizedCheckBox.isChecked()
        display_config.set_start_minimized(start_minimized)

        tray_menu_mode_idx = self.trayMenuModeCombo.currentIndex()
        tray_menu_mode = self.tray_menu_mode_keys[tray_menu_mode_idx]
        display_config.set_tray_menu_mode(tray_menu_mode)

        steam_compat = self.steamCompatCheckBox.isChecked()
        currently_installed = is_steam_compat_tool_installed()
        if steam_compat and not currently_installed:
            add_steam_compat_tool()
        elif not steam_compat and currently_installed:
            remove_steam_compat_tool()

        if hasattr(self, 'downloadWineToSteamCheckBox'):
            ui_config.set_download_wine_to_steam(self.downloadWineToSteamCheckBox.isChecked())

        if hasattr(self, 'disableRuntimeDownloadCheckBox'):
            ui_config.set_disable_runtime_download(self.disableRuntimeDownloadCheckBox.isChecked())
        else:
            ui_config.get_disable_runtime_download()

        set_user_conf_setting('MIRROR', self.downloadMirrorCombo.currentText())
        ui_config.set_auto_download_ppdb(self.autoDownloadPPDBCheckBox.isChecked())
        if hasattr(self, 'autoAppImageUpdatesCheckBox'):
            ui_config.set_auto_appimage_updates(self.autoAppImageUpdatesCheckBox.isChecked())

        enable_theme_store = self.enableThemeStoreCheckBox.isChecked()
        ui_config.set_enable_theme_store(enable_theme_store)
        self._refresh_theme_store_visibility()

        # Save GPU selection to user.conf (only if the combo box exists)
        if hasattr(self, 'gpuCombo') and self.gpuCombo.count() > 1:
            selected_gpu = self.gpuCombo.currentText()
            set_user_conf_setting('PW_GPU_USE', selected_gpu)
        if hasattr(self, 'forceSystemDpiCheckBox'):
            if self.forceSystemDpiCheckBox.isChecked():
                system_dpi = get_system_dpi_for_wine()
                set_user_conf_setting('PW_FORCE_SYSTEM_DPI', "1")
                set_user_conf_setting('PW_WINE_DPI_VALUE', system_dpi)
            else:
                set_user_conf_setting('PW_FORCE_SYSTEM_DPI', "0")

        # Get hide auto-install tab setting
        hide_autoinstall = self.hideAutoInstallTabCheckBox.isChecked()

        if hasattr(self, 'input_manager'):
            self._apply_gamepad_type_setting()
            self.updateControlHints()
            if hasattr(self, 'keyboard'):
                self.keyboard.update_keyboard()

        if economy_mode_changed:
            if self.game_library_manager.gamesListLayout is not None:
                self.game_library_manager.clear_layout(self.game_library_manager.gamesListLayout)
        else:
            display_filter = game_config.get_display_filter()
            for card in self.game_library_manager.game_card_cache.values():
                card.update_badge_visibility(display_filter)
                card.update_badge_view_mode(badge_view_mode)

        self._refresh_current_detail_time()

        self.settingsDebounceTimer.start()

        gamepad_connected = self.input_manager.gamepad is not None
        if fullscreen or (auto_fullscreen_gamepad and gamepad_connected):
            self.showFullScreen()

        # Apply the hide auto-install tab setting
        if hide_autoinstall:  # Hide the tab
            # Find the auto-install tab button and hide it
            if hasattr(self, 'tabButtons') and self.auto_install_tab_index in self.tabButtons:
                tab_button = self.tabButtons[self.auto_install_tab_index]
                tab_button.setVisible(False)

                # If currently on the hidden tab, switch to the first tab
                if self.stackedWidget.currentIndex() == self.auto_install_tab_index:
                    self.switchTab(0)  # Switch to Library tab

            # Hide the stacked widget page too
            if hasattr(self, 'stackedWidget'):
                auto_install_page = self.stackedWidget.widget(self.auto_install_tab_index)
                if auto_install_page:
                    auto_install_page.setVisible(False)

            # Stop any ongoing auto-install loading if present
            if hasattr(self, 'autoInstallLoadThread') and self.autoInstallLoadThread:
                self.autoInstallLoadThread.requestInterruption()
                self.autoInstallLoadThread.wait(5000)  # Wait up to 5 seconds for thread to finish
                self.autoInstallLoadThread = None
        else:  # Show the tab
            # Make sure the tab button is visible
            if hasattr(self, 'tabButtons') and self.auto_install_tab_index in self.tabButtons:
                tab_button = self.tabButtons[self.auto_install_tab_index]
                tab_button.setVisible(True)

            # Make sure the stacked widget page is visible
            if hasattr(self, 'stackedWidget'):
                auto_install_page = self.stackedWidget.widget(self.auto_install_tab_index)
                if auto_install_page:
                    auto_install_page.setVisible(True)

        # Save the hide auto-install tab setting to config
        ui_config.set_hide_autoinstall_tab(hide_autoinstall)

        sounds_enabled = self.soundsEnabledCheckBox.isChecked()
        ui_config.set_sounds_enabled(sounds_enabled)
        ui_config.set_crash_reports_enabled(
            self.crashReportsEnabledCheckBox.isChecked()
        )
        if self.disableAltDependencyCheckCheckBox is not None:
            ui_config.set_disable_alt_i586_dependency_check(
                self.disableAltDependencyCheckCheckBox.isChecked()
            )

        from portprotonqt.sound_manager import SoundManager
        SoundManager().reload_config()

    def _retranslate_interface(self) -> None:
        """Apply the selected language to the existing interface."""
        objects = [self, *self.findChildren(QObject)]
        for obj in objects:
            if isinstance(obj, QAction):
                obj.setText(retranslate(obj.text()))
            if isinstance(obj, (QLabel, QAbstractButton)):
                obj.setText(retranslate(obj.text()))
            if isinstance(obj, (QGroupBox, QMenu)):
                obj.setTitle(retranslate(obj.title()))
            if isinstance(obj, QLineEdit):
                obj.setPlaceholderText(retranslate(obj.placeholderText()))
            if isinstance(obj, QComboBox):
                for index in range(obj.count()):
                    obj.setItemText(index, retranslate(obj.itemText(index)))
            if isinstance(obj, QTabBar):
                for index in range(obj.count()):
                    obj.setTabText(index, retranslate(obj.tabText(index)))
            if isinstance(obj, QTableWidget):
                for column in range(obj.columnCount()):
                    item = obj.horizontalHeaderItem(column)
                    if item is not None:
                        item.setText(retranslate(item.text()))
                for row in range(obj.rowCount()):
                    for column in range(obj.columnCount()):
                        item = obj.item(row, column)
                        if item is not None:
                            item.setText(retranslate(item.text()))
            if isinstance(obj, QTreeWidget):
                for column in range(obj.columnCount()):
                    item = obj.headerItem()
                    item.setText(column, retranslate(item.text(column)))
        self.steamAccountTitle.setText(_("Account") + " Steam:")
        self.gogAccountTitle.setText(_("Account") + " GOG:")
        self.egsAccountTitle.setText(_("Account") + " Epic Games:")
        self.autoDownloadPPDBTitle.setText(
            _("Auto download PPDB from") + " linux-gaming.ru"
        )
        self.enableThemeStoreTitle.setText(
            _("Enable Theme Store from %(source)s (%(warning)s)") % {
                "source": "linux-gaming.ru",
                "warning": _("third-party themes may be unsafe"),
            }
        )

    def _apply_gamepad_type_setting(self) -> None:
        """Apply configured gamepad type to current input manager."""
        input_manager = getattr(self, "input_manager", None)
        if input_manager is None:
            return
        input_manager.apply_gamepad_type_setting()
