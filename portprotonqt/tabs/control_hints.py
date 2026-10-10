"""Main window control hints mixin."""

from typing import Any

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QWidget

from portprotonqt.config import ui_config
from portprotonqt.custom_widgets import FlowLayout
from portprotonqt.input_manager import BUTTONS, GamepadType
from portprotonqt.localization import _, retranslate
from portprotonqt.logger import get_logger
from portprotonqt.qt_utils import get_device_pixel_ratio

logger = get_logger(__name__)

GAMEPAD_HINT_ACTIONS = ("confirm", "back", "add_game", "search", "decrease_size", "increase_size", "context_menu", "menu", "guide_select", "mouse_emulation", "prev_section", "next_section")
COMBINATION_HINT_ACTIONS = ("guide_select", "mouse_emulation")
VOLUME_HINT_ACTIONS = ("decrease_size", "increase_size")

def _load_control_hint_pixmap(paths: tuple[str | None, ...], width: int, height: int) -> QPixmap:
    for path in paths:
        if path is None:
            continue
        pixmap = _render_control_hint_path(str(path), width, height)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


def _render_control_hint_path(path: str, width: int, height: int) -> QPixmap:
    device_pixel_ratio = get_device_pixel_ratio()
    target_width = max(1, int(width * device_pixel_ratio))
    target_height = max(1, int(height * device_pixel_ratio))

    if path.lower().endswith(".svg"):
        pixmap = QPixmap(target_width, target_height)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(device_pixel_ratio)
        painter = QPainter(pixmap)
        QSvgRenderer(path).render(painter, QRectF(0, 0, width, height))
        painter.end()
        return pixmap

    pixmap = QPixmap(path)
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaled(
        target_width,
        target_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(device_pixel_ratio)
    return scaled


def _set_control_hint_icon(label: QLabel, paths: tuple[str | None, ...], width: int, height: int) -> None:
    if isinstance(label, _ControlHintIconLabel):
        label.set_icon_paths(paths)
        return
    pixmap = _load_control_hint_pixmap(paths, width, height)
    if not pixmap.isNull():
        label.setPixmap(pixmap)


class _ControlHintIconLabel(QLabel):
    clicked = Signal()

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self._icon_path = ""
        self._icon_width = width
        self._icon_height = height
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_icon_paths(self, paths: tuple[str | None, ...]) -> None:
        self._icon_path = ""
        for path in paths:
            if path is None:
                continue
            if str(path).lower().endswith(".svg"):
                renderer = QSvgRenderer(str(path))
                if renderer.isValid():
                    self._icon_path = str(path)
                    break
                continue
            pixmap = _render_control_hint_path(str(path), self._icon_width, self._icon_height)
            if not pixmap.isNull():
                self.setPixmap(pixmap)
                return
        self.clear()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._icon_path:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        QSvgRenderer(self._icon_path).render(painter, QRectF(self.rect()))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class MainWindowControlHintsMixin:
    """Provide control hints and navigation icon logic for main window."""

    theme: Any
    theme_manager: Any
    input_manager: Any
    stackedWidget: QStackedWidget
    leftNavButton: QLabel
    rightNavButton: QLabel
    current_theme_name: str
    system_tab_index: int
    hintsLabels: list[tuple[QWidget, Any, str | None]]
    gamepadHintTextLabels: dict[str, QLabel]
    gamepadHintDefaultTexts: dict[str, str]
    gamepadHintContainers: dict[str, QWidget]

    def get_button_icon(self, action: str, gtype: GamepadType) -> str:
        """Get the icon name for a specific action and gamepad type."""
        mappings = {
            'confirm': {
                GamepadType.XBOX: "xbox_a",
                GamepadType.PLAYSTATION: "ps_cross",
            },
            'back': {
                GamepadType.XBOX: "xbox_b",
                GamepadType.PLAYSTATION: "ps_circle",
            },
            'add_game': {
                GamepadType.XBOX: "xbox_x",
                GamepadType.PLAYSTATION: "ps_square",
            },
            'context_menu': {
                GamepadType.XBOX: "xbox_start",
                GamepadType.PLAYSTATION: "ps_options",
            },
            'menu': {
                GamepadType.XBOX: "xbox_view",
                GamepadType.PLAYSTATION: "ps_share",
            },
            'search': {
                GamepadType.XBOX: "xbox_y",
                GamepadType.PLAYSTATION: "ps_triangle",
            },
            'decrease_size': {
                GamepadType.XBOX: "xbox_lt",
                GamepadType.PLAYSTATION: "ps_l2",
            },
            'increase_size': {
                GamepadType.XBOX: "xbox_rt",
                GamepadType.PLAYSTATION: "ps_r2",
            },
            'prev_dir': {
                GamepadType.XBOX: "xbox_y",
                GamepadType.PLAYSTATION: "ps_triangle",
            },
            'guide_select': {
                GamepadType.XBOX: "xbox_xbox",
                GamepadType.PLAYSTATION: "ps_ps",
            },
            'prev_section': {
                GamepadType.XBOX: "dpad_left",
                GamepadType.PLAYSTATION: "dpad_left",
            },
            'next_section': {
                GamepadType.XBOX: "dpad_right",
                GamepadType.PLAYSTATION: "dpad_right",
            },
        }
        return mappings.get(action, {}).get(gtype, "placeholder")

    def get_nav_icon(self, direction: str, gtype: GamepadType) -> str:
        """Get the icon name for navigation direction and gamepad type."""
        if direction == 'left':
            action = 'prev_tab'
        else:
            action = 'next_tab'
        mappings = {
            'prev_tab': {
                GamepadType.XBOX: "xbox_lb",
                GamepadType.PLAYSTATION: "ps_l1",
            },
            'next_tab': {
                GamepadType.XBOX: "xbox_rb",
                GamepadType.PLAYSTATION: "ps_r1",
            },
        }
        return mappings.get(action, {}).get(gtype, "placeholder")

    def createControlHintsWidget(self) -> QWidget:
        """Create a widget displaying control hints for gamepad and keyboard."""
        logger.debug("Creating control hints widget")
        hintsWidget = QWidget()
        hintsWidget.setStyleSheet(self.theme.STATUS_BAR_STYLE)

        hintsLayout = FlowLayout(hintsWidget)
        hintsLayout.setContentsMargins(10, 0, 10, 0)

        gamepad_actions = [
            ("confirm", _("Select")),
            ("back", _("Back")),
            ("add_game", _("Add a shortcut")),
            ("decrease_size", _("Volume") + " -"),
            ("increase_size", _("Volume") + " +"),
            ("context_menu", _("Menu")),
            ("menu", _("Fullscreen")),
            ("search", _("Search")),
            ("guide_select", _("Refresh Grid")),
            ("mouse_emulation", _("Mouse Emulation")),
            ("prev_section", _("Prev Tab")),
            ("next_section", _("Next Tab")),
        ]

        keyboard_hints = [
            ("key_enter", _("Select"), "confirm"),
            ("key_backspace", _("Back"), "back"),
            ("key_e", _("Add a shortcut"), "add_game"),
            ("key_context", _("Menu"), "context_menu"),
            ("key_f11", _("Fullscreen"), "menu"),
            ("key_f5", _("Refresh Grid"), "guide_select"),
        ]

        self.hintsLabels = []
        self.hintTextLabels = []
        self.gamepadHintTextLabels = {}
        self.gamepadHintDefaultTexts = {}
        self.gamepadHintContainers = {}

        def makeHint(
            icon_name: str,
            action_text: str,
            is_gamepad: bool,
            action: str | None = None,
            click_action: str | None = None,
        ):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 5, 0, 0)
            layout.setSpacing(6)

            icon_label = _ControlHintIconLabel(26, 26)
            _set_control_hint_icon(
                icon_label,
                (
                    self.theme_manager.get_icon(icon_name, self.current_theme_name, as_path=True),
                    self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                ),
                26,
                26,
            )
            hint_action = click_action or action
            icon_label.clicked.connect(lambda: self._triggerControlHintAction(hint_action))

            layout.addWidget(icon_label)

            text_label = QLabel(action_text)
            text_label.setProperty("theme_style_name", "HINTS_LABEL_STYLE")
            text_label.setStyleSheet(self.theme.HINTS_LABEL_STYLE)
            self.hintTextLabels.append(text_label)
            text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(text_label)

            if is_gamepad:
                container.setVisible(False)
                self.hintsLabels.append((container, icon_label, action))
                if action is not None:
                    self.gamepadHintContainers[action] = container
                    self.gamepadHintTextLabels[action] = text_label
                    self.gamepadHintDefaultTexts[action] = action_text
            else:
                container.setVisible(True)
                self.hintsLabels.append((container, icon_label, None))

            hintsLayout.addWidget(container)

        def makeCombinationHint(action_text: str, action: str | None = None):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 5, 0, 0)
            layout.setSpacing(6)

            guide_icon = _ControlHintIconLabel(26, 26)
            if action == "mouse_emulation":
                _set_control_hint_icon(
                    guide_icon,
                    (
                        self.theme_manager.get_icon("xbox_view", self.current_theme_name, as_path=True),
                        self.theme_manager.get_icon("ps_share", self.current_theme_name, as_path=True),
                        self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                    ),
                    26,
                    26,
                )
            else:
                _set_control_hint_icon(
                    guide_icon,
                    (
                        self.theme_manager.get_icon("xbox_xbox", self.current_theme_name, as_path=True),
                        self.theme_manager.get_icon("ps_ps", self.current_theme_name, as_path=True),
                        self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                    ),
                    26,
                    26,
                )

            layout.addWidget(guide_icon)

            plus_icon = _ControlHintIconLabel(26, 26)
            _set_control_hint_icon(
                plus_icon,
                (
                    self.theme_manager.get_icon("key_+", self.current_theme_name, as_path=True),
                    self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                ),
                26,
                26,
            )

            layout.addWidget(plus_icon)

            select_icon = _ControlHintIconLabel(26, 26)

            if action == "mouse_emulation":
                _set_control_hint_icon(
                    select_icon,
                    (
                        self.theme_manager.get_icon("xbox_start", self.current_theme_name, as_path=True),
                        self.theme_manager.get_icon("ps_options", self.current_theme_name, as_path=True),
                        self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                    ),
                    26,
                    26,
                )
            else:
                _set_control_hint_icon(
                    select_icon,
                    (
                        self.theme_manager.get_icon("xbox_view", self.current_theme_name, as_path=True),
                        self.theme_manager.get_icon("ps_share", self.current_theme_name, as_path=True),
                        self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                    ),
                    26,
                    26,
                )

            layout.addWidget(select_icon)
            for icon in (guide_icon, plus_icon, select_icon):
                icon.clicked.connect(lambda hint_action=action: self._triggerControlHintAction(hint_action))

            text_label = QLabel(action_text)
            text_label.setProperty("theme_style_name", "HINTS_LABEL_STYLE")
            text_label.setStyleSheet(self.theme.HINTS_LABEL_STYLE)
            self.hintTextLabels.append(text_label)
            text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(text_label)

            container.setVisible(False)
            self.hintsLabels.append((container, [guide_icon, plus_icon, select_icon], action))
            if action is not None:
                self.gamepadHintContainers[action] = container
                self.gamepadHintTextLabels[action] = text_label
                self.gamepadHintDefaultTexts[action] = action_text

            hintsLayout.addWidget(container)

        for action, text in gamepad_actions:
            if action in COMBINATION_HINT_ACTIONS:
                makeCombinationHint(text, action)
            else:
                makeHint("placeholder", text, True, action)

        for icon, text, action in keyboard_hints:
            makeHint(icon, text, False, click_action=action)

        return hintsWidget

    def _triggerControlHintAction(self, action: str | None) -> None:
        if action is None:
            return
        if action == "menu":
            self._triggerControlHintFullscreen()
            return
        if action == "guide_select":
            refresh_games = getattr(self, "refreshGames", None)
            if callable(refresh_games):
                refresh_games()
            return
        if action == "mouse_emulation":
            self.input_manager.emulation_triggered = not self.input_manager.emulation_triggered
            return
        if action in ("prev_section", "next_section"):
            switch_section = getattr(self, "switchSystemSectionRelative", None)
            if callable(switch_section):
                switch_section(-1 if action == "prev_section" else 1)
            return
        button_action = "prev_dir" if action == "search" else action
        button_codes = BUTTONS.get(button_action)
        if button_codes:
            self.input_manager.handle_button_slot(next(iter(button_codes)), 1)

    def _triggerControlHintFullscreen(self) -> None:
        if getattr(self.input_manager, "_is_gamescope_session", False):
            return
        self.input_manager.toggle_fullscreen.emit(not self.input_manager._is_fullscreen)

    def updateNavButtons(self, *args) -> None:
        """Update navigation buttons based on gamepad connection status and type."""
        is_gamepad_connected = self.input_manager.gamepad is not None
        gtype = self.input_manager.gamepad_type
        logger.debug(
            "Updating nav buttons, gamepad connected: %s, type: %s",
            is_gamepad_connected,
            gtype.value,
        )

        if is_gamepad_connected:
            left_icon_name = self.get_nav_icon('left', gtype)
        else:
            left_icon_name = "key_left"
        left_pix = _load_control_hint_pixmap(
            (self.theme_manager.get_icon(left_icon_name, self.current_theme_name, as_path=True),),
            32,
            32,
        )
        if not left_pix.isNull():
            self.leftNavButton.setPixmap(left_pix)
        self.leftNavButton.setVisible(True)

        if is_gamepad_connected:
            right_icon_name = self.get_nav_icon('right', gtype)
        else:
            right_icon_name = "key_right"
        right_pix = _load_control_hint_pixmap(
            (self.theme_manager.get_icon(right_icon_name, self.current_theme_name, as_path=True),),
            32,
            32,
        )
        if not right_pix.isNull():
            self.rightNavButton.setPixmap(right_pix)
        self.rightNavButton.setVisible(True)

    def updateControlHints(self, *args) -> None:
        """Update control hints based on gamepad connection status and type."""
        if not hasattr(self, "hintsLabels"):
            return
        control_hints_widget = getattr(self, "controlHintsWidget", None)
        hide_control_hints = ui_config.get_hide_control_hints()
        if isinstance(control_hints_widget, QWidget):
            control_hints_widget.setVisible(not hide_control_hints)
        if hide_control_hints:
            return
        force_update = bool(args and args[0] == "force")
        is_gamepad_connected = self.input_manager.gamepad is not None
        gtype = self.input_manager.gamepad_type
        current_tab_index = self.stackedWidget.currentIndex()
        system_section_index = -1
        section_stack = getattr(self, "systemSectionStack", None)
        if isinstance(section_stack, QStackedWidget):
            system_section_index = section_stack.currentIndex()
        hints_state = (
            is_gamepad_connected,
            gtype.value,
            current_tab_index,
            system_section_index,
            getattr(self, "current_theme_name", ""),
            ui_config.get_force_english(),
        )
        if not force_update and hints_state == getattr(self, "_last_control_hints_state", None):
            return
        self._last_control_hints_state = hints_state

        on_system_tab = self.stackedWidget.currentIndex() == getattr(self, "system_tab_index", -1)
        logger.debug(
            "Updating control hints, gamepad connected: %s, type: %s",
            is_gamepad_connected,
            gtype.value,
        )

        for container, icon_element, action in self.hintsLabels:
            if action in GAMEPAD_HINT_ACTIONS:
                if is_gamepad_connected:
                    if action in ("prev_section", "next_section"):
                        container.setVisible(False)
                    elif not on_system_tab:
                        container.setVisible(True)
                    if (
                        isinstance(icon_element, list)
                        and len(icon_element) == 3
                        and action in COMBINATION_HINT_ACTIONS
                    ):
                        guide_icon, plus_icon, select_icon = icon_element

                        if action == "mouse_emulation":
                            if gtype == GamepadType.PLAYSTATION:
                                guide_icon_name = "ps_share"
                            else:
                                guide_icon_name = "xbox_view"
                        elif gtype == GamepadType.XBOX:
                            guide_icon_name = "xbox_xbox"
                        elif gtype == GamepadType.PLAYSTATION:
                            guide_icon_name = "ps_ps"
                        else:
                            guide_icon_name = "xbox_xbox"

                        _set_control_hint_icon(
                            guide_icon,
                            (
                                self.theme_manager.get_icon(guide_icon_name, self.current_theme_name, as_path=True),
                                self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                            ),
                            26,
                            26,
                        )

                        _set_control_hint_icon(
                            plus_icon,
                            (
                                self.theme_manager.get_icon("key_+", self.current_theme_name, as_path=True),
                                self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                            ),
                            26,
                            26,
                        )

                        select_icon_name = "xbox_view"
                        if action == "guide_select":
                            if gtype == GamepadType.XBOX:
                                select_icon_name = "xbox_view"
                            elif gtype == GamepadType.PLAYSTATION:
                                select_icon_name = "ps_share"
                        elif action == "mouse_emulation":
                            if gtype == GamepadType.XBOX:
                                select_icon_name = "xbox_start"
                            elif gtype == GamepadType.PLAYSTATION:
                                select_icon_name = "ps_options"
                            else:
                                select_icon_name = "xbox_start"

                        _set_control_hint_icon(
                            select_icon,
                            (
                                self.theme_manager.get_icon(select_icon_name, self.current_theme_name, as_path=True),
                                self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                            ),
                            26,
                            26,
                        )
                    else:
                        if isinstance(icon_element, list):
                            logger.warning(
                                "Unexpected list found for single-icon hint with action: %s",
                                action,
                            )
                            continue
                        icon_label = icon_element
                        icon_name = self.get_button_icon(action, gtype)
                        _set_control_hint_icon(
                            icon_label,
                            (
                                self.theme_manager.get_icon(icon_name, self.current_theme_name, as_path=True),
                                self.theme_manager.get_theme_image("placeholder", self.current_theme_name),
                            ),
                            26,
                            26,
                        )
                else:
                    container.setVisible(False)
            else:
                container.setVisible(not is_gamepad_connected and not on_system_tab)

        self._updateSystemGamepadHintTexts()
        if isinstance(control_hints_widget, QWidget):
            control_hints_widget.updateGeometry()
            control_hints_widget.update()
        self.updateNavButtons()

    def _setGamepadHintText(self, action: str, text: str) -> None:
        label = getattr(self, "gamepadHintTextLabels", {}).get(action)
        if label is not None:
            label.setText(text)

    def _setGamepadHintVisible(self, action: str, visible: bool) -> None:
        container = getattr(self, "gamepadHintContainers", {}).get(action)
        if container is not None:
            container.setVisible(visible)

    def _updateSystemGamepadHintTexts(self) -> None:
        default_texts = getattr(self, "gamepadHintDefaultTexts", {})
        if not default_texts:
            return
        for action, text in default_texts.items():
            if action in VOLUME_HINT_ACTIONS:
                text = _("Volume") + text[-2:]
            self._setGamepadHintText(action, retranslate(text))
        for action in VOLUME_HINT_ACTIONS:
            self._setGamepadHintVisible(action, False)

        if self.stackedWidget.currentIndex() != getattr(self, "system_tab_index", -1):
            return

        for action in GAMEPAD_HINT_ACTIONS:
            self._setGamepadHintVisible(action, False)

        if self.input_manager.gamepad is None:
            return

        self._setGamepadHintVisible("prev_section", True)
        self._setGamepadHintVisible("next_section", True)

        section_stack = getattr(self, "systemSectionStack", None)
        if not isinstance(section_stack, QStackedWidget):
            return

        section_index = section_stack.currentIndex()
        wifi_index = getattr(self, "systemSectionWifiIndex", -1)
        vpn_index = getattr(self, "systemSectionVpnIndex", -1)
        bluetooth_index = getattr(self, "systemSectionBluetoothIndex", -1)
        storage_index = getattr(self, "systemSectionStorageIndex", -1)
        audio_index = getattr(self, "systemSectionAudioIndex", -1)

        if section_index == wifi_index:
            self._setGamepadHintVisible("confirm", True)
            self._setGamepadHintVisible("back", True)
            self._setGamepadHintVisible("add_game", True)
            self._setGamepadHintVisible("search", True)
            self._setGamepadHintText("confirm", _("Connect"))
            self._setGamepadHintText("back", _("Disconnect"))
            self._setGamepadHintText("add_game", _("Enable/Disable"))
            self._setGamepadHintText("search", _("Refresh"))
            return
        if section_index == vpn_index:
            self._setGamepadHintVisible("confirm", True)
            self._setGamepadHintVisible("back", True)
            self._setGamepadHintVisible("add_game", True)
            self._setGamepadHintText("confirm", _("Connect"))
            self._setGamepadHintText("back", _("Disconnect"))
            self._setGamepadHintText("add_game", _("Add VPN"))
            return
        if section_index == bluetooth_index:
            self._setGamepadHintVisible("confirm", True)
            self._setGamepadHintVisible("back", True)
            self._setGamepadHintVisible("add_game", True)
            self._setGamepadHintVisible("search", True)
            self._setGamepadHintText("confirm", _("Connect"))
            self._setGamepadHintText("back", _("Disconnect"))
            self._setGamepadHintText("add_game", _("Enable/Disable"))
            self._setGamepadHintText("search", _("Scan"))
            return
        if section_index == storage_index:
            self._setGamepadHintVisible("confirm", True)
            self._setGamepadHintVisible("back", True)
            self._setGamepadHintText("confirm", _("Mount"))
            self._setGamepadHintText("back", _("Unmount"))
            return
        if section_index == audio_index:
            self._setGamepadHintVisible("confirm", True)
            self._setGamepadHintVisible("search", True)
            self._setGamepadHintVisible("decrease_size", True)
            self._setGamepadHintVisible("increase_size", True)
            self._setGamepadHintText("confirm", _("Set output"))
            self._setGamepadHintText("search", _("Refresh"))
            return
