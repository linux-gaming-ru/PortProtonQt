"""Read bundled keyboard layers and compositor-provided symbol maps."""
from functools import lru_cache
from importlib.resources import files
import re
from typing import Any

import orjson
from evdev import ecodes

from portprotonqt.keyboard_layouts import keyboard_layouts
from portprotonqt.system_keyboard.keys import (
    ROWS, MODIFIERS, XKB_SHIFT_MASK, XKB_LOCK_MASK, XKB_ALTGR_MASK, XKB_KEYCODE_OFFSET,
    KEYSYM_UNICODE_FLAG, KEYSYM_UNICODE_MASK, UNICODE_MAX,
)


@lru_cache(maxsize=1)
def _symbols() -> dict[str, dict[str, str]]:
    return orjson.loads(files('portprotonqt').joinpath('keyboard_symbols.json').read_bytes())


def keysym_label(symbol: int | str) -> str:
    """Translate X11 keysyms without a runtime xkbcommon library."""
    if isinstance(symbol, int):
        value = symbol & KEYSYM_UNICODE_MASK if symbol & ~KEYSYM_UNICODE_MASK == KEYSYM_UNICODE_FLAG else symbol
        if symbol & ~KEYSYM_UNICODE_MASK == KEYSYM_UNICODE_FLAG and value <= UNICODE_MAX:
            return chr(value) if chr(value).isprintable() else ''
        return _symbols()['values'].get(str(symbol), '')
    if re.fullmatch(r'U[0-9a-fA-F]{4,8}', symbol):
        value = int(symbol[1:], 16)
        return chr(value) if value <= UNICODE_MAX and chr(value).isprintable() else symbol
    if symbol.startswith('0x'):
        value = int(symbol, 16)
        fallback = f'U{value & KEYSYM_UNICODE_MASK:04X}' if value & ~KEYSYM_UNICODE_MASK == KEYSYM_UNICODE_FLAG else symbol
        return _symbols()['keysyms'].get(str(value), keysym_label(value) or fallback)
    return _symbols()['names'].get(symbol, symbol)


class Layout:
    def __init__(self, layout: Any='us', variant: Any='', *, keymap_text: Any=None) -> None:
        layout = 'us' if layout == 'en' else layout
        self.identifier = f'{layout}+{variant}' if variant else layout
        self.groups: dict[int, str] = {}
        self.types: dict[str, tuple[set[str], dict[frozenset[str], int], dict[frozenset[str], set[str]]]] = {}
        self.keys: dict[int, tuple[dict[int, str], dict[int, list[str]]]] = {}
        if keymap_text is not None:
            self._read_keymap(keymap_text.decode() if isinstance(keymap_text, bytes) else keymap_text)
        elif self.identifier not in keyboard_layouts:
            raise ValueError(f'Unknown keyboard layout: {self.identifier}')

    def _read_keymap(self, text: str) -> None:
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.DOTALL)
        codes = {name: int(code) - XKB_KEYCODE_OFFSET
                 for name, code in re.findall(r'<([^>]+)>\s*=\s*(\d+)\s*;', text)}
        self.groups = {int(group) - 1: name for group, name in re.findall(
            r'name\[(?:Group)?(\d+)\]\s*=\s*"([^"]*)"', text)}
        for name, body in re.findall(r'type\s+"([^"]+)"\s*\{(.*?)\};', text, re.DOTALL):
            modifiers = re.search(r'modifiers\s*=\s*([^;]+)', body)
            allowed = set(modifiers[1].split('+')) if modifiers else set()
            levels = {frozenset(part.strip() for part in mask.split('+') if part.strip() != 'None'):
                      int(level) - 1 for mask, level in re.findall(
                          r'map\[([^]]+)\]\s*=\s*(?:Level)?(\d+)', body)}
            preserved = {frozenset(part.strip() for part in mask.split('+')):
                         {part.strip() for part in value.split('+')} for mask, value in re.findall(
                             r'preserve\[([^]]+)\]\s*=\s*([^;]+)', body)}
            self.types[name] = ({part.strip() for part in allowed}, levels, preserved)
        for name, body in re.findall(r'key\s+<([^>]+)>\s*\{(.*?)\};', text, re.DOTALL):
            if name not in codes:
                continue
            types = {int(group or 1) - 1: kind for group, kind in re.findall(
                r'type(?:\[(?:Group)?(\d+)\])?\s*=\s*"([^"]+)"', body)}
            groups = {int(group) - 1: [part.strip() for part in symbols.split(',')]
                      for group, symbols in re.findall(
                          r'symbols\[(?:Group)?(\d+)\]\s*=\s*\[([^]]*)\]', body)}
            if not groups:
                symbols = re.search(r'\[([^]]*)\]', body)
                if symbols:
                    groups[0] = [part.strip() for part in symbols[1].split(',')]
            self.keys[codes[name]] = types, groups
        if not self.keys:
            raise ValueError('Keyboard keymap contains no physical keys')

    def _keymap_labels(self, modifiers: set[int], mask: tuple[int, ...]) -> dict[str, str]:
        depressed, latched, locked, group = mask
        bits = depressed | latched | locked
        active = set()
        _, alt_groups = self.keys.get(ecodes.KEY_RIGHTALT, ({}, {}))
        alt_symbols = alt_groups.get(group, alt_groups.get(0, []))
        altgr_codes = {ecodes.KEY_RIGHTALT} if any(
            keysym_label(symbol) in {'ISO_Level3_Shift', 'Mode_switch'} for symbol in alt_symbols) else set()
        for name, bit, codes in (
            ('Shift', XKB_SHIFT_MASK, {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}),
            ('Lock', XKB_LOCK_MASK, {ecodes.KEY_CAPSLOCK}),
            ('LevelThree', XKB_ALTGR_MASK, altgr_codes),
        ):
            if bits & bit or modifiers & codes:
                active.add(name)
        result = {}
        for code, (types, groups) in self.keys.items():
            if code in MODIFIERS:
                continue
            symbols = groups.get(group, groups.get(0, []))
            kind = types.get(group, types.get(0, ''))
            if not kind:
                labels = [keysym_label(symbol) for symbol in symbols]
                alphabetic = len(labels) > 1 and labels[0].islower() and labels[1].isupper()
                kind = 'ALPHABETIC' if alphabetic else 'TWO_LEVEL'
                if len(labels) > 2:
                    kind = 'FOUR_LEVEL_SEMIALPHABETIC' if alphabetic else 'FOUR_LEVEL'
                    if alphabetic and len(labels) > 3 and labels[2].islower() and labels[3].isupper():
                        kind = 'FOUR_LEVEL_ALPHABETIC'
                if len(labels) == 1:
                    kind = 'ONE_LEVEL'
            allowed, levels, preserved = self.types.get(kind, (set(), {}, {}))
            selected = frozenset(active & allowed)
            level = levels.get(selected, 0)
            symbol = symbols[level] if level < len(symbols) else 'NoSymbol'
            label = keysym_label(symbol)
            if 'Lock' in active and ('Lock' not in allowed or 'Lock' in preserved.get(selected, set())):
                label = _symbols()['upper'].get(label, label.upper() if len(label) == 1 else label)
            result[str(code)] = label
        return result

    def labels(self, modifiers: Any=(), *, mask: Any=None) -> dict[str, str]:
        native_mask = (0, 0, 0, 0) if mask is None else tuple(mask)
        depressed, latched, locked, group = native_mask
        codes = set(modifiers)
        if self.keys:
            return self._keymap_labels(codes, native_mask)
        bits = depressed | latched | locked
        shift = bool(bits & XKB_SHIFT_MASK or codes & {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})
        altgr = bool(bits & XKB_ALTGR_MASK or ecodes.KEY_RIGHTALT in codes)
        caps = bool(bits & XKB_LOCK_MASK or ecodes.KEY_CAPSLOCK in codes)
        layer = '_'.join(name for name, enabled in (
            ('shift', shift), ('altgr', altgr), ('caps', caps)) if enabled) or 'normal'
        rows = keyboard_layouts[self.identifier][layer]
        return {str(code): label.replace('&&', '&')
                for labels, physical in zip(rows, ROWS, strict=True)
                for label, (_, code) in zip(labels, physical, strict=True) if code not in MODIFIERS}

    def layout_identifier(self, group: int) -> str:
        return self.groups.get(group, self.identifier)


class ManualLayout:
    def __init__(self) -> None:
        self.layout = Layout('us')
        self.language = 'us'

    def switch(self) -> Any:
        language = 'ru' if self.language == 'us' else 'us'
        self.layout = Layout(language)
        self.language = language

    def labels(self, modifiers: Any=()) -> Any:
        return self.layout.labels(modifiers)
