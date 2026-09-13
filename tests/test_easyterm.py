import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from portprotonqt.scripts_utils.easyterm import TerminalWidget


def test_terminal_keeps_failed_command_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = QApplication.instance() or QApplication([])
    exit_codes = []
    monkeypatch.setattr(QApplication, "exit", exit_codes.append)
    monkeypatch.setattr(
        "portprotonqt.scripts_utils.easyterm.find_gamepad", lambda: None
    )
    terminal = TerminalWidget(
        ["/bin/sh", "-c", "printf 'final failure\\n'; exit 7"],
        ".",
        None,
        False,
    )

    deadline = time.monotonic() + 5
    while terminal.child_pid is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)

    assert terminal.exit_code == 7
    assert "final failure" in terminal.toPlainText()
    assert exit_codes == []
    closed = []
    window = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(terminal, "window", lambda: window)
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier,
    )

    terminal.keyPressEvent(event)
    assert closed == [True]

    closed.clear()
    gamepad = SimpleNamespace(
        connected=lambda: True,
        update=lambda: None,
        get_button=lambda _button: 1,
        close=lambda: None,
    )
    monkeypatch.setattr(terminal, "gamepad", gamepad)
    terminal.gamepad_a_pressed = False
    terminal._poll_close_gamepad()
    assert closed == [True]
    terminal._close_gamepad()
    terminal.close()
