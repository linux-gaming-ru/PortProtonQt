"""System keyboard input, focus-independent routing and native lifecycle."""

from collections.abc import Generator
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from evdev import ecodes
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QImage, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from portprotonqt.input_manager import InputManager
from portprotonqt.input_manager.constants import (GamepadType, PAD_BUTTON_START, PAD_BUTTON_NORTH,
                                                PAD_BUTTON_SOUTH, SDL_CONTROLLER_BUTTON_TO_PAD)
from portprotonqt.native_gamepad import SDLGamepad
from portprotonqt.system_keyboard import SystemKeyboard
from portprotonqt.system_keyboard.input import SystemInputWorker
from portprotonqt.system_keyboard.window import SystemKeyboardWindow
from portprotonqt.system_keyboard import input as system_input
from portprotonqt.system_keyboard import window as system_window
from portprotonqt.system_keyboard import detection
from portprotonqt.system_keyboard.detection import CosmicLayout, X11Layout
from portprotonqt.system_keyboard.keys import XKB_GROUP_SHIFT
from portprotonqt.theme_manager import load_theme


@pytest.fixture
def application() -> QApplication:
    return cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.fixture
def keyboard_window(monkeypatch: pytest.MonkeyPatch, application: QApplication) -> Generator[SystemKeyboardWindow]:
    theme = load_theme('standart')
    monkeypatch.setattr(system_window.ThemeManager, 'apply_theme', lambda self, name: theme)
    monkeypatch.setattr(system_window, 'report', MagicMock())
    window = SystemKeyboardWindow()
    yield window
    window.shutdown()
    window.hide()


def test_panel_matches_embedded_layout_without_extra_rows(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard = keyboard_window.keyboard
    assert keyboard.current_layout == 'us'
    assert 'Clear' not in [button.text() for button in keyboard.findChildren(QPushButton)]
    keyboard.update_keyboard()
    assert 'Clear' not in [button.text() for button in keyboard.findChildren(QPushButton)]
    metrics = keyboard_window.theme.SYSTEM_KEYBOARD
    assert keyboard.keyboard_layout.rowCount() == len(metrics['rows']) * metrics['row_units']
    extra_iso_key = keyboard.buttons['<']
    assert isinstance(extra_iso_key, QPushButton)
    assert extra_iso_key.text() == '<'
    assert keyboard.keycodes['<'] == ecodes.KEY_102ND
    assert keyboard.height() == keyboard_window.theme.SYSTEM_KEYBOARD['height']
    assert keyboard_window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus


@pytest.mark.parametrize('width', [1000, 800, 600])
def test_compact_rows_align_without_overlapping(
    keyboard_window: SystemKeyboardWindow, application: QApplication, width: int,
) -> None:
    keyboard = keyboard_window.keyboard
    keyboard_window.resize(width, keyboard_window.theme.SYSTEM_KEYBOARD['height'])
    keyboard.setFixedSize(keyboard_window.size())
    keyboard.update_keyboard()
    keyboard_window.show()
    keyboard.show()
    application.processEvents()
    left = keyboard.buttons['Esc'].geometry().left()
    right = keyboard.buttons['Del'].geometry().right()
    for row in keyboard_window.theme.SYSTEM_KEYBOARD['rows']:
        assert keyboard.buttons[row[0][0]].geometry().left() == left
        assert keyboard.buttons[row[-1][0]].geometry().right() == right
    rectangles = [button.geometry() for button in keyboard.buttons.values()]
    for index, rectangle in enumerate(rectangles):
        assert rectangle.width() > 0 and rectangle.height() > 0
        assert keyboard.keyboard_container.rect().contains(rectangle)
        assert not any(rectangle.intersects(other) for other in rectangles[index + 1:])
    assert abs(keyboard.buttons['⬆'].width() - keyboard.buttons['RShift'].width()) <= 1
    assert keyboard.buttons['Space'].width() > keyboard.buttons['Enter'].width()
    assert keyboard.buttons['▲'].height() + keyboard.buttons['▼'].height() + keyboard.spacing == keyboard.button_height


def test_panel_sends_physical_keys_without_editing_target(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard = keyboard_window.keyboard
    keyboard.on_button_click('q')
    keyboard.on_enter_click()
    keyboard.on_lang_click()
    commands = keyboard_window.worker.commands
    assert commands.get_nowait() == ('tap', (ecodes.KEY_Q,))
    assert commands.get_nowait() == ('tap', (ecodes.KEY_ENTER,))
    assert commands.get_nowait() == ('language', ())
    keyboard.on_shift_click(True)
    assert commands.get_nowait() == ('modifiers', (ecodes.KEY_LEFTSHIFT,))
    keyboard.buttons['q'].click()
    assert commands.get_nowait() == ('tap', (ecodes.KEY_Q,))


@pytest.mark.parametrize('label, code', [
    ('Esc', ecodes.KEY_ESC),
    ('PrtSc', ecodes.KEY_SYSRQ), ('Del', ecodes.KEY_DELETE),
])
def test_service_keys_send_physical_codes(
    keyboard_window: SystemKeyboardWindow, label: str, code: int,
) -> None:
    keyboard = keyboard_window.keyboard
    button = next(button for button in keyboard.findChildren(QPushButton) if button.text() == label)
    button.click()
    assert keyboard_window.worker.commands.get_nowait() == ('tap', (code,))


@pytest.mark.parametrize('label, code', [
    ('Ctrl', ecodes.KEY_LEFTCTRL), ('Super', ecodes.KEY_LEFTMETA),
    ('Alt', ecodes.KEY_LEFTALT), ('AltGr', ecodes.KEY_RIGHTALT), ('RCtrl', ecodes.KEY_RIGHTCTRL),
    ('F1', ecodes.KEY_F1), ('F12', ecodes.KEY_F12),
])
def test_service_modifiers_toggle_and_release(
    keyboard_window: SystemKeyboardWindow, label: str, code: int,
) -> None:
    keyboard = keyboard_window.keyboard
    button = next(button for button in keyboard.findChildren(QPushButton) if button.text() == label)
    button.click()
    assert button.isChecked()
    assert keyboard_window.worker.commands.get_nowait() == ('modifiers', (code,))
    keyboard.on_button_click('q')
    assert keyboard_window.worker.commands.get_nowait() == ('tap', (ecodes.KEY_Q,))
    button.click()
    assert not button.isChecked()
    assert keyboard_window.worker.commands.get_nowait() == ('modifiers', ())
    button.click()
    keyboard_window.worker.commands.get_nowait()
    keyboard._release_modifiers()
    assert not button.isChecked()
    assert keyboard_window.worker.commands.get_nowait() == ('release', ())


def test_hide_cancels_pending_input_and_repeat(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard_window.ready = True
    keyboard_window.show_keyboard()
    keyboard_window.keyboard.on_backspace_pressed()
    keyboard_window.hide_keyboard()
    assert not keyboard_window.worker.enabled.is_set()
    assert keyboard_window.keyboard.backspace_timer is None
    assert keyboard_window.worker.commands.get_nowait() == ('release', ())
    assert not keyboard_window.isVisible()


def test_refresh_preserves_selected_key(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard = keyboard_window.keyboard
    keyboard._set_selected_button(keyboard.buttons['q'])
    original_button = keyboard.buttons['q']
    original_button.setDown(True)
    keyboard_window._state_changed({'labels': {str(ecodes.KEY_Q): 'й'}, 'caps': False,
                                    'shift': False, 'modifiers': (), 'layout': 'ru'})
    assert keyboard.selected_button is keyboard.buttons['q']
    assert keyboard.buttons['q'].text() == 'й'
    assert keyboard.buttons['q'] is original_button
    assert original_button.isDown()


def test_caps_highlight_and_space_follow_system_state(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard = keyboard_window.keyboard
    button = keyboard.buttons['CAPS']
    keyboard_window._state_changed({'labels': {str(ecodes.KEY_CAPSLOCK): '', str(ecodes.KEY_Q): 'Й'},
                                    'caps': True, 'shift': False, 'modifiers': (), 'layout': 'ru'})
    assert button.text() == 'CAPS'
    assert button.isChecked()
    assert keyboard.buttons['q'].text() == 'Й'
    space = keyboard.buttons['Space']
    assert isinstance(space, QPushButton)
    assert space.text() == 'Space'
    keyboard_window._state_changed({'labels': {str(ecodes.KEY_Q): 'q'}, 'caps': False,
                                    'shift': False, 'modifiers': (), 'layout': 'us'})
    assert not button.isChecked()
    assert space.text() == 'Space'


def test_panel_has_themed_background(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard_window.ready = True
    keyboard_window.show_keyboard()
    QApplication.processEvents()
    image = QImage(keyboard_window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    keyboard_window.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(1, keyboard_window.height() // 2).alpha() > 0


def test_caps_button_does_not_keep_unconfirmed_local_toggle(keyboard_window: SystemKeyboardWindow) -> None:
    button = keyboard_window.keyboard.buttons['CAPS']
    button.click()
    assert not button.isChecked()
    assert keyboard_window.worker.commands.get_nowait() == ('caps', ())
    button.setChecked(True)
    keyboard_window._state_changed({'labels': {}, 'caps': False, 'shift': False,
                                    'modifiers': (), 'layout': 'System'})
    assert not button.isChecked()


def test_x11_labels_use_xkb_group_bits(application: QApplication) -> None:
    layout: Any = X11Layout.__new__(X11Layout)
    state = SimpleNamespace(group=1, mods=0)
    layout.state = lambda: state
    layout.display = 123
    layout.lib = MagicMock()
    layout.lib.portproton_keyboard_x11_keysym.return_value = 0
    layout.labels()
    assert layout.lib.portproton_keyboard_x11_keysym.call_args_list
    for call in layout.lib.portproton_keyboard_x11_keysym.call_args_list:
        assert call.args[2] == 1 << XKB_GROUP_SHIFT


@pytest.mark.parametrize('codes, replay', [
    ((ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTALT), (ecodes.KEY_LEFTALT, ecodes.KEY_LEFTSHIFT)),
    ((ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT), ()),
    ((ecodes.KEY_F4, ecodes.KEY_F3), ()), ((ecodes.KEY_LEFTALT, ecodes.KEY_F4), ()),
])
def test_modifiers_send_real_press_and_release_events(
    application: QApplication, codes: tuple[int, ...], replay: tuple[int, ...],
) -> None:
    worker = SystemInputWorker()
    worker.enabled.set()
    device = MagicMock()
    held = []
    for code in codes:
        held.append(code)
        worker._execute(device, 'modifiers', tuple(held))
    worker._execute(device, 'modifiers', ())
    expected = [
        *((ecodes.EV_KEY, code, 1) for code in codes),
        *((ecodes.EV_KEY, code, 0) for code in sorted(codes, reverse=True)),
    ]
    expected += [*((ecodes.EV_KEY, code, 1) for code in replay),
                 *((ecodes.EV_KEY, code, 0) for code in reversed(replay))]
    assert [call.args for call in device.write.call_args_list] == expected
    assert not worker.modifiers


def test_alt_shift_replay_preserves_remaining_alt(application: QApplication) -> None:
    worker = SystemInputWorker()
    worker.enabled.set()
    device = MagicMock()
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTALT,))
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTALT, ecodes.KEY_LEFTSHIFT))
    device.write.reset_mock()
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTALT,))
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0), (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0),
        (ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1), (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1),
        (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0), (ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0),
        (ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1),
    ]
    assert worker.modifiers == {ecodes.KEY_LEFTALT}


@pytest.mark.parametrize('keys', [('F4', 'F3'), ('Alt', 'F4')])
def test_function_chords_latch_both_buttons(
    keyboard_window: SystemKeyboardWindow, keys: tuple[str, str],
) -> None:
    keyboard = keyboard_window.keyboard
    for key in keys:
        keyboard.buttons[key].click()
    expected = {keyboard.keycodes[key] for key in keys}
    assert keyboard.modifiers == expected
    assert all(keyboard.buttons[key].isChecked() for key in keys)
    keyboard_window.worker.commands.get_nowait()
    assert keyboard_window.worker.commands.get_nowait() == ('modifiers', tuple(sorted(expected)))
    keyboard._release_modifiers()
    assert not any(keyboard.buttons[key].isChecked() for key in keys)


def test_modifier_chord_releases_after_key(application: QApplication) -> None:
    worker = SystemInputWorker()
    worker.enabled.set()
    device = MagicMock()
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTMETA,))
    worker._execute(device, 'tap', (ecodes.KEY_E,))
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 1),
        (ecodes.EV_KEY, ecodes.KEY_E, 1), (ecodes.EV_KEY, ecodes.KEY_E, 0),
        (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 0),
    ]
    assert not worker.modifiers


def test_cancel_pending_releases_held_modifiers(application: QApplication) -> None:
    worker = SystemInputWorker()
    worker.enabled.set()
    device = MagicMock()
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTALT, ecodes.KEY_LEFTSHIFT))
    worker.cancel_pending()
    action, codes = worker.commands.get_nowait()
    worker._execute(device, action, codes)
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTMETA,))
    assert not worker.modifiers
    assert [call.args for call in device.write.call_args_list][-2:] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0), (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0),
    ]


def test_key_failure_releases_all_pressed_keys(application: QApplication) -> None:
    worker = SystemInputWorker()
    device = MagicMock()
    device.write.side_effect = [None, OSError('injection failed'), None, None]
    with pytest.raises(OSError, match='injection failed'):
        worker.send_keys(device, (ecodes.KEY_LEFTSHIFT, ecodes.KEY_Q))
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1), (ecodes.EV_KEY, ecodes.KEY_Q, 1),
        (ecodes.EV_KEY, ecodes.KEY_Q, 0), (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)]


def test_hidden_keyboard_cannot_inject(application: QApplication) -> None:
    worker = SystemInputWorker()
    device = MagicMock()
    worker._execute(device, 'tap', (ecodes.KEY_Q,))
    worker._execute(device, 'language', ())
    worker._execute(device, 'caps', ())
    device.write.assert_not_called()


@pytest.mark.parametrize('manual', [False, True])
@pytest.mark.parametrize('session', ['x11', 'wayland'])
def test_worker_shutdown_closes_device_once(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, manual: bool, session: str,
) -> None:
    from portprotonqt.system_keyboard.layouts import ManualLayout
    from portprotonqt.system_keyboard.keys import SERVICE_KEYS

    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    worker = SystemInputWorker()
    if manual:
        worker.layout = ManualLayout()
    device = MagicMock()
    opened = Event()
    capabilities = []
    def open_device(*args: Any, **kwargs: Any) -> Any:
        capabilities.extend(args[0][ecodes.EV_KEY])
        opened.set()
        return device
    monkeypatch.setattr(system_input, 'UInput', open_device)
    monkeypatch.setattr(worker, '_load_layout', lambda: worker._set_modifiers(device, (ecodes.KEY_LEFTMETA,)))
    monkeypatch.setattr(worker, '_refresh_state', MagicMock())
    worker.start()
    try:
        assert opened.wait(2)
    finally:
        worker.stop()
    worker.stop()
    assert not worker.isRunning()
    assert {code for _, code in SERVICE_KEYS} <= set(capabilities)
    assert not worker.modifiers
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 1), (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 0),
    ]
    device.close.assert_called_once()


@pytest.mark.parametrize('session', ['x11', 'wayland'])
def test_worker_failure_reports_and_finishes(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, session: str,
) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    worker = SystemInputWorker()
    monkeypatch.setattr(system_input, 'UInput', MagicMock(side_effect=PermissionError('uinput denied')))
    failures = []
    worker.failed.connect(failures.append)
    worker.start()
    assert worker.wait(2000)
    application.processEvents()
    assert failures == ['uinput denied']


@pytest.mark.parametrize('session', ['wayland', 'x11'])
def test_xwayland_switch_uses_uinput_instead_of_xkb(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, session: str,
) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'XFCE')
    worker = SystemInputWorker()
    worker.enabled.set()
    layout: Any = X11Layout.__new__(X11Layout)
    layout.switch = MagicMock()
    worker.layout = layout
    device = MagicMock()
    worker._execute(device, 'language', ())
    if session == 'x11':
        layout.switch.assert_called_once()
        device.write.assert_not_called()
    else:
        layout.switch.assert_not_called()
        assert [call.args for call in device.write.call_args_list] == [
            (ecodes.EV_KEY, ecodes.KEY_KBD_LAYOUT_NEXT, 1),
            (ecodes.EV_KEY, ecodes.KEY_KBD_LAYOUT_NEXT, 0)]


def test_cosmic_switch_matches_prototype_uinput_path(application: QApplication) -> None:
    worker = SystemInputWorker()
    worker.enabled.set()
    worker.layout = CosmicLayout.__new__(CosmicLayout)
    device = MagicMock()
    worker._execute(device, 'language', ())
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_KBD_LAYOUT_NEXT, 1),
        (ecodes.EV_KEY, ecodes.KEY_KBD_LAYOUT_NEXT, 0)]


def test_niri_switch_uses_ipc(monkeypatch: pytest.MonkeyPatch) -> None:
    command = MagicMock()
    monkeypatch.setattr(detection, 'command', command)
    layout = detection.NiriLayout.__new__(detection.NiriLayout)
    layout.switch()
    command.assert_called_once_with(['niri', 'msg', 'action', 'switch-layout', 'next'])


def test_start_y_is_consumed_before_internal_search(application: QApplication) -> None:
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    keyboard = SimpleNamespace(toggle=MagicMock(), isVisible=lambda: False)
    manager._parent = SimpleNamespace(system_keyboard=keyboard)
    manager.start_held = True
    assert manager._handle_system_keyboard_input(PAD_BUTTON_START, 1, False)
    assert manager._handle_system_keyboard_input(PAD_BUTTON_NORTH, 1, False)
    assert manager._handle_system_keyboard_input(PAD_BUTTON_START, 0, False)
    keyboard.toggle.assert_called_once()
    manager.start_held = False
    assert not manager._handle_system_keyboard_input(PAD_BUTTON_NORTH, 1, False)


def test_system_keyboard_routes_buttons_without_application_focus(application: QApplication) -> None:
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    keyboard = SimpleNamespace(send=MagicMock(), isVisible=lambda: True)
    manager._parent = SimpleNamespace(system_keyboard=keyboard)
    manager.start_held = False
    assert manager._handle_system_keyboard_input(PAD_BUTTON_SOUTH, 1, False)
    keyboard.send.assert_called_once_with('button', 'confirm')


def test_start_is_polled_before_y_in_same_snapshot(application: QApplication) -> None:
    manager: Any = InputManager.__new__(InputManager)
    manager._handle_button_value = MagicMock()
    gamepad = cast(SDLGamepad, SimpleNamespace(get_button=lambda index: 1))
    manager._poll_button_events(gamepad, 1.0)
    codes = [call.args[1] for call in manager._handle_button_value.call_args_list]
    assert codes.index(PAD_BUTTON_START) < codes.index(PAD_BUTTON_NORTH)
    assert set(codes) == set(SDL_CONTROLLER_BUTTON_TO_PAD.values())


def test_controller_shutdown_waits_for_child(monkeypatch: pytest.MonkeyPatch, application: QApplication) -> None:
    parent = QWidget()
    keyboard = SystemKeyboard(parent)
    process = MagicMock()
    from PySide6.QtCore import QProcess
    process.state.return_value = QProcess.ProcessState.Running
    process.waitForFinished.side_effect = [False, False, True]
    keyboard.process = process
    keyboard.shutdown()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.waitForFinished.call_count == 3


@pytest.mark.parametrize('group, name', [(0, 'English (US)'), (1, 'Russian')])
def test_language_state_keeps_space_label_plain(
    keyboard_window: SystemKeyboardWindow, group: int, name: str,
) -> None:
    worker = keyboard_window.worker
    layout = CosmicLayout.__new__(CosmicLayout)
    layout.group = group
    layout.layout = MagicMock()
    layout.layout.layout_identifier.return_value = name
    layout.labels = MagicMock(return_value={str(ecodes.KEY_Q): 'q'})
    worker.layout = layout
    worker.state_changed.connect(keyboard_window._state_changed)
    device = MagicMock()
    device.read.return_value = []
    worker._refresh_state(device)
    layout.layout.layout_identifier.assert_called_once_with(group)
    assert keyboard_window.keyboard.layout_name == name
    space = keyboard_window.keyboard.buttons['Space']
    assert isinstance(space, QPushButton)
    assert space.text() == 'Space'


def test_x11_name_without_rules_property(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import ctypes as C
    import select
    import shutil
    import subprocess

    server_path = shutil.which('Xvfb')
    if server_path is None:
        pytest.skip('Xvfb is not installed')
    with (tmp_path / 'xvfb.log').open('w') as log:
        server = subprocess.Popen(
            [server_path, '-displayfd', '1', '-screen', '0', '800x600x24',
             '-nolisten', 'tcp', '-noreset', '-extension', 'GLX'],
            stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            assert server.stdout is not None
            assert select.select([server.stdout], [], [], 5)[0], 'Xvfb startup timed out'
            number = server.stdout.readline().strip()
            assert number, (tmp_path / 'xvfb.log').read_text()
            monkeypatch.setenv('DISPLAY', ':' + number)
            layout = X11Layout()
            try:
                layout.lib.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
                layout.lib.XInternAtom.restype = C.c_ulong
                layout.lib.XDefaultRootWindow.argtypes = [C.c_void_p]
                layout.lib.XDefaultRootWindow.restype = C.c_ulong
                layout.lib.XDeleteProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong]
                layout.lib.XDeleteProperty.restype = C.c_int
                atom = layout.lib.XInternAtom(layout.display, b'_XKB_RULES_NAMES', False)
                root = layout.lib.XDefaultRootWindow(layout.display)
                layout.lib.XDeleteProperty(layout.display, root, atom)
                layout.lib.XSync(layout.display, False)
                assert layout.layout_identifier() not in ('', 'System')
                assert str(ecodes.KEY_Q) in layout.labels()
            finally:
                layout.close()
        finally:
            server.terminate()
            server.wait(timeout=5)


def test_gamepad_hints_follow_connection(keyboard_window: SystemKeyboardWindow) -> None:
    keyboard = keyboard_window.keyboard
    for gamepad in (None, GamepadType.XBOX.value, None, GamepadType.PLAYSTATION.value):
        keyboard_window.command('gamepad', gamepad)
        language = keyboard.buttons['🌐']
        assert isinstance(language, QPushButton)
        assert language.icon().isNull() == (gamepad is None)


@pytest.mark.parametrize('connected', [False, True])
def test_child_receives_initial_gamepad_state(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, connected: bool,
) -> None:
    parent = QWidget()
    parent.input_manager = SimpleNamespace(  # type: ignore[attr-defined]
        gamepad=object() if connected else None, gamepad_type=GamepadType.XBOX)
    keyboard = SystemKeyboard(parent)
    send = MagicMock()
    monkeypatch.setattr(keyboard, 'send', send)
    keyboard._started()
    send.assert_any_call('gamepad', GamepadType.XBOX.value if connected else None)


@pytest.mark.parametrize('connected', [False, True])
def test_hotplug_forwards_gamepad_presence(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, connected: bool,
) -> None:
    manager = InputManager.__new__(InputManager)
    manager.gamepad = cast(SDLGamepad, object()) if connected else None
    manager.gamepad_type = GamepadType.XBOX
    keyboard = SimpleNamespace(send=MagicMock())
    monkeypatch.setattr(manager, '_parent', SimpleNamespace(system_keyboard=keyboard), raising=False)
    manager._refresh_gamepad_ui()
    keyboard.send.assert_called_once_with('gamepad', GamepadType.XBOX.value if connected else None)


@pytest.fixture(params=['named', 'numeric'])
def native_layout(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    from portprotonqt.system_keyboard.layouts import Layout

    text = b'''xkb_keymap {
        xkb_keycodes "test" { minimum=8; maximum=255; <AD01>=24; <LFSH>=50; };
        xkb_types "test" {
            type "TWO_LEVEL" { modifiers=Shift; map[Shift]=Level2; };
        };
        xkb_compatibility "test" {
            interpret Shift_L { action=SetMods(modifiers=Shift); };
        };
        xkb_symbols "test" {
            name[Group1]="Test English"; name[Group2]="Test Russian";
            key <AD01> { type="TWO_LEVEL", symbols[Group1]=[q,Q],
                symbols[Group2]=[Cyrillic_shorti,Cyrillic_SHORTI] };
            key <LFSH> { [Shift_L] }; modifier_map Shift { <LFSH> };
        };
    };'''
    if request.param == 'numeric':
        text = text.replace(b'Group', b'').replace(b'=Level2', b'=2').replace(b'[q,Q]', b'[0x71,0x51]')
    yield Layout(keymap_text=text)


@pytest.mark.parametrize('identifier, modifiers, code, expected', [
    ('de', (), ecodes.KEY_Q, 'q'),
    ('de', (ecodes.KEY_RIGHTSHIFT,), ecodes.KEY_Q, 'Q'),
    ('de', (ecodes.KEY_RIGHTALT,), ecodes.KEY_Q, '@'),
    ('de', (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTALT), ecodes.KEY_Q, 'Ω'),
    ('de', (ecodes.KEY_RIGHTALT,), ecodes.KEY_E, '€'),
    ('ru', (ecodes.KEY_CAPSLOCK,), ecodes.KEY_Q, 'Й'),
    ('ru', (ecodes.KEY_CAPSLOCK, ecodes.KEY_LEFTSHIFT), ecodes.KEY_Q, 'й'),
    ('us+intl', (ecodes.KEY_RIGHTALT,), ecodes.KEY_E, 'é'),
    ('us+intl', (ecodes.KEY_RIGHTALT, ecodes.KEY_CAPSLOCK), ecodes.KEY_E, 'É'),
    ('us+dvorak', (), ecodes.KEY_Q, "'"),
])
def test_bundled_keyboard_layers(
    identifier: str, modifiers: tuple[int, ...], code: int, expected: str,
) -> None:
    from portprotonqt.system_keyboard.layouts import Layout

    assert Layout(identifier).labels(modifiers)[str(code)] == expected


def test_all_bundled_layouts_have_complete_layers() -> None:
    from portprotonqt.keyboard_layouts import keyboard_layouts
    from portprotonqt.system_keyboard.layouts import Layout
    from portprotonqt.system_keyboard.keys import ROWS, MODIFIERS

    expected_codes = {str(code) for row in ROWS for _, code in row if code not in MODIFIERS}
    for identifier, layers in keyboard_layouts.items():
        if identifier == 'en':
            continue
        assert set(layers) == {
            'normal', 'shift', 'altgr', 'shift_altgr',
            'caps', 'shift_caps', 'altgr_caps', 'shift_altgr_caps',
        }, identifier
        layout = Layout(identifier)
        for shift in ((), (ecodes.KEY_LEFTSHIFT,)):
            for altgr in ((), (ecodes.KEY_RIGHTALT,)):
                for caps in ((), (ecodes.KEY_CAPSLOCK,)):
                    assert set(layout.labels(shift + altgr + caps)) == expected_codes, identifier


@pytest.mark.parametrize('symbol, expected', [
    (0x06CA, 'й'), (0x010020AC, '€'), (ord('A'), 'A'),
    ('Cyrillic_shorti', 'й'), ('U20AC', '€'), ('dead_acute', 'dead_acute'),
])
def test_keysym_labels_without_native_library(symbol: int | str, expected: str) -> None:
    from portprotonqt.system_keyboard.layouts import keysym_label

    assert keysym_label(symbol) == expected


def test_unknown_bundled_layout_fails() -> None:
    from portprotonqt.system_keyboard.layouts import Layout

    with pytest.raises(ValueError, match='Unknown keyboard layout'):
        Layout('unknown-layout')


def test_native_labels_preserve_modifiers_and_group(native_layout: Any) -> None:
    assert native_layout.labels()[str(ecodes.KEY_Q)] == 'q'
    assert native_layout.labels((ecodes.KEY_LEFTSHIFT,))[str(ecodes.KEY_Q)] == 'Q'
    assert native_layout.labels(mask=(0, 0, 0, 1))[str(ecodes.KEY_Q)] == 'й'
    assert native_layout.labels(mask=(1, 0, 0, 1))[str(ecodes.KEY_Q)] == 'Й'
    assert native_layout.layout_identifier(0) == 'Test English'
    assert native_layout.layout_identifier(1) == 'Test Russian'
    with pytest.raises(ValueError):
        native_layout.labels(mask=(0,))


def test_wayland_protocol_metadata_is_native(application: QApplication) -> None:
    from portprotonqt.system_keyboard.window import WaylandWindow
    from portprotonqt.system_keyboard.native import load_library

    window = WaylandWindow.__new__(WaylandWindow)
    window.lib = load_library()
    window._configure_library()
    for name in ('wl_surface', 'wl_shm', 'zwlr_layer_shell_v1', 'zwlr_layer_surface_v1',
                 'zcosmic_keyboard_layout_manager_v1', 'zcosmic_keyboard_layout_v1'):
        assert window._interface(name)
    with pytest.raises(RuntimeError, match='Unknown Wayland interface'):
        window._interface('not_a_protocol')


@pytest.mark.parametrize('desktop', ['labwc', 'wayfire', 'Qtile', 'river', 'unknown'])
def test_generic_wayland_uses_manual_labels_without_xwayland(
    monkeypatch: pytest.MonkeyPatch, desktop: str,
) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', desktop)
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-test')
    for variable in ('HYPRLAND_INSTANCE_SIGNATURE', 'SWAYSOCK', 'NIRI_SOCKET',
                     'UMBRIEL_SOCKET', 'MANGO_INSTANCE_SIGNATURE'):
        monkeypatch.delenv(variable, raising=False)
    x11 = MagicMock()
    monkeypatch.setattr(detection, 'X11Layout', x11)
    with pytest.raises(RuntimeError, match='No keyboard layout adapter'):
        detection.detect_layout()
    x11.assert_not_called()


@pytest.mark.parametrize('platform', [None, 'wayland', 'xcb', 'offscreen'])
@pytest.mark.parametrize('wayland, supported', [(False, False), (True, False), (True, True)])
def test_layer_shell_selection_uses_protocol_not_desktop(
    monkeypatch: pytest.MonkeyPatch, wayland: bool, supported: bool, platform: str | None,
) -> None:
    from portprotonqt.system_keyboard import __main__ as keyboard_main
    from portprotonqt.system_keyboard import native

    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'unknown')
    if platform is None:
        monkeypatch.delenv('QT_QPA_PLATFORM', raising=False)
    else:
        monkeypatch.setenv('QT_QPA_PLATFORM', platform)
    if wayland:
        monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-test')
    else:
        monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    library = MagicMock()
    library.portproton_keyboard_has_layer_shell.return_value = int(supported)
    loader = MagicMock(return_value=library)
    monkeypatch.setattr(native, 'load_library', loader)
    app = MagicMock()
    app.exec.return_value = 0
    monkeypatch.setattr(keyboard_main, 'QApplication', MagicMock(return_value=app))
    monkeypatch.setattr(keyboard_main, 'CommandReader', MagicMock())
    monkeypatch.setattr(keyboard_main, 'setup_logger', MagicMock())
    window = MagicMock()
    layer = MagicMock()
    monkeypatch.setattr(system_window, 'SystemKeyboardWindow', window)
    monkeypatch.setattr(system_window, 'WaylandWindow', layer)
    assert keyboard_main.main() == 0
    window.assert_called_once_with(layer_shell=supported)
    assert layer.called == supported
    assert loader.called == wayland
    assert keyboard_main.os.environ.get('QT_QPA_PLATFORM') == platform


@pytest.mark.parametrize('name, variable', [('umbriel', 'UMBRIEL_SOCKET'),
                                           ('mango', 'MANGO_INSTANCE_SIGNATURE')])
def test_new_compositor_detection(
    monkeypatch: pytest.MonkeyPatch, name: str, variable: str,
) -> None:
    assert detection.compositor({variable: '/test/ipc.sock'}) == name
    assert detection.compositor({'XDG_CURRENT_DESKTOP': name.upper()}) == name
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', name)
    monkeypatch.setattr(detection, 'compositor', lambda env: name)
    adapter_name = 'UmbrielLayout' if name == 'umbriel' else 'MangoLayout'
    adapter = MagicMock()
    monkeypatch.setattr(detection, adapter_name, adapter)
    assert detection.detect_layout() is adapter.return_value
    adapter.assert_called_once_with()


@pytest.fixture
def ipc_layout_registry(tmp_path: Any) -> Any:
    registry = tmp_path / 'evdev.xml'
    registry.write_text('''<xkbConfigRegistry><layoutList>
        <layout><configItem><name>us</name><description>English (US)</description></configItem>
            <variantList><variant><configItem><name>dvorak</name>
                <description>English (Dvorak)</description></configItem></variant></variantList>
        </layout>
        <layout><configItem><name>ru</name><description>Russian</description></configItem></layout>
    </layoutList></xkbConfigRegistry>''')
    return registry


@pytest.mark.parametrize('adapter', [detection.UmbrielLayout, detection.MangoLayout])
def test_ipc_layout_tracks_external_changes_and_variants(
    monkeypatch: pytest.MonkeyPatch, ipc_layout_registry: Any, adapter: Any,
) -> None:
    if adapter is detection.UmbrielLayout:
        responses = ['{"names":["English (Dvorak)","Russian"],"current_index":0}',
                     '{"names":["English (Dvorak)","Russian"],"current_index":1}']
        query = ['umbriel', 'keyboard-layouts', '--json']
    else:
        responses = ['{"layout":"English (Dvorak)"}', '{"layout":"Russian"}']
        query = ['mmsg', 'get', 'keyboardlayout']
    command = MagicMock(side_effect=[responses[0], responses[0], responses[1]])
    monkeypatch.setattr(detection, 'command', command)
    first, second = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(detection, 'Layout', factory)
    layout = adapter(ipc_layout_registry)
    try:
        assert layout.current == ('us', 'dvorak')
        assert layout.labels((ecodes.KEY_LEFTSHIFT,)) is first.labels.return_value
        first.labels.assert_called_once_with((ecodes.KEY_LEFTSHIFT,))
        assert factory.call_count == 1
        assert layout.labels() is second.labels.return_value
        assert layout.current == ('ru', '')
        assert layout.layout is second
        assert [call.args for call in factory.call_args_list] == [('us', 'dvorak'), ('ru', '')]
        assert all(call.args == (query,) for call in command.call_args_list)
    finally:
        layout.close()
    assert layout.layout is None


@pytest.mark.parametrize('adapter, reply, expected', [
    (detection.UmbrielLayout, '', ['umbriel', 'msg', 'keyboard-layout-next']),
    (detection.MangoLayout, '{"success":true}', ['mmsg', 'dispatch', 'switch_keyboard_layout,0']),
])
def test_new_compositor_language_button_uses_ipc(
    monkeypatch: pytest.MonkeyPatch, adapter: Any, reply: str, expected: list[str],
) -> None:
    command = MagicMock(return_value=reply)
    monkeypatch.setattr(detection, 'command', command)
    worker = SystemInputWorker()
    worker.enabled.set()
    worker.layout = adapter.__new__(adapter)
    device = MagicMock()
    worker._execute(device, 'language', ())
    command.assert_called_once_with(expected)
    device.write.assert_not_called()


@pytest.mark.parametrize('adapter, reply', [
    (detection.UmbrielLayout, 'null'),
    (detection.UmbrielLayout, '{"err":"no keyboard"}'),
    (detection.UmbrielLayout, '{"names":["Russian"],"current_index":true}'),
    (detection.UmbrielLayout, '{"names":["Russian"],"current_index":-1}'),
    (detection.UmbrielLayout, '{"names":["Russian"],"current_index":1}'),
    (detection.UmbrielLayout, '{"names":[],"current_index":0}'),
    (detection.UmbrielLayout, '{"names":[null],"current_index":0}'),
    (detection.UmbrielLayout, '{"names":[""],"current_index":0}'),
    (detection.MangoLayout, 'null'),
    (detection.MangoLayout, '{"error":"no keyboard"}'),
    (detection.MangoLayout, '{"layout":""}'),
    (detection.MangoLayout, '{"layout":[]}'),
    (detection.MangoLayout, 'invalid json'),
])
def test_new_compositor_rejects_invalid_layout_reply(
    monkeypatch: pytest.MonkeyPatch, adapter: Any, reply: str,
) -> None:
    monkeypatch.setattr(detection, 'command', MagicMock(return_value=reply))
    layout = adapter.__new__(adapter)
    with pytest.raises(ValueError):
        layout._query_name()


@pytest.mark.parametrize('reply', ['{"success":false}', '{"error":"unknown function"}',
                                 '{"success":1}', 'null'])
def test_mango_reports_switch_failure(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    monkeypatch.setattr(detection, 'command', MagicMock(return_value=reply))
    layout = detection.MangoLayout.__new__(detection.MangoLayout)
    with pytest.raises(RuntimeError, match='Mango failed to switch keyboard layout'):
        layout.switch()


def test_wayland_buffer_without_memfd_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, application: QApplication,
) -> None:
    import os

    monkeypatch.delattr(os, 'memfd_create', raising=False)
    monkeypatch.delattr(os, 'MFD_CLOEXEC', raising=False)
    monkeypatch.setattr(system_window.tempfile, 'tempdir', str(tmp_path))
    window: Any = system_window.WaylandWindow.__new__(system_window.WaylandWindow)
    window.buffers = {}
    window.shm = 1
    window._interface = MagicMock(return_value=123)
    window._request = MagicMock(side_effect=[2, 3])
    window._destroy = MagicMock()
    window._listen = MagicMock()
    assert window._buffer(4, 4) == 3
    memory = window.buffers[3]['memory']
    try:
        assert len(memory) == 4 * 4 * system_window.PIXEL_BYTES
        memory[:4] = b'test'
        assert memory[:4] == b'test'
        assert window._buffer(4, 4) == 3
        assert window._request.call_count == 2
        window._destroy.assert_called_once_with(2, 1)
        assert list(tmp_path.iterdir()) == []
    finally:
        memory.close()


def test_wayland_buffer_failure_closes_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, application: QApplication,
) -> None:
    monkeypatch.setattr(system_window.tempfile, 'tempdir', str(tmp_path))
    memory = MagicMock()
    monkeypatch.setattr(system_window.mmap, 'mmap', MagicMock(return_value=memory))
    window: Any = system_window.WaylandWindow.__new__(system_window.WaylandWindow)
    window.buffers = {}
    window.shm = 1
    window._interface = MagicMock(return_value=123)
    window._request = MagicMock(side_effect=RuntimeError('Cannot create Wayland protocol object'))
    with pytest.raises(RuntimeError, match='Cannot create Wayland protocol object'):
        window._buffer(4, 4)
    memory.close.assert_called_once_with()
    assert not window.buffers
    assert list(tmp_path.iterdir()) == []


def test_kde_tracks_layout_and_switches_via_dbus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, application: QApplication,
) -> None:
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    (tmp_path / 'kxkbrc').write_text('[Layout]\nLayoutList=us,ru\nVariantList=dvorak,\n')
    rows = [['us', '', 'English (Dvorak)'], ['ru', '', 'Russian']]
    call = MagicMock(side_effect=[[rows], [0], [], [rows], [1]])
    monkeypatch.setattr(detection.KDELayout, '_call', call)
    first, second = MagicMock(), MagicMock()
    monkeypatch.setattr(detection, 'Layout', MagicMock(side_effect=[first, second]))
    layout = detection.KDELayout()
    assert layout.current == ('us', 'dvorak')
    worker = SystemInputWorker()
    worker.enabled.set()
    worker.layout = layout
    device = MagicMock()
    worker._execute(device, 'language', ())
    device.write.assert_not_called()
    assert layout.labels() is second.labels.return_value
    assert layout.current == ('ru', '')
    assert layout.layout is second
    assert [item.args[0] for item in call.call_args_list] == [
        'getLayoutsList', 'getLayout', 'switchToNextLayout', 'getLayoutsList', 'getLayout']
    layout.close()
    assert layout.layout is None


@pytest.mark.parametrize('index', [-1, 2, True, '0'])
def test_kde_rejects_invalid_layout_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, index: Any,
) -> None:
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    rows = [['us', '', 'English (US)'], ['ru', '', 'Russian']]
    monkeypatch.setattr(detection.KDELayout, '_call', MagicMock(side_effect=[[rows], [index]]))
    with pytest.raises(ValueError, match='Invalid KDE keyboard layout index'):
        detection.KDELayout()


def test_kde_selection_uses_native_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    factory = MagicMock()
    monkeypatch.setattr(detection, 'KDELayout', factory)
    assert detection.detect_layout() is factory.return_value


def test_wayland_mouse_moves_selection_and_shows_pressed_state(
    keyboard_window: SystemKeyboardWindow, application: QApplication,
) -> None:
    from PySide6.QtCore import QEvent, QPointF

    keyboard_window.ready = True
    keyboard_window.show_keyboard()
    application.processEvents()
    keyboard = keyboard_window.keyboard
    target = keyboard.buttons['q']
    previous = keyboard.selected_button
    assert previous is not None
    native: Any = system_window.WaylandWindow.__new__(system_window.WaylandWindow)
    native.window = keyboard_window
    native.pressed_widget = None
    native.position = QPointF(target.mapTo(keyboard_window, target.rect().center()))
    native._mouse_event(QEvent.Type.MouseMove)
    assert keyboard.selected_button is target
    assert target.property('vk_selected')
    if previous is not target:
        assert not previous.property('vk_selected')
    native._mouse_event(QEvent.Type.MouseButtonPress)
    assert target.isDown()
    native._mouse_event(QEvent.Type.MouseButtonRelease)
    assert not target.isDown()
    assert keyboard_window.worker.commands.get_nowait() == ('tap', (ecodes.KEY_Q,))


@pytest.mark.parametrize('failed', [False, True])
def test_kde_dbus_connection_is_retained_and_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, failed: bool,
) -> None:
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    bus = MagicMock()
    bus.connect = AsyncMock(return_value=bus)
    bus.wait_for_disconnect = AsyncMock()
    factory = MagicMock(return_value=bus)
    monkeypatch.setattr(detection, 'MessageBus', factory)
    monkeypatch.setattr(detection, 'Layout', MagicMock())
    rows = [['us', '', 'English (US)'], ['ru', '', 'Russian']]
    calls = AsyncMock(side_effect=[None] if failed else [[rows], [0], [], [rows], [1]])
    monkeypatch.setattr(detection, '_bus_call', calls)
    if failed:
        with pytest.raises(RuntimeError, match='KDE keyboard layout request failed'):
            detection.KDELayout()
    else:
        layout = detection.KDELayout()
        try:
            layout.switch()
            layout.labels()
            assert layout.current == ('ru', '')
            assert calls.await_count == 5
        finally:
            layout.close()
        layout.close()
    factory.assert_called_once_with(bus_type=detection.BusType.SESSION)
    bus.connect.assert_awaited_once_with()
    bus.disconnect.assert_called_once_with()
    bus.wait_for_disconnect.assert_awaited_once_with()


@pytest.mark.parametrize('desktop, schema', [
    ('X-Cinnamon', 'org.cinnamon.desktop.keybindings.wm'),
    ('GNOME', detection.BINDINGS_SCHEMA),
])
def test_layout_shortcut_uses_desktop_binding(
    monkeypatch: pytest.MonkeyPatch, desktop: str, schema: str,
) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', desktop)
    binding = '<Super>space' if desktop == 'X-Cinnamon' else '<Shift><Super>space'
    command = MagicMock(return_value=repr([binding]))
    keymap = MagicMock()
    keymap.keycode.return_value = ecodes.KEY_SPACE
    monkeypatch.setattr(detection, 'command', command)
    monkeypatch.setattr(detection, 'X11Layout', lambda: keymap)
    expected = ((ecodes.KEY_LEFTSHIFT,) if desktop == 'GNOME' else ()) + (
        ecodes.KEY_LEFTMETA, ecodes.KEY_SPACE)
    assert detection.GSettingsLayout.switch_codes() == expected
    key = 'switch-input-source' if desktop == 'X-Cinnamon' else 'switch-input-source-backward'
    command.assert_called_once_with(['gsettings', 'get', schema, key])
    keymap.close.assert_called_once()


@pytest.mark.parametrize('session', ['x11', 'wayland'])
def test_cinnamon_language_button_uses_system_shortcut(
    monkeypatch: pytest.MonkeyPatch, keyboard_window: SystemKeyboardWindow, session: str,
) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'X-Cinnamon')
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    codes = (ecodes.KEY_LEFTMETA, ecodes.KEY_SPACE)
    monkeypatch.setattr(detection.GSettingsLayout, 'switch_codes', staticmethod(lambda: codes))
    worker = keyboard_window.worker
    worker.enabled.set()
    layout: Any = detection.CinnamonLayout.__new__(detection.CinnamonLayout)
    layout.switch = MagicMock()
    worker.layout = layout
    device = MagicMock()
    keyboard_window.keyboard.buttons['🌐'].click()
    action, keys = worker.commands.get_nowait()
    worker._execute(device, action, keys)
    layout.switch.assert_not_called()
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 1), (ecodes.EV_KEY, ecodes.KEY_SPACE, 1),
        (ecodes.EV_KEY, ecodes.KEY_SPACE, 0), (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, 0),
    ]


@pytest.mark.parametrize('theme_name', ['standart', 'standart-light'])
def test_latched_super_repaints_without_manual_polish(
    keyboard_window: SystemKeyboardWindow, application: QApplication, theme_name: str,
) -> None:
    keyboard_window.keyboard.refresh_theme(load_theme(theme_name))
    button = keyboard_window.keyboard.buttons['Super']
    button.setProperty('vk_selected', False)
    button.style().unpolish(button)
    button.style().polish(button)
    button.show()
    application.processEvents()
    released = button.grab().toImage()
    button.click()
    application.processEvents()
    assert button.isChecked()
    assert button.grab().toImage() != released
    button.click()
    application.processEvents()
    assert not button.isChecked()
    assert button.grab().toImage() == released


@pytest.mark.parametrize('desktop', ['X-Cinnamon', 'Cinnamon:GNOME'])
@pytest.mark.parametrize('session', ['x11', 'wayland'])
def test_cinnamon_adapter(monkeypatch: pytest.MonkeyPatch, desktop: str, session: str) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', desktop)
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    adapter = MagicMock()
    monkeypatch.setattr(detection, 'CinnamonLayout', adapter)
    assert detection.detect_layout() is adapter.return_value


def test_cinnamon_tracks_current_source(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = object.__new__(detection.CinnamonLayout)
    sources = [
        ['xkb', 'us', 0, 'English', 'en', 'us', 'us', 'us', '', '', 0, True],
        ['xkb', 'ru', 1, 'Russian', 'ru', 'ru', 'ru', 'ru', 'phonetic', '', 0, False],
    ]
    call = MagicMock(return_value=[sources])
    monkeypatch.setattr(adapter, '_call', call)
    assert adapter._source() == ('us', '')
    sources[0][-1], sources[1][-1] = False, True
    assert adapter._source() == ('ru', 'phonetic')
    call.assert_called_with('GetInputSources')


@pytest.mark.parametrize('sources', [[], [['xkb']], [
    ['ibus', 'test', 0, '', '', '', '', '', '', '', 0, True],
]])
def test_cinnamon_rejects_unavailable_source(monkeypatch: pytest.MonkeyPatch, sources: list) -> None:
    adapter = object.__new__(detection.CinnamonLayout)
    monkeypatch.setattr(adapter, '_call', MagicMock(return_value=[sources]))
    with pytest.raises(ValueError):
        adapter._source()


@pytest.mark.parametrize('session, presses', [('x11', 1), ('wayland', 2)])
def test_super_replays_only_on_wayland(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, session: str, presses: int,
) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    worker = SystemInputWorker()
    worker.enabled.set()
    device = MagicMock()
    worker._execute(device, 'modifiers', (ecodes.KEY_LEFTMETA,))
    worker._execute(device, 'modifiers', ())
    assert [call.args for call in device.write.call_args_list] == [
        (ecodes.EV_KEY, ecodes.KEY_LEFTMETA, value)
        for _ in range(presses) for value in (1, 0)
    ]
    assert not worker.modifiers


def test_x11_labels_follow_keymap_replacement(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import os
    import select
    import shutil
    import subprocess

    server_path = shutil.which('Xvfb')
    if server_path is None and os.environ.get('DISPLAY'):
        server_path = shutil.which('Xephyr')
    if server_path is None or shutil.which('setxkbmap') is None:
        pytest.skip('An isolated X server and setxkbmap are required')
    screen = ['0', '800x600x24'] if server_path.endswith('Xvfb') else ['800x600']
    with (tmp_path / 'xserver.log').open('w') as log:
        server = subprocess.Popen(
            [server_path, '-displayfd', '1', '-screen', *screen,
             '-nolisten', 'tcp', '-noreset'], stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            assert server.stdout is not None
            assert select.select([server.stdout], [], [], 5)[0], 'X server startup timed out'
            number = server.stdout.readline().strip()
            assert number, (tmp_path / 'xserver.log').read_text()
            monkeypatch.setenv('DISPLAY', ':' + number)
            subprocess.run(['setxkbmap', '-layout', 'us,ru,de'], check=True, timeout=5)
            layout = X11Layout()
            try:
                assert layout.labels()[str(ecodes.KEY_Q)] == 'q'
                subprocess.run(['setxkbmap', '-layout', 'ru,us,de'], check=True, timeout=5)
                for expected in ('н', 'y', 'z', 'н'):
                    assert layout.labels()[str(ecodes.KEY_Y)] == expected
                    layout.switch()
            finally:
                layout.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=2)


def test_ibus_switch_cycles_all_configured_layouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    engines = ['xkb:us::eng', 'xkb:ru::rus', 'xkb:de::deu']
    current = [engines[0]]
    switched = []

    def run(args: list[str]) -> str:
        if args == ['gsettings', 'get', detection.IBUS_SCHEMA, 'preload-engines']:
            return repr(engines)
        if args == ['ibus', 'engine']:
            return current[0]
        assert args[:2] == ['ibus', 'engine']
        current[0] = args[2]
        switched.append(args[2])
        return ''

    monkeypatch.setattr(detection, 'command', run)
    worker = SystemInputWorker()
    worker.enabled.set()
    worker.layout = detection.IBusLayout.__new__(detection.IBusLayout)
    device = MagicMock()
    for _ in engines:
        worker._execute(device, 'language', ())
    assert switched == [engines[1], engines[2], engines[0]]
    device.write.assert_not_called()


@pytest.mark.parametrize('engines, current, error', [
    ([], 'xkb:us::eng', ValueError),
    (['xkb:us::eng', 'pinyin'], 'xkb:us::eng', ValueError),
    (['xkb:us::eng'], 'xkb:de::deu', RuntimeError),
])
def test_ibus_switch_rejects_unusable_sources(
    monkeypatch: pytest.MonkeyPatch, engines: list[str], current: str, error: type[Exception],
) -> None:
    command = MagicMock(side_effect=[repr(engines), current])
    monkeypatch.setattr(detection, 'command', command)
    layout = detection.IBusLayout.__new__(detection.IBusLayout)
    with pytest.raises(error):
        layout.switch()
    assert all(len(call.args[0]) != 3 or call.args[0][0] != 'ibus'
               for call in command.call_args_list)


@pytest.mark.parametrize('system_map, engine, uses_ibus', [
    ('false', 'xkb:de::deu', True),
    ('true', 'xkb:de::deu', False),
    ('false', 'pinyin', False),
])
def test_x11_detects_ibus_managed_layouts(
    monkeypatch: pytest.MonkeyPatch, system_map: str, engine: str, uses_ibus: bool,
) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'XFCE')
    monkeypatch.setenv('XMODIFIERS', '@im=ibus')
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(detection, 'command', MagicMock(side_effect=[system_map, engine]))
    ibus = MagicMock()
    x11 = MagicMock()
    monkeypatch.setattr(detection, 'IBusLayout', ibus)
    monkeypatch.setattr(detection, 'X11Layout', x11)
    assert detection.detect_layout() is (ibus.return_value if uses_ibus else x11.return_value)
    assert ibus.call_count == int(uses_ibus)


def test_ibus_detection_failure_keeps_x11_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'XFCE')
    monkeypatch.setenv('XMODIFIERS', '@im=ibus')
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(detection, 'command', MagicMock(side_effect=RuntimeError('IBus unavailable')))
    x11 = MagicMock()
    monkeypatch.setattr(detection, 'X11Layout', x11)
    assert detection.detect_layout() is x11.return_value


@pytest.mark.parametrize('session', ['x11', 'wayland'])
def test_gnome_uses_session_layout_backend(
    monkeypatch: pytest.MonkeyPatch, session: str,
) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'ubuntu:GNOME')
    monkeypatch.setenv('XDG_SESSION_TYPE', session)
    x11, settings = MagicMock(), MagicMock()
    monkeypatch.setattr(detection, 'X11Layout', x11)
    monkeypatch.setattr(detection, 'GSettingsLayout', settings)

    assert detection.detect_layout() is (x11.return_value if session == 'x11' else settings.return_value)
    (settings if session == 'x11' else x11).assert_not_called()


def test_gsettings_layout_does_not_describe_deprecated_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        'sources': "[('xkb', 'us'), ('xkb', 'ru')]",
        'per-window': 'false',
        'mru-sources': "[('xkb', 'ru'), ('xkb', 'us')]",
    }
    command = MagicMock(side_effect=lambda args: values[args[-1]])
    monkeypatch.setattr(detection, 'command', command)
    factory = MagicMock()
    monkeypatch.setattr(detection, 'Layout', factory)

    layout = detection.GSettingsLayout()
    assert layout.current == ('ru', '')
    factory.assert_called_once_with('ru', '')
    for call in command.call_args_list:
        assert call.args[0][:2] == ['gsettings', 'get']
        assert call.args[0][-1] != 'current'
    layout.close()


def test_gnome_x11_switch_uses_configured_desktop_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'ubuntu:GNOME')
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    worker = SystemInputWorker()
    worker.enabled.set()
    layout = X11Layout.__new__(X11Layout)
    layout.switch = MagicMock()
    worker.layout = layout
    shortcut = (ecodes.KEY_LEFTALT, ecodes.KEY_LEFTSHIFT)
    monkeypatch.setattr(detection.GSettingsLayout, 'switch_codes', staticmethod(lambda: shortcut))
    send = MagicMock()
    monkeypatch.setattr(worker, 'send_keys', send)
    device = MagicMock()

    worker._execute(device, 'language', ())

    send.assert_called_once_with(device, shortcut)
    layout.switch.assert_not_called()


@pytest.mark.parametrize('sources', [('us',), ('us', 'ru'), ('us', 'ru', 'kz')])
def test_gsettings_labels_follow_all_mru_sources(
    monkeypatch: pytest.MonkeyPatch, sources: tuple[str, ...],
) -> None:
    history = [('xkb', name) for name in sources]
    values = {'sources': repr(history), 'per-window': 'false'}
    monkeypatch.setattr(detection, 'command', lambda args: (
        repr(history) if args[-1] == 'mru-sources' else values[args[-1]]))
    factory = MagicMock()
    monkeypatch.setattr(detection, 'Layout', factory)
    layout = detection.GSettingsLayout()
    try:
        for _ in sources:
            following = history.pop()
            history.insert(0, following)
            layout.labels()
            assert layout.current == (following[1], '')
        assert {call.args[0] for call in factory.call_args_list} == set(sources)
    finally:
        layout.close()


def test_keyboard_child_errors_go_to_terminal_without_dialog(
    monkeypatch: pytest.MonkeyPatch, application: QApplication, capfd: pytest.CaptureFixture[str],
) -> None:
    import sys
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QMessageBox

    dialog = MagicMock()
    monkeypatch.setattr(QMessageBox, 'warning', dialog)
    parent = QWidget()
    keyboard = SystemKeyboard(parent)
    message = 'TimeoutExpired: gsettings timed out\n' * 512
    assert keyboard.process.processChannelMode() == QProcess.ProcessChannelMode.ForwardedErrorChannel
    keyboard.process.start(sys.executable, [
        '-c', 'import sys; sys.stderr.write(sys.argv[1]); sys.exit(1)', message])
    assert keyboard.process.waitForFinished(5000)
    application.processEvents()

    assert message in capfd.readouterr().err
    assert not keyboard.visible
    dialog.assert_not_called()
    keyboard.shutdown()


def test_keyboard_start_failure_does_not_open_dialog(
    monkeypatch: pytest.MonkeyPatch, application: QApplication,
) -> None:
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QMessageBox

    dialog = MagicMock()
    monkeypatch.setattr(QMessageBox, 'warning', dialog)
    parent = QWidget()
    keyboard = SystemKeyboard(parent)
    keyboard.process = MagicMock()
    keyboard.process.errorString.return_value = 'Cannot execute keyboard process'
    keyboard.visible = True

    keyboard._process_error(QProcess.ProcessError.FailedToStart)

    assert not keyboard.visible
    dialog.assert_not_called()
    keyboard.shutdown()
