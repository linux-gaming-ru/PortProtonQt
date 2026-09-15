import time
import os
import math
from typing import Protocol, cast, Any
from evdev import UInput, ecodes
from PySide6.QtWidgets import QWidget, QStackedWidget, QApplication, QScrollArea, QMenu, QMessageBox, QTableWidget, QSlider
from PySide6.QtCore import Qt, QObject, Signal, Slot, QTimer, QThread
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager
from portprotonqt.game_card import AnimatedCard
from portprotonqt.config import display_config, window_config
from portprotonqt.dialogs import AddGameDialog
from portprotonqt.input_manager.constants import (
    BUTTONS,
    GamepadType as GamepadType,
    PAD_AXIS_RIGHT_Y,
    PAD_DPAD_X,
    PAD_DPAD_Y,
)
from portprotonqt.native_gamepad import SDLGamepad
from portprotonqt.input_manager.buttons import ButtonInputMixin
from portprotonqt.input_manager.dialog_modes import DialogInputModesMixin
from portprotonqt.input_manager.dpad import DpadInputMixin
from portprotonqt.input_manager.file_explorer import FileExplorerInputMixin
from portprotonqt.input_manager.keyboard import KeyboardInputMixin
from portprotonqt.input_manager.runtime import GamepadRuntimeMixin
from portprotonqt.input_manager.settings import SettingsInputMixin
from portprotonqt.input_manager.settings_visual import SettingsVisualNavigationMixin

logger = get_logger(__name__)

class MainWindowProtocol(Protocol):
    def activateFocusedWidget(self) -> None:
        ...
    def goBackDetailPage(self, page: QWidget | None) -> None:
        ...
    def switchTab(self, index: int) -> None:
        ...
    def openAddGameDialog(self, exe_path: str | None = None) -> None:
        ...
    def toggleGame(self, exec_line: str | None, button: QWidget | None = None) -> None:
        ...
    def on_slider_released(self) -> None:
        ...
    def on_auto_slider_released(self) -> None:
        ...
    def isActiveWindow(self) -> bool:
        ...
    def refreshGames(self) -> None:
        ...
    def handleSystemTableGamepadAction(self, table: QTableWidget, action: str) -> bool:
        ...
    def handleSystemGamepadAction(self, action: str) -> bool:
        ...
    stackedWidget: QStackedWidget
    tabButtons: dict[int, QWidget]
    gamesListWidget: QWidget
    autoInstallContainer: QWidget | None
    currentDetailPage: QWidget | None
    current_exec_line: str | None
    current_add_game_dialog: AddGameDialog | None
    game_library_manager: Any  # GameLibraryManager - using Any to avoid circular import
    theme: Any
    auto_size_slider: QSlider | None

class MouseEmulationThread(QThread):
    """Thread for creating UInput virtual mouse device without blocking UI."""

    finished = Signal(bool)  # Emitted when done (True = success, False = failed)

    def run(self):
        """Run UInput device creation in background thread."""
        try:
            if not os.path.exists('/dev/uinput'):
                logger.error("EMUL: /dev/uinput does not exist")
                self.finished.emit(False)
                return

            if not os.access('/dev/uinput', os.W_OK):
                logger.error("EMUL: No write access to /dev/uinput")
                self.finished.emit(False)
                return

            ui = UInput({
                ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL],
            }, name="Virtual DPad Mouse")

            self.finished.emit(True)
            # Store device in thread result
            self._device = ui

        except PermissionError as e:
            logger.error("EMUL: Permission denied for /dev/uinput: %s", e)
            self.finished.emit(False)
        except Exception as ex:
            logger.error(f"EMUL: Error creating virtual mouse: {ex}", exc_info=True)
            self.finished.emit(False)

    def get_device(self) -> UInput | None:
        """Get the created UInput device after thread finishes."""
        return getattr(self, '_device', None)


class InputManager(
    FileExplorerInputMixin,
    DialogInputModesMixin,
    SettingsInputMixin,
    SettingsVisualNavigationMixin,
    ButtonInputMixin,
    DpadInputMixin,
    KeyboardInputMixin,
    GamepadRuntimeMixin,
    QObject,
):
    """
    Manages input from gamepads and keyboards for navigating the application interface.
    Supports gamepad hotplugging, button and axis events, and keyboard shortcuts.
    """
    # Signals for gamepad events
    button_event = Signal(int, int)  # Signal for button events: (code, value) where value=1 (press), 0 (release)
    dpad_moved = Signal(int, int, float)  # Signal for D-pad movements
    toggle_fullscreen = Signal(bool)  # Signal for toggling fullscreen mode (True for fullscreen, False for normal)
    gamepad_hotplug = Signal(str)  # 'add' or 'remove'

    def __init__(
        self,
        main_window: MainWindowProtocol,
        axis_deadzone: float = 0.5,
        initial_axis_move_delay: float = 0.5,
        repeat_axis_move_delay: float = 0.15
    ):
        super().__init__(cast(QObject, main_window))
        self._parent = main_window
        self._gamepad_handling_enabled = True
        self.gamepad_type = self._get_configured_gamepad_type()
        self._parent.currentDetailPage = getattr(self._parent, 'currentDetailPage', None)
        self._parent.current_exec_line = getattr(self._parent, 'current_exec_line', None)
        self._parent.current_add_game_dialog = getattr(self._parent, 'current_add_game_dialog', None)
        self._parent.autoInstallContainer = getattr(self._parent, 'autoInstallContainer', None)
        self.axis_deadzone = axis_deadzone
        self.initial_axis_move_delay = initial_axis_move_delay
        self.repeat_axis_move_delay = repeat_axis_move_delay
        self.current_axis_delay = initial_axis_move_delay
        self.last_move_time = 0.0
        self.axis_moving = False
        self.gamepad: SDLGamepad | None = None
        self.running = True
        self._is_fullscreen = display_config.get_fullscreen()
        self.lt_pressed = False
        self.rt_pressed = False
        self.last_trigger_time = 0.0
        self.trigger_cooldown = 0.2

        # Mouse emulation attributes
        self.mouse_emulation_enabled = True
        self.ui = None
        self.mouse_emulation_thread: MouseEmulationThread | None = None
        self.stick_x_raw = 0
        self.stick_y_raw = 0

        # Axis parameters (will be filled from kernel)
        self.center_x = 127      # X axis center
        self.center_y = 127      # Y axis center
        self.min_value = 0       # axis minimum
        self.max_value = 255     # axis maximum
        self.deadzone_value = 15 # deadzone from kernel (flat parameter)
        self.scroll_axis_code = PAD_AXIS_RIGHT_Y
        self.scroll_center = self.center_y
        self.scroll_min_value = self.min_value
        self.scroll_max_value = self.max_value
        self.scroll_deadzone_value = self.deadzone_value

        self.sensitivity = 20.0

        # Dynamic attributes for different modes (declared here to satisfy type checkers)
        self.winetricks_dialog: Any = None
        self.settings_dialog: Any = None
        self.file_explorer: Any = None
        self.proton_manager_dialog: Any = None
        self.appimage_update_dialog: Any = None
        self._input_surfaces: list[Any] = []
        self._input_surface_base_state: bool | None = None
        self.scroll_accumulator = 0.0
        self.scroll_sensitivity = 0.15
        self.scroll_threshold = 0.2
        self.last_update = time.time()
        self.update_interval = 0.016  # ~60 FPS
        self.emulation_active = False
        self.emulation_triggered = False
        self.start_held = False
        self.select_held = False
        self.pending_menu_fullscreen_time = 0.0
        self.guide_held = False
        # Variables for key combination handling
        self.guide_pressed_time = 0
        self.select_pressed_time = 0
        self.guide_timer = QTimer(self)
        self.guide_timer.setSingleShot(True)
        self.guide_timer.timeout.connect(self._handle_guide_timeout)
        self.guide_combination_timeout = 0.3  # 300ms timeout for combination
        self.in_guide_combination_attempt = False  # Flag to track if we're in a guide+select combination attempt
        self._button_states: dict[int, int] = {}
        self._hat_states: dict[int, tuple[int, int]] = {}
        self._axis_states: dict[int, int] = {}
        self._gamepad_polling_suspended = False
        self._last_gamepad_check_time = 0.0
        self._last_gamepad_error: str | None = None

        # Focus check timer for emulation flag (runs in main thread)
        self.focus_check_timer = QTimer(self)
        self.focus_check_timer.timeout.connect(self._update_emulation_flag)
        self.focus_check_timer.start(100)  # Check every 100ms

        logger.info("EMUL: Mouse emulation initialized (enabled=%s)", self.mouse_emulation_enabled)

        if self.mouse_emulation_enabled:
            # Initialize mouse emulation asynchronously to avoid blocking startup
            QTimer.singleShot(0, self._async_enable_mouse_emulation)

        # FileExplorer specific attributes
        self.file_explorer = None
        self.nav_timer = QTimer(self)
        self.nav_timer.timeout.connect(self.handle_navigation_repeat)
        self.current_direction = 0
        self.last_nav_time = 0
        self.initial_nav_delay = 0.1  # Initial delay before first repeat (sec)
        self.repeat_nav_delay = 0.05  # Interval between repeats (sec)
        self.stick_activated = False
        self.stick_value = 0  # Current stick value (for smoothness)
        self.dead_zone = 8000  # Stick deadzone

        self._is_gamescope_session = 'gamescope' in os.environ.get('DESKTOP_SESSION', '').lower()

        # Add variables for continuous D-pad movement
        self.dpad_timer = QTimer(self)
        self.dpad_timer.timeout.connect(self.handle_dpad_repeat)
        self.current_dpad_code = None  # Tracks the current D-pad axis (e.g., ABS_HAT0X, ABS_HAT0Y)
        self.current_dpad_value = 0    # Tracks the current D-pad direction value (e.g., -1, 1)

        # Connect signals to slots
        self.button_event.connect(
            self.handle_button_slot,
            Qt.ConnectionType.QueuedConnection,
        )
        self.dpad_moved.connect(
            self.handle_dpad_slot,
            Qt.ConnectionType.QueuedConnection,
        )
        self.toggle_fullscreen.connect(self.handle_fullscreen_slot)

        # Install wheel event filter
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.init_gamepad()

    def _async_enable_mouse_emulation(self):
        """Asynchronously enable mouse emulation to avoid blocking startup."""
        logger.info("EMUL: Attempting to create UInput virtual mouse...")
        self.mouse_emulation_thread = MouseEmulationThread()
        self.mouse_emulation_thread.finished.connect(self._on_mouse_emulation_finished)
        self.mouse_emulation_thread.start()

    def _on_mouse_emulation_finished(self, success: bool):
        """Handle mouse emulation thread completion."""
        if success and self.mouse_emulation_thread:
            device = self.mouse_emulation_thread.get_device()
            if device:
                self.ui = device
                self.mouse_emulation_enabled = True
                logger.info("EMUL: Virtual mouse created successfully")
        else:
            self.mouse_emulation_enabled = False

    def _update_emulation_flag(self):
        """Update emulation_active flag based on Qt app focus (main thread only)."""
        # True when mouse emulation is enabled (works regardless of focus)
        # The difference is whether other inputs are disabled (based on focus)
        self.emulation_active = self.mouse_emulation_enabled
        if not self.emulation_active:
            self.emulation_triggered = False

    def _navigate_game_cards(self, container, tab_index: int, code: int, value: int) -> None:
        """Common navigation logic for game cards in a container."""
        if container is None:
            return
        game_cards = [
            card for card in container.findChildren(AnimatedCard)
            if card.isVisible() and card.isEnabled()
        ]
        if self._navigate_horizontal_library(game_cards, tab_index, code, value):
            return
        focused = QApplication.focusWidget()
        if game_cards and focused not in game_cards:
            self._focus_grid_card(game_cards[0])
            return
        moved = self._navigate_card_grid(game_cards, code, value)
        if not moved and code == PAD_DPAD_Y and value < 0 and focused in game_cards:
            first_row = self._get_card_grid_rows(game_cards)[0]
            if focused in first_row:
                self._parent.tabButtons[tab_index].setFocus(Qt.FocusReason.OtherFocusReason)

    def _navigate_horizontal_library(
        self, cards: list[QWidget], tab_index: int, code: int, value: int
    ) -> bool:
        if tab_index == 1:
            mode = str(
                getattr(self._parent.theme, "LIBRARY_LAYOUT_MODE", "grid")
            ).lower()
            layout = getattr(self._parent, "autoInstallContainerLayout", None)
        else:
            manager = getattr(self._parent, "game_library_manager", None)
            mode = getattr(manager, "layout_mode", "grid")
            layout = getattr(manager, "gamesListLayout", None)
        if mode not in {
            "horizontal", "horizontal_top"
        }:
            return False
        if code != PAD_DPAD_X or value == 0 or layout is None:
            return False
        ordered_cards = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget in cards:
                ordered_cards.append(widget)
        focused = QApplication.focusWidget()
        if not ordered_cards:
            return True
        if focused not in ordered_cards:
            self._focus_grid_card(ordered_cards[0])
            return True
        target_index = (ordered_cards.index(focused) + value) % len(ordered_cards)
        self._focus_grid_card(ordered_cards[target_index])
        return True

    def _get_card_grid_rows(self, cards: list[QWidget]) -> list[list[QWidget]]:
        """Group cards into rows ordered by their visual position."""
        rows = {}
        y_tolerance = 10  # Allow slight variations in y-position
        for card in cards:
            y = card.pos().y()
            for row_y in rows:
                if abs(y - row_y) <= y_tolerance:
                    rows[row_y].append(card)
                    break
            else:
                rows[y] = [card]
        sorted_rows = [row for _y, row in sorted(rows.items())]
        for row_cards in sorted_rows:
            row_cards.sort(key=lambda card: card.pos().x())
        return sorted_rows

    def _grid_navigation_target(
        self, rows: list[list[QWidget]], focused: QWidget, code: int, value: int
    ) -> QWidget | None:
        row_index = next(index for index, row in enumerate(rows) if focused in row)
        if code == PAD_DPAD_X:
            flat_cards = [card for row in rows for card in row]
            card_index = flat_cards.index(focused) + value
            return flat_cards[card_index] if 0 <= card_index < len(flat_cards) else None
        target_row_index = row_index + value
        if not 0 <= target_row_index < len(rows):
            return None
        focused_x = focused.pos().x() + focused.width() / 2
        return min(
            rows[target_row_index],
            key=lambda card: abs(card.pos().x() + card.width() / 2 - focused_x),
        )

    def _focus_grid_card(self, card: QWidget) -> None:
        card.setFocus(Qt.FocusReason.OtherFocusReason)
        scroll_area = card.parentWidget()
        while scroll_area and not isinstance(scroll_area, QScrollArea):
            scroll_area = scroll_area.parentWidget()
        if isinstance(scroll_area, QScrollArea):
            scroll_area.ensureWidgetVisible(card, 50, 50)

    def _navigate_card_grid(self, cards: list[QWidget], code: int, value: int) -> bool:
        """Move focus through a card grid using its visual layout."""
        if not cards or value == 0:
            return False
        rows = self._get_card_grid_rows(cards)
        focused = QApplication.focusWidget()
        if focused not in cards:
            return False
        target = self._grid_navigation_target(rows, focused, code, value)
        if target is None:
            return False
        self._focus_grid_card(target)
        return True

    def handle_navigation_repeat(self):
        """Smooth movement repeat with variable speed for FileExplorer"""
        try:
            if not self.file_explorer or not hasattr(self.file_explorer, 'file_list') or not self.file_explorer.file_list:
                return

            if self.current_direction != 0:
                now = time.time()
                # Dynamic interval based on stick_value
                dynamic_delay = self.repeat_nav_delay / self.stick_value
                if now - self.last_nav_time >= dynamic_delay:
                    self.file_explorer.move_selection(self.current_direction)
                    self.last_nav_time = now
        except Exception as e:
            logger.error(f"Error in navigation repeat: {e}")

    def disable_mouse_emulation(self):
        """Disable mouse emulation mode (closes virtual mouse device)."""
        logger.info("EMUL: Disabling mouse emulation...")

        # Stop the thread if still running
        thread = self.mouse_emulation_thread
        if thread and thread.isRunning():
            thread.wait()
            self.mouse_emulation_thread = None

        if self.ui:
            try:
                self.ui.close()
                logger.info("EMUL: Virtual mouse closed")
            except Exception as e:
                logger.error("EMUL: Error closing virtual mouse: %s", e)
            self.ui = None
        self.mouse_emulation_enabled = False
        self.stick_x_raw = 0
        self.stick_y_raw = 0
        self.scroll_accumulator = 0.0


    def handle_scroll(self, raw_value):
        """Handle scrolling from right stick Y"""
        if not self._is_mouse_emulation_active() or not self.ui:
            return

        # Normalize from center
        centered_value = raw_value - self.scroll_center

        if abs(centered_value) < self.scroll_deadzone_value:
            self.scroll_accumulator = 0.0
            return

        # Normalize value (-1.0 to 1.0)
        range_val = (self.scroll_max_value - self.scroll_min_value) / 2
        if range_val <= 0:
            return
        normalized = centered_value / range_val

        # Accumulate scroll
        self.scroll_accumulator += normalized * self.scroll_sensitivity

        # Send scroll events
        while abs(self.scroll_accumulator) >= self.scroll_threshold:
            scroll_step = 1 if self.scroll_accumulator > 0 else -1
            self.scroll_wheel(-scroll_step)
            self.scroll_accumulator -= scroll_step * self.scroll_threshold

    def update_mouse_position(self):
        """Constant update of mouse position based on stick state"""
        if not self.ui or not self.emulation_active:
            return

        # Center values
        x = self.stick_x_raw - self.center_x
        y = self.stick_y_raw - self.center_y

        # Apply deadzone from kernel
        magnitude = math.sqrt(x * x + y * y)

        if magnitude < self.deadzone_value:
            return

        if magnitude > 0:
            norm_x = x / magnitude
            norm_y = y / magnitude
        else:
            return

        # Normalize to axis range
        max_range = (self.max_value - self.min_value) / 2
        adjusted_magnitude = (magnitude - self.deadzone_value) / (max_range - self.deadzone_value)
        adjusted_magnitude = max(0.0, min(1.0, adjusted_magnitude))

        # Non-linear curve
        adjusted_magnitude = math.pow(adjusted_magnitude, 1.5)

        speed = adjusted_magnitude * self.sensitivity
        dx = int(norm_x * speed)
        dy = int(norm_y * speed)

        if dx != 0 or dy != 0:
            self.move_mouse(dx, dy)

    def move_mouse(self, dx, dy):
        """Move system cursor"""
        if self.ui:
            self.ui.write(ecodes.EV_REL, ecodes.REL_X, dx)
            self.ui.write(ecodes.EV_REL, ecodes.REL_Y, dy)
            self.ui.syn()

    def scroll_wheel(self, steps):
        """Mouse wheel scroll"""
        if self.ui:
            self.ui.write(ecodes.EV_REL, ecodes.REL_WHEEL, steps)
            self.ui.syn()

    def click_left(self):
        """Left mouse button click"""
        if self.ui:
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
            self.ui.syn()
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
            self.ui.syn()

    def click_right(self):
        """Right mouse button click"""
        if self.ui:
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1)
            self.ui.syn()
            self.ui.write(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0)
            self.ui.syn()

    @Slot(bool)
    def handle_fullscreen_slot(self, enable: bool) -> None:
        try:
            window = self._parent
            if not isinstance(window, QWidget):
                return
            if enable and not self._is_fullscreen:
                if not window.isFullScreen():
                    window_config.set_geometry(window.width(), window.height())
                window.showFullScreen()
                self._is_fullscreen = True
            elif not enable and self._is_fullscreen:
                window.showNormal()
                width, height = window_config.get_geometry()
                if width > 0 and height > 0:
                    window.resize(width, height)
                self._is_fullscreen = False
                window_config.set_geometry(width, height)
        except Exception as e:
            logger.error(f"Error in handle_fullscreen_slot: {e}", exc_info=True)

    def disable_gamepad_handling(self) -> None:
        """Disable gamepad event handling."""
        self._gamepad_handling_enabled = False
        self.dpad_timer.stop()
        self.nav_timer.stop()

    def enable_gamepad_handling(self) -> None:
        """Enable gamepad event handling."""
        self._gamepad_handling_enabled = True

    def suspend_gamepad_polling(self) -> None:
        """Disable PPQT gamepad handling while keeping mouse emulation available."""
        self._gamepad_polling_suspended = True
        self._gamepad_handling_enabled = False
        self.dpad_timer.stop()
        self.nav_timer.stop()

    def resume_gamepad_polling(self) -> None:
        """Resume SDL controller polling after the external game exits."""
        self._gamepad_polling_suspended = False
        self._gamepad_handling_enabled = True
        self.check_gamepad()

    def _handle_guide_timeout(self) -> None:
        if self.guide_held:
            time_since_guide = time.time() - self.guide_pressed_time
            time_since_select = time.time() - self.select_pressed_time

            if (self.select_pressed_time > self.guide_pressed_time and
                time_since_select <= self.guide_combination_timeout and
                time_since_guide <= self.guide_combination_timeout):
                logger.debug("Guide + Select combination detected, refreshing game grid")
                self._parent.refreshGames()
            else:
                logger.debug("Guide button pressed alone")

        self._reset_guide_combination()


    def _handle_common_ui_elements(self, button_code):
        """
        Common handler for common UI elements like QMessageBox, QMenu, etc.
        Returns True if the event was handled, False otherwise.
        """
        # Check for popup widgets first
        popup = QApplication.activePopupWidget()
        if popup:
            if isinstance(popup, QMessageBox):
                self._handle_qmessagebox_button(popup, button_code)
                SoundManager().play("click")
                return True
            elif isinstance(popup, QMenu):
                if button_code in BUTTONS['confirm']:
                    SoundManager().play("click")
                    if popup.activeAction():
                        popup.activeAction().trigger()
                    popup.close()
                elif button_code in BUTTONS['back']:
                    SoundManager().play("back")
                    popup.close()
                return True

        # Check for top-level QMessageBox specifically
        active = QApplication.activeWindow()
        if isinstance(active, QMessageBox):
            self._handle_qmessagebox_button(active, button_code)
            return True

        # Check for top-level message boxes (additional check)
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible() and widget != active:
                self._handle_qmessagebox_button(widget, button_code)
                return True

        return False  # Not handled by common handler

    def _handle_qmessagebox_button(self, msg_box, button_code):
        """
        Unified handler for QMessageBox across all modes.
        For single button dialogs, A button accepts the dialog.
        For multiple button dialogs, navigate between buttons and allow selection.
        """
        if button_code in BUTTONS['confirm']:
            # Check if there's a focused button in the message box
            focused_widget = msg_box.focusWidget()
            if focused_widget:
                # If a specific button is focused, click/activate it
                focused_widget.click()
            else:
                # If no button is focused, accept with default behavior
                msg_box.accept()
        elif button_code in BUTTONS['back']:
            # For back button, reject the dialog (typically cancels or selects cancel button)
            msg_box.reject()
