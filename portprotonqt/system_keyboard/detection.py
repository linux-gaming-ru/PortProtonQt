"""Detect active keyboard layouts through X11, compositor IPC or desktop settings."""

import ast
import asyncio
import ctypes as C
import os
import re
import select
import socket
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import orjson
from evdev import ecodes
from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus

from portprotonqt.logger import get_logger
from portprotonqt.scripts_utils.dbus_tools import _bus_call, dbus_call
from portprotonqt.system_keyboard.keys import (ROWS, MODIFIERS, XKB_KEYCODE_OFFSET, XKB_CORE_KEYBOARD,
                   XKB_SHIFT_MASK, XKB_LOCK_MASK, XKB_ALTGR_MASK, XKB_GROUP_COUNT, XKB_GROUP_SHIFT)
from portprotonqt.system_keyboard.layouts import Layout, keysym_label
from portprotonqt.system_keyboard.native import load_library

logger = get_logger(__name__)
LAYOUT_NAME_BUFFER_BYTES = 256
WAYFIRE_IPC_HEADER_BYTES = 4
WAYFIRE_IPC_MAX_REPLY_BYTES = 64 * 1024
WAYFIRE_IPC_TIMEOUT = 1.0
IBUS_SCHEMA = 'org.freedesktop.ibus.general'


def is_x11_session(environment: Mapping[str, str]) -> bool:
    if environment.get('XDG_SESSION_TYPE'):
        return environment['XDG_SESSION_TYPE'] == 'x11'
    return bool(environment.get('DISPLAY')) and not environment.get('WAYLAND_DISPLAY')


class X11Layout:
    def __init__(self) -> None:
        self.display = None
        self.lib = load_library()
        functions = {
            'portproton_keyboard_x11_open_display': ([C.c_char_p], C.c_void_p),
            'XCloseDisplay': ([C.c_void_p], C.c_int),
            'portproton_keyboard_x11_state': ([C.c_void_p, C.POINTER(C.c_uint)], C.c_int),
            'XkbLockGroup': ([C.c_void_p, C.c_uint, C.c_uint], C.c_int),
            'XkbLockModifiers': ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint], C.c_int),
            'portproton_keyboard_x11_keysym': ([C.c_void_p, C.c_uint, C.c_uint], C.c_uint),
            'XStringToKeysym': ([C.c_char_p], C.c_ulong),
            'XKeysymToKeycode': ([C.c_void_p, C.c_ulong], C.c_ubyte),
            'XSync': ([C.c_void_p, C.c_int], C.c_int),
            'portproton_keyboard_x11_layout_name': ([C.c_void_p, C.c_uint, C.c_void_p, C.c_size_t], C.c_int),
        }
        for name, (args, result) in functions.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.display = self.lib.portproton_keyboard_x11_open_display(None)
        if not self.display:
            raise RuntimeError('Cannot read the X11 keyboard layout')

    def state(self) -> SimpleNamespace:
        values = (C.c_uint * 3)()
        if not self.lib.portproton_keyboard_x11_state(self.display, values):
            raise RuntimeError('Cannot read XKB state')
        return SimpleNamespace(group=values[0], mods=values[1], locked_mods=values[2])

    def switch(self) -> None:
        group = (self.state().group + 1) % XKB_GROUP_COUNT
        if not self.lib.XkbLockGroup(self.display, XKB_CORE_KEYBOARD, group):
            raise RuntimeError('Cannot switch XKB layout')
        self.lib.XSync(self.display, False)

    def caps_lock(self) -> bool:
        return bool(self.state().locked_mods & XKB_LOCK_MASK)

    def layout_identifier(self) -> str:
        name = C.create_string_buffer(LAYOUT_NAME_BUFFER_BYTES)
        if self.lib.portproton_keyboard_x11_layout_name(self.display, self.state().group, name, len(name)):
            return name.value.decode()
        return 'System'

    def toggle_caps_lock(self) -> None:
        value = 0 if self.caps_lock() else XKB_LOCK_MASK
        if not self.lib.XkbLockModifiers(self.display, XKB_CORE_KEYBOARD, XKB_LOCK_MASK, value):
            raise RuntimeError('Cannot switch XKB Caps Lock')
        self.lib.XSync(self.display, False)

    def keycode(self, name: str) -> int:
        symbol = self.lib.XStringToKeysym(name.encode())
        code = self.lib.XKeysymToKeycode(self.display, symbol) if symbol else 0
        if code < XKB_KEYCODE_OFFSET:
            raise ValueError(f'Unknown shortcut key: {name}')
        return code - XKB_KEYCODE_OFFSET

    def labels(self, modifiers: set[int] | tuple[int, ...] = ()) -> dict[str, str]:
        state = self.state()
        mask = state.mods & (XKB_SHIFT_MASK | XKB_LOCK_MASK | XKB_ALTGR_MASK)
        for code, bit in ((ecodes.KEY_LEFTSHIFT, XKB_SHIFT_MASK),
                          (ecodes.KEY_RIGHTSHIFT, XKB_SHIFT_MASK),
                          (ecodes.KEY_CAPSLOCK, XKB_LOCK_MASK),
                          (ecodes.KEY_RIGHTALT, XKB_ALTGR_MASK)):
            if code in modifiers:
                mask |= bit
        # Match XkbBuildCoreState from X11/extensions/XKB.h.
        mask |= state.group << XKB_GROUP_SHIFT
        result = {}
        for row in ROWS:
            for fallback, code in row:
                if code in MODIFIERS or code in {ecodes.KEY_TAB, ecodes.KEY_CAPSLOCK}:
                    continue
                value = self.lib.portproton_keyboard_x11_keysym(
                    self.display, code + XKB_KEYCODE_OFFSET, mask)
                character = keysym_label(value) if value else ''
                result[str(code)] = character if character.isprintable() else fallback
        return result

    def close(self) -> None:
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None


class IBusLayout(X11Layout):
    def switch(self) -> None:
        text = command(['gsettings', 'get', IBUS_SCHEMA, 'preload-engines']).strip()
        engines = ast.literal_eval(re.sub(r'^@as\s+', '', text))
        if (not isinstance(engines, list) or not engines
                or any(not isinstance(engine, str) or not engine.startswith('xkb:') for engine in engines)):
            raise ValueError('IBus input sources must be XKB keyboard layouts')
        current = command(['ibus', 'engine']).strip()
        if current not in engines:
            raise RuntimeError('Current IBus engine is not in the configured input sources')
        following = engines[(engines.index(current) + 1) % len(engines)]
        command(['ibus', 'engine', following])


class CosmicLayout:
    use_cosmic_protocol = True

    def __init__(self) -> None:
        self.display = self.layout = None
        # Labwc sends the keymap first and may defer the group until a modifier event.
        self.group = None if self.use_cosmic_protocol else 0
        self.error = None
        self.callbacks, self.proxies = [], []
        self.keyboard = self.manager = self.tracker = None
        self.lib = load_library()
        self._configure_library()
        if self.use_cosmic_protocol:
            self.group_interface = self._interface('zcosmic_keyboard_layout_v1')
            self.manager_interface = self._interface('zcosmic_keyboard_layout_manager_v1')
        try:
            self.display = self.lib.portproton_keyboard_wayland_connect(None)
            if not self.display:
                raise RuntimeError('Failed to connect to Wayland')
            self.registry = self._new(self.display, (1, self._interface('wl_registry')), C.c_void_p())
            self._listen(self.registry, [
                (self._global, [C.c_uint32, C.c_char_p, C.c_uint32]),
                (lambda *args: None, [C.c_uint32])])
            for _ in range(4):
                self._check(self.lib.wl_display_roundtrip(self.display))
            if self.layout is None or self.group is None:
                raise RuntimeError('Wayland keyboard layout or keymap unavailable')
        except Exception:
            self.close()
            raise

    def _configure_library(self) -> None:
        p = C.c_void_p
        for name, args, result in (
            ('portproton_keyboard_wayland_connect', [C.c_char_p], p),
            ('portproton_keyboard_wayland_interface', [C.c_char_p], p),
            ('wl_display_disconnect', [p], None),
            ('wl_display_roundtrip', [p], C.c_int),
            ('wl_display_dispatch', [p], C.c_int),
            ('wl_display_dispatch_pending', [p], C.c_int),
            ('wl_display_get_fd', [p], C.c_int),
            ('wl_display_flush', [p], C.c_int),
            ('wl_proxy_destroy', [p], None),
            ('wl_proxy_add_listener', [p, p, p], C.c_int),
            ('wl_proxy_marshal_flags', [p, C.c_uint32, p,
                                        C.c_uint32, C.c_uint32], p),
        ):
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result

    def _interface(self, name: str) -> int:
        interface = self.lib.portproton_keyboard_wayland_interface(name.encode())
        if not interface:
            raise RuntimeError(f'Unknown Wayland interface: {name}')
        return interface

    def _new(self, proxy: Any, request: tuple[Any, Any], *args: Any) -> Any:
        opcode, interface = request
        result = self.lib.wl_proxy_marshal_flags(proxy, opcode, interface,
                                                1, 0, *args)
        if not result:
            raise RuntimeError('COSMIC: failed to create Wayland object')
        self.proxies.append(result)
        return result

    def _listen(self, proxy: Any, handlers: Any) -> None:
        callbacks = []
        for handler, types in handlers:
            def guarded(data: Any, obj: Any, *args: Any, handler: Any = handler) -> None:
                try:
                    handler(*args)
                except Exception as exc:
                    self.error = exc
            callbacks.append(C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, *types)(guarded))
        table = (C.c_void_p * len(callbacks))(*[C.cast(fn, C.c_void_p) for fn in callbacks])
        self.callbacks.append((callbacks, table))
        if self.lib.wl_proxy_add_listener(proxy, table, None) != 0:
            raise RuntimeError('COSMIC: failed to subscribe to Wayland events')

    def _global(self, name: Any, interface: Any, version: Any) -> None:
        if interface == b'wl_seat' and not hasattr(self, 'seat'):
            self.seat = self._new(self.registry, (0, self._interface('wl_seat')),
                                 C.c_uint32(name), interface, C.c_uint32(1), C.c_void_p())
            self._listen(self.seat, [(self._capabilities, [C.c_uint32])])
        elif (self.use_cosmic_protocol and interface == b'zcosmic_keyboard_layout_manager_v1'
              and self.manager is None):
            self.manager = self._new(self.registry, (0, self.manager_interface),
                                    C.c_uint32(name), interface, C.c_uint32(1), C.c_void_p())
            self._track()

    def _capabilities(self, capabilities: Any) -> None:
        if capabilities & 2 and self.keyboard is None:
            self.keyboard = self._new(self.seat, (1, self._interface('wl_keyboard')), C.c_void_p())
            u, p = C.c_uint32, C.c_void_p
            modifiers = (lambda *args: None) if self.use_cosmic_protocol else (
                lambda serial, depressed, latched, locked, group: self._group(group))
            self._listen(self.keyboard, [
                (self._keymap, [u, C.c_int, u]),
                (lambda *args: None, [u, p, p]),
                (lambda *args: None, [u, p]),
                (lambda *args: None, [u, u, u, u]),
                (modifiers, [u, u, u, u, u])])
            self._track()
        elif not capabilities & 2 and self.keyboard is not None:
            self.error = RuntimeError('COSMIC: keyboard disconnected')

    def _track(self) -> None:
        if self.keyboard and self.manager and self.tracker is None:
            self.tracker = self._new(self.manager, (0, self.group_interface),
                                     C.c_void_p(), C.c_void_p(self.keyboard))
            self._listen(self.tracker, [(self._group, [C.c_uint32])])

    def _group(self, group: Any) -> None:
        self.group = group

    def layout_identifier(self) -> str:
        if self.layout is None or self.group is None:
            return 'System'
        return self.layout.layout_identifier(self.group)

    def _keymap(self, format: Any, fd: Any, size: Any) -> None:
        try:
            if format != 1 or not 0 < size <= 16 * 1024 * 1024:
                raise RuntimeError('COSMIC: invalid Wayland keymap')
            text = os.pread(fd, size, 0)
            if len(text) != size:
                raise RuntimeError('COSMIC: incomplete Wayland keymap')
            replacement = Layout(keymap_text=text)
        finally:
            os.close(fd)
        self.layout = replacement

    def _check(self, result: Any) -> None:
        if result < 0:
            raise RuntimeError('COSMIC: Wayland connection closed')
        if self.error is not None:
            raise self.error

    def labels(self, modifiers: Any=()) -> Any:
        self._check(self.lib.wl_display_dispatch_pending(self.display))
        fd = self.lib.wl_display_get_fd(self.display)
        for _ in range(32):
            if not select.select([fd], [], [], 0)[0]:
                break
            self._check(self.lib.wl_display_dispatch(self.display))
        if self.layout is None or self.group is None:
            raise RuntimeError('COSMIC: keyboard layout unavailable')
        return self.layout.labels(modifiers, mask=(0, 0, 0, self.group))

    def close(self) -> None:
        if self.layout is not None:
            self.layout = None
        if self.display:
            for proxy in reversed(self.proxies):
                self.lib.wl_proxy_destroy(proxy)
            self.proxies.clear()
            self.lib.wl_display_disconnect(self.display)
            self.display = None


class LabwcLayout(CosmicLayout):
    # Labwc broadcasts wl_keyboard group changes even without keyboard focus.
    use_cosmic_protocol = False


SOURCE_SCHEMA = 'org.gnome.desktop.input-sources'
BINDINGS_SCHEMA = 'org.gnome.desktop.wm.keybindings'
SHORTCUT_MODIFIERS = {
    'Control': ecodes.KEY_LEFTCTRL, 'Ctrl': ecodes.KEY_LEFTCTRL,
    'Primary': ecodes.KEY_LEFTCTRL, 'Alt': ecodes.KEY_LEFTALT,
    'Shift': ecodes.KEY_LEFTSHIFT, 'Super': ecodes.KEY_LEFTMETA,
}


class GSettingsLayout:
    def __init__(self) -> None:
        self.layout: Layout | None = None
        self.current: tuple[str, str] | None = None
        self._update()

    def _read(self, key: str) -> object:
        text = command(['gsettings', 'get', SOURCE_SCHEMA, key]).strip()
        text = re.sub(r'^@[a-z()]+\s+|^uint32\s+', '', text)
        if text in ('true', 'false'):
            return text == 'true'
        return ast.literal_eval(text)

    def _source(self) -> tuple[str, str]:
        sources = self._read('sources')
        if self._read('per-window'):
            raise ValueError('GSettings cannot track per-window input sources')
        if not isinstance(sources, list) or not sources:
            raise ValueError('GSettings has no input sources')
        if len(sources) == 1:
            selected = sources[0]
        else:
            recent = self._read('mru-sources')
            if not isinstance(recent, list) or not recent or recent[0] not in sources:
                raise ValueError('GSettings input-source history is unavailable')
            selected = recent[0]
        kind, name = selected
        if kind != 'xkb' or not isinstance(name, str) or not name:
            raise ValueError('GSettings input source is not an XKB layout')
        layout, _, variant = name.partition('+')
        return layout, variant

    def _update(self) -> None:
        choice = self._source()
        if choice == self.current:
            return
        replacement = Layout(*choice)
        self.layout, self.current = replacement, choice

    def labels(self, modifiers: set[int] | tuple[int, ...] = ()) -> dict[str, str]:
        self._update()
        assert self.layout is not None
        return self.layout.labels(modifiers)

    @staticmethod
    def switch_codes() -> tuple[int, ...]:
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
        cinnamon = any('cinnamon' in name for name in desktop)
        schema = 'org.cinnamon.desktop.keybindings.wm' if cinnamon else BINDINGS_SCHEMA
        # GNOME's forward shortcut toggles the two most recent sources; reverse MRU cycles all.
        key = 'switch-input-source' if cinnamon or 'budgie' in desktop else 'switch-input-source-backward'
        text = command(['gsettings', 'get', schema, key]).strip()
        bindings = ast.literal_eval(re.sub(r'^@as\s+', '', text))
        if not isinstance(bindings, list):
            raise ValueError('Invalid GSettings input-source shortcuts')
        keymap = X11Layout()
        try:
            for accelerator in bindings:
                modifiers = re.findall(r'<([^>]+)>', accelerator)
                name = re.sub(r'<[^>]+>', '', accelerator)
                if not name or any(item not in SHORTCUT_MODIFIERS for item in modifiers):
                    continue
                try:
                    code = keymap.keycode(name)
                except ValueError:
                    continue
                return tuple(SHORTCUT_MODIFIERS[item] for item in modifiers) + (code,)
        finally:
            keymap.close()
        raise RuntimeError('No supported GSettings switch-input-source shortcut')

    def close(self) -> None:
        if self.layout is not None:
            self.layout = None


def compositor(environment: Any) -> Any:
    desktop = environment.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
    for name, variable in [('hyprland', 'HYPRLAND_INSTANCE_SIGNATURE'),
                           ('sway', 'SWAYSOCK'), ('niri', 'NIRI_SOCKET'),
                           ('umbriel', 'UMBRIEL_SOCKET'), ('mango', 'MANGO_INSTANCE_SIGNATURE'),
                           ('wayfire', 'WAYFIRE_SOCKET')]:
        if environment.get(variable):
            return name
    name = next((name for name in ('hyprland', 'sway', 'niri', 'cosmic', 'umbriel', 'mango', 'wayfire')
                 if name in desktop), None)
    if name is not None:
        return name
    if environment.get("WAYLAND_DISPLAY") and (environment.get("LABWC_PID") or "labwc" in desktop):
        return "labwc"
    return 'wayland' if environment.get('WAYLAND_DISPLAY') else None


def command(args: Any) -> Any:
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=1, check=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'IPC error ({args[0]}): {exc}') from exc


class NiriLayout:
    def __init__(self, registry: Any='/usr/share/X11/xkb/rules/evdev.xml') -> None:
        self.names = {}
        for entry in ET.parse(registry).findall('./layoutList/layout'):
            code = entry.findtext('./configItem/name')
            self.names[entry.findtext('./configItem/description')] = (code, '')
            for variant in entry.findall('./variantList/variant'):
                self.names[variant.findtext('./configItem/description')] = (
                    code, variant.findtext('./configItem/name'))
        self.layout = None
        self.current = None
        self._update()

    def _query_name(self) -> Any:
        data = orjson.loads(command(['niri', 'msg', '--json', 'keyboard-layouts']))
        index = data['current_idx']
        if type(index) is not int or not 0 <= index < len(data['names']):
            raise ValueError('Invalid niri keyboard layout index')
        return data['names'][index]

    def _update(self) -> None:
        name = self._query_name()
        if name not in self.names:
            raise ValueError(f'Layout not found in XKB registry: {name}')
        choice = self.names[name]
        if choice != self.current:
            replacement = Layout(*choice)
            self.layout = replacement
            self.current = choice

    def labels(self, modifiers: Any=()) -> Any:
        self._update()
        assert self.layout is not None
        return self.layout.labels(modifiers)

    def switch(self) -> None:
        command(['niri', 'msg', 'action', 'switch-layout', 'next'])

    def close(self) -> None:
        if self.layout is not None:
            self.layout = None


class WayfireLayout(NiriLayout):
    @staticmethod
    def _request(method: str, data: dict[str, int] | None = None) -> dict[str, Any]:
        path = os.environ.get('WAYFIRE_SOCKET')
        if not path:
            raise RuntimeError('Wayfire IPC unavailable: enable the ipc and ipc-rules plugins')
        payload = orjson.dumps({'method': method, 'data': data or {}})
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(WAYFIRE_IPC_TIMEOUT)
                sock.connect(path)
                sock.sendall(len(payload).to_bytes(WAYFIRE_IPC_HEADER_BYTES, 'little') + payload)
                with sock.makefile('rb') as stream:
                    header = stream.read(WAYFIRE_IPC_HEADER_BYTES)
                    if len(header) != WAYFIRE_IPC_HEADER_BYTES:
                        raise ValueError('incomplete reply header')
                    size = int.from_bytes(header, 'little')
                    if not 0 < size <= WAYFIRE_IPC_MAX_REPLY_BYTES:
                        raise ValueError('invalid reply size')
                    body = stream.read(size)
                    if len(body) != size:
                        raise ValueError('incomplete reply')
                    reply = orjson.loads(body)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'Wayfire IPC error ({method}): {exc}') from exc
        if not isinstance(reply, dict):
            raise ValueError('Invalid Wayfire IPC reply')
        if 'error' in reply:
            raise RuntimeError(f"Wayfire IPC error ({method}): {reply['error']}")
        return reply

    def _keyboard_state(self) -> tuple[list[str], int]:
        reply = self._request('wayfire/get-keyboard-state')
        names, index = reply.get('possible-layouts'), reply.get('layout-index')
        if (not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names)
                or type(index) is not int or not 0 <= index < len(names)):
            raise ValueError('Invalid Wayfire keyboard layout state')
        return names, index

    def _query_name(self) -> str:
        names, index = self._keyboard_state()
        return names[index]

    def switch(self) -> None:
        names, index = self._keyboard_state()
        if len(names) > 1:
            reply = self._request('wayfire/set-keyboard-state', {'layout-index': (index + 1) % len(names)})
            if reply.get('result') != 'ok':
                raise RuntimeError('Wayfire did not confirm the keyboard layout change')


class SwayLayout(NiriLayout):
    def _query_name(self) -> Any:
        inputs = orjson.loads(command(['swaymsg', '-t', 'get_inputs', '-r']))
        keyboards = [item for item in inputs if item.get('type') == 'keyboard'
                     and item.get('xkb_active_layout_name')]
        if not keyboards:
            raise RuntimeError('Sway did not report a keyboard layout')
        # Never silently display one of several conflicting device layouts.
        names = {item['xkb_active_layout_name'] for item in keyboards}
        if len(names) != 1:
            raise RuntimeError('Sway keyboards have conflicting layouts')
        return keyboards[0]['xkb_active_layout_name']

    def switch(self) -> Any:
        result = orjson.loads(command(['swaymsg', '-r', 'input type:keyboard xkb_switch_layout next']))
        if not result or not all(item.get('success') for item in result):
            raise RuntimeError(f'Sway failed to switch keyboard layout: {result}')


class HyprlandLayout(NiriLayout):
    def _query_name(self) -> Any:
        data = orjson.loads(command(['hyprctl', '-j', 'devices']))
        keyboard = next((item for item in data['keyboards'] if item.get('main')), None)
        if keyboard is None or not keyboard.get('active_keymap'):
            raise RuntimeError('Hyprland did not report the main keyboard layout')
        self.keyboard = keyboard['name']
        return keyboard['active_keymap']

    def switch(self) -> Any:
        self._query_name()
        result = command(['hyprctl', 'switchxkblayout', self.keyboard, 'next'])
        if result.strip() != 'ok':
            raise RuntimeError(f'Hyprland failed to switch keyboard layout: {result.strip()}')


class KDELayout(GSettingsLayout):
    def __init__(self) -> None:
        self.layout = None
        self.current = None
        self.names: list[tuple[str, str, str]] = []
        self.sources: list[tuple[str, str]] = []
        self.runner = asyncio.Runner()
        self.bus: MessageBus | None = None
        try:
            self._update()
        except Exception:
            self.close()
            raise

    async def _request(self, method: str) -> list[Any] | None:
        bus = self.bus
        if bus is None:
            bus = MessageBus(bus_type=BusType.SESSION)
            await dbus_call(bus.connect())
            self.bus = bus
        return await _bus_call(bus, Message(
            destination='org.kde.keyboard', path='/Layouts',
            interface='org.kde.KeyboardLayouts', member=method))

    def _call(self, method: str) -> list[Any]:
        try:
            result = self.runner.run(self._request(method))
        except Exception as error:
            raise RuntimeError(f'KDE keyboard layout request failed: {error}') from error
        if result is None:
            raise RuntimeError(f'KDE keyboard layout request failed: {method}')
        return result

    def _source(self) -> tuple[str, str]:
        result = self._call('getLayoutsList')
        if len(result) != 1:
            raise ValueError('Invalid KDE keyboard layouts response')
        rows = result[0]
        if not isinstance(rows, list) or any(
            not isinstance(row, (list, tuple)) or len(row) != 3 for row in rows
        ):
            raise ValueError('Invalid KDE keyboard layout entries')
        entries = [(row[0], row[1], row[2]) for row in rows]
        names = [entry[0] for entry in entries]
        if not names or any(not isinstance(name, str) or not name for name in names):
            raise ValueError('Invalid KDE keyboard layout names')
        if entries != self.names:
            config = ConfigParser(interpolation=None)
            directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
            config.read(directory / 'kxkbrc', encoding='utf-8')
            variants = config.get('Layout', 'VariantList', fallback='').split(',')
            if not any(variants):
                variants = [''] * len(names)
            if len(variants) != len(names):
                raise ValueError('KDE keyboard layout variants do not match the layout list')
            self.sources = list(zip(names, variants, strict=True))
            self.names = entries
        current = self._call('getLayout')
        if len(current) != 1 or type(current[0]) is not int or not 0 <= current[0] < len(self.sources):
            raise ValueError('Invalid KDE keyboard layout index')
        return self.sources[current[0]]

    def switch(self) -> None:
        self._call('switchToNextLayout')

    def close(self) -> None:
        try:
            super().close()
            if self.bus is not None:
                self.bus.disconnect()
                self.runner.run(dbus_call(self.bus.wait_for_disconnect()))
                self.bus = None
        finally:
            self.runner.close()


class CinnamonLayout(KDELayout):
    async def _request(self, method: str) -> list[Any] | None:
        bus = self.bus
        if bus is None:
            bus = MessageBus(bus_type=BusType.SESSION)
            await dbus_call(bus.connect())
            self.bus = bus
        return await _bus_call(bus, Message(
            destination='org.Cinnamon', path='/org/Cinnamon',
            interface='org.Cinnamon', member=method))

    def _source(self) -> tuple[str, str]:
        result = self._call('GetInputSources')
        if len(result) != 1 or not isinstance(result[0], list):
            raise ValueError('Invalid Cinnamon input sources response')
        selected = []
        for source in result[0]:
            if not isinstance(source, (list, tuple)) or len(source) != 12:
                raise ValueError('Invalid Cinnamon input source entry')
            if source[-1] is True:
                selected.append(source)
        if len(selected) != 1:
            raise ValueError('Cinnamon current input source is unavailable')
        source = selected[0]
        layout, variant = source[7], source[8]
        if source[0] != 'xkb' or not isinstance(layout, str) or not layout:
            raise ValueError('Cinnamon input source is not an XKB layout')
        if not isinstance(variant, str):
            raise ValueError('Invalid Cinnamon XKB variant')
        return layout, variant


class UmbrielLayout(NiriLayout):
    def _query_name(self) -> str:
        data = orjson.loads(command(['umbriel', 'keyboard-layouts', '--json']))
        if not isinstance(data, dict):
            raise ValueError('Invalid Umbriel keyboard layout response')
        names, index = data.get('names'), data.get('current_index')
        if not isinstance(names, list) or type(index) is not int or not 0 <= index < len(names):
            raise ValueError('Invalid Umbriel keyboard layout index')
        name = names[index]
        if not isinstance(name, str) or not name:
            raise ValueError('Invalid Umbriel keyboard layout name')
        return name

    def switch(self) -> None:
        command(['umbriel', 'msg', 'keyboard-layout-next'])


class MangoLayout(NiriLayout):
    def _query_name(self) -> str:
        data = orjson.loads(command(['mmsg', 'get', 'keyboardlayout']))
        name = data.get('layout') if isinstance(data, dict) else None
        if not isinstance(name, str) or not name:
            raise ValueError('Invalid Mango keyboard layout response')
        return name

    def switch(self) -> None:
        # Zero cycles layouts; positive values select a one-based layout index.
        result = orjson.loads(command(['mmsg', 'dispatch', 'switch_keyboard_layout,0']))
        if not isinstance(result, dict) or result.get('success') is not True:
            raise RuntimeError(f'Mango failed to switch keyboard layout: {result}')


def detect_layout() -> object:
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
    if any('cinnamon' in name for name in desktop):
        return CinnamonLayout()
    if 'gnome' in desktop:
        return X11Layout() if is_x11_session(os.environ) else GSettingsLayout()
    if 'kde' in desktop:
        return KDELayout()
    name = compositor(os.environ)
    if name is None:
        ibus = (os.environ.get('XMODIFIERS') == '@im=ibus'
                or any(os.environ.get(key) == 'ibus' for key in ('GTK_IM_MODULE', 'QT_IM_MODULE')))
        if ibus and is_x11_session(os.environ):
            try:
                system_map = command(['gsettings', 'get', IBUS_SCHEMA, 'use-system-keyboard-layout'])
                if system_map.strip() == 'false' and command(['ibus', 'engine']).strip().startswith('xkb:'):
                    return IBusLayout()
            except RuntimeError as error:
                logger.warning('IBus layout detection unavailable: %s', error)
        return X11Layout()
    adapter = {'cosmic': CosmicLayout, 'niri': NiriLayout, 'sway': SwayLayout,
               'hyprland': HyprlandLayout, 'umbriel': UmbrielLayout, 'mango': MangoLayout,
               'labwc': LabwcLayout, 'wayfire': WayfireLayout}.get(name)
    if adapter is None:
        raise RuntimeError('No keyboard layout adapter for this compositor')
    return adapter()
