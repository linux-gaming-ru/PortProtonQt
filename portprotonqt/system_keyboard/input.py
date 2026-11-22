"""System input for the themed on-screen keyboard."""

from queue import Empty, Queue
from threading import Event
import time
from typing import Any

from evdev import UInput, ecodes
from PySide6.QtCore import QThread, Signal

from portprotonqt.logger import get_logger

logger = get_logger(__name__)

INPUT_POLL_SECONDS = 0.15
KEY_ROWS = (
    (ecodes.KEY_GRAVE, *range(ecodes.KEY_1, ecodes.KEY_EQUAL + 1)),
    (ecodes.KEY_TAB, *range(ecodes.KEY_Q, ecodes.KEY_RIGHTBRACE + 1), ecodes.KEY_BACKSLASH),
    (ecodes.KEY_CAPSLOCK, *range(ecodes.KEY_A, ecodes.KEY_APOSTROPHE + 1)),
    (ecodes.KEY_LEFTSHIFT, ecodes.KEY_102ND, *range(ecodes.KEY_Z, ecodes.KEY_SLASH + 1)),
)
SPECIAL_KEYS = (
    ecodes.KEY_BACKSPACE, ecodes.KEY_ENTER, ecodes.KEY_SPACE,
    ecodes.KEY_HOME, ecodes.KEY_END, ecodes.KEY_LEFT, ecodes.KEY_RIGHT,
    ecodes.KEY_UP, ecodes.KEY_DOWN,
    ecodes.KEY_LEFTCTRL, ecodes.KEY_KBD_LAYOUT_NEXT, ecodes.KEY_DELETE,
    ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT, ecodes.KEY_LEFTMETA,
)


class SystemInputWorker(QThread):
    """Own the input backend and serialize all key events off the UI thread."""

    ready = Signal()
    failed = Signal(str)
    state_changed = Signal(dict)
    warning = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.commands: Queue[tuple[str, tuple[int, ...]]] = Queue()
        self.stopping = Event()
        self.enabled = Event()
        self.modifiers: set[int] = set()
        self.pending_super = False
        self.caps_lock = False
        self.layout: Any = None
        self.manual_layout = False

    def run(self) -> None:
        from portprotonqt.system_keyboard.keys import SERVICE_KEYS

        device = None
        try:
            keys = {code for row in KEY_ROWS for code in row} | set(SPECIAL_KEYS)
            keys.update(code for _, code in SERVICE_KEYS)
            device = UInput({ecodes.EV_KEY: sorted(keys), ecodes.EV_LED: [ecodes.LED_CAPSL]},
                            name="PortProtonQt Keyboard", bustype=ecodes.BUS_USB)
            self._load_layout()
            self.ready.emit()
            self._run_commands(device)
        except OSError as error:
            logger.warning("System keyboard input unavailable: %s", error)
            self.failed.emit(str(error))
        except Exception as error:
            logger.exception("System keyboard input failed")
            self.failed.emit(str(error))
        finally:
            if device is not None:
                self._set_modifiers(device, ())
                device.close()
            close_layout = getattr(self.layout, 'close', None)
            if close_layout is not None:
                close_layout()

    def _run_commands(self, device: UInput) -> None:
        next_poll = 0.0
        while not self.stopping.is_set():
            try:
                action, codes = self.commands.get(timeout=INPUT_POLL_SECONDS)
            except Empty:
                action, codes = '', ()
            if self.stopping.is_set():
                break
            try:
                if action:
                    self._execute(device, action, codes)
            except RuntimeError as error:
                logger.warning('System keyboard command failed: %s', error)
                self.warning.emit(str(error))
            except ValueError as error:
                logger.warning('Invalid system keyboard command: %s', error)
                self.warning.emit(str(error))
            if action or time.monotonic() >= next_poll:
                self._refresh_state(device)
                next_poll = time.monotonic() + INPUT_POLL_SECONDS

    def _load_layout(self) -> None:
        import os
        from portprotonqt.system_keyboard.detection import compositor, detect_layout
        from portprotonqt.system_keyboard.layouts import ManualLayout
        try:
            self.layout = detect_layout()
        except Exception as error:
            if not compositor(os.environ):
                raise
            logger.warning("System layout detection unavailable: %s", error)
            self.layout = ManualLayout()
            self.manual_layout = True
            self.warning.emit(f'{error}. Manual US/RU labels; external layout changes are not tracked.')

    def _execute(self, device: UInput, action: str, codes: tuple[int, ...]) -> None:
        from portprotonqt.system_keyboard.detection import CinnamonLayout, GSettingsLayout, KDELayout, LabwcLayout, X11Layout, is_x11_session
        import os
        if action in {'tap', 'caps', 'language', 'modifiers'} and not self.enabled.is_set():
            return
        if action == 'modifiers':
            if isinstance(self.layout, LabwcLayout):
                self._set_labwc_modifiers(device, codes)
                return
            modifier_only = ((self.modifiers == {ecodes.KEY_LEFTMETA}
                              and not is_x11_session(os.environ))
                             or (len(self.modifiers) == 2 and ecodes.KEY_LEFTALT in self.modifiers
                                 and bool(self.modifiers & {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})))
            if self.modifiers - set(codes) and modifier_only:
                # Replay modifier-only chords after the mouse release, with Shift last.
                chord = tuple(sorted(self.modifiers, key=lambda code: (
                    code in {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}, code)))
                self._set_modifiers(device, ())
                self.send_keys(device, chord)
            self._set_modifiers(device, codes)
        elif action == 'release':
            self.pending_super = False
            self._set_modifiers(device, ())
        elif action == 'caps':
            if isinstance(self.layout, X11Layout) and is_x11_session(os.environ):
                self.layout.toggle_caps_lock()
            else:
                self.send_keys(device, (ecodes.KEY_CAPSLOCK,))
        elif action == 'language':
            self.pending_super = False
            self._set_modifiers(device, ())
            if (type(self.layout) is X11Layout
                    and 'gnome' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')):
                self.send_keys(device, GSettingsLayout.switch_codes())
            elif isinstance(self.layout, X11Layout) and is_x11_session(os.environ):
                self.layout.switch()
            elif isinstance(self.layout, CinnamonLayout):
                self.send_keys(device, self.layout.switch_codes())
            elif isinstance(self.layout, KDELayout):
                self.layout.switch()
            elif isinstance(self.layout, GSettingsLayout):
                self.send_keys(device, self.layout.switch_codes())
            elif self.manual_layout:
                self.send_keys(device, (ecodes.KEY_KBD_LAYOUT_NEXT,))
                self.layout.switch()
            elif hasattr(self.layout, 'switch') and not isinstance(self.layout, X11Layout):
                self.layout.switch()
            else:
                self.send_keys(device, (ecodes.KEY_KBD_LAYOUT_NEXT,))
        elif action == 'tap':
            try:
                if self.pending_super:
                    self.pending_super = False
                    self._set_modifiers(device, (ecodes.KEY_LEFTMETA,))
                self.send_keys(device, tuple(code for code in codes if code not in self.modifiers))
            finally:
                self._set_modifiers(device, ())

    def _set_labwc_modifiers(self, device: UInput, codes: tuple[int, ...]) -> None:
        requested = set(codes)
        super_key = {ecodes.KEY_LEFTMETA}
        if self.pending_super and not requested:
            # Send both edges after the click; labwc cancels release bindings on pointer presses.
            self.pending_super = False
            self.send_keys(device, (ecodes.KEY_LEFTMETA,))
            return
        self.pending_super = requested == super_key and not self.modifiers
        if self.pending_super:
            return
        shift_keys = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}
        if (len(self.modifiers) == 2 and ecodes.KEY_LEFTALT in self.modifiers
                and self.modifiers & shift_keys and self.modifiers - requested):
            # XKB already switched when the chord was pressed; do not replay it.
            requested.difference_update(self.modifiers)
            self._set_modifiers(device, (ecodes.KEY_LEFTALT,))
        self._set_modifiers(device, tuple(requested))

    def _set_modifiers(self, device: UInput, codes: tuple[int, ...]) -> None:
        requested = set(codes)
        for code in sorted(self.modifiers - requested, reverse=True):
            try:
                device.write(ecodes.EV_KEY, code, 0)
                device.syn()
            except OSError:
                logger.exception('Failed to release system keyboard modifier %s', code)
                continue
            self.modifiers.discard(code)
        for code in sorted(requested - self.modifiers):
            self.modifiers.add(code)
            device.write(ecodes.EV_KEY, code, 1)
            device.syn()

    def _refresh_state(self, device: UInput) -> None:
        from portprotonqt.system_keyboard.detection import X11Layout, is_x11_session
        import os
        try:
            for event in device.read():
                if event.type == ecodes.EV_LED and event.code == ecodes.LED_CAPSL:
                    self.caps_lock = bool(event.value)
        except BlockingIOError:
            pass
        try:
            caps = (self.layout.caps_lock() if isinstance(self.layout, X11Layout)
                    and is_x11_session(os.environ) else self.caps_lock)
            modifiers = self.modifiers & {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT, ecodes.KEY_RIGHTALT}
            if caps:
                modifiers.add(ecodes.KEY_CAPSLOCK)
            labels = self.layout.labels(modifiers)
            current = getattr(self.layout, 'current', None)
            name = current[0] if isinstance(current, tuple) else getattr(self.layout, 'language', 'System')
            if hasattr(self.layout, 'layout_identifier'):
                name = self.layout.layout_identifier()
            active = self.modifiers | ({ecodes.KEY_LEFTMETA} if self.pending_super else set())
            self.state_changed.emit({'labels': labels, 'caps': caps,
                                     'shift': bool(active & {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}),
                                     'modifiers': tuple(sorted(active)), 'layout': name})
        except Exception as error:
            logger.warning("Cannot update system keyboard labels: %s", error)
            self.warning.emit(str(error))

    def send_keys(self, device: UInput, codes: tuple[int, ...]) -> None:
        pressed = []
        try:
            for code in codes:
                pressed.append(code)
                device.write(ecodes.EV_KEY, code, 1)
                device.syn()
        finally:
            for code in reversed(pressed):
                try:
                    device.write(ecodes.EV_KEY, code, 0)
                    device.syn()
                except OSError:
                    logger.exception("Failed to release system keyboard key %s", code)

    def stop(self) -> None:
        self.enabled.clear()
        self.stopping.set()
        self.commands.put(('', ()))
        self.wait()

    def cancel_pending(self) -> None:
        self.enabled.clear()
        while True:
            try:
                self.commands.get_nowait()
            except Empty:
                break
        self.commands.put(('release', ()))
