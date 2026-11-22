"""Reuse the embedded keyboard's buttons and theme for system input."""

import ctypes as C
from functools import partial
import mmap
import select
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, cast

import orjson
from evdev import ecodes
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSocketNotifier, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QMouseEvent, QImage, QRegion
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QSizePolicy, QWidget
from shiboken6 import isValid

from portprotonqt.config import gamepad_config, ui_config
from portprotonqt.input_manager.constants import GamepadType
from portprotonqt.keyboard_layouts import keyboard_layouts
from portprotonqt.logger import get_logger
from portprotonqt.tabs.control_hints import MainWindowControlHintsMixin
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.virtual_keyboard import VirtualKeyboard

from portprotonqt.system_keyboard.input import KEY_ROWS, SystemInputWorker
from portprotonqt.system_keyboard.keys import LATCH_KEYS, SERVICE_KEYS
from portprotonqt.system_keyboard.native import load_library

logger = get_logger(__name__)


def report(event: str, value: object = None) -> None:
    sys.stdout.buffer.write(orjson.dumps({'event': event, 'value': value}) + b'\n')
    sys.stdout.buffer.flush()


class SystemKeyboardPanel(VirtualKeyboard):
    def __init__(self, owner: 'SystemKeyboardWindow', theme: Any) -> None:
        self.owner = owner
        self.keycodes: dict[str, int] = {}
        self.labels: dict[str, str] = {}
        self.modifiers: set[int] = set()
        self.layout_name = 'System'
        self.drag_origin: QPoint | None = None
        self.emoji_open = False
        super().__init__(owner, theme)
        self.set_slide_animation_enabled(False)
        self.setObjectName('systemKeyboard')
        self.keyboard_container.setObjectName('systemKeyboardContainer')
        self.refresh_theme(theme)

    def refresh_theme(self, theme: Any) -> None:
        super().refresh_theme(theme)
        self.setStyleSheet(theme.VIRTUAL_KEYBOARD_STYLE + theme.SYSTEM_KEYBOARD_BACKGROUND_STYLE)

    def set_gamepad_icon(self, button: QPushButton, icon_type: str, gtype: Any = '') -> None:
        if self.owner.input_manager.gamepad:
            super().set_gamepad_icon(button, icon_type, gtype)
        else:
            button.setIcon(QIcon())

    def get_layouts_setxkbmap(self) -> list[str]:
        return ['us']

    def _space_button_text(self) -> str:
        return 'Space'

    def _save_focused_coords(self) -> tuple[int, int] | None:
        current = self.selected_button
        if current is None:
            return None
        index = self.keyboard_layout.indexOf(current)
        if index < 0:
            return None
        row, column, _, _ = cast(tuple[int, int, int, int], self.keyboard_layout.getItemPosition(index))
        return row, column

    def _apply_responsive_metrics(self) -> None:
        metrics = self.theme.SYSTEM_KEYBOARD
        self.num_cols = metrics['columns']
        self.button_height = metrics['key_height']
        self.spacing = metrics['spacing']
        margin = metrics['margin']
        self.keyboard_layout.setSpacing(self.spacing)
        self.keyboard_layout.setContentsMargins(margin, margin, margin, margin)
        width = min(self.owner.width(), metrics['width'])
        height = metrics['height'] + (metrics['warning_height'] if self.owner.warning_message else 0)
        if hasattr(self, 'keyboard_container'):
            self.keyboard_container.setFixedSize(width, height)
        for column in range(self.num_cols):
            self.keyboard_layout.setColumnStretch(column, 1)

    def update_keyboard(self) -> None:
        self._apply_responsive_metrics()
        selected = next((key for key, button in self.buttons.items() if button is self.selected_button), None)
        self.selected_button = None
        while self.keyboard_layout.count():
            item = self.keyboard_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.buttons.clear()
        self.keycodes = dict(SERVICE_KEYS)
        for row, codes in zip(keyboard_layouts['us']['normal'], KEY_ROWS, strict=True):
            self.keycodes.update(zip(row, codes, strict=True))
        units = self.theme.SYSTEM_KEYBOARD['row_units']
        rows = self.theme.SYSTEM_KEYBOARD['emoji_rows' if self.emoji_open else 'rows']
        for row, keys in enumerate(rows):
            column = 0
            for key, span in keys:
                if key == '▲▼':
                    self._add_key('▲', (row * units, column, 1, span))
                    self._add_key('▼', (row * units + 1, column, 1, span))
                else:
                    self._add_key(key, (row * units, column, units, span))
                column += span
        self.apply_key_state()
        default = rows[0][0][0]
        self._set_selected_button(self.buttons.get(selected or default, self.buttons[default]))
        if self.owner.warning_message:
            warning = QLabel(self.owner.warning_message)
            warning.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
            warning.setWordWrap(True)
            self.keyboard_layout.addWidget(warning, len(self.theme.SYSTEM_KEYBOARD['rows']) * units,
                                           0, units, self.num_cols)

    def _add_key(self, key: str, position: tuple[int, int, int, int]) -> None:
        button = QPushButton('⬆' if key == 'RShift' else key)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        button.setMinimumWidth(self.theme.SYSTEM_KEYBOARD['minimum_key_width'])
        units = self.theme.SYSTEM_KEYBOARD['row_units']
        height = (self.button_height + self.spacing) * position[2] // units - self.spacing
        button.setFixedHeight(height)
        code = self.keycodes.get(key)
        if code is not None and code in LATCH_KEYS:
            button.setCheckable(True)
            button.clicked.connect(lambda checked: self._toggle_modifier(code, checked))
        elif key == 'CAPS':
            button.setCheckable(True)
            button.clicked.connect(self.on_caps_click)
        elif key == '⌫':
            button.setProperty('sound_event', False)
            button.pressed.connect(self.on_backspace_pressed)
            button.released.connect(self.stop_backspace_repeat)
        elif key in {'🌐', 'Hide'}:
            button.clicked.connect(self.on_lang_click if key == '🌐' else self.hide)
        else:
            button.clicked.connect(lambda checked=False: self.on_button_click(key))
        self.keyboard_layout.addWidget(button, *position)
        self.buttons[key] = button
        icon = {'⬆': 'right', 'RShift': 'right', '⌫': 'add_game', '🌐': 'left', 'Hide': 'back'}.get(key)
        if icon is not None:
            self.set_gamepad_icon(button, icon, self.input_manager.gamepad_type)

    def _toggle_modifier(self, code: int, checked: bool) -> None:
        if checked:
            self.modifiers.add(code)
        else:
            self.modifiers.discard(code)
        self.shift_pressed = bool(self.modifiers & {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})
        self.owner.worker.commands.put(('modifiers', tuple(sorted(self.modifiers))))
        self.apply_key_state()

    def apply_key_state(self) -> None:
        for key, button in self.buttons.items():
            code = self.keycodes.get(key)
            if code not in LATCH_KEYS | {None, ecodes.KEY_TAB, ecodes.KEY_CAPSLOCK} and str(code) in self.labels:
                text = self.labels[str(code)].replace('&', '&&')
                if button.text() != text:
                    button.setText(text)
        for key, button in self.buttons.items():
            checked = None
            if key == 'CAPS':
                checked = self.caps_lock
            elif button.isCheckable():
                checked = self.keycodes[key] in self.modifiers
            if checked is not None and button.isChecked() != checked:
                button.setChecked(checked)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def _release_modifiers(self) -> None:
        self.modifiers.clear()
        self.shift_pressed = False
        self.owner.worker.commands.put(('release', ()))
        self.apply_key_state()

    def close_emoji_panel(self) -> None:
        if self.emoji_open:
            self.emoji_open = False
            self.update_keyboard()
            self._set_selected_button(self.buttons['🙂'])

    def on_button_click(self, key: str) -> None:
        if self.emoji_open:
            if key != 'ABC':
                report('emoji', key)
            self.close_emoji_panel()
            return
        if key == '🙂':
            self.stop_backspace_repeat()
            self._release_modifiers()
            self.emoji_open = True
            self.update_keyboard()
            self._set_selected_button(self.buttons['😀'])
            return
        code = ecodes.KEY_SPACE if key == ' ' else self.keycodes.get(key)
        if code is not None:
            self.owner.worker.commands.put(('tap', (code,)))

    def on_backspace_click(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_BACKSPACE,)))

    def on_enter_click(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_ENTER,)))

    def on_caps_click(self) -> None:
        self.apply_key_state()
        self.owner.worker.commands.put(('caps', ()))

    def on_shift_click(self, checked: bool) -> None:
        self._toggle_modifier(ecodes.KEY_LEFTSHIFT, checked)

    def on_lang_click(self) -> None:
        self.owner.worker.commands.put(('language', ()))

    def up_key(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_UP,)))

    def down_key(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_DOWN,)))

    def left_key(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_LEFT,)))

    def right_key(self) -> None:
        self.owner.worker.commands.put(('tap', (ecodes.KEY_RIGHT,)))

    def hide(self) -> None:
        self.stop_backspace_repeat()
        QFrame.hide(self)
        if getattr(self.owner, 'keyboard', None) is self:
            self.owner.hide_keyboard()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        return QFrame.eventFilter(self, obj, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag_origin is not None:
            position = event.globalPosition().toPoint()
            delta = position - self.drag_origin
            self.drag_origin = position
            if self.owner.layer_shell:
                position = self.pos() + delta
                self.move(max(0, min(position.x(), self.owner.width() - self.width())),
                          max(0, min(position.y(), self.owner.height() - self.height())))
            else:
                self.owner.move(self.owner.pos() + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag_origin = None
        super().mouseReleaseEvent(event)


class SystemKeyboardWindow(QWidget, MainWindowControlHintsMixin):
    def __init__(self, layer_shell: bool = False) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle('PortProtonQt System Keyboard')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_X11NetWmWindowTypeDock)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layer_shell = layer_shell
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, layer_shell)
        self.native_layer: Any = None
        self.theme_manager = ThemeManager()
        self.theme = self.theme_manager.apply_theme(ui_config.get_theme())
        gtype = GamepadType.PLAYSTATION if gamepad_config.get_gamepad_type() == 'playstation' else GamepadType.XBOX
        self.input_manager = SimpleNamespace(gamepad_type=gtype, gamepad=False)
        self.worker = SystemInputWorker()
        self.ready = False
        self.wanted_visible = False
        self.warning_message = ''
        self.resize(self.theme.SYSTEM_KEYBOARD['width'], self.theme.SYSTEM_KEYBOARD['height'])
        self.keyboard = SystemKeyboardPanel(self, self.theme)
        self.worker.ready.connect(self._ready)
        self.worker.failed.connect(self._failed)
        self.worker.state_changed.connect(self._state_changed)
        self.worker.warning.connect(self._warning)
        self._position_keyboard()
        screen = self.screen()
        if screen is not None:
            screen.availableGeometryChanged.connect(self._position_keyboard)
            screen.geometryChanged.connect(self._position_keyboard)

    def _position_keyboard(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        metrics = self.theme.SYSTEM_KEYBOARD
        area = screen.geometry() if self.layer_shell else screen.availableGeometry()
        available_width = self.width() if self.layer_shell else area.width()
        width, height = min(available_width, metrics['width']), metrics['height']
        if self.warning_message:
            height += metrics['warning_height']
        if self.layer_shell:
            self.keyboard.setFixedSize(width, height)
            self.keyboard.move((self.width() - width) // 2, max(0, self.height() - height))
        else:
            self.resize(width, height)
            self.move(area.x() + (area.width() - width) // 2, area.bottom() - height + 1)
            self.keyboard.setFixedSize(width, height)
            self.keyboard.move(0, 0)
        self.keyboard.update_keyboard()

    def show_keyboard(self) -> None:
        self.wanted_visible = True
        if not self.ready:
            return
        self.worker.enabled.set()
        self._position_keyboard()
        self.keyboard.show()
        self.show()
        self.keyboard.raise_()
        if self.native_layer is not None:
            self.native_layer.show_layer()

    def hide_keyboard(self) -> None:
        self.wanted_visible = False
        self.worker.cancel_pending()
        self.keyboard.stop_backspace_repeat()
        self.keyboard._release_modifiers()
        self.keyboard.close_emoji_panel()
        if self.native_layer is not None:
            self.native_layer.hide_layer()
        self.hide()
        report('hidden')

    def _ready(self) -> None:
        self.ready = True
        if self.wanted_visible:
            self.show_keyboard()

    def _failed(self, message: str) -> None:
        logger.error('System keyboard: %s', message)
        app = QApplication.instance()
        if app is not None:
            app.exit(1)

    def _warning(self, message: str) -> None:
        logger.warning('System keyboard: %s', message)
        if self.warning_message != message:
            self.warning_message = message
            self._position_keyboard()

    def _state_changed(self, state: dict[str, Any]) -> None:
        changed = self.keyboard.labels != state['labels'] or self.keyboard.caps_lock != state['caps']
        changed |= self.keyboard.shift_pressed != state['shift']
        changed |= self.keyboard.modifiers != set(state['modifiers'])
        changed |= self.keyboard.layout_name != state['layout']
        self.keyboard.labels = state['labels']
        self.keyboard.caps_lock = state['caps']
        self.keyboard.shift_pressed = state['shift']
        self.keyboard.modifiers = set(state['modifiers'])
        self.keyboard.layout_name = state['layout']
        self.keyboard.apply_key_state()
        if changed:
            report('shift', state['shift'])

    def command(self, action: str, value: Any = None) -> None:
        if action == 'show':
            self.show_keyboard()
        elif action == 'hide':
            self.hide_keyboard()
        elif action == 'theme' and isinstance(value, str):
            self.theme = self.theme_manager.apply_theme(value)
            self.keyboard.refresh_theme(self.theme)
            self.keyboard.current_theme_name = value
            self._position_keyboard()
        elif action == 'gamepad' and (value is None or isinstance(value, str)):
            self.input_manager.gamepad = value is not None
            if value is not None:
                self.input_manager.gamepad_type = GamepadType(value)
            self.keyboard.update_keyboard()
        elif action == 'direction' and value in ('up', 'down', 'left', 'right'):
            self.keyboard.focusNextKey(value)
        elif action == 'button' and self.ready and self.wanted_visible:
            handlers = {'confirm': self.keyboard.activateFocusedKey, 'back': self.hide_keyboard,
                        'language': self.keyboard.on_lang_click, 'backspace': self.keyboard.on_backspace_pressed,
                        'backspace_release': self.keyboard.stop_backspace_repeat}
            if self.keyboard.emoji_open and value != 'confirm':
                if value == 'back':
                    self.keyboard.close_emoji_panel()
                return
            if value == 'shift':
                self.keyboard.on_shift_click(not self.keyboard.shift_pressed)
            elif value in handlers:
                handlers[value]()
        elif action == 'quit':
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide_keyboard()

    def shutdown(self) -> None:
        self.keyboard.stop_backspace_repeat()
        self.worker.stop()
        if self.native_layer is not None:
            self.native_layer.shutdown()


WL_VERSION = 1
WL_DESTROY = 1
WL_FIXED_SCALE = 256
LAYER_OVERLAY = 3
ANCHOR_ALL_EDGES = 15
KEYBOARD_INTERACTIVITY_NONE = 0
SHM_ARGB8888 = 0
PIXEL_BYTES = 4
FRAME_INTERVAL_MS = 33
MAX_SURFACE_PIXELS = 33_177_600
POINTER_BUTTON_LEFT = 272


class WaylandWindow(QObject):
    """Keep native surfaces separate from Qt's offscreen platform plugin."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.callbacks: list[Any] = []
        self.proxies: list[int] = []
        self.buffers: dict[int, dict[str, Any]] = {}
        self.compositor = self.shm = self.shell = None
        self.seat: int | None = None
        self.surface = self.layer = self.pointer = self.touch = None
        self.display = None
        self.wanted_visible = self.configured = False
        self.dirty = True
        self.position = QPointF()
        self.pressed_widget: Any = None
        self.lib = load_library()
        self._configure_library()
        self.layer_interface = self._interface('zwlr_layer_surface_v1')
        self.shell_interface = self._interface('zwlr_layer_shell_v1')
        self.display = self.lib.portproton_keyboard_wayland_connect(None)
        if not self.display:
            raise RuntimeError('Cannot connect to the Wayland compositor')
        self.registry = self._request(self.display, (1, self._interface('wl_registry')), (C.c_void_p(),))
        self._listen(self.registry, [(self._global, [C.c_uint32, C.c_char_p, C.c_uint32]),
                                     (self._global_removed, [C.c_uint32])])
        self.sync = self._request(self.display, (0, self._interface('wl_callback')), (C.c_void_p(),))
        self._listen(self.sync, [(self._registry_ready, [C.c_uint32])])
        self.notifier = QSocketNotifier(self.lib.wl_display_get_fd(self.display), QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._dispatch)
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_INTERVAL_MS)
        self.timer.timeout.connect(self._render)
        self.timer.start()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.lib.wl_display_flush(self.display)

    def _configure_library(self) -> None:
        p = C.c_void_p
        functions = {
            'portproton_keyboard_wayland_connect': ([C.c_char_p], p),
            'portproton_keyboard_wayland_interface': ([C.c_char_p], p),
            'wl_display_disconnect': ([p], None),
            'wl_display_dispatch_pending': ([p], C.c_int),
            'wl_display_prepare_read': ([p], C.c_int),
            'wl_display_read_events': ([p], C.c_int),
            'wl_display_cancel_read': ([p], None),
            'wl_display_get_fd': ([p], C.c_int),
            'wl_display_flush': ([p], C.c_int),
            'wl_proxy_destroy': ([p], None),
            'wl_proxy_add_listener': ([p, p, p], C.c_int),
            'wl_proxy_marshal_flags': ([p, C.c_uint32, p, C.c_uint32, C.c_uint32], p),
        }
        for name, (args, result) in functions.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result

    def _interface(self, name: str) -> int:
        interface = self.lib.portproton_keyboard_wayland_interface(name.encode())
        if not interface:
            raise RuntimeError(f'Unknown Wayland interface: {name}')
        return interface

    def _request(self, proxy: int | None, request: tuple[int, Any], arguments: tuple[Any, ...] = ()) -> Any:
        opcode, interface = request
        result = self.lib.wl_proxy_marshal_flags(proxy, opcode, interface, WL_VERSION, 0, *arguments)
        if interface is not None:
            if not result:
                raise RuntimeError('Cannot create Wayland protocol object')
            self.proxies.append(result)
        return result

    def _listen(self, proxy: int, handlers: list[tuple[Any, list[Any]]]) -> None:
        callbacks = []
        for handler, types in handlers:
            def guarded(data: Any, obj: Any, *args: Any, handler: Any = handler) -> None:
                try:
                    handler(*args)
                except Exception:
                    logger.exception('System keyboard Wayland event failed')
                    QApplication.exit(1)
            callbacks.append(C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, *types)(guarded))
        table = (C.c_void_p * len(callbacks))(*[C.cast(callback, C.c_void_p) for callback in callbacks])
        self.callbacks.append((callbacks, table))
        if self.lib.wl_proxy_add_listener(proxy, table, None) != 0:
            raise RuntimeError('Cannot subscribe to Wayland events')

    def _global(self, name: int, interface: bytes, version: int) -> None:
        interfaces = {b'wl_compositor': ('compositor', self._interface('wl_compositor')),
                      b'wl_shm': ('shm', self._interface('wl_shm')),
                      b'zwlr_layer_shell_v1': ('shell', self.shell_interface),
                      b'wl_seat': ('seat', self._interface('wl_seat'))}
        if interface not in interfaces:
            return
        attribute, metadata = interfaces[interface]
        if getattr(self, attribute, None) is not None:
            return
        proxy = self._request(self.registry, (0, metadata),
                              (C.c_uint32(name), interface, C.c_uint32(WL_VERSION), C.c_void_p()))
        setattr(self, attribute, proxy)
        if interface == b'wl_seat':
            self._listen(proxy, [(self._seat_capabilities, [C.c_uint32])])
        self._create_surface()

    def _global_removed(self, name: int) -> None:
        logger.debug('Wayland global removed: %s', name)

    def _registry_ready(self, serial: int) -> None:
        self.lib.wl_proxy_destroy(self.sync)
        self.proxies.remove(self.sync)
        if not all((self.compositor, self.shm, self.shell)):
            logger.error('The compositor does not provide layer-shell or shared-memory surfaces')
            QApplication.exit(1)

    def show_layer(self) -> None:
        self.wanted_visible = True
        self._create_surface()

    def _create_surface(self) -> None:
        if self.surface or not self.wanted_visible or not all((self.compositor, self.shm, self.shell)):
            return
        self.surface = self._request(self.compositor, (0, self._interface('wl_surface')), (C.c_void_p(),))
        self._listen(self.surface, [(self._surface_output, [C.c_void_p]),
                                    (self._surface_output, [C.c_void_p])])
        self.layer = self._request(self.shell, (0, self.layer_interface),
                                  (C.c_void_p(), C.c_void_p(self.surface), C.c_void_p(),
                                   C.c_uint32(LAYER_OVERLAY), b'portprotonqt-system-keyboard'))
        self._listen(self.layer, [(self._configured, [C.c_uint32, C.c_uint32, C.c_uint32]),
                                  (self.window.hide_keyboard, [])])
        self._request(self.layer, (0, None), (C.c_uint32(0), C.c_uint32(0)))
        self._request(self.layer, (1, None), (C.c_uint32(ANCHOR_ALL_EDGES),))
        self._request(self.layer, (2, None), (C.c_int32(-1),))
        self._request(self.layer, (4, None), (C.c_uint32(KEYBOARD_INTERACTIVITY_NONE),))
        self._input_region(False)
        self._request(self.surface, (6, None))
        self.lib.wl_display_flush(self.display)

    def _configured(self, serial: int, width: int, height: int) -> None:
        if not width or not height or width * height > MAX_SURFACE_PIXELS:
            raise ValueError('Invalid Wayland layer-surface dimensions')
        self._request(self.layer, (6, None), (C.c_uint32(serial),))
        if self.configured and (width, height) == (self.window.width(), self.window.height()):
            return
        self.window.resize(width, height)
        self.window._position_keyboard()
        self.configured = self.dirty = True

    def _surface_output(self, output: int) -> None:
        self.dirty = True

    def _input_region(self, include_panel: bool = True) -> None:
        region = self._request(self.compositor, (1, self._interface('wl_region')), (C.c_void_p(),))
        if include_panel:
            rect = self.window.keyboard.geometry()
            args = tuple(C.c_int32(value) for value in (rect.x(), rect.y(), rect.width(), rect.height()))
            self._request(region, (1, None), args)
        self._request(self.surface, (5, None), (C.c_void_p(region),))
        self._destroy(region, 0)

    def _destroy(self, proxy: int | None, opcode: int) -> None:
        if proxy is not None:
            self.lib.wl_proxy_marshal_flags(proxy, opcode, None, WL_VERSION, WL_DESTROY)
            self.proxies.remove(proxy)

    def _buffer(self, width: int, height: int) -> int | None:
        size = width * height * PIXEL_BYTES
        for proxy, buffer in self.buffers.items():
            if buffer['size'] == (width, height) and not buffer['busy']:
                return proxy
        if sum(buffer['size'] == (width, height) for buffer in self.buffers.values()) >= 2:
            return None
        with tempfile.TemporaryFile() as storage:
            storage.truncate(size)
            memory = mmap.mmap(storage.fileno(), size)
            try:
                pool = self._request(self.shm, (0, self._interface('wl_shm_pool')),
                                      (C.c_void_p(), C.c_int(storage.fileno()), C.c_int32(size)))
                proxy = self._request(pool, (0, self._interface('wl_buffer')),
                                     (C.c_void_p(), C.c_int32(0), C.c_int32(width), C.c_int32(height),
                                      C.c_int32(width * PIXEL_BYTES), C.c_uint32(SHM_ARGB8888)))
                self._destroy(pool, 1)
            except Exception:
                memory.close()
                raise
        self.buffers[proxy] = {'memory': memory, 'size': (width, height), 'busy': False}
        self._listen(proxy, [(partial(self._released, proxy), [])])
        return proxy

    def _released(self, proxy: int) -> None:
        buffer = self.buffers.get(proxy)
        if buffer is not None:
            buffer['busy'] = False
            if buffer['size'] != (self.window.width(), self.window.height()):
                self._destroy(proxy, 0)
                buffer['memory'].close()
                del self.buffers[proxy]

    def _render(self) -> None:
        if not self.surface or not self.configured or not self.dirty:
            return
        width, height = self.window.width(), self.window.height()
        proxy = self._buffer(width, height)
        if proxy is None:
            return
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        self.dirty = False
        self.window.render(image, QPoint(), QRegion(), self.window.RenderFlag.DrawChildren)
        buffer = self.buffers[proxy]
        buffer['memory'].seek(0)
        buffer['memory'].write(image.constBits())
        buffer['busy'] = True
        self._request(self.surface, (1, None), (C.c_void_p(proxy), C.c_int32(0), C.c_int32(0)))
        self._request(self.surface, (2, None), tuple(C.c_int32(v) for v in (0, 0, width, height)))
        self._input_region()
        self._request(self.surface, (6, None))
        self.lib.wl_display_flush(self.display)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.UpdateRequest:
            self.dirty = True
        return False

    def _dispatch(self) -> None:
        while self.lib.wl_display_prepare_read(self.display) != 0:
            if self.lib.wl_display_dispatch_pending(self.display) < 0:
                QApplication.exit(1)
                return
        fd = self.lib.wl_display_get_fd(self.display)
        if select.select([fd], [], [], 0)[0]:
            result = self.lib.wl_display_read_events(self.display)
        else:
            self.lib.wl_display_cancel_read(self.display)
            result = 0
        if result < 0 or self.lib.wl_display_dispatch_pending(self.display) < 0:
            logger.error('System keyboard Wayland connection closed')
            QApplication.exit(1)
            return
        self.lib.wl_display_flush(self.display)

    def _seat_capabilities(self, capabilities: int) -> None:
        if capabilities & 1 and self.pointer is None:
            self.pointer = self._request(self.seat, (0, self._interface('wl_pointer')), (C.c_void_p(),))
            u, i, p = C.c_uint32, C.c_int32, C.c_void_p
            self._listen(self.pointer, [(self._pointer_enter, [u, p, i, i]),
                                        (self._pointer_leave, [u, p]),
                                        (self._pointer_motion, [u, i, i]),
                                        (self._pointer_button, [u, u, u, u]),
                                        (self._pointer_axis, [u, u, i])])
        if capabilities & 4 and self.touch is None:
            self.touch = self._request(self.seat, (2, self._interface('wl_touch')), (C.c_void_p(),))
            u, i, p = C.c_uint32, C.c_int32, C.c_void_p
            self._listen(self.touch, [(self._touch_down, [u, u, p, i, i, i]),
                                      (self._touch_up, [u, u, i]), (self._touch_motion, [u, i, i, i]),
                                      (self._touch_frame, []), (self._touch_cancel, [])])

    def _pointer_enter(self, *event: int) -> None:
        serial, surface, x, y = event
        self.position = QPointF(x / WL_FIXED_SCALE, y / WL_FIXED_SCALE)

    def _pointer_leave(self, serial: int, surface: int) -> None:
        self.dirty = True

    def _pointer_motion(self, timestamp: int, x: int, y: int) -> None:
        self.position = QPointF(x / WL_FIXED_SCALE, y / WL_FIXED_SCALE)
        self._mouse_event(QEvent.Type.MouseMove)

    def _pointer_button(self, *event: int) -> None:
        serial, timestamp, button, state = event
        if button == POINTER_BUTTON_LEFT:
            kind = QEvent.Type.MouseButtonPress if state else QEvent.Type.MouseButtonRelease
            self._mouse_event(kind)

    def _pointer_axis(self, timestamp: int, axis: int, value: int) -> None:
        logger.debug('System keyboard pointer axis: %s', axis)

    def _touch_down(self, *event: int) -> None:
        serial, timestamp, surface, touch_id, x, y = event
        if self.pressed_widget is None:
            self.touch_id = touch_id
            self.position = QPointF(x / WL_FIXED_SCALE, y / WL_FIXED_SCALE)
            self._mouse_event(QEvent.Type.MouseButtonPress)

    def _touch_up(self, serial: int, timestamp: int, touch_id: int) -> None:
        if touch_id == getattr(self, 'touch_id', None):
            self._mouse_event(QEvent.Type.MouseButtonRelease)
            self.touch_id = None

    def _touch_motion(self, *event: int) -> None:
        timestamp, touch_id, x, y = event
        if touch_id == getattr(self, 'touch_id', None):
            self._pointer_motion(timestamp, x, y)

    def _touch_frame(self) -> None:
        self.dirty = True

    def _touch_cancel(self) -> None:
        self.touch_id = None
        self.pressed_widget = None
        self.window.keyboard.stop_backspace_repeat()

    def _mouse_event(self, kind: QEvent.Type) -> None:
        pressed = self.pressed_widget
        if pressed is not None and (not isValid(pressed) or not self.window.isAncestorOf(pressed)):
            self.pressed_widget = None
            self.window.keyboard.stop_backspace_repeat()
            self.dirty = True
        if kind == QEvent.Type.MouseButtonRelease and self.pressed_widget is None:
            return
        point = self.position.toPoint()
        target = self.pressed_widget or self.window.childAt(point) or self.window.keyboard
        if isinstance(target, QPushButton) and self.window.keyboard.selected_button is not target:
            self.window.keyboard._set_selected_button(target)
        if kind == QEvent.Type.MouseButtonPress:
            self.pressed_widget = target
        local = QPointF(target.mapFrom(self.window, point))
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        held = self.pressed_widget is not None and kind != QEvent.Type.MouseButtonRelease
        buttons = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
        event = QMouseEvent(kind, local, self.position, button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, event)
        if kind == QEvent.Type.MouseButtonRelease:
            self.pressed_widget = None
        self.dirty = True

    def hide_layer(self) -> None:
        self.wanted_visible = self.configured = False
        self.pressed_widget = None
        self._destroy(self.layer, 7)
        self._destroy(self.surface, 0)
        self.layer = self.surface = None
        self.lib.wl_display_flush(self.display)

    def shutdown(self) -> None:
        self.timer.stop()
        self.notifier.setEnabled(False)
        if self.display:
            for proxy in reversed(self.proxies):
                self.lib.wl_proxy_destroy(proxy)
            self.proxies.clear()
            self.lib.wl_display_disconnect(self.display)
            self.display = None
        for buffer in self.buffers.values():
            buffer['memory'].close()
        self.buffers.clear()
