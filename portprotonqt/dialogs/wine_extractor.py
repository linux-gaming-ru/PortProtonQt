"""Wine archive extractor for PortProtonQt."""

import os
import sys
import shutil
import tempfile
import time
import libarchive
from PySide6.QtCore import QThread, Signal, QMutex
from portprotonqt.logger import get_logger

logger = get_logger(__name__)


class ExtractionThread(QThread):
    """Thread for extracting Wine/Proton archives."""

    progress = Signal(int)
    speed = Signal(float)
    eta = Signal(int)
    finished = Signal(str, bool)
    error = Signal(str)

    def __init__(self, archive_path: str, extract_dir: str):
        super().__init__()
        self.archive_path = archive_path
        self.extract_dir = extract_dir
        self._is_running = True
        self._mutex = QMutex()

    def _should_stop(self) -> bool:
        self._mutex.lock()
        running = self._is_running
        self._mutex.unlock()
        return not running

    def _get_entry_path(self, entry_path: str, link_path: str | None = None) -> str:
        extract_root = os.path.realpath(self.extract_dir)
        target_path = os.path.realpath(os.path.join(extract_root, entry_path))
        if os.path.commonpath((extract_root, target_path)) != extract_root:
            raise ValueError(f"Archive entry escapes extraction directory: {entry_path}")
        if link_path is None:
            return target_path
        link_target = os.path.realpath(
            os.path.join(os.path.dirname(target_path), link_path)
        )
        if os.path.commonpath((extract_root, link_target)) != extract_root:
            raise ValueError(f"Archive link escapes extraction directory: {entry_path}")
        return target_path

    def run(self):
        destination = self.extract_dir
        staging = None
        try:
            if sys.platform == "darwin":
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                staging = tempfile.mkdtemp(prefix=".wine-install-", dir=os.path.dirname(destination))
                self.extract_dir = staging
            self.progress.emit(0)
            self.speed.emit(0.0)
            self.eta.emit(0)

            os.makedirs(self.extract_dir, exist_ok=True)

            archive_size = os.path.getsize(self.archive_path)
            if archive_size <= 0:
                archive_size = 1

            start_time = time.monotonic()
            last_emit_time = start_time
            last_progress = -1
            last_bytes_read = 0

            try:
                deferred_times = []

                with libarchive.file_reader(self.archive_path) as archive:
                    for entry in archive:
                        if self._should_stop():
                            return

                        entry_path = entry.pathname
                        if entry_path is None:
                            continue
                        link_path = os.fsdecode(entry.linkpath) if entry.issym else None
                        target_path = self._get_entry_path(entry_path, link_path)

                        if entry.isdir:
                            os.makedirs(target_path, exist_ok=True)
                            if entry.mode:
                                try:
                                    os.chmod(target_path, entry.mode)
                                except (OSError, PermissionError):
                                    pass
                            if entry.mtime:
                                deferred_times.append((target_path, entry.mtime))

                        elif entry.isfile:
                            parent_dir = os.path.dirname(target_path)
                            if parent_dir:
                                os.makedirs(parent_dir, exist_ok=True)

                            with open(target_path, 'wb') as f:
                                for block in entry.get_blocks():
                                    if self._should_stop():
                                        return
                                    f.write(block)

                            if entry.mode:
                                try:
                                    os.chmod(target_path, entry.mode)
                                except (OSError, PermissionError):
                                    pass

                            if entry.mtime:
                                try:
                                    os.utime(target_path, (entry.mtime, entry.mtime))
                                except (OSError, PermissionError):
                                    pass

                        elif entry.issym:
                            parent_dir = os.path.dirname(target_path)
                            if parent_dir:
                                os.makedirs(parent_dir, exist_ok=True)

                            if os.path.lexists(target_path):
                                os.remove(target_path)

                            if link_path is not None:
                                try:
                                    os.symlink(link_path, target_path)
                                except (OSError, NotImplementedError):
                                    pass

                        bytes_read = archive.bytes_read
                        now = time.monotonic()
                        elapsed = now - start_time

                        if bytes_read != last_bytes_read:
                            last_bytes_read = bytes_read

                            if now - last_emit_time >= 0.1 or elapsed < 0.1:
                                progress = int((bytes_read / archive_size) * 100)
                                if progress != last_progress:
                                    self.progress.emit(min(progress, 99))
                                    last_progress = progress

                                if elapsed > 0:
                                    speed = (bytes_read / (1024 * 1024)) / elapsed
                                    self.speed.emit(round(speed, 2))

                                    if speed > 0:
                                        remaining_mb = (archive_size - bytes_read) / (1024 * 1024)
                                        self.eta.emit(max(0, int(remaining_mb / speed)))
                                    else:
                                        self.eta.emit(0)
                                else:
                                    self.speed.emit(0.0)
                                    self.eta.emit(0)

                                last_emit_time = now

                for dir_path, mtime in reversed(deferred_times):
                    try:
                        os.utime(dir_path, (mtime, mtime))
                    except (OSError, PermissionError):
                        pass

                if self._should_stop():
                    return
                if staging is not None:
                    from pathlib import Path
                    from portprotonqt.macos import find_wine
                    if find_wine(Path(staging)) is None:
                        raise ValueError("Archive does not contain a macOS Wine executable")
                    os.rename(staging, destination)
                self.progress.emit(100)
                self.speed.emit(0.0)
                self.eta.emit(0)
                self.finished.emit(self.archive_path, True)

            finally:
                self.eta.emit(0)

        except Exception as e:
            if not self._should_stop():
                self.error.emit(str(e))
        finally:
            self.extract_dir = destination
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def stop(self):
        self._mutex.lock()
        self._is_running = False
        self._mutex.unlock()

        if self.isRunning():
            self.quit()
            self.wait(1000)
