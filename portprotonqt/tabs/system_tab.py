import os
import sys
import shlex
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QPoint, QProcess, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QScroller,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.context_menu_manager import CustomLineEdit
from portprotonqt.custom_widgets import AutoSizeButton
from portprotonqt.dialogs.base import DraggableDialog
from portprotonqt.dialogs import FileExplorer
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager
from portprotonqt.preloader import Preloader
if sys.platform != "darwin":
    from portprotonqt.system_manager import (
        AudioManagerWorker,
        BluetoothManagerWorker,
        NetworkManagerWorker,
        StorageManagerWorker,
    )

logger = get_logger(__name__)

AUDIO_MAX_VOLUME = 150
RETURN_TO_DESKTOP_ENV = "PORTPROTONQT_RETURN_TO_DESKTOP_SCRIPT"
SYSTEM_DEVICE_RETRY_INTERVAL_MS = 2000
SYSTEM_DEVICE_RETRY_LIMIT = 5


if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class WifiPasswordDialog(DraggableDialog):
    """Custom password dialog for Wi-Fi networks with virtual keyboard support."""

    def __init__(self, parent=None, ssid: str = "", initial_password: str = "", theme=None):
        super().__init__(parent)
        self.theme = theme

        self.setWindowTitle("Wi-Fi")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE if self.theme else "")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        ssid_label = QLabel(_("Enter password for: {0}").format(ssid) if ssid else "")
        if self.theme and hasattr(self.theme, 'PARAMS_TITLE_STYLE'):
            ssid_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        layout.addWidget(ssid_label)

        input_layout = QHBoxLayout()
        self.passwordEdit = CustomLineEdit(self, theme=self.theme)
        if self.theme and hasattr(self.theme, 'ADDGAME_INPUT_STYLE'):
            self.passwordEdit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        if initial_password:
            self.passwordEdit.setText(initial_password)
        self.passwordEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passwordEdit.returnPressed.connect(self.accept)
        input_layout.addWidget(self.passwordEdit)

        self.toggleButton = QPushButton("", self)
        if self.theme and hasattr(self.theme, 'ACTION_BUTTON_STYLE'):
            self.toggleButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.toggleButton.setText("")
        self.toggleButton.clicked.connect(self._togglePasswordVisibility)
        self._updatePasswordToggleIcon()
        input_layout.addWidget(self.toggleButton)

        layout.addLayout(input_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_button = QPushButton(_("Cancel"), self)
        if self.theme and hasattr(self.theme, 'ACTION_BUTTON_STYLE'):
            cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        ok_button = QPushButton(_("Connect"), self)
        if self.theme and hasattr(self.theme, 'ACTION_BUTTON_STYLE'):
            ok_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        ok_button.clicked.connect(self.accept)
        ok_button.setDefault(True)
        buttons_layout.addWidget(ok_button)

        layout.addLayout(buttons_layout)

        self.passwordEdit.setFocus()

    def _togglePasswordVisibility(self) -> None:
        if self.passwordEdit.echoMode() == QLineEdit.EchoMode.Password:
            self.passwordEdit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.passwordEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self._updatePasswordToggleIcon()

    def _updatePasswordToggleIcon(self) -> None:
        icon_name = "wifi_show" if self.passwordEdit.echoMode() == QLineEdit.EchoMode.Password else "wifi_hide"
        parent = self.parent()
        theme_manager = getattr(parent, "theme_manager", None)
        if theme_manager is None:
            self.toggleButton.setIcon(QIcon())
            return
        raw_icon = theme_manager.get_icon(icon_name)
        icon = raw_icon if isinstance(raw_icon, QIcon) else QIcon(raw_icon) if isinstance(raw_icon, str) else QIcon()
        self.toggleButton.setIcon(icon)

    def getPassword(self) -> str:
        """Return the entered password."""
        return self.passwordEdit.text()


class MainWindowSystemTabMixin(_MainWindowTypingBase):
    if TYPE_CHECKING:
        stackedWidget: QStackedWidget
        theme: Any
        theme_manager: Any

    def _focusSystemNetworkOnTabEnter(self) -> None:
        if self.stackedWidget.currentIndex() != getattr(self, "system_tab_index", -1):
            return
        preferred_index = 0
        if hasattr(self, "systemSectionButtons"):
            wifi_index = getattr(self, "systemSectionWifiIndex", 0)
            vpn_index = getattr(self, "systemSectionVpnIndex", 1)
            if wifi_index < len(self.systemSectionButtons) and self.systemSectionButtons[wifi_index].isVisible():
                preferred_index = wifi_index
            elif vpn_index < len(self.systemSectionButtons) and self.systemSectionButtons[vpn_index].isVisible():
                preferred_index = vpn_index
            else:
                visible_indices = self._getVisibleSystemSectionIndices()
                if visible_indices:
                    preferred_index = visible_indices[0]
        self.switchSystemSection(preferred_index)


    def createSystemTab(self) -> None:
        """System settings tab."""
        self.systemWidget = QWidget()
        self.systemWidget.setProperty("theme_style_name", "OTHER_PAGES_WIDGET_STYLE")
        self.systemWidget.setStyleSheet(self.theme.OTHER_PAGES_WIDGET_STYLE)
        self.systemWidget.setObjectName("otherPage")
        layout = QVBoxLayout(self.systemWidget)
        layout.setContentsMargins(10, 18, 10, 10)
        self._addSystemTabTitle(layout)
        scroll_widget, scroll_layout, section_switcher = self._createSystemTabScrollLayout()
        self._buildSystemSections()
        self._setupSystemSectionButtons(section_switcher)
        self._finalizeSystemTabLayout(layout, scroll_layout, scroll_widget, section_switcher)
        self._initializeSystemTabState()
        self._startSystemBackgroundTasks()

    def _addSystemTabTitle(self, layout: QVBoxLayout) -> None:
        title = QLabel(_("System"))
        title.setStyleSheet(self.theme.TAB_TITLE_STYLE)
        title.setObjectName("tabTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(title)

    def _createSystemTabScrollLayout(self) -> tuple[QWidget, QVBoxLayout, QHBoxLayout]:
        self.systemScrollArea = QScrollArea()
        self.systemScrollArea.setWidgetResizable(True)
        self.systemScrollArea.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.systemScrollArea.setStyleSheet(self.theme.SCROLL_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE)
        self.systemScrollArea.setFrameShape(QFrame.Shape.NoFrame)
        self.systemScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QScroller.grabGesture(
            self.systemScrollArea.viewport(),
            QScroller.ScrollerGestureType.LeftMouseButtonGesture,
        )
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)
        section_switcher = QWidget()
        self.systemSectionSwitcher = section_switcher
        section_switcher_layout = QHBoxLayout(section_switcher)
        section_switcher_layout.setContentsMargins(0, 0, 0, 0)
        section_switcher_layout.setSpacing(8)
        return scroll_widget, scroll_layout, section_switcher_layout

    def _buildSystemSections(self) -> None:
        self.systemSectionButtons = []
        self.systemSectionStack = QStackedWidget()
        self.systemSectionStack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._addSystemNetworkSection()
        self._addSystemVpnSection()
        self._addSystemBluetoothSection()
        self._addSystemStorageSection()
        self._addSystemAudioSection()
        self._addSystemPowerSection()

    def _addSystemNetworkSection(self) -> None:
        network_frame, network_layout = self._createSystemSection("Wi-Fi")
        self.networkSectionFrame = network_frame
        self._setupSystemNetworkControls(network_layout)
        self._setupSystemNetworkTable(network_layout)
        self._setupSystemActionButtons(network_layout)
        self.systemSectionStack.addWidget(network_frame)

    def _addSystemVpnSection(self) -> None:
        vpn_frame, vpn_layout = self._createSystemSection("VPN")
        self._setupSystemVpnControls(vpn_layout)
        self.systemSectionStack.addWidget(vpn_frame)

    def _addSystemBluetoothSection(self) -> None:
        bluetooth_frame, bluetooth_layout = self._createSystemSection("Bluetooth")
        self.bluetoothSectionFrame = bluetooth_frame
        self._setupSystemBluetoothControls(bluetooth_layout)
        self._setupSystemBluetoothTable(bluetooth_layout)
        self._setupSystemBluetoothActionButtons(bluetooth_layout)
        self.systemSectionStack.addWidget(bluetooth_frame)

    def _addSystemStorageSection(self) -> None:
        storage_frame, storage_layout = self._createSystemSection(_("Storage"))
        self._setupSystemStorageControls(storage_layout)
        self._setupSystemStorageTable(storage_layout)
        self._setupSystemStorageActionButtons(storage_layout)
        self.systemSectionStack.addWidget(storage_frame)

    def _addSystemAudioSection(self) -> None:
        audio_frame, audio_layout = self._createSystemSection(_("Audio"))
        self._setupSystemAudioControls(audio_layout)
        self._setupSystemAudioTables(audio_layout)
        self._setupSystemAudioActionButtons(audio_layout)
        self.systemSectionStack.addWidget(audio_frame)

    def _addSystemPowerSection(self) -> None:
        power_frame, power_layout = self._createSystemSection(_("Power"))
        self._setupSystemPowerActionButtons(power_layout)
        self.systemSectionStack.addWidget(power_frame)

    def _setupSystemSectionButtons(self, section_switcher_layout: QHBoxLayout) -> None:
        section_titles = ["Wi-Fi", "VPN", "Bluetooth", _("Storage"), _("Audio"), _("Power")]
        for index, section_title in enumerate(section_titles):
            button = AutoSizeButton(section_title)
            button.setCheckable(True)
            button.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
            button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setProperty("sound_event", False)
            button.clicked.connect(lambda _checked=False, section_index=index: self.switchSystemSection(section_index))
            self.systemSectionButtons.append(button)
            section_switcher_layout.addWidget(button)
        section_switcher_layout.addStretch()

    def _finalizeSystemTabLayout(
        self,
        layout: QVBoxLayout,
        scroll_layout: QVBoxLayout,
        scroll_widget: QWidget,
        section_switcher_layout: QHBoxLayout,
    ) -> None:
        section_switcher = section_switcher_layout.parentWidget()
        if section_switcher is None:
            return
        self.systemSectionFocusTargets = [
            self.wirelessEnabledCheckBox,
            self.vpnTable,
            self.bluetoothEnabledCheckBox,
            self.storageTable,
            self.audioSinksTable,
            self.systemRebootButton,
        ]
        self.systemSectionWifiIndex = 0
        self.systemSectionVpnIndex = 1
        self.systemSectionBluetoothIndex = 2
        self.systemSectionStorageIndex = 3
        self.systemSectionAudioIndex = 4
        self.systemSectionPowerIndex = 5
        scroll_layout.addWidget(section_switcher)
        scroll_layout.addWidget(self.systemSectionStack)
        self.switchSystemSection(0)
        scroll_layout.addStretch(1)
        self.systemScrollArea.setWidget(scroll_widget)
        layout.addWidget(self.systemScrollArea)

    def _initializeSystemTabState(self) -> None:
        self.networkRows = []
        self.vpnRows = []
        self.networkPasswords = {}
        self._pendingNetworkPath = ""
        self.networkWorker = None
        self.networkBusy = False
        self.systemWirelessEnabled = False
        self.bluetoothRows = []
        self.bluetoothWorker = None
        self.bluetoothBusy = False
        self.systemBluetoothEnabled = False
        self.storageRows = []
        self.storageWorker = None
        self.storageBusy = False
        self.audioSinksRows = []
        self.audioWorker = None
        self.audioBusy = False
        self.audioVolumeUpdating = False
        self.audioFocusSinkName = ""
        self.networkRetryTimer = QTimer(self)
        self.networkRetryTimer.setInterval(SYSTEM_DEVICE_RETRY_INTERVAL_MS)
        self.networkRetryTimer.timeout.connect(self.loadSystemNetworks)
        self.networkRetryCount = 0
        self.bluetoothRetryTimer = QTimer(self)
        self.bluetoothRetryTimer.setInterval(SYSTEM_DEVICE_RETRY_INTERVAL_MS)
        self.bluetoothRetryTimer.timeout.connect(self.loadSystemBluetoothDevices)
        self.bluetoothRetryCount = 0

    def _startSystemBackgroundTasks(self) -> None:
        self.system_tab_index = self.stackedWidget.addWidget(self.systemWidget)
        QTimer.singleShot(0, self.loadSystemNetworks)
        QTimer.singleShot(0, self.loadSystemBluetoothDevices)
        QTimer.singleShot(0, self.loadSystemStorageDevices)
        QTimer.singleShot(0, self.loadSystemAudioDevices)

    def switchSystemSection(self, index: int) -> bool:
        if not hasattr(self, "systemSectionStack"):
            return False
        if index < 0 or index >= self.systemSectionStack.count():
            return False
        if index < len(self.systemSectionButtons) and not self.systemSectionButtons[index].isVisible():
            return False
        previous_index = self.systemSectionStack.currentIndex()
        self.systemSectionStack.setCurrentIndex(index)
        if previous_index != index:
            SoundManager().play("tab_switch")
        for button_index, button in enumerate(self.systemSectionButtons):
            button.setChecked(button_index == index)
        self._focusCurrentSystemSection(index)
        update_hints = getattr(self, "updateControlHints", None)
        if callable(update_hints):
            update_hints()
        return True

    def switchSystemSectionRelative(self, step: int) -> bool:
        if not step:
            return False
        if not hasattr(self, "systemSectionStack"):
            return False
        visible_indices = self._getVisibleSystemSectionIndices()
        if not visible_indices:
            return False
        current_index = self.systemSectionStack.currentIndex()
        if current_index not in visible_indices:
            return self.switchSystemSection(visible_indices[0])
        current_pos = visible_indices.index(current_index)
        next_pos = (current_pos + step) % len(visible_indices)
        return self.switchSystemSection(visible_indices[next_pos])

    def _getVisibleSystemSectionIndices(self) -> list[int]:
        if not hasattr(self, "systemSectionButtons"):
            return []
        return [index for index, button in enumerate(self.systemSectionButtons) if button.isVisible()]

    def _setSystemSectionVisible(self, index: int, visible: bool) -> None:
        if not hasattr(self, "systemSectionButtons") or not hasattr(self, "systemSectionStack"):
            return
        if index < 0 or index >= len(self.systemSectionButtons):
            return
        button = self.systemSectionButtons[index]
        section_widget = self.systemSectionStack.widget(index)
        button.setVisible(visible)
        if section_widget is not None:
            section_widget.setVisible(visible)
        if not visible and self.systemSectionStack.currentIndex() == index:
            self._switchToFirstVisibleSystemSection()

    def _switchToFirstVisibleSystemSection(self) -> None:
        visible_indices = self._getVisibleSystemSectionIndices()
        if not visible_indices:
            return
        self.switchSystemSection(visible_indices[0])

    def _focusCurrentSystemSection(self, index: int) -> None:
        if not hasattr(self, "systemSectionFocusTargets"):
            return
        if index < 0 or index >= len(self.systemSectionFocusTargets):
            return
        target = self.systemSectionFocusTargets[index]
        if target is not None and target.isVisible() and target.isEnabled():
            target.setFocus(Qt.FocusReason.OtherFocusReason)
            if hasattr(self, "systemScrollArea"):
                self.systemScrollArea.ensureWidgetVisible(target)
            return
        if index < len(self.systemSectionButtons):
            self.systemSectionButtons[index].setFocus(Qt.FocusReason.OtherFocusReason)

    def _createSystemSection(self, title_text: str) -> tuple[QFrame, QVBoxLayout]:
        section_frame = QFrame()
        section_frame.setProperty("theme_style_name", "SETTINGS_FRAME_STYLE")
        section_frame.setStyleSheet(self.theme.SETTINGS_FRAME_STYLE)
        section_layout = QVBoxLayout(section_frame)
        section_layout.setContentsMargins(15, 15, 15, 15)
        section_layout.setSpacing(10)

        section_title = QLabel(title_text)
        section_title.setStyleSheet(self.theme.SETTINGS_FRAME_TITLE_STYLE)
        section_layout.addWidget(section_title)
        return section_frame, section_layout

    def _setupSystemNetworkControls(self, layout: QVBoxLayout) -> None:
        self.networkStatusLabel = QLabel("")
        self.networkStatusLabel.setStyleSheet(self.theme.CONTENT_STYLE)
        self.networkStatusLabel.setWordWrap(True)
        layout.addWidget(self.networkStatusLabel)

        self.wirelessControlsWidget = QWidget()
        wireless_layout = QHBoxLayout(self.wirelessControlsWidget)
        wireless_layout.setContentsMargins(0, 0, 0, 0)
        self.wirelessEnabledCheckBox = QCheckBox()
        self.wirelessEnabledCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.wirelessEnabledCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.wirelessEnabledCheckBox.toggled.connect(self.toggleWirelessNetworking)
        enable_text = _("Enable/Disable").split("/", maxsplit=1)[0]
        self.wirelessEnabledTitle = QLabel(enable_text + " Wi-Fi")
        self.wirelessEnabledTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.wirelessEnabledTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        wireless_layout.addWidget(self.wirelessEnabledCheckBox)
        wireless_layout.addWidget(self.wirelessEnabledTitle)
        wireless_layout.addStretch()
        layout.addWidget(self.wirelessControlsWidget)

    def _setupSystemNetworkTable(self, layout: QVBoxLayout) -> None:
        self.networkTable = QTableWidget()
        self.networkTable.setColumnCount(4)
        self.networkTable.setMinimumHeight(120)
        self.networkTable.setHorizontalHeaderLabels(
            [_("Network"), _("Security"), _("Signal"), _("State")]
        )
        self.networkTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.networkTable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.networkTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.networkTable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.networkTable.setMouseTracking(True)
        self.networkTable.setStyleSheet(
            self.theme.WINETRICKS_TABBLE_STYLE + self.theme.SCROLL_STYLE
        )
        self.networkTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.networkTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.networkTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.networkTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.networkTable.verticalHeader().setVisible(False)
        self.networkTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.networkTable.customContextMenuRequested.connect(self.showSystemNetworkContextMenu)
        self.networkTable.currentCellChanged.connect(lambda *_: self.onSystemNetworkSelectionChanged())
        self.networkTable.cellEntered.connect(lambda row, _column: self._onSystemTableHovered(self.networkTable, row))
        self.networkTable.cellDoubleClicked.connect(self.onSystemNetworkActivated)
        layout.addWidget(self.networkTable)

    def _setupSystemActionButtons(self, layout: QVBoxLayout) -> None:
        self.networkActionButtonsWidget = QWidget()
        buttons_layout = QHBoxLayout(self.networkActionButtonsWidget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.systemRefreshButton = AutoSizeButton(_("Refresh"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.systemRefreshButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.systemRefreshButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.systemRefreshButton.clicked.connect(self.loadSystemNetworks)
        buttons_layout.addWidget(self.systemRefreshButton)

        self.networkConnectButton = AutoSizeButton(_("Connect"), icon=self.theme_manager.get_icon("login", as_path=True))

        self.networkDisconnectButton = AutoSizeButton(_("Disconnect"), icon=self.theme_manager.get_icon("stop", as_path=True))

        self.networkForgetButton = AutoSizeButton(_("Forget"), icon=self.theme_manager.get_icon("delete", as_path=True))

        self.networkShareButton = AutoSizeButton(_("Share"), icon=self.theme_manager.get_icon("menu", as_path=True))
        buttons_layout.addStretch()
        layout.addWidget(self.networkActionButtonsWidget)

    def _setupSystemVpnControls(self, layout) -> None:
        self.vpnStatusLabel = QLabel("")
        self.vpnStatusLabel.setStyleSheet(self.theme.CONTENT_STYLE)
        self.vpnStatusLabel.setWordWrap(True)
        layout.addWidget(self.vpnStatusLabel)

        self.vpnTable = QTableWidget()
        self.vpnTable.setColumnCount(3)
        self.vpnTable.setMinimumHeight(120)
        self.vpnTable.setHorizontalHeaderLabels([_("Profile"), _("Type"), _("State")])
        self.vpnTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vpnTable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.vpnTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vpnTable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.vpnTable.setMouseTracking(True)
        self.vpnTable.setStyleSheet(self.theme.WINETRICKS_TABBLE_STYLE + self.theme.SCROLL_STYLE)
        self.vpnTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.vpnTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.vpnTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.vpnTable.verticalHeader().setVisible(False)
        self.vpnTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.vpnTable.customContextMenuRequested.connect(self.showSystemVpnContextMenu)
        self.vpnTable.currentCellChanged.connect(lambda *_: self.onSystemVpnSelectionChanged())
        self.vpnTable.cellEntered.connect(lambda row, _column: self._onSystemTableHovered(self.vpnTable, row))
        layout.addWidget(self.vpnTable)

        vpn_layout = QHBoxLayout()
        self.vpnConnectButton = AutoSizeButton(_("Connect"), icon=self.theme_manager.get_icon("login", as_path=True))

        self.vpnDisconnectButton = AutoSizeButton(_("Disconnect"), icon=self.theme_manager.get_icon("stop", as_path=True))

        self.vpnAddButton = AutoSizeButton(_("Add"), icon=self.theme_manager.get_icon("folder", as_path=True))
        self.vpnAddButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.vpnAddButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.vpnAddButton.clicked.connect(self.addVpnProfile)
        vpn_layout.addWidget(self.vpnAddButton)

        self.vpnDeleteButton = AutoSizeButton(_("Delete"), icon=self.theme_manager.get_icon("delete", as_path=True))
        layout.addLayout(vpn_layout)

    def _setupSystemBluetoothControls(self, layout) -> None:
        self.bluetoothStatusLabel = QLabel("")
        self.bluetoothStatusLabel.setStyleSheet(self.theme.CONTENT_STYLE)
        self.bluetoothStatusLabel.setWordWrap(True)
        layout.addWidget(self.bluetoothStatusLabel)

        bluetooth_layout = QHBoxLayout()
        self.bluetoothEnabledCheckBox = QCheckBox()
        self.bluetoothEnabledCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bluetoothEnabledCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.bluetoothEnabledCheckBox.toggled.connect(self.toggleBluetooth)
        enable_text = _("Enable/Disable").split("/", maxsplit=1)[0]
        self.bluetoothEnabledTitle = QLabel(enable_text + " Bluetooth")
        self.bluetoothEnabledTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bluetoothEnabledTitle.setStyleSheet(self.theme.SETTINGS_TITLE_CHECKBOX_STYLE)
        bluetooth_layout.addWidget(self.bluetoothEnabledCheckBox)
        bluetooth_layout.addWidget(self.bluetoothEnabledTitle)
        bluetooth_layout.addStretch()
        layout.addLayout(bluetooth_layout)

    def _setupSystemBluetoothTable(self, layout) -> None:
        self.bluetoothStackedWidget = QStackedWidget()
        self.bluetoothScanPreloader = Preloader(parent=self.bluetoothStackedWidget)
        preloader_layout = QHBoxLayout()
        preloader_layout.addStretch()
        preloader_layout.addWidget(self.bluetoothScanPreloader)
        preloader_layout.addStretch()
        preloader_widget = QWidget()
        preloader_widget.setLayout(preloader_layout)
        self.bluetoothStackedWidget.addWidget(preloader_widget)

        self.bluetoothTable = QTableWidget()
        self.bluetoothTable.setColumnCount(4)
        self.bluetoothTable.setMinimumHeight(120)
        self.bluetoothTable.setHorizontalHeaderLabels(
            [_("Device"), _("Type"), _("Battery"), _("State")]
        )
        self.bluetoothTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bluetoothTable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bluetoothTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bluetoothTable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bluetoothTable.setMouseTracking(True)
        self.bluetoothTable.setStyleSheet(
            self.theme.WINETRICKS_TABBLE_STYLE + self.theme.SCROLL_STYLE
        )
        self.bluetoothTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.bluetoothTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.bluetoothTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.bluetoothTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.bluetoothTable.verticalHeader().setVisible(False)
        self.bluetoothTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bluetoothTable.customContextMenuRequested.connect(self.showSystemBluetoothContextMenu)
        self.bluetoothTable.currentCellChanged.connect(lambda *_: self.onSystemBluetoothSelectionChanged())
        self.bluetoothTable.cellEntered.connect(lambda row, _column: self._onSystemTableHovered(self.bluetoothTable, row))
        self.bluetoothTable.cellDoubleClicked.connect(self.onSystemBluetoothActivated)

        self.bluetoothStackedWidget.addWidget(self.bluetoothTable)
        self.bluetoothStackedWidget.setCurrentWidget(self.bluetoothTable)
        layout.addWidget(self.bluetoothStackedWidget)

    def _setupSystemBluetoothActionButtons(self, layout) -> None:
        buttons_layout = QHBoxLayout()
        self.bluetoothRefreshButton = AutoSizeButton(_("Refresh"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.bluetoothRefreshButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.bluetoothRefreshButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.bluetoothRefreshButton.clicked.connect(self.loadSystemBluetoothDevices)
        buttons_layout.addWidget(self.bluetoothRefreshButton)

        self.bluetoothScanButton = AutoSizeButton(_("Scan"), icon=self.theme_manager.get_icon("search", as_path=True))
        self.bluetoothScanButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.bluetoothScanButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.bluetoothScanButton.clicked.connect(self.scanSystemBluetoothDevices)
        buttons_layout.addWidget(self.bluetoothScanButton)

        self.bluetoothConnectButton = AutoSizeButton(_("Connect"), icon=self.theme_manager.get_icon("login", as_path=True))

        self.bluetoothDisconnectButton = AutoSizeButton(_("Disconnect"), icon=self.theme_manager.get_icon("stop", as_path=True))

        self.bluetoothForgetButton = AutoSizeButton(_("Forget"), icon=self.theme_manager.get_icon("delete", as_path=True))
        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

    def _setupSystemStorageControls(self, layout) -> None:
        self.storageStatusLabel = QLabel("")
        self.storageStatusLabel.setStyleSheet(self.theme.CONTENT_STYLE)
        self.storageStatusLabel.setWordWrap(True)
        layout.addWidget(self.storageStatusLabel)

    def _setupSystemStorageTable(self, layout) -> None:
        self.storageTable = QTableWidget()
        self.storageTable.setColumnCount(6)
        self.storageTable.setMinimumHeight(120)
        self.storageTable.setHorizontalHeaderLabels(
            [_("Device"), _("Volume label"), _("Size"), _("Used"), _("Mount point"), _("State")]
        )
        self.storageTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.storageTable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.storageTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.storageTable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.storageTable.setMouseTracking(True)
        self.storageTable.setStyleSheet(
            self.theme.WINETRICKS_TABBLE_STYLE + self.theme.SCROLL_STYLE
        )
        self.storageTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.storageTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.storageTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.storageTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.storageTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.storageTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.storageTable.verticalHeader().setVisible(False)
        self.storageTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.storageTable.customContextMenuRequested.connect(self.showSystemStorageContextMenu)
        self.storageTable.currentCellChanged.connect(lambda *_: self.onSystemStorageSelectionChanged())
        self.storageTable.cellEntered.connect(lambda row, _column: self._onSystemTableHovered(self.storageTable, row))
        layout.addWidget(self.storageTable)

    def _setupSystemStorageActionButtons(self, layout) -> None:
        buttons_layout = QHBoxLayout()
        self.storageRefreshButton = AutoSizeButton(_("Refresh"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.storageRefreshButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.storageRefreshButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.storageRefreshButton.clicked.connect(self.loadSystemStorageDevices)
        buttons_layout.addWidget(self.storageRefreshButton)

        self.storageMountButton = AutoSizeButton(_("Mount"), icon=self.theme_manager.get_icon("login", as_path=True))

        self.storageUnmountButton = AutoSizeButton(_("Unmount"), icon=self.theme_manager.get_icon("stop", as_path=True))
        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

    def _setupSystemAudioControls(self, layout) -> None:
        self.audioStatusLabel = QLabel("")
        self.audioStatusLabel.setStyleSheet(self.theme.CONTENT_STYLE)
        self.audioStatusLabel.setWordWrap(True)
        layout.addWidget(self.audioStatusLabel)

        volume_layout = QHBoxLayout()
        self.audioVolumeTitle = QLabel(_("Volume"))
        self.audioVolumeTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        self.audioVolumeTitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        volume_layout.addWidget(self.audioVolumeTitle)

        self.audioVolumeSlider = QSlider(Qt.Orientation.Horizontal)
        self.audioVolumeSlider.setRange(0, AUDIO_MAX_VOLUME)
        self.audioVolumeSlider.setSingleStep(1)
        self.audioVolumeSlider.setPageStep(5)
        self.audioVolumeSlider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.audioVolumeSlider.setStyleSheet(self.theme.SLIDER_SIZE_STYLE)
        self.audioVolumeSlider.valueChanged.connect(self._onAudioVolumeChanged)
        self.audioVolumeSlider.sliderReleased.connect(self._applySelectedAudioVolume)
        volume_layout.addWidget(self.audioVolumeSlider)

        self.audioVolumeValueLabel = QLabel("100%")
        self.audioVolumeValueLabel.setStyleSheet(self.theme.SETTINGS_FRAME_TITLE_STYLE)
        self.audioVolumeValueLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        volume_layout.addWidget(self.audioVolumeValueLabel)
        layout.addLayout(volume_layout)

    def _setupSystemAudioTables(self, layout) -> None:
        self._setupSystemAudioSinks(layout)

    def _setupSystemAudioSinks(self, layout) -> None:
        sinks_title = QLabel(_("Playback devices"))
        sinks_title.setStyleSheet(self.theme.SETTINGS_FRAME_TITLE_STYLE)
        layout.addWidget(sinks_title)
        self.audioSinksTable = self._createSystemAudioDeviceTable([_("Output"), _("State")])
        self.audioSinksTable.itemSelectionChanged.connect(self.onSystemAudioSelectionChanged)
        self.audioSinksTable.cellEntered.connect(self.onSystemAudioSinkHovered)
        layout.addWidget(self.audioSinksTable)

    def _createSystemAudioDeviceTable(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setMinimumHeight(120)
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.setMouseTracking(True)
        table.setStyleSheet(self.theme.WINETRICKS_TABBLE_STYLE + self.theme.SCROLL_STYLE)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        if len(headers) > 1:
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        if len(headers) > 2:
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        return table

    def _setupSystemAudioActionButtons(self, layout) -> None:
        buttons_layout = QHBoxLayout()
        self.audioRefreshButton = AutoSizeButton(_("Refresh"), icon=self.theme_manager.get_icon("update", as_path=True))
        self.audioRefreshButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.audioRefreshButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.audioRefreshButton.clicked.connect(self.loadSystemAudioDevices)
        buttons_layout.addWidget(self.audioRefreshButton)

        self.audioSetOutputButton = AutoSizeButton(_("Set output"), icon=self.theme_manager.get_icon("login", as_path=True))
        self.audioSetOutputButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.audioSetOutputButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.audioSetOutputButton.clicked.connect(self.setSelectedAudioSinkDefault)
        buttons_layout.addWidget(self.audioSetOutputButton)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

    def _createSystemContextMenu(self) -> QMenu:
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(self.theme.CONTEXT_MENU_STYLE)
        menu.setParent(self, Qt.WindowType.Popup)
        return menu

    def _addSystemMenuAction(self, menu: QMenu, icon_name: str, text: str) -> QAction:
        raw_icon = self.theme_manager.get_icon(icon_name)
        icon = raw_icon if isinstance(raw_icon, QIcon) else QIcon(raw_icon) if isinstance(raw_icon, str) else QIcon()
        action = menu.addAction(icon, text)
        return action

    def _resolveSystemContextGlobalPos(self, table: QTableWidget, pos: QPoint) -> QPoint:
        if pos.isNull():
            current_row = table.currentRow()
            if current_row >= 0:
                item = table.item(current_row, 0)
                if item is not None:
                    pos = table.visualItemRect(item).center()
                else:
                    pos = table.viewport().rect().center()
            else:
                pos = table.viewport().rect().center()
        return table.viewport().mapToGlobal(pos)

    def _onSystemTableHovered(self, table: QTableWidget, row: int) -> None:
        if row < 0:
            return
        if row >= table.rowCount():
            return
        table.setCurrentCell(row, 0)

    def showSystemNetworkContextMenu(self, pos: QPoint = QPoint()) -> None:
        menu = self._createSystemContextMenu()
        connect_action = self._addSystemMenuAction(menu, "login", _("Connect"))
        disconnect_action = self._addSystemMenuAction(menu, "stop", _("Disconnect"))
        forget_action = self._addSystemMenuAction(menu, "delete", _("Forget"))
        share_action = self._addSystemMenuAction(menu, "menu", _("Share"))
        connect_action.triggered.connect(self.connectSelectedNetwork)
        disconnect_action.triggered.connect(self.disconnectSelectedNetwork)
        forget_action.triggered.connect(self.forgetSelectedNetwork)
        share_action.triggered.connect(self.shareSelectedNetworkQr)
        connect_action.setEnabled(self.networkConnectButton.isEnabled())
        disconnect_action.setEnabled(self.networkDisconnectButton.isEnabled())
        forget_action.setEnabled(self.networkForgetButton.isEnabled())
        share_action.setEnabled(self.networkShareButton.isEnabled())
        menu.exec(self._resolveSystemContextGlobalPos(self.networkTable, pos))

    def showSystemVpnContextMenu(self, pos: QPoint = QPoint()) -> None:
        menu = self._createSystemContextMenu()
        connect_action = self._addSystemMenuAction(menu, "login", _("Connect"))
        disconnect_action = self._addSystemMenuAction(menu, "stop", _("Disconnect"))
        delete_action = self._addSystemMenuAction(menu, "delete", _("Delete"))
        connect_action.triggered.connect(self.connectSelectedVpn)
        disconnect_action.triggered.connect(self.disconnectSelectedVpn)
        delete_action.triggered.connect(self.deleteSelectedVpn)
        connect_action.setEnabled(self.vpnConnectButton.isEnabled())
        disconnect_action.setEnabled(self.vpnDisconnectButton.isEnabled())
        delete_action.setEnabled(self.vpnDeleteButton.isEnabled())
        menu.exec(self._resolveSystemContextGlobalPos(self.vpnTable, pos))

    def showSystemBluetoothContextMenu(self, pos: QPoint = QPoint()) -> None:
        menu = self._createSystemContextMenu()
        connect_action = self._addSystemMenuAction(menu, "login", _("Connect"))
        disconnect_action = self._addSystemMenuAction(menu, "stop", _("Disconnect"))
        forget_action = self._addSystemMenuAction(menu, "delete", _("Forget"))
        connect_action.triggered.connect(self.connectSelectedBluetoothDevice)
        disconnect_action.triggered.connect(self.disconnectSelectedBluetoothDevice)
        forget_action.triggered.connect(self.forgetSelectedBluetoothDevice)
        connect_action.setEnabled(self.bluetoothConnectButton.isEnabled())
        disconnect_action.setEnabled(self.bluetoothDisconnectButton.isEnabled())
        forget_action.setEnabled(self.bluetoothForgetButton.isEnabled())
        menu.exec(self._resolveSystemContextGlobalPos(self.bluetoothTable, pos))

    def showSystemStorageContextMenu(self, pos: QPoint = QPoint()) -> None:
        menu = self._createSystemContextMenu()
        mount_action = self._addSystemMenuAction(menu, "login", _("Mount"))
        unmount_action = self._addSystemMenuAction(menu, "stop", _("Unmount"))
        mount_action.triggered.connect(self.mountSelectedStorageDevice)
        unmount_action.triggered.connect(self.unmountSelectedStorageDevice)
        mount_action.setEnabled(self.storageMountButton.isEnabled())
        unmount_action.setEnabled(self.storageUnmountButton.isEnabled())
        menu.exec(self._resolveSystemContextGlobalPos(self.storageTable, pos))

    def _systemTableActionHandlers(self) -> dict[QTableWidget, dict[str, Callable[[], None]]]:
        return {
            self.networkTable: {
                "confirm": self.connectSelectedNetwork,
                "back": self.disconnectSelectedNetwork,
                "prev_dir": self.loadSystemNetworks,
                "add_game": self.loadSystemNetworks,
            },
            self.vpnTable: {
                "confirm": self.connectSelectedVpn,
                "back": self.disconnectSelectedVpn,
                "add_game": self.addVpnProfile,
            },
            self.bluetoothTable: {
                "confirm": self.connectSelectedBluetoothDevice,
                "back": self.forgetSelectedBluetoothDevice,
                "prev_dir": self.scanSystemBluetoothDevices,
                "add_game": self._toggleBluetoothFromGamepad,
            },
            self.storageTable: {
                "confirm": self.mountSelectedStorageDevice,
                "back": self.unmountSelectedStorageDevice,
            },
            self.audioSinksTable: {
                "confirm": self.setSelectedAudioSinkDefault,
                "prev_dir": self.loadSystemAudioDevices,
            },
        }

    def handleSystemTableGamepadAction(self, table: QTableWidget, action: str) -> bool:
        if self.stackedWidget.currentIndex() != getattr(self, "system_tab_index", -1):
            return False
        handler = self._systemTableActionHandlers().get(table, {}).get(action)
        if handler is None:
            return False
        handler()
        return True

    def _toggleSystemCheckBox(self, checkbox: QCheckBox) -> bool:
        if not checkbox.isVisible() or not checkbox.isEnabled():
            return False
        checkbox.toggle()
        return True

    def _toggleBluetoothFromGamepad(self) -> None:
        self._toggleSystemCheckBox(self.bluetoothEnabledCheckBox)

    def handleSystemGamepadAction(self, action: str) -> bool:
        if self.stackedWidget.currentIndex() != getattr(self, "system_tab_index", -1):
            return False
        if action != "add_game" or not hasattr(self, "systemSectionStack"):
            return False
        section_index = self.systemSectionStack.currentIndex()
        if section_index == self.systemSectionWifiIndex:
            return self._toggleSystemCheckBox(self.wirelessEnabledCheckBox)
        if section_index == self.systemSectionVpnIndex:
            self.addVpnProfile()
            return True
        if section_index == self.systemSectionBluetoothIndex:
            return self._toggleSystemCheckBox(self.bluetoothEnabledCheckBox)
        return False

    def _setupSystemPowerActionButtons(self, layout) -> None:
        buttons_layout = QHBoxLayout()

        return_command = os.getenv(RETURN_TO_DESKTOP_ENV, "").strip()
        if return_command:
            self.systemReturnToDesktopButton = AutoSizeButton(
                _("Return to desktop"), icon=self.theme_manager.get_icon("exit", as_path=True)
            )
            self.systemReturnToDesktopButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
            self.systemReturnToDesktopButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            self.systemReturnToDesktopButton.clicked.connect(self.returnToDesktop)
            buttons_layout.addWidget(self.systemReturnToDesktopButton)

        self.systemLogoutButton = AutoSizeButton(_("Logout"), icon=self.theme_manager.get_icon("exit", as_path=True))
        self.systemLogoutButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.systemLogoutButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.systemLogoutButton.clicked.connect(self.logoutSystem)
        buttons_layout.addWidget(self.systemLogoutButton)

        self.systemRebootButton = AutoSizeButton(_("Reboot"), icon=self.theme_manager.get_icon("reboot", as_path=True))
        self.systemRebootButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.systemRebootButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.systemRebootButton.clicked.connect(self.rebootSystem)
        buttons_layout.addWidget(self.systemRebootButton)

        self.systemShutdownButton = AutoSizeButton(_("Shutdown"), icon=self.theme_manager.get_icon("shutdown", as_path=True))
        self.systemShutdownButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.systemShutdownButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.systemShutdownButton.clicked.connect(self.shutdownSystem)
        buttons_layout.addWidget(self.systemShutdownButton)

        self.systemSuspendButton = AutoSizeButton(_("Suspend"), icon=self.theme_manager.get_icon("suspend", as_path=True))
        self.systemSuspendButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.systemSuspendButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.systemSuspendButton.clicked.connect(self.suspendSystem)
        buttons_layout.addWidget(self.systemSuspendButton)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)
        layout.addStretch()

    def _runSystemAction(self, action: str) -> None:
        command = "systemctl" if os.path.isdir("/run/systemd/system") else "loginctl"
        if QProcess.startDetached(command, [action]):
            return
        logger.error("Failed to execute %s %s", command, action)

    def returnToDesktop(self) -> None:
        command_text = os.getenv(RETURN_TO_DESKTOP_ENV, "").strip()
        try:
            command = shlex.split(command_text)
        except ValueError as error:
            logger.error("Invalid return-to-desktop command: %s", error)
            return
        if not command:
            logger.error("Cannot return to desktop: %s is empty", RETURN_TO_DESKTOP_ENV)
            return
        if QProcess.startDetached(command[0], command[1:]):
            return
        logger.error("Failed to execute return-to-desktop command: %s", command_text)

    def rebootSystem(self) -> None:
        self._runSystemAction("reboot")

    def shutdownSystem(self) -> None:
        self._runSystemAction("poweroff")

    def suspendSystem(self) -> None:
        self._runSystemAction("suspend")

    def logoutSystem(self) -> None:
        session_id = os.getenv("XDG_SESSION_ID")
        if not session_id:
            logger.error("Cannot log out: XDG_SESSION_ID is not set")
            return
        if QProcess.startDetached("loginctl", ["terminate-session", session_id]):
            return
        logger.error("Failed to execute loginctl terminate-session %s", session_id)

    def loadSystemNetworks(self) -> None:
        self.runNetworkOperation("load")

    def scanSystemNetworks(self) -> None:
        self.runNetworkOperation("scan")

    def toggleWirelessNetworking(self, enabled: bool) -> None:
        if self.networkBusy:
            return
        self.runNetworkOperation("toggle_wireless", enabled=enabled)

    def connectSelectedNetwork(self) -> None:
        network = self.getSelectedNetworkData()
        if not network:
            logger.info("Skip network connect: no network selected")
            return
        if not network.get("secured") or network.get("saved"):
            self.runNetworkOperation(
                "connect",
                network_path=network["path"],
                password="",
            )
            return

        network_path = network["path"]
        stored_password = self.networkPasswords.get(network_path, "")
        dialog = WifiPasswordDialog(self, network.get("ssid", ""), stored_password, self.theme)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        password = dialog.getPassword()
        self.networkPasswords[network_path] = password
        self.runNetworkOperation(
            "connect",
            network_path=network["path"],
            password=password,
        )

    def shareSelectedNetworkQr(self) -> None:
        network = self.getSelectedNetworkData()
        if not network:
            return
        ssid = network.get("ssid", "")
        if not ssid:
            return
        password = ""
        if network.get("secured"):
            network_path = network["path"]
            password = self.networkPasswords.get(network_path, "")
            if not password:
                self._fetchPasswordAndShowQr(network)
                return

        self._showWifiQr(ssid, password, network)

    def _fetchPasswordAndShowQr(self, network: dict) -> None:
        if self.isNetworkWorkerRunning():
            return
        self._pendingNetworkPath = network["path"]
        self.setNetworkBusy(True)
        self.networkWorker = NetworkManagerWorker("get_password", {"ssid": network["ssid"]}, self)
        self.networkWorker.operation_finished.connect(self._onPasswordLoadedForQr)
        self.networkWorker.operation_failed.connect(self._onPasswordLoadFailedForQr)
        self.networkWorker.finished.connect(self.onNetworkWorkerFinished)
        self.networkWorker.start()

    def _onPasswordLoadedForQr(self, operation: str, payload: dict) -> None:
        password = payload.get("password", "")
        if password:
            self.networkPasswords[self._pendingNetworkPath] = password
            network = self.getSelectedNetworkData()
            if network:
                self._showWifiQr(network["ssid"], password, network)
        else:
            logger.warning("Saved password is empty")
        self.setNetworkBusy(False)

    def _onPasswordLoadFailedForQr(self, operation: str, error: str) -> None:
        self.setNetworkBusy(False)
        logger.warning("Failed to load saved password: %s", error)

    def _showWifiQr(self, ssid: str, password: str, network: dict) -> None:
        security = self._resolveWifiQrSecurity(network)
        payload = self._buildWifiQrPayload(ssid, security, password)
        qr_pixmap = self._createWifiQrPixmap(payload)
        if qr_pixmap is None or qr_pixmap.isNull():
            logger.warning("Failed to generate QR")
            return

        dialog = DraggableDialog(self)
        dialog.setWindowTitle("QR")
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(12, 12, 12, 12)
        qr_label = QLabel(dialog)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(
            qr_pixmap.scaled(
                260,
                260,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        dialog_layout.addWidget(qr_label)
        dialog.exec()

    def _resolveWifiQrSecurity(self, network: dict) -> str:
        security = str(network.get("security", "")).upper()
        if not network.get("secured"):
            return "nopass"
        if "WEP" in security:
            return "WEP"
        return "WPA"

    def _buildWifiQrPayload(self, ssid: str, security: str, password: str) -> str:
        safe_ssid = ssid.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        safe_password = password.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        return f"WIFI:T:{security};S:{safe_ssid};P:{safe_password};;"

    def _createWifiQrPixmap(self, payload: str) -> QPixmap | None:
        try:
            import io
            import qrcode
        except ImportError:
            return None
        try:
            qr_code = qrcode.QRCode(box_size=8, border=2)
            qr_code.add_data(payload)
            qr_code.make(fit=True)
            image_obj = qr_code.make_image(fill_color="black", back_color="white")
            image = cast(Any, image_obj).convert("RGB")
            image_bytes = io.BytesIO()
            image.save(image_bytes, format="PNG")
            qr_pixmap = QPixmap()
            qr_pixmap.loadFromData(image_bytes.getvalue())
            self._applyPortProtonLogoToQr(qr_pixmap)
            return qr_pixmap
        except Exception as exc:
            logger.exception("Failed to build Wi-Fi QR pixmap: %s", exc)
            return None

    def _applyPortProtonLogoToQr(self, qr_pixmap: QPixmap) -> None:
        if qr_pixmap.isNull():
            return
        logo_icon = self.theme_manager.get_icon("badge_portproton")
        if logo_icon is None or logo_icon.isNull():
            return

        qr_size = min(qr_pixmap.width(), qr_pixmap.height())
        logo_size = max(24, int(qr_size * 0.18))
        src_pixmap = logo_icon.pixmap(logo_size, logo_size)
        if src_pixmap is None or src_pixmap.isNull():
            return

        black_pixmap = QPixmap(logo_size, logo_size)
        black_pixmap.fill(Qt.GlobalColor.transparent)
        icon_painter = QPainter(black_pixmap)
        icon_painter.drawPixmap(0, 0, src_pixmap)
        icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        icon_painter.fillRect(black_pixmap.rect(), Qt.GlobalColor.black)
        icon_painter.end()

        painter = QPainter(qr_pixmap)
        x = (qr_pixmap.width() - logo_size) // 2
        y = (qr_pixmap.height() - logo_size) // 2
        padding = 4
        painter.fillRect(
            x - padding,
            y - padding,
            logo_size + padding * 2,
            logo_size + padding * 2,
            Qt.GlobalColor.white,
        )
        painter.drawPixmap(x, y, black_pixmap)
        painter.end()

    def disconnectSelectedNetwork(self) -> None:
        network = self.getSelectedNetworkData()
        network_path = network["path"] if network else ""
        self.runNetworkOperation("disconnect", network_path=network_path)

    def forgetSelectedNetwork(self) -> None:
        network = self.getSelectedNetworkData()
        if not network:
            logger.info("Skip network forget: no network selected")
            return
        self.runNetworkOperation(
            "forget",
            ssid=network["ssid"],
            network_path=network["path"],
        )

    def connectSelectedVpn(self) -> None:
        vpn = self.getSelectedVpnData()
        if not vpn:
            logger.info("Skip VPN connect: no VPN selected")
            return
        self.runNetworkOperation("connect_vpn", connection_path=vpn["path"])

    def disconnectSelectedVpn(self) -> None:
        vpn = self.getSelectedVpnData()
        if not vpn:
            logger.info("Skip VPN disconnect: no VPN selected")
            return
        self.runNetworkOperation("disconnect_vpn", connection_path=vpn["path"])

    def addVpnProfile(self) -> None:
        file_explorer = FileExplorer(
            self,
            theme=self.theme,
            file_filter=(".ovpn", ".conf"),
            initial_path=os.path.expanduser("~"),
        )
        file_explorer.file_signal.file_selected.connect(
            lambda file_path: self.runNetworkOperation("add_vpn", file_path=os.path.normpath(file_path))
        )
        file_explorer.exec()

    def deleteSelectedVpn(self) -> None:
        vpn = self.getSelectedVpnData()
        if not vpn:
            logger.info("Skip VPN delete: no VPN selected")
            return
        self.runNetworkOperation("delete_vpn", connection_path=vpn["path"])

    def onSystemNetworkActivated(self, _row: int, _column: int) -> None:
        self.connectSelectedNetwork()

    def getSelectedNetworkData(self) -> dict | None:
        current_row = self.networkTable.currentRow()
        if current_row < 0 or current_row >= len(self.networkRows):
            return None
        return self.networkRows[current_row]

    def getSelectedVpnData(self) -> dict | None:
        current_row = self.vpnTable.currentRow()
        if current_row < 0 or current_row >= len(self.vpnRows):
            return None
        return self.vpnRows[current_row]

    def runNetworkOperation(self, operation: str, **params: Any) -> None:
        if self.isNetworkWorkerRunning():
            return

        self.setNetworkBusy(True)
        self.networkWorker = NetworkManagerWorker(operation, params, self)
        self.networkWorker.operation_finished.connect(self.onNetworkOperationFinished)
        self.networkWorker.operation_failed.connect(self.onNetworkOperationFailed)
        self.networkWorker.finished.connect(self.onNetworkWorkerFinished)
        self.networkWorker.start()

    def isNetworkWorkerRunning(self) -> bool:
        worker = getattr(self, "networkWorker", None)
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            self.networkWorker = None
            return False

    def onNetworkWorkerFinished(self) -> None:
        worker = getattr(self, "networkWorker", None)
        self.networkWorker = None
        if worker is None:
            return
        try:
            worker.deleteLater()
        except RuntimeError:
            return

    def onNetworkOperationFinished(self, operation: str, payload: dict) -> None:
        self.networkRows = payload.get("networks", [])
        self.vpnRows = payload.get("vpns", [])
        self.populateSystemNetworks(payload)
        self.setNetworkBusy(False)
        if payload.get("available"):
            self.networkRetryTimer.stop()
            self.networkRetryCount = 0
        elif operation == "load" and self.networkRetryCount < SYSTEM_DEVICE_RETRY_LIMIT:
            self.networkRetryCount += 1
            self.networkRetryTimer.start()
        elif operation == "load":
            self.networkRetryTimer.stop()
        if operation == "scan":
            logger.info("Network scan finished: wifi_networks=%d", len(self.networkRows))
        elif operation == "load":
            logger.info(
                "Network list updated: wifi_networks=%d vpn_profiles=%d",
                len(self.networkRows),
                len(self.vpnRows),
            )

    def onNetworkOperationFailed(self, operation: str, error_text: str) -> None:
        self.setNetworkBusy(False)
        logger.warning("Network operation failed: %s", error_text)
        if operation == "load" and self.networkRetryCount < SYSTEM_DEVICE_RETRY_LIMIT:
            self.networkRetryCount += 1
            self.networkRetryTimer.start()
        elif operation == "load":
            self.networkRetryTimer.stop()
        self.networkStatusLabel.setText("Error")
        self.wirelessEnabledCheckBox.blockSignals(True)
        self.wirelessEnabledCheckBox.setChecked(self.systemWirelessEnabled)
        self.wirelessEnabledCheckBox.blockSignals(False)

    def populateSystemNetworks(self, payload: dict) -> None:
        self._setSystemSectionVisible(self.systemSectionWifiIndex, bool(payload.get("available")))
        if not payload.get("available") and self.systemSectionStack.currentIndex() == self.systemSectionWifiIndex:
            self.switchSystemSection(self.systemSectionVpnIndex)
        self.systemWirelessEnabled = payload.get("wireless_enabled", False)
        self.wirelessEnabledCheckBox.blockSignals(True)
        self.wirelessEnabledCheckBox.setChecked(self.systemWirelessEnabled)
        self.wirelessEnabledCheckBox.blockSignals(False)
        if not payload.get("available"):
            self.networkStatusLabel.setText("NetworkManager Wi-Fi device not found")
            self.networkStatusLabel.setVisible(False)
            self.wirelessControlsWidget.setVisible(False)
            self.networkTable.setVisible(False)
            self.networkActionButtonsWidget.setVisible(False)
            self.networkTable.setRowCount(0)
            self.updateSystemNetworkButtons(None, payload.get("wireless_enabled", False))
        else:
            self.networkSectionFrame.setVisible(True)
            self.networkStatusLabel.setVisible(True)
            self.wirelessControlsWidget.setVisible(True)
            self.networkTable.setVisible(True)
            self.networkActionButtonsWidget.setVisible(True)
            device_name = payload.get("device_name", "")
            network_count = len(self.networkRows)
            self.networkStatusLabel.clear()
            logger.info("Wi-Fi adapter: %s. Networks found: %d", device_name, network_count)
            self.networkTable.setRowCount(network_count)
            for row, network in enumerate(self.networkRows):
                self._setSystemNetworkRow(row, network)
            if network_count > 0:
                self.networkTable.setCurrentCell(0, 0)
            self.onSystemNetworkSelectionChanged()

        self.populateSystemVpns()

    def _setSystemNetworkRow(self, row: int, network: dict) -> None:
        values = [
            network["ssid"],
            network["security"],
            f'{network["strength"]}%',
            network["state"],
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.networkTable.setItem(row, column, item)

    def onSystemNetworkSelectionChanged(self) -> None:
        network = self.getSelectedNetworkData()
        wireless_enabled = self.wirelessEnabledCheckBox.isChecked()
        self.updateSystemNetworkButtons(network, wireless_enabled)

    def updateSystemNetworkButtons(self, network: dict | None, wireless_enabled: bool) -> None:
        has_network = network is not None
        can_connect = bool(has_network and wireless_enabled and not network["active"])
        can_disconnect = bool(has_network and network["active"])
        can_forget = bool(has_network and network["saved"])
        can_share = bool(has_network and (network["saved"] or network["active"] or not network["secured"]))
        self.networkConnectButton.setEnabled(can_connect and not self.networkBusy)
        self.networkDisconnectButton.setEnabled(can_disconnect and not self.networkBusy)
        self.networkForgetButton.setEnabled(can_forget and not self.networkBusy)
        self.networkShareButton.setEnabled(can_share and not self.networkBusy)

    def setNetworkBusy(self, busy: bool) -> None:
        self.networkBusy = busy
        for widget in (
            self.wirelessEnabledCheckBox,
            self.systemRefreshButton,
            self.networkShareButton,
            self.vpnConnectButton,
            self.vpnDisconnectButton,
            self.vpnAddButton,
            self.vpnDeleteButton,
        ):
            widget.setEnabled(not busy)
        self.onSystemNetworkSelectionChanged()
        self.onSystemVpnSelectionChanged()

    def populateSystemVpns(self) -> None:
        vpn_count = len(self.vpnRows)
        if not vpn_count:
            self.vpnStatusLabel.clear()
            logger.info("VPN profiles not found")
            self.vpnTable.setRowCount(0)
            self.updateSystemVpnButtons(None)
            return

        self.vpnStatusLabel.clear()
        logger.info("VPN profiles found: %d", vpn_count)
        self.vpnTable.setRowCount(vpn_count)
        selected_row = 0
        for index, vpn in enumerate(self.vpnRows):
            if vpn["active"]:
                selected_row = index
            self._setSystemVpnRow(index, vpn)
        self.vpnTable.setCurrentCell(selected_row, 0)
        self.onSystemVpnSelectionChanged()

    def _setSystemVpnRow(self, row: int, vpn: dict) -> None:
        values = [vpn["id"], vpn.get("vpn_type", "VPN"), vpn["state"]]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            self.vpnTable.setItem(row, column, item)

    def onSystemVpnSelectionChanged(self) -> None:
        self.updateSystemVpnButtons(self.getSelectedVpnData())

    def updateSystemVpnButtons(self, vpn: dict | None) -> None:
        has_vpn = vpn is not None
        can_connect = bool(has_vpn and not vpn["active"])
        can_disconnect = bool(has_vpn and vpn["active"])
        can_delete = bool(has_vpn)
        self.vpnConnectButton.setEnabled(can_connect and not self.networkBusy)
        self.vpnDisconnectButton.setEnabled(can_disconnect and not self.networkBusy)
        self.vpnDeleteButton.setEnabled(can_delete and not self.networkBusy)

    def loadSystemBluetoothDevices(self) -> None:
        self.runBluetoothOperation("load")

    def scanSystemBluetoothDevices(self) -> None:
        self.runBluetoothOperation("scan")

    def _setBluetoothScanPreloaderVisible(self, visible: bool) -> None:
        if not hasattr(self, "bluetoothStackedWidget"):
            return
        if visible:
            self.bluetoothStackedWidget.setCurrentIndex(0)  # Preloader widget
            return
        self.bluetoothStackedWidget.setCurrentWidget(self.bluetoothTable)

    def toggleBluetooth(self, enabled: bool) -> None:
        if self.bluetoothBusy:
            return
        self.runBluetoothOperation("toggle_bluetooth", enabled=enabled)

    def connectSelectedBluetoothDevice(self) -> None:
        device = self.getSelectedBluetoothDeviceData()
        if not device:
            logger.info("Skip Bluetooth connect: no device selected")
            return
        self.runBluetoothOperation("connect", address=device["address"])

    def disconnectSelectedBluetoothDevice(self) -> None:
        device = self.getSelectedBluetoothDeviceData()
        address = device["address"] if device else ""
        self.runBluetoothOperation("disconnect", address=address)

    def forgetSelectedBluetoothDevice(self) -> None:
        device = self.getSelectedBluetoothDeviceData()
        if not device:
            logger.info("Skip Bluetooth forget: no device selected")
            return
        self.runBluetoothOperation("forget", address=device["address"])

    def onSystemBluetoothActivated(self, _row: int, _column: int) -> None:
        self.connectSelectedBluetoothDevice()

    def getSelectedBluetoothDeviceData(self) -> dict | None:
        current_row = self.bluetoothTable.currentRow()
        if current_row < 0 or current_row >= len(self.bluetoothRows):
            return None
        return self.bluetoothRows[current_row]

    def runBluetoothOperation(self, operation: str, **params) -> None:
        if self.isBluetoothWorkerRunning():
            return

        self._setBluetoothScanPreloaderVisible(operation == "scan")
        self.setBluetoothBusy(True)
        self.bluetoothWorker = BluetoothManagerWorker(operation, params, self)
        self.bluetoothWorker.operation_finished.connect(self.onBluetoothOperationFinished)
        self.bluetoothWorker.operation_failed.connect(self.onBluetoothOperationFailed)
        self.bluetoothWorker.pairing_requested.connect(self.onBluetoothPairingRequested)
        self.bluetoothWorker.finished.connect(self.onBluetoothWorkerFinished)
        self.bluetoothWorker.start()

    def isBluetoothWorkerRunning(self) -> bool:
        worker = getattr(self, "bluetoothWorker", None)
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            self.bluetoothWorker = None
            return False

    def onBluetoothWorkerFinished(self) -> None:
        worker = getattr(self, "bluetoothWorker", None)
        self.bluetoothWorker = None
        if worker is None:
            return
        try:
            worker.deleteLater()
        except RuntimeError:
            return

    def onBluetoothOperationFinished(self, operation: str, payload: dict) -> None:
        self._setBluetoothScanPreloaderVisible(False)
        self.bluetoothRows = payload.get("devices", [])
        self.populateSystemBluetoothDevices(payload)
        self.setBluetoothBusy(False)
        if payload.get("available"):
            self.bluetoothRetryTimer.stop()
            self.bluetoothRetryCount = 0
        elif operation == "load" and self.bluetoothRetryCount < SYSTEM_DEVICE_RETRY_LIMIT:
            self.bluetoothRetryCount += 1
            self.bluetoothRetryTimer.start()
        elif operation == "load":
            self.bluetoothRetryTimer.stop()
        if operation != "load":
            QTimer.singleShot(800, self.loadSystemBluetoothDevices)
        if operation == "scan":
            logger.info("Bluetooth scan finished: devices=%d", len(self.bluetoothRows))
        elif operation == "load":
            logger.info("Bluetooth list updated: devices=%d", len(self.bluetoothRows))

    def onBluetoothOperationFailed(self, operation: str, error_text: str) -> None:
        self._setBluetoothScanPreloaderVisible(False)
        self.setBluetoothBusy(False)
        cleaned_error = error_text.strip()
        if cleaned_error:
            logger.warning("Bluetooth operation failed: %s", cleaned_error)
            self.bluetoothStatusLabel.setText("Error")
        else:
            logger.info("Bluetooth operation finished without actionable error text")
        if operation == "load":
            self.bluetoothRows = []
            self.bluetoothTable.setRowCount(0)
            self._setSystemSectionVisible(self.systemSectionBluetoothIndex, False)
            if self.bluetoothRetryCount < SYSTEM_DEVICE_RETRY_LIMIT:
                self.bluetoothRetryCount += 1
                self.bluetoothRetryTimer.start()
            else:
                self.bluetoothRetryTimer.stop()
        self.bluetoothEnabledCheckBox.blockSignals(True)
        self.bluetoothEnabledCheckBox.setChecked(self.systemBluetoothEnabled)
        self.bluetoothEnabledCheckBox.blockSignals(False)

    def onBluetoothPairingRequested(self, request: dict) -> None:
        worker = getattr(self, "bluetoothWorker", None)
        if worker is None:
            return
        if request.get("kind") == "display":
            worker.submit_pairing_response("ok")
            return
        if request.get("kind") == "confirm":
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(request.get("title", _("Bluetooth pairing")))
            msg_box.setText(request.get("message", ""))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg_box.button(QMessageBox.StandardButton.Yes).setText(_("Yes"))
            msg_box.button(QMessageBox.StandardButton.No).setText(_("No"))
            button = msg_box.exec()
            worker.submit_pairing_response("yes" if button == QMessageBox.StandardButton.Yes else "no")
            return

        text, accepted = QInputDialog.getText(
            self,
            request.get("title", _("Bluetooth pairing")),
            request.get("message", ""),
        )
        worker.submit_pairing_response(text if accepted else "")

    def populateSystemBluetoothDevices(self, payload: dict) -> None:
        self._setSystemSectionVisible(self.systemSectionBluetoothIndex, bool(payload.get("available")))
        self.systemBluetoothEnabled = payload.get("powered", False)
        self.bluetoothEnabledCheckBox.blockSignals(True)
        self.bluetoothEnabledCheckBox.setChecked(self.systemBluetoothEnabled)
        self.bluetoothEnabledCheckBox.blockSignals(False)
        if not payload.get("available"):
            self.bluetoothStatusLabel.setText("Bluetooth adapter not found")
            self.bluetoothTable.setRowCount(0)
            self.updateSystemBluetoothButtons(None, payload.get("powered", False))
            return

        adapter_name = payload.get("adapter_name", "")
        device_count = len(self.bluetoothRows)
        self.bluetoothStatusLabel.clear()
        logger.info("Bluetooth adapter: %s. Devices found: %d", adapter_name, device_count)
        self.bluetoothTable.setRowCount(device_count)
        for row, device in enumerate(self.bluetoothRows):
            self._setSystemBluetoothRow(row, device)
        if device_count > 0:
            self.bluetoothTable.setCurrentCell(0, 0)
        self.onSystemBluetoothSelectionChanged()

    def _setSystemBluetoothRow(self, row: int, device: dict) -> None:
        values = [
            device["name"],
            device["icon"] or _("Unknown"),
            device["battery"] or "—",
            device["state"],
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bluetoothTable.setItem(row, column, item)

    def onSystemBluetoothSelectionChanged(self) -> None:
        device = self.getSelectedBluetoothDeviceData()
        bluetooth_enabled = self.bluetoothEnabledCheckBox.isChecked()
        self.updateSystemBluetoothButtons(device, bluetooth_enabled)

    def updateSystemBluetoothButtons(self, device: dict | None, bluetooth_enabled: bool) -> None:
        has_device = device is not None
        can_connect = bool(has_device and bluetooth_enabled and not device["connected"])
        can_disconnect = bool(has_device and device["connected"])
        can_forget = bool(has_device and (device["paired"] or device["trusted"]))
        self.bluetoothConnectButton.setEnabled(can_connect and not self.bluetoothBusy)
        self.bluetoothDisconnectButton.setEnabled(can_disconnect and not self.bluetoothBusy)
        self.bluetoothForgetButton.setEnabled(can_forget and not self.bluetoothBusy)

    def setBluetoothBusy(self, busy: bool) -> None:
        self.bluetoothBusy = busy
        for widget in (
            self.bluetoothEnabledCheckBox,
            self.bluetoothRefreshButton,
            self.bluetoothScanButton,
        ):
            widget.setEnabled(not busy)
        self.onSystemBluetoothSelectionChanged()

    def loadSystemStorageDevices(self) -> None:
        self.runStorageOperation("load")

    def mountSelectedStorageDevice(self) -> None:
        device = self.getSelectedStorageDeviceData()
        if not device:
            logger.info("Skip storage mount: no device selected")
            return
        self.runStorageOperation("mount", device_path=device["path"])

    def unmountSelectedStorageDevice(self) -> None:
        device = self.getSelectedStorageDeviceData()
        if not device:
            logger.info("Skip storage unmount: no device selected")
            return
        self.runStorageOperation("unmount", device_path=device["path"])

    def getSelectedStorageDeviceData(self) -> dict | None:
        current_row = self.storageTable.currentRow()
        if current_row < 0 or current_row >= len(self.storageRows):
            return None
        return self.storageRows[current_row]

    def runStorageOperation(self, operation: str, **params) -> None:
        if self.isStorageWorkerRunning():
            return

        self.setStorageBusy(True)
        self.storageWorker = StorageManagerWorker(operation, params, self)
        self.storageWorker.operation_finished.connect(self.onStorageOperationFinished)
        self.storageWorker.operation_failed.connect(self.onStorageOperationFailed)
        self.storageWorker.finished.connect(self.onStorageWorkerFinished)
        self.storageWorker.start()

    def isStorageWorkerRunning(self) -> bool:
        worker = getattr(self, "storageWorker", None)
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            self.storageWorker = None
            return False

    def onStorageWorkerFinished(self) -> None:
        worker = getattr(self, "storageWorker", None)
        self.storageWorker = None
        if worker is None:
            return
        try:
            worker.deleteLater()
        except RuntimeError:
            return

    def onStorageOperationFinished(self, operation: str, payload: dict) -> None:
        self.storageRows = payload.get("devices", [])
        self.populateSystemStorageDevices(payload)
        self.setStorageBusy(False)
        if operation == "load":
            logger.info("Storage list updated: devices=%d", len(self.storageRows))

    def onStorageOperationFailed(self, _operation: str, error_text: str) -> None:
        self.setStorageBusy(False)
        logger.warning("Storage operation failed: %s", error_text)
        self.storageStatusLabel.setText("Error")

    def populateSystemStorageDevices(self, payload: dict) -> None:
        if not payload.get("available"):
            self.storageStatusLabel.setText("Storage management is not available")
            self.storageTable.setRowCount(0)
            self.updateSystemStorageButtons(None)
            return

        device_count = len(self.storageRows)
        self.storageStatusLabel.clear()
        logger.info("Removable devices found: %d", device_count)
        self.storageTable.setRowCount(device_count)
        for row, device in enumerate(self.storageRows):
            self._setSystemStorageRow(row, device)
        if device_count > 0:
            self.storageTable.setCurrentCell(0, 0)
        self.onSystemStorageSelectionChanged()

    def _setSystemStorageRow(self, row: int, device: dict) -> None:
        values = [
            device["path"],
            device["label"],
            device["size"],
            device.get("used", "—"),
            device["mount_point"] or "—",
            device["state"],
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in (2, 3):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.storageTable.setItem(row, column, item)

    def onSystemStorageSelectionChanged(self) -> None:
        self.updateSystemStorageButtons(self.getSelectedStorageDeviceData())

    def updateSystemStorageButtons(self, device: dict | None) -> None:
        has_device = device is not None
        can_mount = bool(has_device and not device["mounted"])
        can_unmount = bool(has_device and device["mounted"])
        self.storageMountButton.setEnabled(can_mount and not self.storageBusy)
        self.storageUnmountButton.setEnabled(can_unmount and not self.storageBusy)

    def setStorageBusy(self, busy: bool) -> None:
        self.storageBusy = busy
        for widget in (
            self.storageRefreshButton,
        ):
            widget.setEnabled(not busy)
        self.onSystemStorageSelectionChanged()

    def loadSystemAudioDevices(self) -> None:
        self.runAudioOperation("load")

    def setSelectedAudioSinkDefault(self) -> None:
        sink = self.getSelectedAudioSinkData()
        if not sink:
            logger.info("Skip set default output: no sink selected")
            return
        self.audioFocusSinkName = str(sink.get("name", ""))
        self.runAudioOperation("set_default_sink", sink_name=sink["name"])

    def getSelectedAudioSinkData(self) -> dict | None:
        current_row = self.audioSinksTable.currentRow()
        if current_row < 0 or current_row >= len(self.audioSinksRows):
            return None
        return self.audioSinksRows[current_row]

    def _onAudioVolumeChanged(self, value: int) -> None:
        self.audioVolumeValueLabel.setText(f"{value}%")

    def _applySelectedAudioVolume(self) -> None:
        if self.audioVolumeUpdating or self.audioBusy:
            return
        sink = self.getSelectedAudioSinkData()
        if not sink:
            return
        current_volume = int(sink.get("volume", 0))
        new_volume = int(self.audioVolumeSlider.value())
        if current_volume == new_volume:
            return
        self.runAudioOperation("set_sink_volume", sink_name=sink["name"], volume=new_volume)

    def runAudioOperation(self, operation: str, **params) -> None:
        if self.isAudioWorkerRunning():
            return

        if operation != "set_sink_volume":
            self.setAudioBusy(True)
        self.audioWorker = AudioManagerWorker(operation, params, self)
        self.audioWorker.operation_finished.connect(self.onAudioOperationFinished)
        self.audioWorker.operation_failed.connect(self.onAudioOperationFailed)
        self.audioWorker.finished.connect(self.onAudioWorkerFinished)
        self.audioWorker.start()

    def isAudioWorkerRunning(self) -> bool:
        worker = getattr(self, "audioWorker", None)
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            self.audioWorker = None
            return False

    def onAudioWorkerFinished(self) -> None:
        worker = getattr(self, "audioWorker", None)
        self.audioWorker = None
        if worker is None:
            return
        try:
            worker.deleteLater()
        except RuntimeError:
            return

    def onAudioOperationFinished(self, operation: str, payload: dict) -> None:
        if operation == "set_sink_volume":
            sink = self.getSelectedAudioSinkData()
            if sink is not None:
                sink["volume"] = int(self.audioVolumeSlider.value())
            return

        self.audioSinksRows = payload.get("sinks", [])
        self.populateSystemAudioDevices(payload)
        self.setAudioBusy(False)
        if operation == "set_default_sink" and self.audioFocusSinkName:
            self._restoreAudioSinkFocusByName(self.audioFocusSinkName)
            self.audioFocusSinkName = ""
        if operation == "load":
            logger.info("Audio list updated: outputs=%d", len(self.audioSinksRows))

    def onAudioOperationFailed(self, _operation: str, error_text: str) -> None:
        self.setAudioBusy(False)
        logger.warning("Audio operation failed: %s", error_text)
        self.audioStatusLabel.setText("Error")

    def populateSystemAudioDevices(self, payload: dict) -> None:
        if not payload.get("available"):
            self.audioStatusLabel.setText(payload.get("status", "Audio management is not available"))
            self.audioSinksTable.setRowCount(0)
            self._setAudioVolumeFromSink(None)
            self.updateSystemAudioButtons(None)
            return

        self.audioStatusLabel.clear()
        logger.info("Outputs: %d", len(self.audioSinksRows))
        self._populateAudioSinksTable()
        self.onSystemAudioSelectionChanged()

    def _populateAudioSinksTable(self) -> None:
        self.audioSinksTable.setRowCount(len(self.audioSinksRows))
        default_row = 0
        for row, sink in enumerate(self.audioSinksRows):
            self._setSystemAudioSinkRow(row, sink)
            if sink.get("default"):
                default_row = row
        if self.audioSinksRows:
            self.audioSinksTable.setCurrentCell(default_row, 0)

    def _restoreAudioSinkFocusByName(self, sink_name: str) -> None:
        if not sink_name:
            return
        for row, sink in enumerate(self.audioSinksRows):
            if str(sink.get("name", "")) != sink_name:
                continue
            self.audioSinksTable.setCurrentCell(row, 0)
            self.audioSinksTable.setFocus(Qt.FocusReason.OtherFocusReason)
            return

    def _setSystemAudioSinkRow(self, row: int, sink: dict) -> None:
        state_label = _("Selected") if sink.get("default") else _("Not selected")
        values = [sink["description"], state_label]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            self.audioSinksTable.setItem(row, column, item)

    def onSystemAudioSelectionChanged(self) -> None:
        sink = self.getSelectedAudioSinkData()
        self._setAudioVolumeFromSink(sink)
        self.updateSystemAudioButtons(sink)

    def onSystemAudioSinkHovered(self, row: int, _column: int) -> None:
        self.audioSinksTable.setCurrentCell(row, 0)
        self.onSystemAudioSelectionChanged()

    def _setAudioVolumeFromSink(self, sink: dict | None) -> None:
        if self.audioVolumeSlider.isSliderDown():
            return
        volume = int(sink.get("volume", 0)) if sink else 0
        volume = max(0, min(AUDIO_MAX_VOLUME, volume))
        self.audioVolumeUpdating = True
        self.audioVolumeSlider.setValue(volume)
        self.audioVolumeUpdating = False

    def updateSystemAudioButtons(self, sink: dict | None) -> None:
        has_sink = sink is not None
        self.audioSetOutputButton.setEnabled(bool(has_sink and not sink.get("default") and not self.audioBusy))
        self.audioVolumeSlider.setEnabled(bool(has_sink))

    def setAudioBusy(self, busy: bool) -> None:
        self.audioBusy = busy
        for widget in (
            self.audioRefreshButton,
        ):
            widget.setEnabled(not busy)
        self.onSystemAudioSelectionChanged()
