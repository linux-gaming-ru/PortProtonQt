#!/usr/bin/env python3
import argparse
import codecs
import fcntl
import os
import pty
import re
import shlex
import struct
import sys
import termios
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QMimeData, QSocketNotifier, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPalette,
    QResizeEvent,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QPlainTextEdit

from portprotonqt.logger import get_logger
from portprotonqt.theme_manager import ThemeManager

logger = get_logger(__name__)
APPLICATION_ID = "ru.linux_gaming.PortProtonQt"

CONF_NAME = "PortProtonQt Terminal"
CONF_FALLBACK_SHELL = "/bin/bash"
CONF_DEF_SIZE = (800, 260)
CONF_FALLBACK_FONT_EXTRA = 6
CONF_SCROLLBACK_LINES = 2000
CONF_RENDER_INTERVAL_MS = 16

XDG_DATA_HOME = os.getenv(
    "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
)

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEME_DIRS = [
    os.path.join(XDG_DATA_HOME, "PortProtonQt", "terminal_schemes"),
    os.path.join(PACKAGE_DIR, "terminal_schemes"),
]


@dataclass
class TerminalScheme:
    """Terminal color/font scheme loaded from Kitty-style .conf files."""

    color_b: str = "#000000"
    color_f: str = "#ffffff"
    color_selection_f: str = ""
    color_selection_b: str = ""
    color_cursor: str = ""
    cursor_shape: str = "beam"
    enable_audio_bell: bool = False
    background_opacity: float = 1.0
    background_image: str = "none"
    background_image_layout: str = "tiled"
    background_tint: float = 0.0
    dim_opacity: float = 0.4
    font_size_b: str = "14px"
    font_family_b: str = ""
    terminal_ansi_colors: list[str] = field(
        default_factory=lambda: [""] * 256
    )

CMD_CONTROL_RE = re.compile(
    r"(?:"
    r"\x1b\][^\a]*(?:\a|\x1b\\)"  # OSC, for example window title
    r"|\x1b\[[0-?]*[ -/]*[@-~]"       # CSI, for example colors/cursor show-hide
    r"|\x1b[()#%*+\-./ ][\x20-\x7e]" # charset and similar short controls
    r"|\x1b."                            # any other two-byte ESC control
    r")"
)


def _parse_bool(value: str, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


def _parse_cursor_shape(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in ("block", "beam", "underline"):
        return normalized
    return "beam"


def load_terminal_scheme(scheme_name: str) -> TerminalScheme | None:
    """Load terminal scheme from a Kitty-style .conf file."""
    for scheme_dir in SCHEME_DIRS:
        scheme_path = os.path.join(scheme_dir, f"{scheme_name}.conf")
        if not os.path.exists(scheme_path):
            continue

        try:
            with open(scheme_path, encoding="utf-8") as file:
                lines = file.readlines()

            data: dict[str, str] = {}
            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(maxsplit=1) if " " in line else line.split("=", 1)
                if len(parts) == 2:
                    data[parts[0].strip()] = parts[1].strip()

            raw_font_size = data.get("font_size", "14")
            try:
                font_size = float(raw_font_size.replace("px", "").replace("pt", ""))
            except ValueError:
                font_size = 14

            return TerminalScheme(
                color_b=data.get("background", "#000000"),
                color_f=data.get("foreground", "#ffffff"),
                color_selection_f=data.get("selection_foreground", ""),
                color_selection_b=data.get("selection_background", ""),
                color_cursor=data.get("cursor", data.get("cursor_color", "")),
                cursor_shape=_parse_cursor_shape(data.get("cursor_shape", "beam")),
                enable_audio_bell=_parse_bool(
                    data.get("enable_audio_bell", "no")
                ),
                background_opacity=float(data.get("background_opacity", "1.0")),
                background_image=data.get("background_image", "none"),
                background_image_layout=data.get(
                    "background_image_layout", "tiled"
                ),
                background_tint=float(data.get("background_tint", "0.0")),
                dim_opacity=float(data.get("dim_opacity", "0.4")),
                font_size_b=f"{int(font_size)}px",
                font_family_b=data.get("font_family", ""),
                terminal_ansi_colors=[
                    data.get(f"color{index}", "") for index in range(256)
                ],
            )
        except (OSError, ValueError) as e:
            logger.warning("Failed to load terminal scheme %s: %s", scheme_name, e)
    return None

def load_current_terminal_scheme() -> TerminalScheme | None:
    """Load the selected terminal scheme."""
    try:
        from portprotonqt.config import ui_config

        scheme_name = ui_config.get_terminal_scheme()
        return load_terminal_scheme(scheme_name)
    except ImportError:
        return None


def list_terminal_schemes() -> list[str]:
    """Return a list of available terminal schemes."""
    schemes = set()
    for scheme_dir in SCHEME_DIRS:
        if not os.path.exists(scheme_dir):
            continue
        try:
            for entry in os.listdir(scheme_dir):
                if entry.endswith(".conf"):
                    schemes.add(entry[:-5])
        except OSError:
            continue
    return sorted(schemes)


def _theme_font_size(theme: object | None) -> int:
    value = getattr(theme, "font_size_b", "")
    match = re.match(r"(\d+)px", str(value))
    if match:
        return int(match.group(1))
    return QApplication.font().pointSize() + CONF_FALLBACK_FONT_EXTRA


def _theme_color(theme: object | None, name: str) -> QColor:
    value = getattr(theme, name, "")
    color = QColor(value)
    return color if color.isValid() else QColor()


def _theme_ansi_colors(theme: object | None) -> list[QColor]:
    values = getattr(theme, "terminal_ansi_colors", [])
    base_colors = [QColor(v) if v else QColor() for v in values]

    colors = [QColor() for _ in range(256)]
    for i in range(min(len(base_colors), 256)):
        colors[i] = base_colors[i]

    # Standard 16 colors fallbacks
    default_16 = [
        "#000000", "#cd3131", "#0dbc79", "#e5e510",
        "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
        "#666666", "#f14c4c", "#23d18b", "#f5f543",
        "#3b8eea", "#d670d6", "#29b8db", "#e5e5e5"
    ]
    for i in range(16):
        if not colors[i].isValid():
            colors[i] = QColor(default_16[i])

    # Color cube 16-231
    levels = [0, 95, 135, 175, 215, 255]
    for r in range(6):
        for g in range(6):
            for b in range(6):
                idx = 16 + r * 36 + g * 6 + b
                if idx < 256 and not colors[idx].isValid():
                    colors[idx] = QColor(levels[r], levels[g], levels[b])

    # Grayscale 232-255
    for i in range(24):
        idx = 232 + i
        if idx < 256 and not colors[idx].isValid():
            v = 8 + i * 10
            colors[idx] = QColor(v, v, v)

    return colors


def load_current_theme() -> Any | None:
    """Load the selected PortProtonQt theme."""
    try:
        from portprotonqt.config import ui_config
        from portprotonqt.theme_manager import ThemeManager
    except ImportError as e:
        logger.warning("Cannot load PortProtonQt theme: %s", e)
        return None
    return ThemeManager().apply_theme(ui_config.get_theme())


def default_shell() -> str:
    """Return the user's shell, falling back to bash."""
    shell = os.environ.get("SHELL", "")
    if shell and os.path.isabs(shell) and os.access(shell, os.X_OK):
        return shell
    return CONF_FALLBACK_SHELL


def _command_entrypoint(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return ""
    return parts[0] if parts else ""


def _uses_exported_bash_function(command: str) -> bool:
    entrypoint = _command_entrypoint(command)
    return bool(entrypoint and f"BASH_FUNC_{entrypoint}%%" in os.environ)


def _needs_portproton_functions(command: str) -> bool:
    entrypoint = _command_entrypoint(command)
    return entrypoint.startswith("pw_") or _uses_exported_bash_function(command)


def _portproton_functions_helper_path() -> str:
    helper = os.path.join(
        os.environ.get("PORT_SCRIPTS_PATH", ""), "functions_helper"
    )
    if os.path.isfile(helper):
        return helper

    try:
        from portprotonqt.config import get_portproton_scripts_path
    except ImportError:
        return ""

    scripts_path = get_portproton_scripts_path()
    if not scripts_path:
        return ""

    helper = os.path.join(scripts_path, "functions_helper")
    return helper if os.path.isfile(helper) else ""


def _with_portproton_functions(command: str) -> str:
    helper = _portproton_functions_helper_path()
    if _needs_portproton_functions(command) and helper:
        return f"source {shlex.quote(helper)}; {command}"
    return command


def _is_cmd_mode(args: argparse.Namespace) -> bool:
    candidates = [str(item) for item in getattr(args, "e", []) or []]
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if "pw_run cmd" in normalized:
            return True
        if normalized.endswith("cmd.exe"):
            return True
        if normalized == "cmd":
            return True
    return False


class TerminalCell:
    """A character and its text attributes in the terminal buffer."""

    def __init__(
        self, char: str = " ", text_format: QTextCharFormat | None = None
    ) -> None:
        self.char = char
        if text_format is None:
            text_format = QTextCharFormat()
        self.text_format = QTextCharFormat(text_format)


class TerminalScreen:
    """Small VT-style screen buffer for ANSI terminal output."""

    def __init__(self, rows: int, columns: int, colors: list[QColor]) -> None:
        self.rows = rows
        self.columns = columns
        self.colors = colors
        self.cursor_row = 0
        self.cursor_column = 0
        self.pending_wrap = False
        self.wrap_enabled = True
        self.application_cursor = False
        self.saved_cursor = (0, 0)
        self.bell_count = 0
        self.current_format = QTextCharFormat()
        self.buffer = self._blank_buffer()
        self.history: list[list[TerminalCell]] = []
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.responses: list[str] = []
        self.pending_input = ""
        self.main_state: tuple[
            Any, int, int, tuple[int, int], QTextCharFormat
        ] | None = None

    def resize(self, rows: int, columns: int) -> None:
        if rows == self.rows and columns == self.columns:
            return
        old_buffer = self.buffer
        self.history = [self._fit_row(row, columns) for row in self.history]
        self.rows = rows
        self.columns = columns
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.buffer = self._blank_buffer()
        for row in range(min(rows, len(old_buffer))):
            limit = min(columns, len(old_buffer[row]))
            self.buffer[row][:limit] = old_buffer[row][:limit]
        self._clamp_cursor()

    def feed(self, text: str) -> None:
        if self.pending_input:
            text = self.pending_input + text
            self.pending_input = ""
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\x1b":
                next_index = self._read_escape(text, index + 1)
                if next_index is None:
                    self.pending_input = text[index:]
                    break
                index = next_index
            else:
                self._put_char(char)
                index += 1

    def pop_responses(self) -> list[str]:
        responses = self.responses
        self.responses = []
        return responses

    def pop_bell_count(self) -> int:
        bell_count = self.bell_count
        self.bell_count = 0
        return bell_count

    def line_cells(self, row: int) -> list[TerminalCell]:
        return self.buffer[row]

    def display_lines(self) -> list[list[TerminalCell]]:
        if self.main_state is not None:
            return self.buffer
        return self.history + self.buffer

    def display_cursor_row(self) -> int:
        if self.main_state is not None:
            return self.cursor_row
        return len(self.history) + self.cursor_row

    def last_column(self, row: int) -> int:
        cells = self.buffer[row]
        last = self.cursor_column if row == self.cursor_row else -1
        for column, cell in enumerate(cells):
            if cell.char != " " or cell.text_format.background().style():
                last = column
        return last

    def _blank_buffer(self) -> list[list[TerminalCell]]:
        return [
            [TerminalCell() for _column in range(self.columns)]
            for _row in range(self.rows)
        ]

    def _read_escape(self, text: str, index: int) -> int | None:
        if index >= len(text):
            return None
        if text[index] == "[":
            return self._read_csi(text, index + 1)
        if text[index] == "]":
            return self._read_osc(text, index + 1)
        if text[index] in ("(", ")", "*", "+"):
            if index + 1 >= len(text):
                return None
            return index + 2
        if text[index] in ("=", ">"):
            return min(index + 1, len(text))
        if text[index] == "7":
            self.saved_cursor = (self.cursor_row, self.cursor_column)
        elif text[index] == "8":
            self.cursor_row, self.cursor_column = self.saved_cursor
            self._clamp_cursor()
        elif text[index] == "c":
            self._reset()
        return min(index + 1, len(text))

    def _read_csi(self, text: str, index: int) -> int | None:
        start = index
        while index < len(text):
            if "@" <= text[index] <= "~":
                self._apply_csi(text[start:index], text[index])
                return index + 1
            index += 1
        return None

    def _read_osc(self, text: str, index: int) -> int | None:
        start = index
        while index < len(text):
            if text[index] == "\a":
                self._apply_osc(text[start:index])
                return index + 1
            if text.startswith("\x1b\\", index):
                self._apply_osc(text[start:index])
                return index + 2
            index += 1
        return None

    def _apply_osc(self, text: str) -> None:
        if text == "11;?":
            self.responses.append(f"\x1b]11;{self._background_response()}\x1b\\")

    def _background_response(self) -> str:
        color = self.colors[0] if self.colors else QColor("#000000")
        red = color.red() * 257
        green = color.green() * 257
        blue = color.blue() * 257
        return f"rgb:{red:04x}/{green:04x}/{blue:04x}"

    def _put_char(self, char: str) -> None:
        if char == "\n":
            self.pending_wrap = False
            self._linefeed()
            self.cursor_column = 0
        elif char == "\r":
            self.pending_wrap = False
            self.cursor_column = 0
        elif char in ("\b", "\x7f"):
            self.pending_wrap = False
            self.cursor_column = max(0, self.cursor_column - 1)
        elif char == "\a":
            self.bell_count += 1
        elif char == "\t":
            self.pending_wrap = False
            self.cursor_column = min(self.columns - 1, self.cursor_column + 8)
        elif ord(char) >= 32:
            self._draw_char(char)

    def _draw_char(self, char: str) -> None:
        if self.pending_wrap:
            self.cursor_column = 0
            self._linefeed()
            self.pending_wrap = False
        self.buffer[self.cursor_row][self.cursor_column] = TerminalCell(
            char, self.current_format
        )
        if self.cursor_column >= self.columns - 1:
            if self.wrap_enabled:
                self.pending_wrap = True
            return
        self.cursor_column += 1

    def _linefeed(self) -> None:
        if self.cursor_row >= self.scroll_bottom:
            self._scroll_up(1)
            return
        self.cursor_row += 1

    def _append_history(self, line: list[TerminalCell]) -> None:
        self.history.append(
            [TerminalCell(cell.char, cell.text_format) for cell in line]
        )
        if len(self.history) > CONF_SCROLLBACK_LINES:
            del self.history[: len(self.history) - CONF_SCROLLBACK_LINES]

    def _apply_csi(self, params: str, command: str) -> None:
        values = self._parse_params(params)
        if command == "m":
            self._apply_sgr(values)
        elif command in ("H", "f"):
            self._set_cursor(values)
        elif command in ("A", "B", "C", "D", "E", "F", "G"):
            self._move_cursor(values, command)
        elif command == "d":
            self._set_cursor([values[0] if values else 1, self.cursor_column + 1])
        elif command == "@":
            self._insert_blanks(self._count(values))
        elif command == "P":
            self._delete_chars(self._count(values))
        elif command == "X":
            self._erase_chars(self._count(values))
        elif command == "L":
            self._insert_lines(self._count(values))
        elif command == "M":
            self._delete_lines(self._count(values))
        elif command == "J":
            self._erase_display(values[0] if values else 0)
        elif command == "K":
            self._erase_line(values[0] if values else 0)
        elif command == "n":
            self._report_status(values[0] if values else 0)
        elif command == "c":
            self.responses.append("\x1b[?6c")
        elif command == "r":
            self._set_scroll_region(values)
        elif command == "h" and params.startswith("?"):
            self._set_private_mode(values, True)
        elif command == "l" and params.startswith("?"):
            self._set_private_mode(values, False)
        elif command == "s":
            self.saved_cursor = (self.cursor_row, self.cursor_column)
        elif command == "u":
            self.cursor_row, self.cursor_column = self.saved_cursor
            self._clamp_cursor()

    def _parse_params(self, params: str) -> list[int]:
        cleaned = params.lstrip("?").replace(":", ";")
        values: list[int] = []
        for item in cleaned.split(";"):
            if not item:
                values.append(0)
            elif item.isdigit():
                values.append(int(item))
        return values

    def _uses_alternate_screen(self, values: list[int]) -> bool:
        return any(value in (47, 1047, 1049) for value in values)

    def _set_private_mode(self, values: list[int], enabled: bool) -> None:
        if 1 in values:
            self.application_cursor = enabled
        if 7 in values:
            self.wrap_enabled = enabled
        if not self._uses_alternate_screen(values):
            return
        if enabled:
            self._enter_alternate_screen()
        else:
            self._leave_alternate_screen()

    def _count(self, values: list[int]) -> int:
        return values[0] if values and values[0] else 1

    def _report_status(self, mode: int) -> None:
        if mode == 5:
            self.responses.append("\x1b[0n")
        elif mode == 6:
            row = self.cursor_row + 1
            column = self.cursor_column + 1
            self.responses.append(f"\x1b[{row};{column}R")

    def _reset(self, clear_history: bool = True) -> None:
        self.cursor_row = 0
        self.cursor_column = 0
        self.pending_wrap = False
        self.wrap_enabled = True
        self.application_cursor = False
        self.saved_cursor = (0, 0)
        self.bell_count = 0
        self.current_format = QTextCharFormat()
        self.buffer = self._blank_buffer()
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        if clear_history:
            self.history = []

    def _enter_alternate_screen(self) -> None:
        if self.main_state is None:
            self.main_state = (
                self._copy_buffer(self.buffer),
                self.cursor_row,
                self.cursor_column,
                self.saved_cursor,
                QTextCharFormat(self.current_format),
            )
        self._reset(False)

    def _leave_alternate_screen(self) -> None:
        if self.main_state is None:
            self._reset()
            return
        buffer, row, column, saved_cursor, text_format = self.main_state
        self.buffer = self._fit_buffer(buffer)
        self.cursor_row = row
        self.cursor_column = column
        self.pending_wrap = False
        self.saved_cursor = saved_cursor
        self.current_format = QTextCharFormat(text_format)
        self.main_state = None
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self.application_cursor = False
        self.wrap_enabled = True
        self._clamp_cursor()

    def _copy_buffer(
        self, buffer: list[list[TerminalCell]]
    ) -> list[list[TerminalCell]]:
        return [
            [TerminalCell(cell.char, cell.text_format) for cell in row]
            for row in buffer
        ]

    def _fit_buffer(self, buffer: list[list[TerminalCell]]) -> list[list[TerminalCell]]:
        fitted = self._blank_buffer()
        for row in range(min(self.rows, len(buffer))):
            fitted[row] = self._fit_row(buffer[row], self.columns)
        return fitted

    def _fit_row(self, row: list[TerminalCell], columns: int) -> list[TerminalCell]:
        fitted = [TerminalCell() for _column in range(columns)]
        limit = min(columns, len(row))
        fitted[:limit] = row[:limit]
        return fitted

    def _set_cursor(self, values: list[int]) -> None:
        row = values[0] if values else 1
        column = values[1] if len(values) > 1 else 1
        self.cursor_row = max(0, min(self.rows - 1, row - 1))
        self.cursor_column = max(0, min(self.columns - 1, column - 1))
        self.pending_wrap = False

    def _move_cursor(self, values: list[int], command: str) -> None:
        self.pending_wrap = False
        count = values[0] if values and values[0] else 1
        if command == "A":
            self.cursor_row -= count
        elif command == "B":
            self.cursor_row += count
        elif command == "C":
            self.cursor_column += count
        elif command == "D":
            self.cursor_column -= count
        elif command == "E":
            self.cursor_row += count
            self.cursor_column = 0
        elif command == "F":
            self.cursor_row -= count
            self.cursor_column = 0
        elif command == "G":
            self.cursor_column = count - 1
        self._clamp_cursor()

    def _insert_blanks(self, count: int) -> None:
        row = self.buffer[self.cursor_row]
        count = min(count, self.columns - self.cursor_column)
        blanks = [TerminalCell() for _index in range(count)]
        start = self.cursor_column
        self.buffer[self.cursor_row] = (row[:start] + blanks + row[start:])[
            : self.columns
        ]

    def _delete_chars(self, count: int) -> None:
        row = self.buffer[self.cursor_row]
        count = min(count, self.columns - self.cursor_column)
        start = self.cursor_column
        blanks = [TerminalCell() for _index in range(count)]
        self.buffer[self.cursor_row] = (
            row[:start] + row[start + count :] + blanks
        )[: self.columns]

    def _erase_chars(self, count: int) -> None:
        end = min(self.columns, self.cursor_column + count)
        self._erase_row(self.cursor_row, self.cursor_column, end)

    def _insert_lines(self, count: int) -> None:
        top, bottom = self._line_region()
        count = min(count, bottom - self.cursor_row + 1)
        for _index in range(count):
            self.buffer.insert(self.cursor_row, self._blank_line())
            del self.buffer[bottom + 1]

    def _delete_lines(self, count: int) -> None:
        top, bottom = self._line_region()
        count = min(count, bottom - self.cursor_row + 1)
        for _index in range(count):
            del self.buffer[self.cursor_row]
            self.buffer.insert(bottom, self._blank_line())

    def _set_scroll_region(self, values: list[int]) -> None:
        top = (values[0] if values else 1) - 1
        bottom = (values[1] if len(values) > 1 and values[1] else self.rows) - 1
        if top < 0 or bottom <= top or bottom >= self.rows:
            self.scroll_top = 0
            self.scroll_bottom = self.rows - 1
        else:
            self.scroll_top = top
            self.scroll_bottom = bottom
        self.cursor_row = self.scroll_top
        self.cursor_column = 0

    def _line_region(self) -> tuple[int, int]:
        if self.scroll_top <= self.cursor_row <= self.scroll_bottom:
            return self.scroll_top, self.scroll_bottom
        return self.cursor_row, self.rows - 1

    def _scroll_up(self, count: int) -> None:
        for _index in range(count):
            line = self.buffer.pop(self.scroll_top)
            if self.scroll_top == 0 and self.main_state is None:
                self._append_history(line)
            self.buffer.insert(self.scroll_bottom, self._blank_line())

    def _blank_line(self) -> list[TerminalCell]:
        return [TerminalCell() for _column in range(self.columns)]

    def _erase_display(self, mode: int) -> None:
        if mode in (2, 3):
            self.buffer = self._blank_buffer()
            if mode == 3:
                self.history = []
            self.cursor_row = 0
            self.cursor_column = 0
            self.pending_wrap = False
        elif mode == 1:
            for row in range(self.cursor_row + 1):
                self._erase_row(row, 0, self.columns)
        else:
            self._erase_line(0)
            for row in range(self.cursor_row + 1, self.rows):
                self._erase_row(row, 0, self.columns)

    def _erase_line(self, mode: int) -> None:
        if mode == 2:
            self._erase_row(self.cursor_row, 0, self.columns)
        elif mode == 1:
            self._erase_row(self.cursor_row, 0, self.cursor_column + 1)
        else:
            self._erase_row(self.cursor_row, self.cursor_column, self.columns)

    def _erase_row(self, row: int, start: int, end: int) -> None:
        for column in range(start, min(end, self.columns)):
            self.buffer[row][column] = TerminalCell()

    def _apply_sgr(self, values: list[int]) -> None:
        values = values or [0]
        index = 0
        while index < len(values):
            index = self._apply_sgr_code(values, index)

    def _apply_sgr_code(self, values: list[int], index: int) -> int:
        code = values[index]
        if code == 0:
            self.current_format = QTextCharFormat()
        elif code == 1:
            self.current_format.setFontWeight(QFont.Weight.Bold)
        elif code == 2:
            # DIM
            color = self.current_format.foreground().color()
            if color.isValid():
                color.setAlphaF(0.6)
                self.current_format.setForeground(color)
        elif code == 22:
            self.current_format.setFontWeight(QFont.Weight.Normal)
            color = self.current_format.foreground().color()
            if color.isValid():
                color.setAlphaF(1.0)
                self.current_format.setForeground(color)
        elif code in (3, 23, 4, 24, 9, 29):
            self._apply_text_style(code)
        elif code in (38, 48):
            return self._apply_extended_color(values, index)
        elif code == 39:
            self.current_format.clearForeground()
        elif code == 49:
            self.current_format.clearBackground()
        elif 30 <= code <= 37 or 90 <= code <= 97:
            self._set_color(code, False)
        elif 40 <= code <= 47 or 100 <= code <= 107:
            self._set_color(code, True)
        return index + 1

    def _apply_text_style(self, code: int) -> None:
        if code in (3, 23):
            self.current_format.setFontItalic(code == 3)
        elif code in (4, 24):
            self.current_format.setFontUnderline(code == 4)
        elif code in (9, 29):
            self.current_format.setFontStrikeOut(code == 9)

    def _apply_extended_color(self, values: list[int], index: int) -> int:
        if index + 2 >= len(values):
            return index + 1
        background = values[index] == 48
        color = QColor()
        if values[index + 1] == 5:
            color = self._ansi_color(values[index + 2])
            index += 3
        elif values[index + 1] == 2 and index + 4 < len(values):
            color = QColor(values[index + 2], values[index + 3], values[index + 4])
            index += 5
        else:
            return index + 1
        self._apply_qcolor(color, background)
        return index

    def _set_color(self, code: int, background: bool) -> None:
        offset = 40 if background else 30
        if code >= 100:
            offset = 100
        elif code >= 90:
            offset = 90
        self._apply_qcolor(self._ansi_color(code - offset), background)

    def _ansi_color(self, index: int) -> QColor:
        if index < 256:
            return self.colors[index]
        return QColor()

    def _apply_qcolor(self, color: QColor, background: bool) -> None:
        if not color.isValid():
            return
        if background:
            self.current_format.setBackground(color)
        else:
            self.current_format.setForeground(color)

    def _clamp_cursor(self) -> None:
        self.cursor_row = max(0, min(self.rows - 1, self.cursor_row))
        self.cursor_column = max(0, min(self.columns - 1, self.cursor_column))


class TerminalWidget(QPlainTextEdit):
    """Small PTY-backed terminal widget for PortProton shell commands."""

    def __init__(
        self,
        command: list[str],
        cwd: str,
        theme: object | None,
        cmd_mode: bool,
        app_theme: object | None = None,
    ) -> None:
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.theme = theme
        self.app_theme = app_theme or load_current_theme()
        self.cmd_mode = cmd_mode
        self.child_pid: int | None = None
        self.pty_fd: int | None = None
        self.notifier: QSocketNotifier | None = None
        self.ansi_colors = _theme_ansi_colors(theme)
        self.current_format = QTextCharFormat()
        self.cursor_color = _theme_color(theme, "color_cursor")
        self.cursor_shape = _parse_cursor_shape(
            getattr(theme, "cursor_shape", "beam")
        )
        self.enable_audio_bell = bool(
            getattr(theme, "enable_audio_bell", False)
        )

        if theme and getattr(theme, "background_opacity", 1.0) < 1.0:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.terminal_screen: TerminalScreen | None = None
        self.cmd_input_start: int | None = None
        self.cmd_echo_pending = ""
        self.cmd_echo_buffer = ""
        self.cmd_escape_pending = ""
        self.cmd_history: list[str] = []
        self.cmd_history_index: int | None = None
        self.cmd_history_draft = ""
        self.output_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.theme_manager = ThemeManager()
        self.child_timer = QTimer(self)
        self.child_timer.timeout.connect(self._check_child)
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self._render_screen)

        # Keep the caret visible and route all input to the PTY.
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.setFont(self._build_font(theme))
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self._apply_cursor_settings(theme)
        if not self.cmd_mode:
            self._init_screen()
        self._start_child()

    def apply_theme(self, theme: object | None) -> None:
        """Apply a new theme/scheme to the terminal widget."""
        self.theme = theme
        self.ansi_colors = _theme_ansi_colors(theme)
        self.setFont(self._build_font(theme))
        if self.terminal_screen:
            self.terminal_screen.colors = self.ansi_colors
        apply_palette(self, theme)
        self._apply_cursor_settings(theme)
        self._schedule_screen_render()

    def _apply_cursor_settings(self, theme: object | None) -> None:
        """Apply terminal cursor and bell settings from scheme."""
        self.cursor_color = _theme_color(theme, "color_cursor")
        self.cursor_shape = _parse_cursor_shape(
            getattr(theme, "cursor_shape", "beam")
        )
        self.enable_audio_bell = bool(
            getattr(theme, "enable_audio_bell", False)
        )
        if self.cmd_mode:
            self.setCursorWidth(2)
            self.viewport().update()
            return
        custom_cursor = self.cursor_color.isValid() or self.cursor_shape != "beam"
        self.setCursorWidth(0 if custom_cursor else 2)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.cmd_mode:
            return
        if not self.hasFocus():
            return
        if not self.cursor_color.isValid() and self.cursor_shape == "beam":
            return
        rect = self.cursorRect()
        if self.cursor_shape == "underline":
            rect.setWidth(self.fontMetrics().horizontalAdvance("M"))
            rect.setTop(rect.bottom() - 2)
        elif self.cursor_shape == "beam":
            rect.setWidth(2)
        else:
            rect.setWidth(self.fontMetrics().horizontalAdvance("M"))
        painter = QPainter(self.viewport())
        painter.fillRect(rect, self._cursor_fill_color())

    def _cursor_fill_color(self) -> QColor:
        if self.cursor_color.isValid():
            return self.cursor_color
        return self.palette().color(QPalette.ColorRole.Text)

    def _build_font(self, theme: object | None) -> QFont:
        family = getattr(theme, "font_family_b", "")
        if family:
            font = QFont(family)
        else:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPixelSize(_theme_font_size(theme))
        return font

    def _terminal_size(self) -> tuple[int, int]:
        columns = max(
            1,
            self.viewport().width()
            // self.fontMetrics().horizontalAdvance("M"),
        )
        rows = max(1, self.viewport().height() // self.fontMetrics().height())
        return rows, columns

    def _init_screen(self) -> None:
        rows, columns = self._terminal_size()
        self.terminal_screen = TerminalScreen(rows, columns, self.ansi_colors)

    def _start_child(self) -> None:
        pid, fd = pty.fork()
        if pid == 0:
            self._exec_child()
        self.child_pid = pid
        self.pty_fd = fd
        fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)
        self.notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._read_pty)
        self.child_timer.start(250)
        self._sync_pty_size()

    def _exec_child(self) -> None:
        """Run the requested command in the child side of the PTY."""
        try:
            try:
                max_fd = os.sysconf("SC_OPEN_MAX")
            except ValueError:
                max_fd = 256
            for fd in range(3, max_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass

            if self.cwd:
                os.chdir(self.cwd)

            env = os.environ.copy()
            env.pop("TERMIOS", None)
            env["TERM"] = "xterm-256color"

            os.execvpe(self.command[0], self.command, env)
        except OSError as e:
            os.write(
                2, f"portprotonqt-terminal: failed to start {self.command[0]}: {e}\n".encode()
            )
            os._exit(127)

    def _read_pty(self) -> None:
        if self.pty_fd is None:
            return
        try:
            data = os.read(self.pty_fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:
            logger.warning("Terminal read failed: %s", e)
            QApplication.quit()
            return
        if not data:
            QApplication.quit()
            return
        text = self.output_decoder.decode(data)
        if self.cmd_mode:
            text = self._strip_cmd_controls(text)
            text = self._filter_cmd_output(text)
            text = self._normalize_cmd_newlines(text)
        if text:
            self._append_output(text)

    def _check_child(self) -> None:
        if self.child_pid is None:
            return
        try:
            pid, _status = os.waitpid(self.child_pid, os.WNOHANG)
        except ChildProcessError:
            pid = self.child_pid
        if pid == 0:
            return
        self.child_pid = None
        self.child_timer.stop()
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        QApplication.quit()

    def _append_output(self, text: str) -> None:
        if self.terminal_screen is not None:
            self.terminal_screen.feed(text)
            if self.terminal_screen.pop_bell_count():
                self._handle_bell()
            for response in self.terminal_screen.pop_responses():
                self._write_pty(response)
            self._schedule_screen_render()
            return

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, self.current_format)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        if self.cmd_mode:
            self._cmd_set_input_start()

    def _handle_bell(self) -> None:
        if self.enable_audio_bell:
            QApplication.beep()

    def _cursor_key_sequence(self, key: Qt.Key) -> str:
        normal = {
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
        }
        application = {
            Qt.Key.Key_Left: "\x1bOD",
            Qt.Key.Key_Right: "\x1bOC",
            Qt.Key.Key_Up: "\x1bOA",
            Qt.Key.Key_Down: "\x1bOB",
        }
        if self.terminal_screen is not None and self.terminal_screen.application_cursor:
            return application.get(key, "")
        return normal.get(key, "")

    def _function_key_sequence(self, key: Qt.Key) -> str:
        return {
            Qt.Key.Key_F1: "\x1bOP",
            Qt.Key.Key_F2: "\x1bOQ",
            Qt.Key.Key_F3: "\x1bOR",
            Qt.Key.Key_F4: "\x1bOS",
            Qt.Key.Key_F5: "\x1b[15~",
            Qt.Key.Key_F6: "\x1b[17~",
            Qt.Key.Key_F7: "\x1b[18~",
            Qt.Key.Key_F8: "\x1b[19~",
            Qt.Key.Key_F9: "\x1b[20~",
            Qt.Key.Key_F10: "\x1b[21~",
            Qt.Key.Key_F11: "\x1b[23~",
            Qt.Key.Key_F12: "\x1b[24~",
        }.get(key, "")

    def _schedule_screen_render(self) -> None:
        if self.render_timer.isActive():
            return
        self.render_timer.start(CONF_RENDER_INTERVAL_MS)

    def _render_screen(self) -> None:
        terminal_screen = self.terminal_screen
        if terminal_screen is None:
            return
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        lines = terminal_screen.display_lines()
        for y, line in enumerate(lines):
            if y:
                cursor.insertBlock()
            self._render_screen_line(cursor, line)
        cursor.endEditBlock()
        self._move_to_screen_cursor(cursor)
        self.ensureCursorVisible()

    def _render_screen_line(
        self, cursor: QTextCursor, line: list[TerminalCell]
    ) -> None:
        terminal_screen = self.terminal_screen
        if terminal_screen is None:
            return
        start = 0
        while start < terminal_screen.columns:
            text_format = line[start].text_format
            end = start + 1
            while (
                end < terminal_screen.columns
                and line[end].text_format == text_format
            ):
                end += 1
            text = "".join(cell.char for cell in line[start:end])
            cursor.insertText(text, text_format)
            start = end

    def _move_to_screen_cursor(self, cursor: QTextCursor) -> None:
        terminal_screen = self.terminal_screen
        if terminal_screen is None:
            return
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down, n=terminal_screen.display_cursor_row()
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.Right, n=terminal_screen.cursor_column
        )
        self.setTextCursor(cursor)

    def _write_pty(self, text: str) -> None:
        if self.pty_fd is None:
            return
        try:
            os.write(self.pty_fd, text.encode())
        except OSError as e:
            logger.warning("Terminal write failed: %s", e)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasText():
            if self.cmd_mode:
                self._cmd_insert_text(source.text())
                return
            self._write_pty(source.text())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.cmd_mode and self._handle_cmd_key(event):
            return
        if self._handle_shortcut(event):
            return
        key_map = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Tab: "\t",
        }
        key = Qt.Key(event.key())
        text = (
            self._cursor_key_sequence(key)
            or self._function_key_sequence(key)
            or key_map.get(key, event.text())
        )
        if text:
            self._write_pty(text)

    def _handle_shortcut(self, event: QKeyEvent) -> bool:
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if ctrl and shift and event.key() == Qt.Key.Key_V:
            text = QApplication.clipboard().text()
            if text:
                if self.cmd_mode:
                    self._cmd_insert_text(text)
                else:
                    self._write_pty(text)
            return True
        if ctrl and shift and event.key() == Qt.Key.Key_C:
            self.copy()
            return True
        if ctrl and event.key() == Qt.Key.Key_C and self.cmd_mode:
            self._cmd_exit()
            return True
        if ctrl:
            self._write_control_key(event)
            return True
        return False


    def _handle_cmd_key(self, event: QKeyEvent) -> bool:
        """Handle line-editing keys for winecmd/cmd.exe mode."""
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._cmd_commit_line()
            return True
        if key == Qt.Key.Key_Backspace:
            self._cmd_backspace()
            return True
        if key == Qt.Key.Key_Delete:
            self._cmd_delete()
            return True
        if key == Qt.Key.Key_Tab:
            self._cmd_complete()
            return True
        if key == Qt.Key.Key_Left:
            self._cmd_move_left()
            return True
        if key == Qt.Key.Key_Right:
            self._cmd_move_right()
            return True
        if key == Qt.Key.Key_Up:
            self._cmd_history_prev()
            return True
        if key == Qt.Key.Key_Down:
            self._cmd_history_next()
            return True
        if key == Qt.Key.Key_Home:
            self._cmd_move_home()
            return True
        if key == Qt.Key.Key_End:
            self._cmd_move_end()
            return True

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_A:
                self._cmd_move_home()
                return True
            if key == Qt.Key.Key_E:
                self._cmd_move_end()
                return True
            return False

        text = event.text()
        if not text:
            return False
        self._cmd_insert_text(text)
        return True

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if self.app_theme:
            style = getattr(self.app_theme, "CONTEXT_MENU_STYLE", None)
            if style:
                menu.setStyleSheet(style)
        self._add_menu_action(
            menu,
            "Copy",
            QKeySequence.StandardKey.Copy,
            "copy",
            self.copy,
            self.textCursor().hasSelection(),
        )
        self._add_menu_action(
            menu,
            "Paste",
            QKeySequence.StandardKey.Paste,
            "paste",
            self._paste_from_clipboard,
            QApplication.clipboard().mimeData().hasText(),
        )
        self._add_menu_action(
            menu,
            "Select All",
            QKeySequence.StandardKey.SelectAll,
            "select_all",
            self.selectAll,
            bool(self.toPlainText()),
        )

        menu.addSeparator()
        icon = self.theme_manager.get_icon("theme")
        if not isinstance(icon, QIcon):
            icon = QIcon()
        scheme_menu = menu.addMenu(icon, "Terminal Color Scheme")
        self._populate_scheme_menu(scheme_menu)

        menu.exec(event.globalPos())

    def _populate_scheme_menu(self, menu: QMenu) -> None:
        try:
            from portprotonqt.config import ui_config
        except ImportError:
            return

        current = ui_config.get_terminal_scheme()

        for scheme_name in list_terminal_schemes():
            action = menu.addAction(scheme_name.replace("_", " ").title())
            action.setCheckable(True)
            action.setChecked(current == scheme_name)
            action.triggered.connect(
                lambda checked, name=scheme_name: self._set_scheme(name)
            )

    def _set_scheme(self, scheme_name: str) -> None:
        try:
            from portprotonqt.config import ui_config
        except ImportError:
            return

        ui_config.set_terminal_scheme(scheme_name)
        theme = load_terminal_scheme(scheme_name) or load_terminal_scheme("default")
        self.apply_theme(theme)

        # Clear screen to force prompt redraw with new colors
        if self.terminal_screen:
            self.terminal_screen._reset(clear_history=True)
            self._schedule_screen_render()
            # Send Form Feed (Ctrl+L) to shell to suggest a redraw
            self._write_pty("\x0c")

    def _add_menu_action(
        self,
        menu: QMenu,
        text: str,
        shortcut: QKeySequence.StandardKey,
        icon_name: str,
        slot,
        enabled: bool = True,
    ) -> None:
        icon = self.theme_manager.get_icon(icon_name)
        if not isinstance(icon, QIcon):
            icon = QIcon(icon) if isinstance(icon, str) else QIcon()
        action = menu.addAction(icon, text)
        action.setShortcut(QKeySequence(shortcut))
        action.setEnabled(enabled)
        action.triggered.connect(slot)

    def _paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        if self.cmd_mode:
            self._cmd_insert_text(text)
            return
        self._write_pty(text)

    def _strip_cmd_controls(self, text: str) -> str:
        """Remove ANSI/VT controls from winecmd output.

        Wine cmd.exe can emit OSC title updates, SGR colors and cursor
        visibility sequences. In cmd_mode we intentionally render output as
        plain editable text, so these controls must not be inserted literally.
        """
        if self.cmd_escape_pending:
            text = self.cmd_escape_pending + text
            self.cmd_escape_pending = ""

        text = self._hold_incomplete_cmd_escape(text)
        return CMD_CONTROL_RE.sub("", text)

    def _hold_incomplete_cmd_escape(self, text: str) -> str:
        esc_index = text.rfind("\x1b")
        if esc_index < 0:
            return text

        tail = text[esc_index:]
        if CMD_CONTROL_RE.fullmatch(tail):
            return text

        if tail.startswith("\x1b]"):
            has_bel = "\a" in tail[2:]
            has_st = "\x1b\\" in tail[2:]
            if not has_bel and not has_st:
                self.cmd_escape_pending = tail
                return text[:esc_index]

        if tail.startswith("\x1b["):
            if not any("@" <= char <= "~" for char in tail[2:]):
                self.cmd_escape_pending = tail
                return text[:esc_index]

        if len(tail) == 1:
            self.cmd_escape_pending = tail
            return text[:esc_index]

        return text


    def _normalize_cmd_newlines(self, text: str) -> str:
        """Normalize Wine cmd.exe CR/LF output before inserting it as text.

        Wine cmd.exe often writes CRCRLF (\r\r\n). QTextEdit treats the
        two carriage returns as additional paragraph breaks, which creates huge
        vertical gaps between lines. Keep one logical newline only.
        """
        if not text:
            return text

        text = text.replace("\r\r\n", "\n")
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")

        # Do not let duplicated empty lines explode after mixed CR/LF chunks.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _filter_cmd_output(self, text: str) -> str:
        if not self.cmd_echo_pending:
            return text
        buffer = self.cmd_echo_buffer + text
        pending = self.cmd_echo_pending
        if pending.startswith(buffer):
            self.cmd_echo_buffer = buffer
            return ""
        if not buffer.startswith(pending):
            self.cmd_echo_pending = ""
            self.cmd_echo_buffer = ""
            return buffer
        tail = buffer[len(pending) :]
        if tail.startswith("\r\r\n"):
            self.cmd_echo_pending = ""
            self.cmd_echo_buffer = ""
            return tail[3:]
        if tail.startswith("\r\n"):
            self.cmd_echo_pending = ""
            self.cmd_echo_buffer = ""
            return tail[2:]
        if tail.startswith("\n") or tail.startswith("\r"):
            self.cmd_echo_pending = ""
            self.cmd_echo_buffer = ""
            return tail[1:]
        self.cmd_echo_pending = ""
        self.cmd_echo_buffer = ""
        return buffer

    def _write_control_key(self, event: QKeyEvent) -> None:
        key = event.key()
        if not Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
            return
        code = key - Qt.Key.Key_A.value + 1
        self._write_pty(chr(code))

    def _cmd_input_text(self) -> str:
        block = self.document().lastBlock().text()
        start = self.cmd_input_start
        if start is None or start > len(block):
            return ""
        return block[start:]

    def _cmd_set_input_start(self) -> None:
        cursor = self.textCursor()
        self.cmd_input_start = cursor.positionInBlock()

    def _cmd_input_end(self) -> int:
        return len(self.document().lastBlock().text())

    def _cmd_cursor(self) -> QTextCursor:
        cursor = self.textCursor()
        start = self.cmd_input_start
        if start is None:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.cmd_input_start = cursor.positionInBlock()
            return cursor
        if cursor.block() != self.document().lastBlock():
            cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.positionInBlock() < start:
            cursor.setPosition(cursor.block().position() + start)
        return cursor

    def _cmd_insert_text(self, text: str) -> None:
        cursor = self._cmd_cursor()
        cursor.insertText(text, self.current_format)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cmd_backspace(self) -> None:
        if self.cmd_input_start is None:
            return
        cursor = self._cmd_cursor()
        if cursor.positionInBlock() <= self.cmd_input_start:
            return
        cursor.deletePreviousChar()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cmd_delete(self) -> None:
        cursor = self._cmd_cursor()
        if cursor.positionInBlock() >= self._cmd_input_end():
            return
        cursor.deleteChar()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cmd_commit_line(self) -> None:
        line = self._cmd_input_text()
        self._cmd_store_history(line)
        self.cmd_echo_pending = line
        self.cmd_echo_buffer = ""
        self._write_pty(f"{line}\r")
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.cmd_input_start = None
        self.cmd_history_index = None

    def _cmd_clear_input(self) -> None:
        if self.cmd_input_start is None:
            return
        self.cmd_echo_pending = ""
        self.cmd_echo_buffer = ""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.positionInBlock() <= self.cmd_input_start:
            return
        cursor.setPosition(cursor.block().position() + self.cmd_input_start)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.cmd_input_start = None

    def _cmd_exit(self) -> None:
        self.cmd_echo_pending = ""
        self.cmd_echo_buffer = ""
        self._write_pty("exit\r")

    def _cmd_move_left(self) -> None:
        if self.cmd_input_start is None:
            return
        cursor = self._cmd_cursor()
        if cursor.positionInBlock() <= self.cmd_input_start:
            return
        cursor.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(cursor)

    def _cmd_move_right(self) -> None:
        cursor = self._cmd_cursor()
        if cursor.positionInBlock() >= self._cmd_input_end():
            return
        cursor.movePosition(QTextCursor.MoveOperation.Right)
        self.setTextCursor(cursor)

    def _cmd_move_home(self) -> None:
        cursor = self._cmd_cursor()
        start = self.cmd_input_start
        if start is None:
            return
        cursor.setPosition(cursor.block().position() + start)
        self.setTextCursor(cursor)

    def _cmd_move_end(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def _cmd_store_history(self, line: str) -> None:
        if not line:
            return
        if self.cmd_history and self.cmd_history[-1] == line:
            return
        self.cmd_history.append(line)

    def _cmd_history_prev(self) -> None:
        if not self.cmd_history:
            return
        if self.cmd_history_index is None:
            self.cmd_history_draft = self._cmd_input_text()
            self.cmd_history_index = len(self.cmd_history) - 1
        else:
            self.cmd_history_index = max(0, self.cmd_history_index - 1)
        self._cmd_replace_input(self.cmd_history[self.cmd_history_index])

    def _cmd_history_next(self) -> None:
        if self.cmd_history_index is None:
            return
        if self.cmd_history_index >= len(self.cmd_history) - 1:
            self.cmd_history_index = None
            self._cmd_replace_input(self.cmd_history_draft)
            return
        self.cmd_history_index += 1
        self._cmd_replace_input(self.cmd_history[self.cmd_history_index])

    def _cmd_complete(self) -> None:
        current = self._cmd_input_text()
        if not current:
            return
        replacement = self._cmd_completion(current)
        if replacement:
            self._cmd_replace_input(replacement)

    def _cmd_replace_input(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.cmd_input_start is None:
            self.cmd_input_start = cursor.positionInBlock()
        cursor.setPosition(cursor.block().position() + self.cmd_input_start)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        cursor.insertText(text, self.current_format)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cmd_completion(self, text: str) -> str:
        word, prefix = self._cmd_split_completion(text)
        if not word:
            return ""
        matches = self._cmd_matches(word)
        if not matches:
            return ""
        match = os.path.commonprefix(matches)
        if len(matches) == 1:
            match = matches[0]
        if len(match) <= len(word):
            return ""
        return text[:prefix] + match

    def _cmd_split_completion(self, text: str) -> tuple[str, int]:
        index = max(text.rfind(" "), text.rfind("\t"))
        if index < 0:
            return text, 0
        return text[index + 1 :], index + 1

    def _cmd_matches(self, word: str) -> list[str]:
        if "\\" in word or "/" in word or ":" in word:
            return self._cmd_path_matches(word)
        return self._cmd_command_matches(word)

    def _cmd_command_matches(self, prefix: str) -> list[str]:
        matches: set[str] = set()
        for directory in self._cmd_search_dirs():
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    name = entry.name
                    if self._cmd_is_command_candidate(name, prefix):
                        matches.add(name)
        return sorted(matches)

    def _cmd_is_command_candidate(self, name: str, prefix: str) -> bool:
        base, ext = os.path.splitext(name)
        if not base.lower().startswith(
            prefix.lower()
        ) and not name.lower().startswith(prefix.lower()):
            return False
        return ext.lower() in (".exe", ".com", ".bat", ".cmd", "")

    def _cmd_search_dirs(self) -> list[str]:
        dirs = [
            os.path.join(self.cwd, "windows", "system32"),
            os.path.join(self.cwd, "windows", "syswow64"),
            self.cwd,
        ]
        return [directory for directory in dirs if os.path.isdir(directory)]

    def _cmd_path_matches(self, word: str) -> list[str]:
        local_path, prefix = self._cmd_windows_to_local(word)
        directory = os.path.dirname(local_path) or self.cwd
        try:
            entries = os.scandir(directory)
        except OSError:
            return []
        matches: list[str] = []
        with entries:
            for entry in entries:
                if entry.name.lower().startswith(prefix.lower()):
                    suffix = "\\" if entry.is_dir() else ""
                    matches.append(
                        self._cmd_local_to_windows(
                            os.path.join(directory, entry.name)
                        )
                        + suffix
                    )
        return sorted(matches)

    def _cmd_windows_to_local(self, path: str) -> tuple[str, str]:
        cleaned = path.replace("/", "\\")
        if len(cleaned) >= 3 and cleaned[1] == ":" and cleaned[2] == "\\":
            cleaned = cleaned[3:]
        parts = [part for part in cleaned.split("\\") if part]
        local = os.path.join(self.cwd, *parts)
        return local, os.path.basename(cleaned)

    def _cmd_local_to_windows(self, path: str) -> str:
        rel = os.path.relpath(path, self.cwd)
        if rel == ".":
            return "C:\\"
        return "C:\\" + rel.replace(os.sep, "\\")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_pty_size()

    def _sync_pty_size(self) -> None:
        rows, columns = self._terminal_size()
        if self.terminal_screen is not None:
            self.terminal_screen.resize(rows, columns)
        if self.pty_fd is None:
            return
        size = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(self.pty_fd, termios.TIOCSWINSZ, size)


class MainWindow(QMainWindow):
    """Main application window embedding the Qt terminal."""

    def __init__(
        self,
        command: list[str],
        cwd: str,
        fullscreen: bool,
        theme: object | None,
        cmd_mode: bool,
        app_theme: object | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(CONF_NAME)
        self.app_theme = app_theme or load_current_theme()
        if theme and getattr(theme, "background_opacity", 1.0) < 1.0:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if self.app_theme is not None:
            self.setStyleSheet(getattr(self.app_theme, "MAIN_WINDOW_STYLE", ""))
        self.terminal = TerminalWidget(command, cwd, theme, cmd_mode, self.app_theme)
        self.setCentralWidget(self.terminal)
        self.resize(*CONF_DEF_SIZE)
        if fullscreen:
            self.showFullScreen()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse xterm-compatible arguments used by PortProton scripts."""
    parser = argparse.ArgumentParser(prog="portprotonqt-terminal")
    parser.add_argument("--fullscreen", "-fullscreen", action="store_true")
    parser.add_argument("-e", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def build_command(args: argparse.Namespace) -> list[str]:
    """Build the command list to execute in the PTY."""
    if args.e:
        if len(args.e) == 1:
            return [
                default_shell(),
                "-lc",
                _with_portproton_functions(args.e[0]),
            ]
        return args.e
    return [default_shell()]


def apply_palette(widget: QPlainTextEdit, theme: object | None) -> None:
    """Apply terminal colors from the selected theme."""
    background_color = _theme_color(theme, "color_bg")
    foreground_color = _theme_color(theme, "color_text")
    selection_f = _theme_color(theme, "color_selection_f")
    selection_b = _theme_color(theme, "color_selection_b")
    opacity = getattr(theme, "background_opacity", 1.0)
    bg_image = getattr(theme, "background_image", "none")
    bg_layout = getattr(theme, "background_image_layout", "tiled")

    if background_color.isValid():
        background_color.setAlphaF(opacity)

    style_parts = []
    if background_color.isValid():
        style_parts.append(f"background-color: {background_color.name(QColor.NameFormat.HexArgb)};")
    if foreground_color.isValid():
        style_parts.append(f"color: {foreground_color.name()};")
    if selection_b.isValid():
        style_parts.append(f"selection-background-color: {selection_b.name()};")
    if selection_f.isValid():
        style_parts.append(f"selection-color: {selection_f.name()};")

    if bg_image != "none" and os.path.exists(bg_image):
        style_parts.append(f"background-image: url({bg_image});")
        if bg_layout == "tiled":
            style_parts.append("background-repeat: repeat;")
        elif bg_layout == "centered":
            style_parts.append("background-position: center; background-repeat: no-repeat;")
        elif bg_layout in ("scaled", "cscaled"):
            style_parts.append("background-position: center; background-repeat: no-repeat; background-attachment: fixed;")

    if style_parts:
        style = f"QPlainTextEdit {{ {' '.join(style_parts)} border: none; }}"
        widget.setStyleSheet(style)

    palette = widget.palette()
    if background_color.isValid():
        palette.setColor(QPalette.ColorRole.Base, background_color)
        palette.setColor(QPalette.ColorRole.Window, background_color)
    if foreground_color.isValid():
        palette.setColor(QPalette.ColorRole.Text, foreground_color)
        palette.setColor(QPalette.ColorRole.WindowText, foreground_color)
    if selection_f.isValid():
        palette.setColor(QPalette.ColorRole.HighlightedText, selection_f)
    if selection_b.isValid():
        palette.setColor(QPalette.ColorRole.Highlight, selection_b)

    widget.setPalette(palette)


def main(argv: list[str] | None = None) -> int:
    """Run PortProtonQt Terminal as a Qt application."""
    args = parse_args(argv or sys.argv[1:])
    command = build_command(args)
    cmd_mode = _is_cmd_mode(args)
    app = QApplication(sys.argv[:1])
    app.setWindowIcon(QIcon.fromTheme(APPLICATION_ID))
    app.setDesktopFileName(APPLICATION_ID)
    app_theme = load_current_theme()
    theme = load_current_terminal_scheme() or load_terminal_scheme("default")
    window = MainWindow(
        command, os.getcwd(), args.fullscreen, theme, cmd_mode, app_theme
    )
    apply_palette(window.terminal, theme)
    if not args.fullscreen:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
