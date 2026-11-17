"""Load the linked keyboard backend using the same paths as the SDL backend."""

import ctypes
from pathlib import Path

KEYBOARD_LIBRARY_NAME = 'libportprotonqt_keyboard.so'
SYSTEM_KEYBOARD_LIBRARY = Path(__file__).parent.parent / KEYBOARD_LIBRARY_NAME
DEV_KEYBOARD_LIBRARY = Path(__file__).parent.parent.parent / 'build-aux' / 'lib' / KEYBOARD_LIBRARY_NAME
KEYBOARD_LIBRARY_PATH = (SYSTEM_KEYBOARD_LIBRARY if SYSTEM_KEYBOARD_LIBRARY.is_file()
                         else DEV_KEYBOARD_LIBRARY)


def load_library() -> ctypes.CDLL:
    return ctypes.CDLL(str(KEYBOARD_LIBRARY_PATH))
