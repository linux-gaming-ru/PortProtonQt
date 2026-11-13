import argparse
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from portprotonqt.scripts_utils.easyterm import (
    CONF_FALLBACK_SHELL,
    TerminalWidget,
    build_command,
)

PROCESS_TIMEOUT_SECONDS = 30
HELPER_PATH = "/usr/share/portproton/scripts/functions_helper"
USER_SHELL = "/usr/bin/zsh"


@pytest.fixture
def user_shell(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        "portprotonqt.scripts_utils.easyterm.default_shell", lambda: USER_SHELL
    )
    monkeypatch.setattr(
        "portprotonqt.scripts_utils.easyterm._portproton_functions_helper_path",
        lambda: HELPER_PATH,
    )
    return USER_SHELL


def test_build_command_uses_bash_for_portproton_functions(user_shell: str) -> None:
    command = build_command(argparse.Namespace(e=["pw_run Game"]))

    assert command == [
        CONF_FALLBACK_SHELL,
        "-lc",
        f"source {HELPER_PATH}; pw_run Game",
    ]


def test_build_command_uses_bash_for_exported_functions(
    user_shell: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASH_FUNC_launch_game%%", "() { :; }")

    command = build_command(argparse.Namespace(e=["launch_game"]))

    assert command[0] == CONF_FALLBACK_SHELL


def test_build_command_keeps_user_shell_for_plain_commands(user_shell: str) -> None:
    command = build_command(argparse.Namespace(e=["ls -l"]))

    assert command == [user_shell, "-lc", "ls -l"]


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

    deadline = time.monotonic() + PROCESS_TIMEOUT_SECONDS
    while terminal.exit_code is None and time.monotonic() < deadline:
        application.processEvents()
        terminal._check_child()
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
