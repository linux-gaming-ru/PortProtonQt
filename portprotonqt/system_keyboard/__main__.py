"""Isolated Qt frontend: X11/XWayland or a native Wayland layer surface."""

import ctypes
import os
import sys

import orjson
from typing import Any
from PySide6.QtCore import QSocketNotifier
from PySide6.QtWidgets import QApplication

from portprotonqt.logger import get_logger, setup_logger

logger = get_logger(__name__)
COMMAND_READ_SIZE = 8192


class CommandReader:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.buffer = bytearray()
        os.set_blocking(sys.stdin.fileno(), False)
        self.notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self.read)

    def read(self) -> None:
        try:
            data = os.read(sys.stdin.fileno(), COMMAND_READ_SIZE)
        except BlockingIOError:
            return
        if not data:
            self.notifier.setEnabled(False)
            self.window.command('quit')
            return
        self.buffer.extend(data)
        while b'\n' in self.buffer:
            line, _, remaining = self.buffer.partition(b'\n')
            self.buffer = bytearray(remaining)
            try:
                command = orjson.loads(line)
                if isinstance(command, dict) and isinstance(command.get('action'), str):
                    self.window.command(command['action'], command.get('value'))
            except Exception:
                logger.exception('Invalid system keyboard command')


def main() -> int:
    setup_logger('WARNING')
    from portprotonqt.system_keyboard.native import load_library
    layer_shell = False
    if os.environ.get('WAYLAND_DISPLAY'):
        library = load_library()
        library.portproton_keyboard_has_layer_shell.argtypes = []
        library.portproton_keyboard_has_layer_shell.restype = ctypes.c_int
        layer_shell = bool(library.portproton_keyboard_has_layer_shell())
    os.environ['QT_QPA_PLATFORM'] = 'offscreen' if layer_shell else 'xcb'
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    from portprotonqt.system_keyboard.window import SystemKeyboardWindow, WaylandWindow
    window = SystemKeyboardWindow(layer_shell=layer_shell)
    try:
        if layer_shell:
            window.native_layer = WaylandWindow(window)
        reader = CommandReader(window)
        app.aboutToQuit.connect(window.shutdown)
        window.worker.start()
        result = app.exec()
        window.shutdown()
        del reader
        return result
    except Exception:
        logger.exception('Failed to start system keyboard')
        window.shutdown()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
