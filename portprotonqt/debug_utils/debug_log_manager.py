"""Debug log manager for game launch and output capture."""

import os
import queue
import signal
import subprocess
import threading
import time
import tempfile
import shutil
from pathlib import Path
from typing import IO

from portprotonqt.logger import get_logger
from portprotonqt.config import get_portproton_location

from portprotonqt.debug_utils.system_info import generate_system_info
from portprotonqt.debug_utils.log_processor import process_portproton_log
from portprotonqt.debug_utils.env_utils import get_portproton_runtime_env

logger = get_logger(__name__)


class DebugLogManager:
    """Manage debug logs for Wine and native game launches."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.exe_path: str | None = None
        self.start_command: list[str] | None = None
        self.wine_output: list[str] = []
        self.runtime_env: dict[str, str] | None = None
        self.native_output: IO[str] | None = None
        self.native_directory: str | None = None
        self.is_running = False
        self.output_queue = queue.Queue()
        self.output_thread = None
        self._stop_event = threading.Event()

    def start(self, exe_path: str, start_command: list[str]) -> bool:
        """Capture game output, enabling PW_LOG for PortProton launches."""
        if self.is_running:
            return False
        if exe_path.startswith("native://"):
            return self._start_native(exe_path)

        self.exe_path = exe_path
        self.start_command = start_command
        self.wine_output = []
        self.runtime_env = None
        self._stop_event.clear()

        portproton_path = get_portproton_location()
        if portproton_path:
            portproton_log_path = os.path.join(portproton_path, "PortProton.log")
            try:
                if os.path.exists(portproton_log_path):
                    os.remove(portproton_log_path)
                    logger.debug(
                        "Deleted existing PortProton.log at %s",
                        portproton_log_path
                    )
            except OSError as e:
                logger.debug(
                    "Could not delete PortProton.log at %s: %s",
                    portproton_log_path, e
                )

        env_vars = os.environ.copy()
        env_vars["PW_LOG"] = "1"

        cmd = start_command + [exe_path]

        try:
            self.process = subprocess.Popen(
                cmd,
                env=env_vars,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )

            self.output_thread = threading.Thread(
                target=self._read_output, daemon=True
            )
            self.output_thread.start()

            self.is_running = True
            logger.info("Started debug session for %s", exe_path)
            return True
        except Exception as e:
            logger.error("Failed to start debug session: %s", e)
            return False

    def _start_native(self, uri: str) -> bool:
        from portprotonqt.native_games import get_native_launch

        try:
            command, directory = get_native_launch(uri.removeprefix("native://"))
            self.native_output = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            self.process = subprocess.Popen(
                command, cwd=directory, stdout=self.native_output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        except Exception as error:
            logger.error("Failed to start native debug session: %s", error)
            if self.native_output is not None:
                self.native_output.close()
                self.native_output = None
            return False
        self.exe_path = uri.removeprefix("native://")
        self.start_command = command
        self.native_directory = directory
        self.is_running = True
        return True

    def _save_native_log(self) -> str | None:
        output = self.native_output
        if output is None:
            return None
        destination = Path(self.native_directory or str(Path.home())) / "PortProtonQt.log"
        try:
            output.seek(0)
            with destination.open("w", encoding="utf-8") as log:
                log.write(generate_system_info("native://" + str(self.exe_path), self.start_command))
                log.write(f"\nCommand: {self.start_command!r}\nWorking directory: {self.native_directory}\n\n")
                shutil.copyfileobj(output, log)
            return str(destination)
        except OSError as error:
            logger.error("Failed to save native debug log: %s", error)
            return None
        finally:
            output.close()
            self.native_output = None
            self.native_directory = None

    def _read_output(self):
        """Read output from subprocess in a separate thread."""
        if self.process and self.process.stdout:
            try:
                for line in iter(self.process.stdout.readline, ''):
                    if self._stop_event.is_set():
                        break
                    self.output_queue.put(line)
            except Exception as e:
                logger.debug("Error reading output: %s", e)

    def stop(self) -> str | None:
        """Stop the game and save its diagnostic log."""
        if self.native_output is None:
            self._capture_env_vars()
        self._stop_event.set()

        if self.is_running and self.process:
            try:
                os.killpg(self.process.pid if self.native_output is not None else os.getpgid(self.process.pid), signal.SIGTERM)

                try:
                    time.sleep(0.1)

                    if self.process.poll() is None:
                        os.killpg(self.process.pid if self.native_output is not None else os.getpgid(self.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except Exception as e:
                logger.debug("Error terminating process: %s", e)

        try:
            while True:
                line = self.output_queue.get_nowait()
                self.wine_output.append(line)
        except queue.Empty:
            pass

        log_file = self._save_native_log() if self.native_output is not None else self._save_log()

        if self.process and self.process.stdout:
            try:
                self.process.stdout.close()
            except (AttributeError, OSError):
                pass
        self.process = None
        self.is_running = False

        return log_file

    def check_running(self) -> bool:
        """Check if process is still running."""
        if self.process is None:
            self.is_running = False
            return False

        poll = self.process.poll()
        if poll is not None:
            self.is_running = False
            return False

        if self.native_output is None:
            self._capture_env_vars()
        return True

    def _capture_env_vars(self) -> None:
        """Keep runtime variables before PortProton removes var.log."""
        env_vars = get_portproton_runtime_env()
        if env_vars.get("PW_USE_RUNTIME") is not None:
            self.runtime_env = env_vars
        elif self.runtime_env is None and env_vars:
            self.runtime_env = env_vars

    def _save_log(self) -> str | None:
        """Save complete debug log to file."""
        portproton_path = get_portproton_location()
        if not portproton_path:
            return None

        runtime_env = self.runtime_env
        if runtime_env is None:
            runtime_env = get_portproton_runtime_env()

        system_info = generate_system_info(
            self.exe_path,
            self.start_command,
            runtime_env
        )

        lines = [system_info]

        portproton_log_content = ""

        if portproton_path:
            portproton_log_path = os.path.join(portproton_path, "PortProton.log")

            if os.path.exists(portproton_log_path):
                try:
                    with open(
                        portproton_log_path,
                        encoding="utf-8",
                        errors="ignore"
                    ) as f:
                        portproton_log_content = f.read()
                except OSError as e:
                    logger.debug(
                        "Could not read PortProton log file %s: %s",
                        portproton_log_path, e
                    )

        if portproton_log_content.strip():
            lines.append(portproton_log_content)

        log_content = "\n".join(lines)

        log_content = process_portproton_log(log_content)

        if self.exe_path and os.path.exists(self.exe_path):
            game_dir = os.path.dirname(self.exe_path)
            log_file = os.path.join(game_dir, "PortProtonQt.log")
        else:
            log_file = os.path.join(portproton_path, "PortProtonQt.log")

        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(log_content)
            logger.info("Debug log saved to %s", log_file)
            return log_file
        except OSError as e:
            logger.error("Failed to save debug log: %s", e)
            return None

    def cleanup_on_exit(self):
        """Clean up resources and save log when application exits."""
        if self.is_running:
            logger.info("Cleaning up debug log manager on application exit...")
            self.stop()
