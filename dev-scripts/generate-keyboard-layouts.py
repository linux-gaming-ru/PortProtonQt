#!/usr/bin/env python3
"""Regenerate bundled keyboard layers; libxkbcommon is a generation-only tool."""
import ctypes as C
import ctypes.util
from pathlib import Path
import re

import orjson

from portprotonqt.system_keyboard.input import KEY_ROWS

ROOT = Path(__file__).resolve().parents[1]
lib = C.CDLL(ctypes.util.find_library('xkbcommon'))


class Names(C.Structure):
    _fields_ = [(name, C.c_char_p) for name in ('rules', 'model', 'layout', 'variant', 'options')]


for name, args, result in (
    ('xkb_context_new', [C.c_int], C.c_void_p),
    ('xkb_keymap_new_from_names', [C.c_void_p, C.POINTER(Names), C.c_int], C.c_void_p),
    ('xkb_state_new', [C.c_void_p], C.c_void_p),
    ('xkb_state_update_key', [C.c_void_p, C.c_uint, C.c_int], C.c_int),
    ('xkb_state_key_get_utf8', [C.c_void_p, C.c_uint, C.c_void_p, C.c_size_t], C.c_int),
    ('xkb_state_key_get_one_sym', [C.c_void_p, C.c_uint], C.c_uint),
    ('xkb_keysym_get_name', [C.c_uint, C.c_void_p, C.c_size_t], C.c_int),
    ('xkb_keysym_to_utf32', [C.c_uint], C.c_uint),
    ('xkb_keysym_to_upper', [C.c_uint], C.c_uint),
    ('xkb_keysym_from_name', [C.c_char_p, C.c_int], C.c_uint),
    ('xkb_state_unref', [C.c_void_p], None),
    ('xkb_keymap_unref', [C.c_void_p], None),
    ('xkb_context_unref', [C.c_void_p], None),
):
    function = getattr(lib, name)
    function.argtypes, function.restype = args, result

path = ROOT / 'portprotonqt/keyboard_layouts.json'
data = orjson.loads(path.read_bytes())
context = lib.xkb_context_new(0)
failures = []
for identifier, layout in data.items():
    language, _, variant = identifier.partition('+')
    names = Names(None, b'pc105', language.encode(), variant.encode(), b'')
    keymap = lib.xkb_keymap_new_from_names(context, C.byref(names), 0)
    if not keymap:
        failures.append(identifier)
        continue
    for layer, modifiers in (
        ('altgr', (108,)), ('shift_altgr', (50, 108)),
        ('caps', (66,)), ('shift_caps', (50, 66)),
        ('altgr_caps', (108, 66)), ('shift_altgr_caps', (50, 108, 66)),
    ):
        state = lib.xkb_state_new(keymap)
        for code in modifiers:
            lib.xkb_state_update_key(state, code, 1)
        rows = []
        for fallbacks, codes in zip(layout['normal'], KEY_ROWS, strict=True):
            row = []
            for fallback, code in zip(fallbacks, codes, strict=True):
                buffer = C.create_string_buffer(128)
                lib.xkb_state_key_get_utf8(state, code + 8, buffer, len(buffer))
                label = buffer.value.decode()
                if not label or not label.isprintable():
                    symbol = lib.xkb_state_key_get_one_sym(state, code + 8)
                    lib.xkb_keysym_get_name(symbol, buffer, len(buffer))
                    label = buffer.value.decode() or fallback
                row.append(label.replace('&', '&&') if code not in (15, 58, 42) else fallback)
            rows.append(row)
        layout[layer] = rows
        lib.xkb_state_unref(state)
    lib.xkb_keymap_unref(keymap)
lib.xkb_context_unref(context)
if failures:
    raise SystemExit(f'Cannot generate layouts: {failures}')
path.write_bytes(orjson.dumps(data) + b'\n')

symbols = {'names': {}, 'values': {}, 'keysyms': {}, 'upper': {}}
header = Path('/usr/include/xkbcommon/xkbcommon-keysyms.h').read_text()
for name in re.findall(r'^#define XKB_KEY_(\w+)\s', header, re.MULTILINE):
    symbol = lib.xkb_keysym_from_name(name.encode(), 0)
    value = lib.xkb_keysym_to_utf32(symbol)
    buffer = C.create_string_buffer(128)
    lib.xkb_keysym_get_name(symbol, buffer, len(buffer))
    symbols['keysyms'][str(symbol)] = buffer.value.decode()
    if value and chr(value).isprintable():
        symbols['keysyms'][str(symbol)] = chr(value)
        symbols['names'][name] = chr(value)
        symbols['values'][str(symbol)] = chr(value)
        upper = lib.xkb_keysym_to_utf32(lib.xkb_keysym_to_upper(symbol))
        if upper and chr(upper).isprintable():
            symbols['upper'][chr(value)] = chr(upper)
(ROOT / 'portprotonqt/keyboard_symbols.json').write_bytes(orjson.dumps(symbols) + b'\n')
