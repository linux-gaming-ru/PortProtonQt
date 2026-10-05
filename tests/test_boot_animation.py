"""Boot page rendering, startup transition, and shutdown regressions."""
from collections.abc import Generator
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from pytest import MonkeyPatch, fixture, mark
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

import portprotonqt.boot_animation as boot
from portprotonqt.config import display_config
from portprotonqt.main_window import MainWindow
from portprotonqt.themes.standart.styles import constants


def test_theme_video_lookup(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    child = tmp_path / "child"
    parent = tmp_path / "parent"
    child.mkdir()
    parent.mkdir()
    monkeypatch.setattr(boot, "_find_theme_folder", lambda name: str(tmp_path / name))
    monkeypatch.setattr(boot, "_read_theme_parent_name", lambda _name: "parent")
    assert boot.find_boot_video("child") is None
    parent_video = parent / "bootanimation.webm"
    parent_video.write_bytes(b"video")
    assert boot.find_boot_video("child") == str(parent_video)
    child_video = child / "bootanimation.webm"
    child_video.write_bytes(b"video")
    assert boot.find_boot_video("child") == str(child_video)
    child_video.unlink()
    child_video.symlink_to(parent_video)
    assert boot.find_boot_video("child") is None


@fixture
def startup(tmp_path: Path, monkeypatch: MonkeyPatch) -> Generator[Any, None, None]:
    import PySide6.QtMultimedia as media

    app = QApplication.instance() or QApplication([])
    player = MagicMock()
    factory = MagicMock(return_value=player)
    factory.MediaStatus = media.QMediaPlayer.MediaStatus
    monkeypatch.setattr(media, "QMediaPlayer", factory)
    monkeypatch.setattr(media, "QAudioOutput", MagicMock())
    monkeypatch.setattr(boot, "find_boot_video", lambda _name: str(tmp_path / "video.webm"))
    monkeypatch.setattr(display_config, "get_boot_animation_enabled", lambda: True)
    window = cast(Any, QMainWindow())
    window.theme = SimpleNamespace(color_boot_animation=constants.color_boot_animation,
                                   bootAnimationTimeoutMs=constants.bootAnimationTimeoutMs)
    window.current_theme_name = "test"
    window.startup_stack = QStackedWidget(window)
    library = QWidget()
    window.startup_stack.addWidget(library)
    window.setCentralWidget(window.startup_stack)
    window.boot_animation = None
    loader = MagicMock()
    window.startup_load_timer = QTimer(window)
    window.startup_load_timer.setSingleShot(True)
    window.startup_load_timer.timeout.connect(loader)
    window.startup_load_timer.start()
    window._finish_boot_animation = MethodType(MainWindow._finish_boot_animation, window)
    window.showFullScreen()
    MainWindow.start_boot_animation(window)
    yield SimpleNamespace(app=app, window=window, library=library, player=player, loader=loader)
    if window.boot_animation is not None:
        window.boot_animation.stop()
    window.close()
    window.deleteLater()


def test_startup_renders_black_and_real_video_frames(startup: Any) -> None:
    from PySide6.QtMultimedia import QVideoFrame

    window = startup.window
    animation = window.boot_animation
    startup.player.play.assert_not_called()
    window.resize(200, 200)
    window.show()
    startup.app.processEvents()
    startup.player.play.assert_called_once_with()
    startup.loader.assert_not_called()
    assert window.startup_stack.currentWidget() is animation
    assert not animation.isWindow()
    assert not startup.library.isVisible()
    black = QColor(constants.color_boot_animation)
    image = animation.grab().toImage()
    assert image.pixelColor(0, 0) == black
    assert image.pixelColor(image.width() // 2, image.height() // 2) == black
    frame = QImage(32, 16, QImage.Format.Format_RGB32)
    color = QColor(constants.color_accent)
    frame.fill(color)
    animation.sink.setVideoFrame(QVideoFrame(frame))
    image = animation.grab().toImage()
    assert image.pixelColor(100, 0) == black
    assert image.pixelColor(image.width() // 2, image.height() // 2) == color
    assert image.pixelColor(image.width() // 2, image.height() - 1) == black


@mark.parametrize("reason", ["end", "error", "key", "click", "timeout"])
def test_startup_completion_loads_library_once(startup: Any, reason: str) -> None:
    from PySide6.QtMultimedia import QMediaPlayer

    animation = startup.window.boot_animation
    startup.window.show()
    startup.app.processEvents()
    if reason == "end":
        animation._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
    elif reason == "error":
        animation._playback_error(object(), "invalid WebM")
    elif reason == "key":
        QTest.keyClick(animation, Qt.Key.Key_Space)
    elif reason == "click":
        QTest.mouseClick(animation, Qt.MouseButton.LeftButton)
    else:
        animation.timeout.timeout.emit()
    animation.finish()
    startup.app.processEvents()
    assert startup.window.boot_animation is None
    assert startup.window.startup_stack.currentWidget() is startup.library
    assert startup.library.isVisible()
    startup.player.stop.assert_called_once_with()
    startup.loader.assert_called_once_with()


def test_shutdown_cancels_pending_playback_without_loading(startup: Any) -> None:
    animation = startup.window.boot_animation
    startup.app.aboutToQuit.emit()
    startup.app.processEvents()
    startup.player.play.assert_not_called()
    startup.player.stop.assert_called_once_with()
    startup.loader.assert_not_called()
    assert not animation.timeout.isActive()


def test_gamepad_button_skips_boot_before_normal_routing(startup: Any) -> None:
    from PySide6.QtCore import QObject
    from portprotonqt.input_manager import InputManager
    from portprotonqt.input_manager.constants import PAD_BUTTON_SOUTH

    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._parent = startup.window
    manager._button_states = {}
    manager.mouse_emulation_enabled = True
    manager.emulation_active = True
    manager.emulation_triggered = True
    manager.button_event.connect(manager.handle_button_slot, Qt.ConnectionType.QueuedConnection)
    startup.app.processEvents()
    manager._handle_button_value(0, PAD_BUTTON_SOUTH, 0, 1.0)
    startup.app.processEvents()
    assert startup.window.boot_animation is not None
    manager._handle_button_value(0, PAD_BUTTON_SOUTH, 1, 2.0)
    assert startup.window.boot_animation is not None
    startup.app.processEvents()
    assert startup.window.boot_animation is None
    startup.app.processEvents()
    startup.loader.assert_called_once_with()


def test_runtime_boot_does_not_reload_library(startup: Any) -> None:
    startup.app.processEvents()
    startup.window.boot_animation.finish()
    startup.app.processEvents()
    startup.loader.reset_mock()
    MainWindow.start_boot_animation(startup.window)
    animation = startup.window.boot_animation
    assert animation is not None
    startup.app.processEvents()
    animation.finish()
    startup.app.processEvents()
    startup.loader.assert_not_called()


def test_windowed_launch_does_not_show_boot(startup: Any) -> None:
    startup.app.processEvents()
    startup.window.boot_animation.finish()
    startup.window.showNormal()
    MainWindow.start_boot_animation(startup.window)
    assert startup.window.boot_animation is None


def test_disabled_boot_does_not_start(startup: Any, monkeypatch: MonkeyPatch) -> None:
    startup.app.processEvents()
    startup.window.boot_animation.finish()
    monkeypatch.setattr(display_config, "get_boot_animation_enabled", lambda: False)
    lookup = MagicMock()
    monkeypatch.setattr(boot, "find_boot_video", lookup)
    MainWindow.start_boot_animation(startup.window)
    assert startup.window.boot_animation is None
    lookup.assert_not_called()
