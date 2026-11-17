"""Physical keys shared by uinput and XKB label readers."""

from evdev import ecodes

from portprotonqt.system_keyboard.input import KEY_ROWS

ROWS = [[("", code) for code in row] for row in KEY_ROWS]
MODIFIERS = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTMETA,
             ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT, ecodes.KEY_RIGHTSHIFT, ecodes.KEY_RIGHTCTRL}
SERVICE_KEYS = (
    ('Esc', ecodes.KEY_ESC), ('PrtSc', ecodes.KEY_SYSRQ), ('Del', ecodes.KEY_DELETE),
    ('⌫', ecodes.KEY_BACKSPACE), ('Enter', ecodes.KEY_ENTER), ('Space', ecodes.KEY_SPACE),
    ('Ctrl', ecodes.KEY_LEFTCTRL), ('RCtrl', ecodes.KEY_RIGHTCTRL), ('Super', ecodes.KEY_LEFTMETA),
    ('Alt', ecodes.KEY_LEFTALT), ('AltGr', ecodes.KEY_RIGHTALT), ('RShift', ecodes.KEY_RIGHTSHIFT),
    ('◄', ecodes.KEY_LEFT), ('►', ecodes.KEY_RIGHT), ('▲', ecodes.KEY_UP), ('▼', ecodes.KEY_DOWN),
    *((f'F{number}', getattr(ecodes, f'KEY_F{number}')) for number in range(1, 13)),
)
KEY_KBD_LAYOUT_NEXT = ecodes.KEY_KBD_LAYOUT_NEXT
LATCH_KEYS = frozenset(MODIFIERS | {code for key, code in SERVICE_KEYS if key.startswith('F')})
XKB_KEYCODE_OFFSET = 8
XKB_CORE_KEYBOARD = 0x0100
XKB_SHIFT_MASK = 1
XKB_LOCK_MASK = 2
XKB_ALTGR_MASK = 128
XKB_GROUP_COUNT = 4
XKB_GROUP_SHIFT = 13
KEYSYM_UNICODE_FLAG = 0x01000000
KEYSYM_UNICODE_MASK = 0xFFFFFF
UNICODE_MAX = 0x10FFFF
