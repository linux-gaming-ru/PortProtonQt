import time
from typing import cast

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from portprotonqt.config import display_config, gamepad_config
from portprotonqt.input_manager.constants import (
    BUTTONS,
    GamepadType,
    INPUT_AXIS_SCALE,
    PAD_AXIS_LEFT_TRIGGER,
    PAD_AXIS_LEFT_X,
    PAD_AXIS_LEFT_Y,
    PAD_AXIS_RIGHT_TRIGGER,
    PAD_AXIS_RIGHT_Y,
    PAD_BUTTON_START,
    PAD_DPAD_X,
    PAD_DPAD_Y,
    SDL3_PLAYSTATION_TYPES,
    SDL3_XBOX_LIKE_TYPES,
    SDL_GAMEPAD_BUTTON_DPAD_DOWN,
    SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_DPAD_RIGHT,
    SDL_GAMEPAD_BUTTON_DPAD_UP,
    SDL_CONTROLLER_AXIS_TO_PAD,
    SDL_CONTROLLER_BUTTON_TO_PAD,
)
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.logger import get_logger
from portprotonqt.native_gamepad import (
    GAMEPAD_LIBRARY_PATH,
    GamepadBackendError,
    SDLGamepad,
    find_gamepad,
    shutdown as shutdown_gamepad_backend,
)
from portprotonqt.sound_manager import SoundManager

logger = get_logger(__name__)


class GamepadRuntimeMixin(InputMixin):
    def init_gamepad(self) -> None:
        self.gamepad_hotplug.connect(self._on_gamepad_hotplug)
        self._initial_gamepad_check = True
        self.check_gamepad()
        self._initial_gamepad_check = False
        self.gamepad_poll_timer = QTimer(cast(QObject, self))
        self.gamepad_poll_timer.setInterval(10)
        self.gamepad_poll_timer.timeout.connect(self._poll_gamepad)
        self.gamepad_poll_timer.start()
        logger.info(
            "Gamepad support initialized with SDL3 events (library: %s)",
            GAMEPAD_LIBRARY_PATH,
        )

    def _on_gamepad_hotplug(self, action: str) -> None:
        try:
            if self._gamepad_polling_suspended:
                return
            if action == 'add':
                self.check_gamepad()
            elif action == 'remove':
                had_gamepad = self.gamepad is not None
                if self.gamepad:
                    self.gamepad.close()
                self.gamepad = None
                self._reset_input_state()
                self._refresh_gamepad_ui()
                self.check_gamepad()

                if had_gamepad and not self.gamepad:
                    SoundManager().play("gamepad_off")
                if had_gamepad and not self.gamepad and display_config.get_auto_fullscreen_gamepad() and not display_config.get_fullscreen():
                    self.toggle_fullscreen.emit(False)

        except Exception as e:
            logger.error(f"Error in hotplug handler: {e}", exc_info=True)

    def check_gamepad(self) -> None:
        try:
            if self._gamepad_polling_suspended:
                return
            new_gamepad = self.find_gamepad()

            if new_gamepad:
                if self.gamepad and new_gamepad.path == self.gamepad.path:
                    new_gamepad.close()
                    return
                if self.gamepad:
                    self.gamepad.close()
                self.detect_gamepad_axes(new_gamepad)
                logger.info(f"Gamepad connected: {new_gamepad.name} at {new_gamepad.path}")
                self.gamepad = new_gamepad
                self._reset_input_state()
                self._last_gamepad_check_time = 0.0
                self.gamepad_type = self._get_effective_gamepad_type(new_gamepad)
                self._refresh_gamepad_ui()
                if not self._initial_gamepad_check:
                    SoundManager().play("gamepad_connect")

                if display_config.get_auto_fullscreen_gamepad() and not display_config.get_fullscreen():
                    self.toggle_fullscreen.emit(True)

            elif self.gamepad:
                logger.info("Gamepad no longer detected")
                self.gamepad.close()
                self.gamepad = None
                self._reset_input_state()
                self._refresh_gamepad_ui()
                SoundManager().play("gamepad_off")

                if display_config.get_auto_fullscreen_gamepad() and not display_config.get_fullscreen():
                    self.toggle_fullscreen.emit(False)

        except Exception as e:
            logger.error(f"Error checking gamepad: {e}", exc_info=True)

    def _reset_input_state(self) -> None:
        """Reset cached joystick state when the active device changes."""
        self._button_states.clear()
        self._hat_states.clear()
        self._axis_states.clear()
        self.stick_x_raw = self.center_x
        self.stick_y_raw = self.center_y
        self.scroll_accumulator = 0.0
        self.lt_pressed = False
        self.rt_pressed = False
        self.start_held = False
        self.select_held = False
        self.pending_menu_fullscreen_time = 0.0
        self.guide_held = False
        self.emulation_triggered = False
        self.gamepad_type = self._get_configured_gamepad_type()

    def _get_configured_gamepad_type(self) -> GamepadType:
        """Return manual gamepad type from config or Unknown for auto mode."""
        value = gamepad_config.get_gamepad_type()
        if value == "playstation":
            return GamepadType.PLAYSTATION
        if value == "xbox":
            return GamepadType.XBOX
        return GamepadType.UNKNOWN

    def _get_effective_gamepad_type(self, gamepad: SDLGamepad) -> GamepadType:
        """Use manual gamepad type when configured, otherwise auto-detect."""
        configured_type = self._get_configured_gamepad_type()
        if configured_type != GamepadType.UNKNOWN:
            return configured_type
        return self._detect_gamepad_type(gamepad)

    def apply_gamepad_type_setting(self) -> None:
        """Apply configured gamepad type to the current device."""
        if self.gamepad is None:
            self.gamepad_type = self._get_configured_gamepad_type()
            return
        self.gamepad_type = self._get_effective_gamepad_type(self.gamepad)

    def _detect_gamepad_type(self, gamepad: SDLGamepad) -> GamepadType:
        """Read gamepad type from SDL or fall back to Xbox."""
        if gamepad.sdl_type in SDL3_PLAYSTATION_TYPES:
            return GamepadType.PLAYSTATION
        if gamepad.sdl_type in SDL3_XBOX_LIKE_TYPES:
            return GamepadType.XBOX
        return GamepadType.XBOX

    def _refresh_gamepad_ui(self) -> None:
        """Refresh control hints and virtual keyboard after gamepad changes."""
        update_hints = getattr(self._parent, "updateControlHints", None)
        if callable(update_hints):
            update_hints()
        keyboard = getattr(self._parent, "keyboard", None)
        if keyboard and hasattr(keyboard, "update_keyboard"):
            keyboard.update_keyboard()

    def find_gamepad(self) -> SDLGamepad | None:
        """Open the SDL3 handle that combines all connected gamepads."""
        try:
            gamepad = find_gamepad()
            self._last_gamepad_error = None
            return gamepad
        except GamepadBackendError as error:
            error_message = str(error)
            if error_message != self._last_gamepad_error:
                logger.error("Error finding gamepad: %s", error_message)
            self._last_gamepad_error = error_message
        except Exception as e:
            logger.error(f"Error finding gamepad: {e}", exc_info=True)
        return None

    def detect_gamepad_axes(self, device: SDLGamepad) -> None:
        """Use normalized SDL axis ranges for navigation and mouse emulation."""
        self.min_value = -INPUT_AXIS_SCALE
        self.max_value = INPUT_AXIS_SCALE
        self.center_x = 0
        self.center_y = 0
        self.deadzone_value = 4000
        self.scroll_axis_code = PAD_AXIS_RIGHT_Y
        self.scroll_center = 0
        self.scroll_min_value = -INPUT_AXIS_SCALE
        self.scroll_max_value = INPUT_AXIS_SCALE
        self.scroll_deadzone_value = self.deadzone_value
        self.stick_x_raw = self.center_x
        self.stick_y_raw = self.center_y
        logger.info("Gamepad axes configured for SDL backend: %s", device.name)

    def _handle_pending_menu_fullscreen(self, current_time: float) -> None:
        if not self.pending_menu_fullscreen_time:
            return
        if current_time < self.pending_menu_fullscreen_time:
            return
        self.pending_menu_fullscreen_time = 0.0
        if self.start_held or self.in_guide_combination_attempt:
            return
        self.toggle_fullscreen.emit(not self._is_fullscreen)

    def _poll_button_events(self, gamepad: SDLGamepad, current_time: float) -> None:
        """Emit button changes using SDL's standardized controller mapping."""
        for button_index, button_code in SDL_CONTROLLER_BUTTON_TO_PAD.items():
            value = gamepad.get_button(button_index)
            self._handle_button_value(button_index, button_code, value, current_time)

    def _handle_button_value(self, button_index: int, button_code: int, value: int, current_time: float) -> None:
        if self._button_states.get(button_index) == value:
            return
        self._button_states[button_index] = value
        if button_code in BUTTONS['guide']:
            self.guide_held = value == 1
        if button_code in BUTTONS['menu']:
            self.select_held = value == 1
        if button_code == PAD_BUTTON_START:
            self.start_held = value == 1
        emulation_combo = self._handle_emulation_combo(button_code, value)
        if self._is_mouse_emulation_active() and value == 1:
            if button_code in BUTTONS['confirm']:
                self.click_left()
            elif button_code in BUTTONS['back']:
                self.click_right()
        if emulation_combo:
            return
        if self._should_skip_regular_events():
            return
        self.button_event.emit(button_code, value)
        if self._should_schedule_menu_fullscreen(button_code, value, emulation_combo):
            self.pending_menu_fullscreen_time = current_time + self.guide_combination_timeout

    def _handle_emulation_combo(self, button_code: int, value: int) -> bool:
        emulation_combo = value == 1 and (
            (button_code in BUTTONS['menu'] and self.start_held) or
            (button_code == PAD_BUTTON_START and self.select_held)
        )
        if emulation_combo:
            self.emulation_triggered = not self.emulation_triggered
            self.pending_menu_fullscreen_time = 0.0
        return emulation_combo

    def _should_schedule_menu_fullscreen(self, button_code: int, value: int, emulation_combo: bool) -> bool:
        return (
            value == 1 and button_code in BUTTONS['menu'] and
            not emulation_combo and
            not self._is_gamescope_session and not self.in_guide_combination_attempt and
            self._parent.isActiveWindow()
        )

    def _poll_hat_events(self, gamepad: SDLGamepad, current_time: float) -> None:
        """Read D-pad state from SDL's standardized gamepad buttons."""
        hat_value = (
            self._read_dpad_button_axis(gamepad, SDL_GAMEPAD_BUTTON_DPAD_LEFT, SDL_GAMEPAD_BUTTON_DPAD_RIGHT),
            self._read_dpad_button_axis(gamepad, SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN),
        )
        previous_value = self._hat_states.get(0, (0, 0))
        self._hat_states[0] = hat_value

        if self._is_mouse_emulation_active():
            if previous_value[0] != hat_value[0]:
                if hat_value[0] < 0:
                    self.move_mouse(-10, 0)
                elif hat_value[0] > 0:
                    self.move_mouse(10, 0)
            if previous_value[1] != hat_value[1]:
                if hat_value[1] > 0:
                    self.move_mouse(0, -10)
                elif hat_value[1] < 0:
                    self.move_mouse(0, 10)

        if self._should_skip_regular_events():
            return

        if previous_value[0] != hat_value[0]:
            self.dpad_moved.emit(PAD_DPAD_X, hat_value[0], current_time)
        if previous_value[1] != hat_value[1]:
            self.dpad_moved.emit(PAD_DPAD_Y, hat_value[1], current_time)

    def _read_dpad_button_axis(self, gamepad: SDLGamepad, negative_button: int, positive_button: int) -> int:
        negative = gamepad.get_button(negative_button)
        positive = gamepad.get_button(positive_button)
        return positive - negative

    def _poll_axis_events(self, gamepad: SDLGamepad, current_time: float) -> None:
        """Emit axis changes using the same evdev-like codes used by the UI."""
        for axis_index, axis_code in SDL_CONTROLLER_AXIS_TO_PAD.items():
            raw_value = gamepad.get_axis(axis_index)
            previous_value = self._axis_states.get(axis_index)
            if previous_value == raw_value:
                continue
            self._axis_states[axis_index] = raw_value
            if axis_code == PAD_AXIS_LEFT_X:
                self.stick_x_raw = raw_value
            elif axis_code == PAD_AXIS_LEFT_Y:
                self.stick_y_raw = raw_value
            elif axis_code == self.scroll_axis_code:
                self.handle_scroll(raw_value)
            if self._should_skip_regular_events():
                continue
            if axis_code in (PAD_AXIS_LEFT_TRIGGER, PAD_AXIS_RIGHT_TRIGGER):
                self._emit_trigger_event(axis_code, raw_value, current_time)
                continue
            if axis_code not in (PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y):
                continue
            self.dpad_moved.emit(axis_code, raw_value, current_time)

    def _emit_trigger_event(self, axis_code: int, raw_value: int, current_time: float) -> None:
        """Convert SDL trigger axis values into press/release button events."""
        if current_time - self.last_trigger_time < self.trigger_cooldown:
            return
        is_pressed = raw_value > 16384
        if axis_code == PAD_AXIS_LEFT_TRIGGER and is_pressed != self.lt_pressed:
            self.lt_pressed = is_pressed
            self.button_event.emit(axis_code, int(is_pressed))
            self.last_trigger_time = current_time
        elif axis_code == PAD_AXIS_RIGHT_TRIGGER and is_pressed != self.rt_pressed:
            self.rt_pressed = is_pressed
            self.button_event.emit(axis_code, int(is_pressed))
            self.last_trigger_time = current_time

    def _is_mouse_emulation_active(self) -> bool:
        """Return True when the gamepad currently drives mouse emulation."""
        return self.mouse_emulation_enabled and self.emulation_active and self.emulation_triggered

    def _should_skip_regular_events(self) -> bool:
        """Skip regular UI events while mouse emulation owns the controller."""
        return self._is_mouse_emulation_active() and QApplication.activeWindow() is not None

    def _poll_gamepad(self) -> None:
        if not self.running or self._gamepad_polling_suspended:
            return
        current_time = time.time()
        active_gamepad = self.gamepad
        if not active_gamepad:
            if current_time - self._last_gamepad_check_time >= 1.0:
                self.gamepad_hotplug.emit('add')
                self._last_gamepad_check_time = current_time
            return
        try:
            active_changed = active_gamepad.update()
            if not active_gamepad.connected():
                self.gamepad_hotplug.emit('remove')
                return
            if active_changed:
                self._reset_input_state()
                logger.info(
                    "Active gamepad changed to SDL instance %s",
                    active_gamepad.active_instance_id,
                )
            self._poll_button_events(active_gamepad, current_time)
            self._handle_pending_menu_fullscreen(current_time)
            self._poll_hat_events(active_gamepad, current_time)
            self._poll_axis_events(active_gamepad, current_time)
            if (
                current_time - self.last_update >= self.update_interval and
                self.mouse_emulation_enabled and self.emulation_active and self.emulation_triggered
            ):
                self.update_mouse_position()
                self.last_update = current_time
        except Exception as error:
            logger.error("Unexpected error in gamepad polling: %s", error, exc_info=True)

    def cleanup(self) -> None:
        """
        Proper shutdown of gamepad and udev monitor.
        """
        try:
            # Mouse emulation cleanup
            self.disable_mouse_emulation()

            # Stop focus check timer
            self.focus_check_timer.stop()

            # Flag to stop udev monitor loop
            self.running = False

            # Stop all timers
            if hasattr(self, 'gamepad_poll_timer'):
                self.gamepad_poll_timer.stop()
            self.dpad_timer.stop()
            self.nav_timer.stop()

            if self.gamepad:
                self.gamepad.close()

            self.gamepad = None
            self._reset_input_state()
            self.gamepad_type = self._get_configured_gamepad_type()
            shutdown_gamepad_backend()

            logger.info("Gamepad cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
