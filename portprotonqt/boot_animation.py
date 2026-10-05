"""Theme boot video rendered inside the application's startup page."""
import os
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QApplication, QWidget

from portprotonqt.logger import get_logger
from portprotonqt.theme_manager import _find_theme_folder, _read_theme_parent_name

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QVideoFrame

logger = get_logger(__name__)


def find_boot_video(theme_name: str) -> str | None:
    """Find the theme's WebM, following its existing inheritance chain."""
    visited = set()
    while theme_name and theme_name not in visited:
        visited.add(theme_name)
        folder = _find_theme_folder(theme_name)
        if folder is not None:
            path = os.path.join(folder, "bootanimation.webm")
            if os.path.isfile(path):
                if os.path.dirname(os.path.realpath(path)) == os.path.realpath(folder):
                    return path
                logger.warning("Boot video outside theme directory blocked: %s", path)
                return None
        theme_name = _read_theme_parent_name(theme_name) or ""
    return None


class BootAnimation(QWidget):
    finished = Signal()

    def __init__(self, theme: Any, video_path: str, parent: QWidget) -> None:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

        super().__init__(parent)
        self._background = QColor(theme.color_boot_animation)
        self._video_path = video_path
        self._frame = QImage()
        self._stopped = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._receive_frame)
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoSink(self.sink)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._playback_error)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(theme.bootAnimationTimeoutMs)
        self.timeout.timeout.connect(self.finish)

    def start(self) -> None:
        if self._stopped:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.timeout.start()
        self.player.setSource(QUrl.fromLocalFile(self._video_path))
        if not self._stopped:
            self.player.play()

    def _receive_frame(self, frame: "QVideoFrame") -> None:
        if self._stopped or not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._frame = image
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)
        if not self._frame.isNull():
            size = self._frame.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(), size)
            target.moveCenter(self.rect().center())
            painter.drawImage(target, self._frame)

    def _media_status_changed(self, status: object) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finish()

    def _playback_error(self, error: object, message: str) -> None:
        logger.warning("Boot video playback failed: %s", message)
        self.finish()

    def finish(self) -> None:
        if not self._stopped:
            self.stop()
            self.finished.emit()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.timeout.stop()
        self.player.stop()
        self.sink.videoFrameChanged.disconnect(self._receive_frame)
        self._frame = QImage()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self and event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress):
            self.finish()
            return True
        return super().eventFilter(watched, event)
