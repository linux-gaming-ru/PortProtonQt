"""Launch and control the system keyboard independently of application focus."""

import sys

import orjson
from PySide6.QtCore import QObject, QProcess
from PySide6.QtWidgets import QApplication, QWidget

from portprotonqt.config import ui_config
from portprotonqt.logger import get_logger

logger = get_logger(__name__)
SHUTDOWN_TIMEOUT_MS = 3000
MAX_EMOJI_LENGTH = 16


class SystemKeyboard(QObject):
    """Retain the child process and forward gamepad commands over its stdin."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.owner = parent
        self.process = QProcess(self)
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read_state)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._finished)
        self.visible = False
        self.shift_pressed = False
        self.output = bytearray()
        self.closing = False
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def isVisible(self) -> bool:
        return self.visible

    def toggle(self) -> None:
        if self.visible:
            self.hide()
            return
        self.visible = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.send('show')
            return
        self.output.clear()
        self.process.start(sys.executable, ['-m', 'portprotonqt.system_keyboard'])

    def _started(self) -> None:
        self.send('theme', ui_config.get_theme())
        manager = getattr(self.owner, 'input_manager', None)
        connected = getattr(manager, 'gamepad', None) is not None
        self.send('gamepad', manager.gamepad_type.value if manager is not None and connected else None)
        self.send('show' if self.visible else 'hide')

    def send(self, action: str, value: object = None) -> None:
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write(orjson.dumps({'action': action, 'value': value}) + b'\n')

    def hide(self) -> None:
        self.visible = False
        self.send('hide')

    def _read_state(self) -> None:
        self.output.extend(bytes(self.process.readAllStandardOutput().data()))
        while b'\n' in self.output:
            line, _, remainder = self.output.partition(b'\n')
            self.output = bytearray(remainder)
            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                logger.warning('Invalid system keyboard response: %r', line)
                continue
            if isinstance(data, dict) and data.get('event') == 'hidden':
                self.visible = False
                self.shift_pressed = False
            elif isinstance(data, dict) and data.get('event') == 'shift':
                self.shift_pressed = bool(data.get('value'))
            elif isinstance(data, dict) and data.get('event') == 'emoji' and self.visible:
                value = data.get('value')
                if (isinstance(value, str) and 0 < len(value) <= MAX_EMOJI_LENGTH
                        and value.isprintable() and not value.isascii()):
                    QApplication.clipboard().setText(value)

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.visible = False
            logger.error('Cannot open system keyboard: %s', self.process.errorString())

    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self.visible = False
        self.shift_pressed = False
        if not self.closing and (code or status == QProcess.ExitStatus.CrashExit):
            logger.error('System keyboard exited with code %s (%s)', code, status.name)

    def shutdown(self) -> None:
        self.closing = True
        self.visible = False
        self.send('quit')
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        if self.process.waitForFinished(SHUTDOWN_TIMEOUT_MS):
            return
        self.process.terminate()
        if not self.process.waitForFinished(SHUTDOWN_TIMEOUT_MS):
            self.process.kill()
            self.process.waitForFinished(SHUTDOWN_TIMEOUT_MS)
