"""Base dialogs for PortProtonQt."""

import os
import re
from pathlib import Path
from collections import deque
from functools import partial
import tempfile
from typing import Any, cast, TYPE_CHECKING
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout,
    QProgressBar, QSizePolicy, QWidget, QCheckBox, QProgressDialog, QScrollArea, QLineEdit, QApplication
)
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QStandardPaths, QSize, QThread
import psutil
import orjson
import pefile

if TYPE_CHECKING:
    from portprotonqt.main_window import MainWindow
    from portprotonqt.dialogs.file_explorer import FileExplorer

from portprotonqt.config import (
    LAUNCH_FILE_EXTENSIONS,
    THEMED_LAUNCH_ICON_NAMES,
    create_desktop_file,
    extract_exec_target_path,
    get_portproton_location,
    parse_desktop_entry,
    ui_config,
)
from portprotonqt.config.portproton import get_custom_icon_path, resolve_custom_data_dir
from portprotonqt.logger import get_logger
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.custom_widgets import AutoSizeButton
from portprotonqt.downloader import Downloader
from portprotonqt.virtual_keyboard import VirtualKeyboard
from portprotonqt.localization import _
from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS, set_animated_cover
from portprotonqt.icon_extractor import generate_thumbnail
from portprotonqt.dialogs.dialog_utils import create_dialog_hints_widget, update_dialog_hints

logger = get_logger(__name__)
theme_manager = ThemeManager()
DISC_IMAGE_EXTENSIONS = (".iso", ".mdf", ".nrg")


class FileSelectedSignal(QObject):
    """Signal class for file selection."""
    file_selected = Signal(str)


class DraggableDialog(QDialog):
    """Dialog with support for system move on left mouse press."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window_handle = self.window().windowHandle()
            if window_handle is not None:
                window_handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)


class GameLaunchDialog(DraggableDialog):
    """Modal dialog to indicate game launch progress, similar to Steam's launch dialog."""

    def __init__(self, parent=None, game_name=None, theme=None, target_exe=None):
        super().__init__(parent)
        self.theme = theme if theme else theme_manager.apply_theme(ui_config.get_theme())
        self.game_name = game_name
        self.target_exe = target_exe
        self.setWindowTitle(_("Launching {0}").format(self.game_name))
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.setStyleSheet(self.theme.MESSAGE_BOX_STYLE)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        label = QLabel(_("Launching {0}").format(self.game_name))
        label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(self.theme.PROGRESS_BAR_STYLE)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.cancel_button = AutoSizeButton(_("Cancel"), icon=theme_manager.get_icon("cancel", as_path=True))
        self.cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        if parent:
            parent_geometry = parent.geometry()
            center_point = parent_geometry.center()
            dialog_geometry = self.geometry()
            dialog_geometry.moveCenter(center_point)
            self.setGeometry(dialog_geometry)

        self.check_process_timer = QTimer(self)
        self.check_process_timer.timeout.connect(self.check_target_exe)
        self.check_process_timer.start(500)

    def is_target_exe_running(self):
        """Check if the target executable is running using psutil."""
        if not self.target_exe:
            return False
        for proc in psutil.process_iter(attrs=["name"]):
            if proc.info["name"].lower() == self.target_exe.lower():
                return True
        return False

    def check_target_exe(self):
        """Check if the game process is running and close the dialog if it is."""
        if self.is_target_exe_running():
            logger.info(f"Game {self.game_name} process detected as running, closing launch dialog")
            self.accept()
            self.check_process_timer.stop()
            self.check_process_timer.deleteLater()
        elif not hasattr(self.parent(), 'game_processes') or not any(proc.poll() is None for proc in cast("MainWindow", self.parent()).game_processes):
            self.check_process_timer.stop()
            self.check_process_timer.deleteLater()

    def reject(self):
        """Handle dialog cancellation."""
        logger.info(f"Game launch cancelled for {self.game_name}")
        self.check_process_timer.stop()
        self.check_process_timer.deleteLater()
        super().reject()


class GameFolderScanWorker(QThread):
    """Find executable files recursively and report scanned directory counts."""

    progressChanged = Signal(object)

    def __init__(self, folder: str, parent: QObject) -> None:
        super().__init__(parent)
        self.folder = folder
        self.games: list[tuple[str, str]] = []
        self.errors: list[str] = []

    MAX_SCAN_DEPTH = 5
    MAX_SCAN_DIRECTORIES = 400
    GAME_SUBDIRECTORIES = frozenset((
        "bin", "bin32", "bin64", "binaries", "win32", "win64", "x64", "x86", "game", "disccontentpc", "api",
    ))

    def run(self) -> None:
        for directory, paths in self._find_executables(self.folder).items():
            if self.isInterruptionRequested():
                return
            try:
                executable = max(paths, key=lambda path: self._executable_score(path, directory))
                self.games.append((self._game_name(executable, directory), executable))
            except OSError as error:
                self._record_error(error)
        self.games.sort(key=lambda game: game[1].casefold())

    def _executable_score(self, executable: str, directory: str) -> tuple[int, int, int]:
        name = Path(executable).stem.casefold()
        folder = re.sub(r"[\W_]", "", os.path.basename(directory).casefold())
        key = re.sub(r"[\W_]", "", name)
        match = int(key == folder) + int(bool(key and folder and (key in folder or folder in key)))
        launcher = name.endswith(("launcher", "redirector")) or name in ("play", "start", "run")
        depth = len(Path(executable).relative_to(directory).parts)
        return match - int(launcher), -depth, os.path.getsize(executable)

    def _executable_name(self, executable: str) -> str:
        try:
            with pefile.PE(executable, fast_load=True) as pe:
                pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
                tables = [table for block in getattr(pe, "FileInfo", []) for info in block
                          for table in getattr(info, "StringTable", [])]
                metadata = {key.decode("utf-8", errors="replace"): value.decode("utf-8", errors="replace")
                            for table in tables for key, value in table.entries.items()}
        except pefile.PEFormatError:
            return ""
        except OSError as error:
            logger.warning("Failed to read executable metadata %s: %s", executable, error)
            return ""
        for field in ("ProductName", "FileDescription"):
            value = metadata.get(field, "").strip()
            if value and not re.fullmatch(
                r"(?i)(?:BootstrapPackagedGame|game|application|launcher|.*launcher.*|.*redistributable.*)", value,
            ):
                return value
        return ""

    def _game_name(self, executable: str, directory: str) -> str:
        name = ""
        for info in sorted(Path(directory).glob("goggame-*.info")):
            try:
                data = orjson.loads(info.read_bytes().removeprefix(b"\xef\xbb\xbf"))
                if (isinstance(data, dict) and isinstance(data.get("name"), str)
                        and data.get("gameId") == data.get("rootGameId")):
                    name = data["name"]
                    break
            except OSError as error:
                logger.warning("Failed to read game metadata %s: %s", info, error)
            except ValueError as error:
                logger.warning("Invalid game metadata %s: %s", info, error)
        if not name:
            name = self._executable_name(executable) or Path(directory).name
        name = re.sub(r"(?i)[._ ]+(?:v?\d+(?:[._]\d+)+|build[._ ]?\d+).*$", "", name)
        name = name.replace(".", " ")
        name = re.sub(r"[\\/\r\n]", " ", name).replace(":", " - ")
        return " ".join(name.replace("_", " ").split()).strip(" .") or Path(executable).stem

    def _record_error(self, error: OSError) -> None:
        logger.warning("Failed to scan game folder: %s", error)
        self.errors.append(str(error))

    def _is_runtime_directory(self, path: str) -> bool:
        name = os.path.basename(path).casefold()
        parent = os.path.basename(os.path.dirname(path)).casefold()
        runtime = r"(?:i386-windows|x86_64-windows|mono|monobleedingedge|wine-mono.*|jre[\d._-]*|jdk[\d._-]*|java-runtime.*|_?commonredist|__installer)"
        if re.fullmatch(runtime, name) or name in ("$recycle.bin", "system volume information", "config.msi", "msdownld.tmp"):
            return True
        if name == "windows" and parent == "drive_c":
            return True
        if name in ("windows media player", "internet explorer", "windows nt") and parent.startswith("program files"):
            return True
        if "proton" in name or name.startswith("wine"):
            return os.path.isfile(os.path.join(path, "proton")) or os.path.isdir(os.path.join(path, "lib", "wine"))
        return False

    def _find_executables(self, folder: str) -> dict[str, list[str]]:
        games: dict[str, list[str]] = {}
        pending = deque([] if self._is_runtime_directory(folder) else [(folder, 0, folder)])
        visited: dict[str, int] = {}
        completed, total = 0, len(pending)
        ignored = r"(?i)(?:unins.*|setup.*|install.*|.*redist.*|dxsetup.*|directx.*|dotnet.*|.*crash.*|.*report.*|.*prereq.*|.*updater?.*|.*config.*|.*settings.*|.*helper.*|.*benchmark.*|.*-win(?:32|64)-shipping|.*easyanticheat.*|.*battleye.*|oalinst|overlay_test.*|.*[-_](?:setup|installer).*|.*errormonitor|pluginhost|.*_api)"
        skipped = {"engine", "melonloader", "mods", "plugins", "userdata", "userlibs", "reshade_shaders",
                   "assets", "data", "resources", "res", "res_mods", "replays", "movies", "cache", "logs"}
        while pending:
            if self.isInterruptionRequested():
                return {}
            root, depth, branch = pending.popleft()
            label = _("Scanning: {folder}").format(folder=root)
            self.progressChanged.emit((completed, total, label))
            try:
                with os.scandir(root) as entries:
                    entries_list = sorted(entries, key=lambda entry: entry.name.casefold())
                files = [entry.path for entry in entries_list if entry.name.casefold().endswith(".exe")
                         and not re.fullmatch(ignored, entry.name[:-len(".exe")])
                         and not entry.is_symlink() and entry.is_file(follow_symlinks=False)]
                directory = root
                while directory != folder and Path(directory).name.casefold() in self.GAME_SUBDIRECTORIES:
                    directory = os.path.dirname(directory)
                if files:
                    games.setdefault(directory, []).extend(files)
                for entry in entries_list:
                    name = entry.name.casefold()
                    if (depth >= self.MAX_SCAN_DEPTH or entry.is_symlink() or not entry.is_dir(follow_symlinks=False)
                            or name.startswith((".", "$")) or name in skipped or name.endswith("_data")
                            or re.fullmatch(ignored, name) or self._is_runtime_directory(entry.path)):
                        continue
                    if files and root != folder and name not in self.GAME_SUBDIRECTORIES:
                        continue
                    owner = entry.path if root == folder or Path(root).name.casefold() == "common" else branch
                    if visited.get(owner, 0) >= self.MAX_SCAN_DIRECTORIES:
                        self._record_error(OSError(f"Game folder scan directory limit reached: {owner}"))
                        break
                    visited[owner] = visited.get(owner, 0) + 1
                    next_depth = 0 if owner == entry.path or name in ("steamapps", "common") else depth + 1
                    pending.append((entry.path, next_depth, owner))
                    total += 1
            except OSError as error:
                self._record_error(error)
            completed += 1
            self.progressChanged.emit((completed, total, label))
        return games


class GameFolderImportWorker(QThread):
    """Create selected shortcuts without overwriting existing entries."""

    progressChanged = Signal(object)

    def __init__(self, games: list[tuple[str, str]], parent: QObject) -> None:
        super().__init__(parent)
        self.games = games
        self.added = 0
        self.skipped = 0
        self.errors: list[str] = []

    def run(self) -> None:
        try:
            location = get_portproton_location()
            if not location:
                raise FileNotFoundError("PortProton directory not found")
            existing = set()
            with os.scandir(location) as entries:
                paths = [entry.path for entry in entries if entry.name.endswith(".desktop") and entry.is_file()]
            for index, path in enumerate(paths):
                if self.isInterruptionRequested():
                    return
                self.progressChanged.emit((index, len(paths), _("Checking existing shortcuts: {path}").format(path=path)))
                entry = parse_desktop_entry(path)
                target = extract_exec_target_path(entry.get("Exec", "")) if entry else None
                if target:
                    existing.add(os.path.realpath(target))
            for index, (name, executable) in enumerate(self.games):
                if self.isInterruptionRequested():
                    return
                self.progressChanged.emit((index, len(self.games), _("Adding: {name}").format(name=name)))
                self._import_game(name, executable, existing)
                self.progressChanged.emit((index + 1, len(self.games), _("Adding: {name}").format(name=name)))
        except OSError as error:
            logger.warning("Failed to import game folder: %s", error)
            self.errors.append(str(error))

    def _import_game(self, name: str, executable: str, existing: set[str]) -> None:
        target = os.path.realpath(executable)
        if target in existing:
            self.skipped += 1
            return
        created = False
        desktop_path = ""
        try:
            name = " ".join(re.sub(r"[\\/]", " ", name).split()).strip(" .")
            result = create_desktop_file(executable, name)
            if result is None:
                raise OSError(_("Failed to create shortcut: {name}").format(name=name))
            content, desktop_path, icon_path = result
            if os.path.exists(desktop_path):
                self.skipped += 1
                return
            if not os.path.exists(icon_path) and not generate_thumbnail(executable, icon_path, size=128):
                content = content.replace(f"Icon={icon_path}\n", "Icon=\n")
            with open(desktop_path, "x", encoding="utf-8") as desktop:
                created = True
                desktop.write(content)
            os.chmod(desktop_path, 0o755)
            existing.add(target)
            self.added += 1
        except FileExistsError:
            self.skipped += 1
        except OSError as error:
            logger.warning("Failed to import '%s': %s", executable, error)
            self.errors.append(f"{name}: {error}")
            if created:
                try:
                    os.unlink(desktop_path)
                except OSError as cleanup_error:
                    logger.warning("Failed to remove incomplete shortcut: %s", cleanup_error)


class AddGameDialog(DraggableDialog):
    """Dialog for adding or editing a game."""

    gamesAdded = Signal()

    def __init__(self, parent=None, theme=None, edit_mode=False, game_name=None, exe_path=None, cover_path=None, steam_appid=None):
        super().__init__(parent)
        from portprotonqt.context_menu_manager import CustomLineEdit
        self.theme = theme if theme else theme_manager.apply_theme(ui_config.get_theme())
        self.edit_mode = edit_mode
        if exe_path is None and steam_appid is not None:
            exe_path = f"steam://rungameid/{steam_appid}"
        self.last_exe_path = exe_path
        self.last_cover_path = cover_path
        refresh_games = getattr(parent, "refreshGames", None)
        if callable(refresh_games):
            self.gamesAdded.connect(refresh_games)
        self.downloader = Downloader(max_workers=4)

        self.setWindowTitle(_("Edit Shortcut") if edit_mode else _("Add a shortcut"))
        self.setModal(True)
        self.setFixedWidth(600)
        self.setFixedHeight(600)
        self.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE)

        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.nameEdit = CustomLineEdit(self, theme=self.theme)
        self.nameEdit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        if game_name:
            self.nameEdit.setText(game_name)
        name_label = QLabel(_("Name:"))
        name_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        layout.addRow(name_label, self.nameEdit)

        self.exeEdit = CustomLineEdit(self, theme=self.theme)
        self.exeEdit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        self.exeEdit.setVisible(steam_appid is None)
        if exe_path:
            self.exeEdit.setText(exe_path)

        exeBrowseButton = AutoSizeButton(_("Browse…"), icon=theme_manager.get_icon("search", as_path=True))
        exeBrowseButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        exeBrowseButton.clicked.connect(self.browseExe)
        exeBrowseButton.setObjectName("exeBrowseButton")
        exeBrowseButton.setVisible(steam_appid is None)
        if steam_appid is None:
            exe_label = QLabel(_("Path to Executable:"))
            exe_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
            layout.addRow(exe_label, self.exeEdit)

            empty_label = QLabel("")
            empty_label.setFixedWidth(exe_label.sizeHint().width())
            layout.addRow(empty_label, exeBrowseButton)

        cover_label = QLabel(_("Custom Cover:"))
        cover_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)

        self.coverEdit = CustomLineEdit(self, theme=self.theme)
        self.coverEdit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        self.coverEdit.setPlaceholderText(_("Enter local path or URL for cover image"))
        if cover_path:
            self.coverEdit.setText(cover_path)

        coverBrowseButton = AutoSizeButton(_("Browse…"), icon=theme_manager.get_icon("search", as_path=True))
        coverBrowseButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        coverBrowseButton.clicked.connect(self.browseCover)
        coverBrowseButton.setObjectName("coverBrowseButton")

        layout.addRow(cover_label, self.coverEdit)
        cover_button_label = QLabel("")
        cover_button_label.setFixedWidth(cover_label.sizeHint().width())
        layout.addRow(cover_button_label, coverBrowseButton)

        self.iconEdit = CustomLineEdit(self, theme=self.theme)
        self.iconEdit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        self.iconEdit.setText(get_custom_icon_path(exe_path) if exe_path else "")
        icon_label = QLabel(_("Custom Icon:"))
        icon_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.iconEdit)
        icon_browse = AutoSizeButton(_("Browse…"), icon=theme_manager.get_icon("search", as_path=True))
        icon_browse.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        icon_browse.clicked.connect(self.browseIcon)
        icon_row.addWidget(icon_browse)
        layout.addRow(icon_label, icon_row)

        self.add_to_steam_checkbox = QCheckBox()
        self.add_to_menu_checkbox = QCheckBox()
        self.add_to_desktop_checkbox = QCheckBox()
        self.add_to_steam_checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.add_to_menu_checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.add_to_desktop_checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        icon = theme_manager.get_icon("menu_steam")
        if isinstance(icon, QIcon):
            self.add_to_steam_checkbox.setIcon(icon)
        icon = theme_manager.get_icon("menu")
        if isinstance(icon, QIcon):
            self.add_to_menu_checkbox.setIcon(icon)
        icon = theme_manager.get_icon("desktop")
        if isinstance(icon, QIcon):
            self.add_to_desktop_checkbox.setIcon(icon)
        self.add_to_steam_checkbox.setIconSize(QSize(20, 20))
        self.add_to_menu_checkbox.setIconSize(QSize(20, 20))
        self.add_to_desktop_checkbox.setIconSize(QSize(20, 20))
        self.add_to_steam_checkbox.setVisible(steam_appid is None)
        options_layout = QHBoxLayout()
        options_layout.setSpacing(12)
        options_layout.addWidget(self.add_to_steam_checkbox)
        options_layout.addWidget(self.add_to_menu_checkbox)
        options_layout.addWidget(self.add_to_desktop_checkbox)
        options_layout.addStretch()
        options_widget = QWidget(self)
        options_widget.setLayout(options_layout)
        options_widget.setVisible(steam_appid is None)
        options_label = QLabel(_("Add shortcut to:"))
        options_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        options_label.setVisible(steam_appid is None)
        if steam_appid is None:
            layout.addRow(options_label, options_widget)

        current_name = game_name.strip() if game_name else self.nameEdit.text().strip()
        self.add_to_steam_checkbox.setChecked(self._steam_shortcut_exists(current_name))
        self.add_to_menu_checkbox.setChecked(self._menu_shortcut_exists(current_name))
        self.add_to_desktop_checkbox.setChecked(self._desktop_shortcut_exists(current_name))

        self.coverPreview = QLabel(self)
        self.coverPreview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coverPreview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview_widget = QWidget(self)
        preview_widget.setStyleSheet(self.theme.PREVIEW_WIDGET_STYLE)
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_label = QLabel(_("Cover Preview:"))
        preview_label.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        preview_layout.addWidget(preview_label, alignment=Qt.AlignmentFlag.AlignLeft)
        preview_layout.addWidget(self.coverPreview, stretch=1)
        layout.addRow(preview_widget)

        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(10)
        self.select_button = AutoSizeButton(_("Apply"), icon=theme_manager.get_icon("apply", as_path=True))
        self.cancel_button = AutoSizeButton(_("Cancel"), icon=theme_manager.get_icon("cancel", as_path=True))
        self.select_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.button_layout.addWidget(self.select_button)
        self.button_layout.addWidget(self.cancel_button)
        layout.addRow(self.button_layout)

        self.select_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.cover_preview_timer = QTimer(self)
        self.cover_preview_timer.setSingleShot(True)
        self.cover_preview_timer.timeout.connect(self.updatePreview)

        self.coverEdit.textChanged.connect(self.onCoverTextChanged)
        self.exeEdit.textChanged.connect(self.updatePreview)

        def update_button_widths():
            exeBrowseButton.setFixedWidth(self.exeEdit.width())
            coverBrowseButton.setFixedWidth(self.coverEdit.width())

        QTimer.singleShot(0, update_button_widths)

        if edit_mode:
            self.updatePreview()

        self.init_keyboard()
        QTimer.singleShot(0, lambda: self.nameEdit.setFocus())

    def _steam_shortcut_exists(self, game_name):
        """Check whether the game already exists in Steam shortcuts."""
        if not game_name:
            return False
        from portprotonqt.steam_api import is_game_in_steam
        return is_game_in_steam(game_name)

    def _menu_shortcut_exists(self, game_name):
        """Check whether the game .desktop shortcut exists in applications menu."""
        if not game_name:
            return False
        applications_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
        return os.path.exists(os.path.join(applications_dir, f"{game_name}.desktop"))

    def _desktop_shortcut_exists(self, game_name):
        """Check whether the game .desktop shortcut exists on the Desktop."""
        if not game_name:
            return False
        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        return os.path.exists(os.path.join(desktop_dir, f"{game_name}.desktop"))

    def init_keyboard(self):
        """Initialize virtual keyboard."""
        self.keyboard = VirtualKeyboard(self, theme=self.theme, button_width=40)
        self.keyboard.hide()

    def show_keyboard_for_widget(self, widget):
        """Show keyboard for specified widget."""
        if not widget or not widget.isVisible():
            return

        self.keyboard.show_for_widget(widget)

    def closeEvent(self, event):
        """Handle window close."""
        if hasattr(self, 'keyboard'):
            self.keyboard.hide()
        super().closeEvent(event)

    def reject(self):
        """Handle Cancel button."""
        if hasattr(self, 'keyboard'):
            self.keyboard.hide()
        super().reject()

    def accept(self):
        """Handle Apply button."""
        icon_path = self.iconEdit.text().strip()
        exe_path = self.last_exe_path if self.edit_mode else self.exeEdit.text().strip()
        if icon_path and exe_path and icon_path != get_custom_icon_path(exe_path):
            from PySide6.QtWidgets import QMessageBox

            image = QPixmap(icon_path)
            if image.isNull():
                QMessageBox.warning(self, _("Error"), _("Invalid image"))
                return
            data_home = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            folder = resolve_custom_data_dir(os.path.join(data_home, "PortProtonQt", "custom_data"), exe_path)
            temporary_path = None
            try:
                os.makedirs(folder, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder, suffix=".png", delete=False) as temporary:
                    temporary_path = temporary.name
                if not image.save(temporary_path, "PNG"):
                    raise OSError("Failed to save icon")
                os.replace(temporary_path, os.path.join(folder, "icon.png"))
            except OSError as error:
                logger.warning("Failed to save custom icon: %s", error)
                QMessageBox.warning(self, _("Error"), str(error))
                return
            finally:
                if temporary_path:
                    Path(temporary_path).unlink(missing_ok=True)
        if hasattr(self, 'keyboard'):
            self.keyboard.hide()
        super().accept()

    def browseIcon(self) -> None:
        from portprotonqt.dialogs.file_explorer import FileExplorer

        explorer = FileExplorer(self, file_filter=COVER_IMAGE_EXTENSIONS + (".ico",),
                                initial_path=os.path.dirname(self.iconEdit.text()) or None)
        explorer.file_signal.file_selected.connect(self.iconEdit.setText)
        explorer.show()

    def browseExe(self):
        """Open file manager to select executable or disc image."""
        try:
            from portprotonqt.dialogs.file_explorer import FileExplorer
            initial_path = os.path.dirname(self.last_exe_path) if self.last_exe_path and os.path.isfile(self.last_exe_path) else None
            file_explorer = FileExplorer(self, file_filter=LAUNCH_FILE_EXTENSIONS, initial_path=initial_path)
            file_explorer.file_signal.file_selected.connect(self.onExeSelected)
            if not self.edit_mode:
                folder_button = AutoSizeButton(_("Select folder"), icon=theme_manager.get_icon("folder", as_path=True))
                folder_button.setObjectName("gamepadAddButton")
                folder_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
                folder_button.clicked.connect(partial(self._select_game_folder, file_explorer))
                file_explorer.button_layout.insertWidget(0, folder_button)

            parent_widget = self.parentWidget()
            if parent_widget:
                parent_geometry = parent_widget.geometry()
                center_point = parent_geometry.center()
                file_explorer_geometry = file_explorer.geometry()
                file_explorer_geometry.moveCenter(center_point)
                file_explorer.setGeometry(file_explorer_geometry)

            file_explorer.show()
        except Exception as e:
            logger.error(f"Error in browseExe: {e}")

    def _select_game_folder(self, explorer: "FileExplorer") -> None:
        folder = explorer.current_path
        item = explorer.file_list.currentItem()
        if item and item.text() != "../":
            selected = os.path.normpath(os.path.join(folder, item.text()))
            if os.path.isdir(selected):
                folder = selected
        self._game_folder_root = folder
        explorer.accept()
        self._start_folder_worker(GameFolderScanWorker(folder, self.parentWidget() or self))

    def _start_folder_worker(self, worker: GameFolderScanWorker | GameFolderImportWorker) -> None:
        owner = cast(Any, self.parentWidget() or self)
        workers = getattr(owner, "_gameFolderWorkers", [])
        owner._gameFolderWorkers = workers
        workers.append(worker)
        progress = QProgressDialog(_("Processing games…"), _("Cancel"), 0, 1, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setStyleSheet(self.theme.MESSAGE_BOX_STYLE + self.theme.PROGRESS_BAR_STYLE)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.canceled.connect(worker.requestInterruption)
        worker.progressChanged.connect(partial(self._update_folder_progress, progress), Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(partial(self._finish_folder_worker, worker, progress), Qt.ConnectionType.QueuedConnection)
        progress.show()
        worker.start()

    def _update_folder_progress(self, progress: QProgressDialog, state: tuple[int, int, str]) -> None:
        if progress.wasCanceled():
            return
        completed, total, current = state
        progress.setLabelText(_("Processed {completed}/{total}\n{current}").format(
            completed=completed, total=total, current=current,
        ))
        progress.setRange(0, max(total, 1))
        progress.setValue(completed)

    def _finish_folder_worker(self, worker: QThread, progress: QProgressDialog) -> None:
        from PySide6.QtWidgets import QMessageBox

        owner = self.parentWidget() or self
        workers = getattr(owner, "_gameFolderWorkers", [])
        cancelled = progress.wasCanceled()
        progress.close()
        progress.deleteLater()
        worker.deleteLater()
        if worker not in workers:
            return
        workers.remove(worker)
        if isinstance(worker, GameFolderImportWorker):
            if worker.added:
                self.gamesAdded.emit()
            if cancelled:
                return
            if worker.errors:
                QMessageBox.warning(self, _("Error"), "\n".join(worker.errors))
            self.reject()
        elif isinstance(worker, GameFolderScanWorker) and not cancelled:
            if worker.errors:
                QMessageBox.warning(self, _("Error"), "\n".join(worker.errors))
            if worker.games:
                self._show_folder_games(worker.games)
            else:
                QMessageBox.information(self, _("Information"), _("No games found in the selected folder."))

    def _create_folder_game_row(
        self, layout: QVBoxLayout, game: tuple[str, str],
    ) -> tuple[QLineEdit, QLineEdit, QCheckBox]:
        from portprotonqt.context_menu_manager import CustomLineEdit

        name, executable = game
        content = layout.parentWidget()
        row = QHBoxLayout()
        checkbox = QCheckBox(content)
        checkbox.setObjectName("gameFolderExecutable")
        checkbox.setAccessibleName(executable)
        checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        checkbox.setChecked(True)
        title = CustomLineEdit(name, content, theme=self.theme)
        title.setAccessibleName(_("Name:"))
        title.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        path = CustomLineEdit(executable, content, theme=self.theme)
        path.setObjectName("gameFolderPath")
        path.setAccessibleName(_("Path to Executable:"))
        path.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        browse = AutoSizeButton(_("Browse…"), icon=theme_manager.get_icon("folder", as_path=True))
        browse.setAutoDefault(False)
        browse.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        browse.clicked.connect(partial(self._browse_folder_exe, path))
        path_row = QHBoxLayout()
        path_row.addWidget(path)
        path_row.addWidget(browse)
        details = QVBoxLayout()
        details.addWidget(title)
        details.addLayout(path_row)
        row.addWidget(checkbox)
        row.addLayout(details)
        layout.addLayout(row)
        QWidget.setTabOrder(checkbox, title)
        QWidget.setTabOrder(title, path)
        QWidget.setTabOrder(path, browse)
        return title, path, checkbox

    def _browse_folder_exe(self, field: QLineEdit) -> None:
        from portprotonqt.dialogs.file_explorer import FileExplorer

        explorer = FileExplorer(
            field.window(), theme=self.theme, file_filter=(".exe",),
            initial_path=os.path.dirname(os.path.expanduser(field.text().strip())),
        )
        explorer.file_signal.file_selected.connect(field.setText)
        explorer.exec()
        field.setFocus(Qt.FocusReason.OtherFocusReason)
        explorer.deleteLater()

    def _accept_folder_games(
        self, dialog: QDialog, rows: list[tuple[QLineEdit, QLineEdit, QCheckBox]],
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        for title, path, checkbox in rows:
            if not checkbox.isChecked():
                continue
            if not title.text().strip():
                QMessageBox.warning(dialog, _("Error"), _("Game name and executable path are required"))
                title.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            executable = os.path.expanduser(path.text().strip())
            if not os.path.isfile(executable):
                QMessageBox.warning(dialog, _("Error"), _("Executable not found: {0}").format(executable))
                path.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            path.setText(executable)
        dialog.accept()

    def _scroll_folder_focus(self, scroll: QScrollArea, _old: QWidget | None, focused: QWidget | None) -> None:
        if focused is not None and scroll.isAncestorOf(focused):
            scroll.ensureWidgetVisible(focused)

    def _show_folder_games(self, games: list[tuple[str, str]]) -> None:
        dialog = cast(Any, DraggableDialog(self))
        dialog.setWindowTitle(_("Select games"))
        dialog.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE)
        dialog.resize(*self.theme.GAME_FOLDER_IMPORT_DIALOG_SIZE)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        rows_layout = QVBoxLayout(content)
        rows = [self._create_folder_game_row(rows_layout, game) for game in games]
        rows_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QHBoxLayout()
        apply_button = AutoSizeButton(_("Apply"), icon=theme_manager.get_icon("apply", as_path=True))
        apply_button.setObjectName("gamepadAddButton")
        cancel_button = AutoSizeButton(_("Close"), icon=theme_manager.get_icon("cancel", as_path=True))
        for button in (apply_button, cancel_button):
            button.setAutoDefault(False)
            button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            buttons.addWidget(button)
        apply_button.clicked.connect(partial(self._accept_folder_games, dialog, rows))
        cancel_button.clicked.connect(dialog.reject)
        layout.addLayout(buttons)
        main_window = self.parentWidget()
        input_manager = getattr(main_window, "input_manager", None)
        hints, labels = create_dialog_hints_widget(self.theme, main_window, input_manager, context='folder_import')
        layout.addWidget(hints)
        update_dialog_hints(labels, main_window, input_manager, theme_manager, ui_config.get_theme())
        dialog.keyboard = VirtualKeyboard(dialog, theme=self.theme)
        dialog.finished.connect(dialog.keyboard.hide)
        if rows:
            QTimer.singleShot(0, rows[0][2].setFocus)
        app = cast(QApplication, QApplication.instance())
        scroll_focus = partial(self._scroll_folder_focus, scroll)
        app.focusChanged.connect(scroll_focus)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            app.focusChanged.disconnect(scroll_focus)
        if accepted:
            selected = [(title.text().strip(), path.text().strip()) for title, path, checkbox in rows
                        if checkbox.isChecked()]
            if selected:
                self._start_folder_worker(GameFolderImportWorker(selected, self.parentWidget() or self))
        dialog.deleteLater()

    def onExeSelected(self, file_path):
        """Handle file selection in FileExplorer."""
        self.exeEdit.setText(file_path)
        self.last_exe_path = file_path
        if not self.edit_mode and not self.nameEdit.text().strip():
            game_name = os.path.splitext(os.path.basename(file_path))[0]
            self.nameEdit.setText(game_name)
        self.updatePreview()

    def browseCover(self):
        """Open file manager to select cover image."""
        try:
            from portprotonqt.dialogs.file_explorer import FileExplorer
            initial_path = os.path.dirname(self.last_cover_path) if self.last_cover_path and os.path.isfile(self.last_cover_path) else None
            file_explorer = FileExplorer(self, file_filter=COVER_IMAGE_EXTENSIONS, initial_path=initial_path)
            file_explorer.file_signal.file_selected.connect(self.onCoverSelected)

            parent_widget = self.parentWidget()
            if parent_widget:
                parent_geometry = parent_widget.geometry()
                center_point = parent_geometry.center()
                file_explorer_geometry = file_explorer.geometry()
                file_explorer_geometry.moveCenter(center_point)
                file_explorer.setGeometry(file_explorer_geometry)

            file_explorer.show()
        except Exception as e:
            logger.error(f"Error in browseCover: {e}")

    def onCoverSelected(self, file_path):
        """Handle cover file selection in FileExplorer."""
        if file_path and os.path.splitext(file_path)[1].lower() in COVER_IMAGE_EXTENSIONS:
            self.coverEdit.setText(file_path)
            self.last_cover_path = file_path
            self.updatePreview()
        else:
            logger.warning(f"Selected file is not a valid image: {file_path}")

    def handleDownloadedCover(self, file_path):
        """Handle the downloaded cover image and update the preview."""
        if not hasattr(self, 'coverPreview') or self.coverPreview is None:
            return

        try:
            if file_path and os.path.isfile(file_path):
                self.last_cover_path = file_path
                if set_animated_cover(self.coverPreview, file_path, 250, 250):
                    return
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    self.coverPreview.setPixmap(pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio))
                else:
                    self.coverPreview.setText(_("Invalid image"))
            else:
                self.coverPreview.setText(_("Failed to download cover"))
                logger.warning(f"Failed to download cover to {file_path}")
        except RuntimeError:
            pass

    def onCoverTextChanged(self):
        """Handle cover text changes with debounce."""
        self.cover_preview_timer.start(500)

    def updatePreview(self):
        """Update the cover preview image."""
        cover_path = self.coverEdit.text().strip()
        exe_path = self.exeEdit.text().strip()
        launch_path = exe_path

        if exe_path.lower().endswith(DISC_IMAGE_EXTENSIONS):
            parent_widget = cast("MainWindow | None", self.parentWidget())
            if parent_widget and hasattr(parent_widget, "resolve_launch_file_path"):
                resolved_path = parent_widget.resolve_launch_file_path(exe_path)
                if resolved_path and os.path.isfile(resolved_path):
                    launch_path = resolved_path

        has_image_extension = any(cover_path.lower().endswith(ext) for ext in COVER_IMAGE_EXTENSIONS)

        if has_image_extension and not os.path.isfile(cover_path):
            suffix = os.path.splitext(cover_path)[1].lower() or ".png"
            fd, local_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            os.unlink(local_path)

            download_url = cover_path if cover_path.startswith(('http://', 'https://')) else f'https://{cover_path}'
            self.downloader.download_async(
                url=download_url,
                local_path=local_path,
                timeout=10,
                callback=self.handleDownloadedCover
            )
            self.coverPreview.setText(_("Downloading cover…"))
        elif cover_path and os.path.isfile(cover_path):
            if set_animated_cover(self.coverPreview, cover_path, 250, 250):
                return
            pixmap = QPixmap(cover_path)
            if not pixmap.isNull():
                self.coverPreview.setPixmap(pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio))
            else:
                self.coverPreview.setText(_("Invalid image"))
        elif os.path.isfile(launch_path) and launch_path.lower().endswith(".exe"):
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            tmp.close()
            if generate_thumbnail(launch_path, tmp.name, size=128):
                pixmap = QPixmap(tmp.name)
                self.coverPreview.setPixmap(pixmap)
            os.unlink(tmp.name)
        elif os.path.isfile(launch_path):
            file_icon_name = THEMED_LAUNCH_ICON_NAMES.get(os.path.splitext(launch_path)[1].lower())
            file_icon_path = theme_manager.get_icon(file_icon_name, as_path=True) if file_icon_name else ""
            pixmap = QPixmap(file_icon_path) if isinstance(file_icon_path, str) and file_icon_path else QPixmap()
            if not pixmap.isNull():
                self.coverPreview.setPixmap(pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio))
            else:
                self.coverPreview.setText(_("No cover selected"))
        else:
            self.coverPreview.setText(_("No cover selected"))

    def getDesktopEntryData(self):
        """Returns the .desktop content and save path."""
        exe_path = self.exeEdit.text().strip()
        name = self.nameEdit.text().strip()
        launch_path = exe_path

        if not exe_path or not os.path.isfile(exe_path):
            return None, None

        if not name:
            return None, None

        if exe_path.lower().endswith(DISC_IMAGE_EXTENSIONS):
            parent_widget = cast("MainWindow | None", self.parentWidget())
            if not parent_widget or not hasattr(parent_widget, "resolve_launch_file_path"):
                return None, None
            resolved_path = parent_widget.resolve_launch_file_path(exe_path)
            if not resolved_path or not os.path.isfile(resolved_path):
                return None, None
            launch_path = resolved_path

        result = create_desktop_file(exe_path, name)
        if not result:
            return None, None
        desktop_entry, desktop_path, icon_path = result

        file_icon_name = THEMED_LAUNCH_ICON_NAMES.get(os.path.splitext(launch_path)[1].lower())
        file_icon_path = theme_manager.get_icon(file_icon_name, as_path=True) if file_icon_name else ""
        if get_custom_icon_path(exe_path):
            return desktop_entry, desktop_path
        if not self.last_cover_path and file_icon_path:
            desktop_entry = desktop_entry.replace(f"Icon={icon_path}\n", f"Icon={file_icon_path}\n")
        elif not self.last_cover_path and not generate_thumbnail(launch_path, icon_path, size=128):
            logger.error(f"Failed to generate thumbnail from exe: {launch_path}")
            desktop_entry = desktop_entry.replace(f"Icon={icon_path}\n", "Icon=\n")

        return desktop_entry, desktop_path
