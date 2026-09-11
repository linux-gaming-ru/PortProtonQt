import os
import glob
import shutil
import tempfile
from typing import TYPE_CHECKING
from PySide6.QtWidgets import QMessageBox, QDialog, QMenu, QLineEdit, QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import QUrl, QPoint, QObject, Signal, Qt, QStandardPaths, QTimer, QSize, QProcess
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence
from portprotonqt.localization import _
from portprotonqt.config import (
    create_desktop_file,
    extract_exec_target_path,
    favorites_config,
    favorites_folders_config,
    get_custom_data_dir_name,
    parse_desktop_entry,
    resolve_custom_data_dir,
)
from portprotonqt.steam_api import (
    add_to_steam,
    fetch_client_icon_async,
    get_steam_home,
    get_steam_libs,
    is_game_in_steam,
    remove_from_steam,
    safe_vdf_load,
)
from portprotonqt.icon_extractor import generate_thumbnail
from portprotonqt.dialogs import AddGameDialog
from portprotonqt.dialogs.base import DraggableDialog
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.logger import get_logger
from portprotonqt.virtual_keyboard import VirtualKeyboard
from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS

logger = get_logger(__name__)

if TYPE_CHECKING:
    from portprotonqt.game_card import GameCard

class ContextMenuSignals(QObject):
    """Signals for thread-safe UI updates from worker threads."""
    show_warning_dialog = Signal(str, str)
    show_info_dialog = Signal(str, str)


class FolderNameDialog(DraggableDialog):
    """Dialog with typed keyboard attribute for folder name input."""
    keyboard: VirtualKeyboard


class ContextMenuManager:
    """Manages context menu actions for game management in PortProtonQt."""

    def __init__(self, parent, portproton_location, theme, game_library_manager):
        """
        Initialize the ContextMenuManager.

        Args:
            parent: The parent widget (MainWindow instance).
            portproton_location: Path to the PortProton directory.
            theme: The current theme object.
            load_games_callback: Callback to reload games list.
            update_game_grid_callback: Callback to update the game grid UI.
        """
        self.parent = parent
        self.portproton_location = portproton_location
        self.theme = theme
        self.theme_manager = ThemeManager()
        self.game_library_manager = game_library_manager
        self.update_game_grid = game_library_manager.update_game_grid
        self.signals = ContextMenuSignals()
        self.signals.show_warning_dialog.connect(
            self._show_warning_dialog,
            Qt.ConnectionType.QueuedConnection
        )
        self.signals.show_info_dialog.connect(
            self._show_info_dialog,
            Qt.ConnectionType.QueuedConnection
        )

    @staticmethod
    def _remove_old_cover_files(custom_folder: str) -> None:
        """Remove stale cover files before saving a new cover."""
        for cover_ext in COVER_IMAGE_EXTENSIONS:
            old_cover_path = os.path.join(custom_folder, f"cover{cover_ext}")
            try:
                os.remove(old_cover_path)
            except FileNotFoundError:
                pass

    def _show_warning_dialog(self, title: str, message: str):
        """Show a warning dialog in the main thread."""
        logger.debug("Displaying warning dialog: %s - %s", title, message)
        QMessageBox.warning(self.parent, title, message)

    def _show_info_dialog(self, title: str, message: str):
        """Show an info dialog in the main thread."""
        logger.debug("Displaying info dialog: %s - %s", title, message)
        QMessageBox.information(self.parent, title, message)

    def _check_portproton(self):
        """Check if PortProton is available."""
        if self.portproton_location is None:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("PortProton directory not found")
            )
            return False
        return True

    def _is_game_running(self, game_card) -> bool:
        """
        Check if the game associated with the game_card is currently running.

        Args:
            game_card: The GameCard instance containing game data.

        Returns:
            bool: True if the game is running, False otherwise.
        """
        if game_card.game_source == "steam":
            return False
        exec_line = self._get_exec_line(game_card.name, game_card.exec_line)
        if not exec_line:
            return False
        exe_path = self._parse_exe_path(exec_line, game_card.name)
        if not exe_path:
            return False
        current_exe = os.path.basename(exe_path)

        return hasattr(self.parent, 'target_exe') and self.parent.target_exe == current_exe

    def show_file_explorer_context_menu(self, file_explorer, pos):
        """Shows the context menu for a file or folder in FileExplorer."""
        try:
            item = file_explorer.file_list.itemAt(pos)
            if not item:
                logger.debug("No item selected at position %s", pos)
                return

            # Ensure the item is visually selected
            file_explorer.file_list.setCurrentItem(item)
            file_explorer.handle_item_click(item)

            selected = item.text()
            if selected in ("../", "./"):
                return

            is_folder = selected.endswith("/")
            full_path = os.path.normpath(os.path.join(file_explorer.current_path, selected.rstrip("/")))

            menu = QMenu(file_explorer)
            menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            menu.setStyleSheet(self.theme.CONTEXT_MENU_STYLE)
            menu.setParent(file_explorer, Qt.WindowType.Popup)  # Set transientParent for Wayland

            if is_folder:
                favorite_folders = favorites_folders_config.get_folders()
                is_favorite = full_path in favorite_folders
                action_text = _("Remove from Favorites") if is_favorite else _("Add to Favorites")
                favorite_action = menu.addAction(self._get_safe_icon("star" if is_favorite else "star_full"), action_text)
                favorite_action.triggered.connect(lambda: self.toggle_favorite_folder(file_explorer, full_path, not is_favorite))

            create_folder_action = menu.addAction(self._get_safe_icon("folder"), _("Create Folder"))
            create_folder_action.triggered.connect(
                lambda: self.create_folder(file_explorer, file_explorer.current_path)
            )

            if is_folder:
                rename_action = menu.addAction(self._get_safe_icon("edit"), _("Rename Folder"))
                rename_action.triggered.connect(lambda: self.rename_folder(file_explorer, full_path))
                delete_action = menu.addAction(self._get_safe_icon("delete"), _("Delete Folder"))
                delete_action.triggered.connect(lambda: self.delete_folder(file_explorer, full_path))
            else:
                rename_action = menu.addAction(self._get_safe_icon("edit"), _("Rename File"))
                rename_action.triggered.connect(lambda: self.rename_file(file_explorer, full_path))
                delete_action = menu.addAction(self._get_safe_icon("delete"), _("Delete File"))
                delete_action.triggered.connect(lambda: self.delete_file(file_explorer, full_path))

            # Disconnect file_list signals to prevent navigation during menu interaction
            try:
                file_explorer.file_list.itemClicked.disconnect(file_explorer.handle_item_click)
                file_explorer.file_list.itemDoubleClicked.disconnect(file_explorer.handle_item_double_click)
            except TypeError:
                pass  # Signals may not be connected

            # Reconnect signals after menu closes
            def reconnect_signals():
                try:
                    file_explorer.file_list.itemClicked.connect(file_explorer.handle_item_click)
                    file_explorer.file_list.itemDoubleClicked.connect(file_explorer.handle_item_double_click)
                except Exception as e:
                    logger.error("Error reconnecting file list signals: %s", e)

            menu.aboutToHide.connect(reconnect_signals)

            # Set focus to the first menu item
            actions = menu.actions()
            if actions:
                menu.setActiveAction(actions[0])

            # Map local position to global for menu display
            global_pos = file_explorer.file_list.mapToGlobal(pos)
            menu.exec(global_pos)
        except Exception as e:
            logger.error("Error displaying file explorer context menu: %s", e)

    def toggle_favorite_folder(self, file_explorer, folder_path, add):
        """Adds or removes a folder from favorites."""
        favorite_folders = favorites_folders_config.get_folders()
        if add:
            if folder_path not in favorite_folders:
                favorite_folders.append(folder_path)
                favorites_folders_config.set_folders(favorite_folders)
                logger.info("Added folder to favorites: %s", folder_path)
        else:
            if folder_path in favorite_folders:
                favorite_folders.remove(folder_path)
                favorites_folders_config.set_folders(favorite_folders)
                logger.info("Removed folder from favorites: %s", folder_path)
        file_explorer.update_drives_list()

    def _prompt_folder_name(self, parent, title: str, label: str, value: str = "") -> str | None:
        """Prompt folder name from user and return it if valid."""
        dialog = FolderNameDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        parent_width = parent.width() if parent else 800
        dialog_width = min(640, max(460, parent_width - 80))
        dialog.setFixedWidth(dialog_width)
        dialog.setMinimumHeight(320)
        main_style = getattr(self.theme, "MAIN_WINDOW_STYLE", "")
        message_box_style = getattr(self.theme, "MESSAGE_BOX_STYLE", "")
        dialog.setStyleSheet(main_style + message_box_style)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        panel = QFrame(dialog)
        panel.setObjectName("folderNamePanel")
        panel.setStyleSheet(message_box_style)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        label_widget = QLabel(label, panel)
        line_edit = CustomLineEdit(panel, theme=self.theme)
        line_edit.setText(value)
        if hasattr(self.theme, "LINE_EDIT_STYLE"):
            line_edit.setStyleSheet(self.theme.LINE_EDIT_STYLE)
        line_edit.setFocus()

        buttons_layout = QHBoxLayout()
        ok_button = QPushButton(_("OK"), panel)
        cancel_button = QPushButton(_("Cancel"), panel)
        if hasattr(self.theme, "ACTION_BUTTON_STYLE"):
            ok_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        line_edit.returnPressed.connect(dialog.accept)

        panel_layout.addWidget(label_widget)
        panel_layout.addWidget(line_edit)
        buttons_layout.addWidget(ok_button)
        buttons_layout.addWidget(cancel_button)
        panel_layout.addLayout(buttons_layout)

        layout.addWidget(panel)
        layout.addStretch()

        keyboard = VirtualKeyboard(dialog, theme=self.theme, button_width=40)
        dialog.keyboard = keyboard
        keyboard.set_slide_animation_enabled(True)
        keyboard.hide()
        dialog.finished.connect(lambda _: keyboard.hide())

        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._restore_file_explorer_focus(parent)

        if not accepted:
            return None
        folder_name = line_edit.text().strip()
        if not folder_name:
            self._show_warning_dialog(_("Error"), _("Folder name cannot be empty"))
            self._restore_file_explorer_focus(parent)
            return None
        if folder_name in {".", ".."} or os.path.basename(folder_name) != folder_name:
            self._show_warning_dialog(_("Error"), _("Invalid folder name"))
            self._restore_file_explorer_focus(parent)
            return None
        return folder_name

    def _restore_file_explorer_focus(self, parent) -> None:
        """Restore focus to FileExplorer after modal dialogs."""
        parent.activateWindow()
        parent.setFocus(Qt.FocusReason.OtherFocusReason)
        if hasattr(parent, "file_list") and parent.file_list:
            parent.file_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def create_folder(self, file_explorer, parent_path: str | None = None) -> None:
        """Create a new folder in the current directory."""
        folder_name = self._prompt_folder_name(file_explorer, _("Create Folder"), _("Folder Name:"))
        if not folder_name:
            return
        target_path = os.path.join(parent_path or file_explorer.current_path, folder_name)
        if os.path.exists(target_path):
            self.signals.show_warning_dialog.emit(_("Error"), _("Folder already exists: {folder_name}").format(folder_name=folder_name))
            return
        try:
            os.mkdir(target_path)
            file_explorer.update_file_list()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to create folder: {error}").format(error=str(e))
            )

    def rename_folder(self, file_explorer, folder_path: str) -> None:
        """Rename selected folder."""
        current_name = os.path.basename(folder_path)
        new_name = self._prompt_folder_name(file_explorer, _("Rename Folder"), _("New Folder Name:"), current_name)
        if not new_name or new_name == current_name:
            return
        target_path = os.path.join(os.path.dirname(folder_path), new_name)
        if os.path.exists(target_path):
            self.signals.show_warning_dialog.emit(_("Error"), _("Folder already exists: {folder_name}").format(folder_name=new_name))
            return
        try:
            os.rename(folder_path, target_path)
            favorite_folders = favorites_folders_config.get_folders()
            if folder_path in favorite_folders:
                favorite_folders.remove(folder_path)
                favorite_folders.append(target_path)
                favorites_folders_config.set_folders(favorite_folders)
            file_explorer.update_file_list()
            file_explorer.update_drives_list()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to rename folder: {error}").format(error=str(e))
            )

    def delete_folder(self, file_explorer, folder_path: str) -> None:
        """Delete selected folder after confirmation."""
        folder_name = os.path.basename(folder_path)
        msg_box = QMessageBox(file_explorer)
        msg_box.setWindowTitle(_("Confirm Deletion"))
        msg_box.setText(
            _("Are you sure you want to delete folder '{folder_name}'? This action cannot be undone.")
            .format(folder_name=folder_name)
        )
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(folder_path)
            favorite_folders = favorites_folders_config.get_folders()
            if folder_path in favorite_folders:
                favorite_folders.remove(folder_path)
                favorites_folders_config.set_folders(favorite_folders)
            file_explorer.update_file_list()
            file_explorer.update_drives_list()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to delete folder: {error}").format(error=str(e))
            )

    def delete_file(self, file_explorer, file_path: str) -> None:
        """Delete selected file after confirmation."""
        file_name = os.path.basename(file_path)
        msg_box = QMessageBox(file_explorer)
        msg_box.setWindowTitle(_("Confirm Deletion"))
        msg_box.setText(
            _("Are you sure you want to delete file '{file_name}'? This action cannot be undone.")
            .format(file_name=file_name)
        )
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(file_path)
            file_explorer.update_file_list()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to delete file: {error}").format(error=str(e))
            )

    def rename_file(self, file_explorer, file_path: str) -> None:
        """Rename selected file."""
        current_name = os.path.basename(file_path)
        new_name = self._prompt_folder_name(file_explorer, _("Rename File"), _("New File Name:"), current_name)
        if not new_name or new_name == current_name:
            return
        target_path = os.path.join(os.path.dirname(file_path), new_name)
        if os.path.exists(target_path):
            self.signals.show_warning_dialog.emit(_("Error"), _("File already exists: {file_name}").format(file_name=new_name))
            return
        try:
            os.rename(file_path, target_path)
            file_explorer.update_file_list()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to rename file: {error}").format(error=str(e))
            )

    def _get_safe_icon(self, icon_name: str) -> QIcon:
        """Returns a QIcon, ensuring it is valid."""
        icon_path = self.theme_manager.get_icon(icon_name, as_path=True)
        if not isinstance(icon_path, str) or not os.path.exists(icon_path):
            return QIcon()

        icon = QIcon()
        normal_path = self._get_colored_menu_icon_path(icon_name, None) or icon_path
        icon.addFile(normal_path, QSize(), QIcon.Mode.Normal)
        active_path = (
            self._get_colored_menu_icon_path(icon_name, "hover")
            or normal_path
        )
        icon.addFile(active_path, QSize(), QIcon.Mode.Active)
        icon.addFile(active_path, QSize(), QIcon.Mode.Selected)
        return icon

    def _get_colored_menu_icon_path(self, icon_name: str, state: str | None) -> str | None:
        colors = getattr(self.theme, "ICON_COLORS", {})
        if not isinstance(colors, dict):
            return None

        keys = []
        if state:
            keys.extend((f"{icon_name}_{state}", f"*_{state}"))
        keys.append(icon_name)

        for key in keys:
            color = colors.get(key)
            if isinstance(color, str):
                return self.theme_manager.get_colored_icon_path(icon_name, color)
        return None

    def show_context_menu(self, game_card, pos: QPoint):
        """
        Show the context menu for a game card at the specified position.

        Args:
            game_card: The GameCard instance requesting the context menu.
            pos: The position (in widget coordinates) where the menu should appear.
        """
        menu = QMenu(self.parent)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setStyleSheet(self.theme.CONTEXT_MENU_STYLE)

        # For non-Steam games, check if exe exists
        if game_card.game_source == "portproton":
            exec_line = self._get_exec_line(game_card.name, game_card.exec_line)
            exe_path = self._parse_exe_path(exec_line, game_card.name) if exec_line else None
            if not exe_path:
                # Show only "Delete from PortProton" if no valid exe
                delete_action = menu.addAction(self._get_safe_icon("delete"), _("Delete from PortProton"))
                delete_action.triggered.connect(lambda: self.delete_game(game_card.name, game_card.exec_line))
                menu.popup(game_card.mapToGlobal(pos))
                return

        # Normal menu for games with valid exe or from Steam
        is_uninstalled_store_game = (
            game_card.game_source in ("gog", "egs")
            and game_card.exec_line.startswith(("gog://install/", "egs://install/"))
        )
        is_running = self._is_game_running(game_card)
        if not is_uninstalled_store_game:
            action_text = _("Stop Game") if is_running else _("Launch Game")
            action_icon = "stop" if is_running else "play"
            launch_action = menu.addAction(self._get_safe_icon(action_icon), action_text)
            launch_action.triggered.connect(
                lambda: self._launch_game(game_card)
            )

        favorites = favorites_config.get_games()
        is_favorite = game_card.name in favorites
        icon_name = "star_full" if is_favorite else "star"
        text = _("Remove from Favorites") if is_favorite else _("Add to Favorites")
        favorite_action = menu.addAction(self._get_safe_icon(icon_name), text)
        favorite_action.triggered.connect(lambda: self.toggle_favorite(game_card, not is_favorite))

        if game_card.game_source == "gog":
            game = {
                "app_id": str(game_card.appid),
                "title": game_card.name,
                "cover": game_card.cover_path,
            }
            if game_card.exec_line.startswith("gog://launch/"):
                repair_action = menu.addAction(
                    self._get_safe_icon("update"), _("Repair")
                )
                repair_action.triggered.connect(
                    lambda: self.parent._repair_gog_game(game)
                )
                desktop_dir = QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.DesktopLocation
                )
                desktop_path = self._get_shortcut_path(
                    game_card.name, desktop_dir
                )
                desktop_exists = os.path.exists(desktop_path)
                desktop_action = menu.addAction(
                    self._get_safe_icon("delete" if desktop_exists else "desktop"),
                    _("Remove from Desktop") if desktop_exists else _("Add to Desktop"),
                )
                desktop_action.triggered.connect(
                    lambda: self.remove_from_desktop(game_card.name)
                    if desktop_exists
                    else self.add_to_desktop(game_card.name, game_card.exec_line)
                )
                menu_path = self._get_menu_shortcut_path(game_card.name)
                menu_exists = os.path.exists(menu_path)
                menu_action = menu.addAction(
                    self._get_safe_icon("delete" if menu_exists else "menu"),
                    _("Remove from Menu") if menu_exists else _("Add to Menu"),
                )
                menu_action.triggered.connect(
                    lambda: self.remove_from_menu(game_card.name)
                    if menu_exists
                    else self.add_to_menu(game_card.name, game_card.exec_line)
                )
                delete_action = menu.addAction(
                    self._get_safe_icon("delete"), _("Delete")
                )
                delete_action.triggered.connect(
                    lambda: self.parent._delete_gog_game(game)
                )
            else:
                import_action = menu.addAction(
                    self._get_safe_icon("folder"), _("Import")
                )
                import_action.triggered.connect(
                    lambda: self.parent._import_gog_game(game)
                )

        if game_card.game_source == "egs":
            app_id = str(game_card.appid)
            if game_card.exec_line.startswith("egs://launch/"):
                desktop_dir = QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.DesktopLocation
                )
                desktop_path = self._get_shortcut_path(game_card.name, desktop_dir)
                desktop_exists = os.path.exists(desktop_path)
                desktop_action = menu.addAction(
                    self._get_safe_icon("delete" if desktop_exists else "desktop"),
                    _("Remove from Desktop") if desktop_exists else _("Add to Desktop"),
                )
                desktop_action.triggered.connect(
                    lambda: self.remove_from_desktop(game_card.name)
                    if desktop_exists
                    else self.add_to_desktop(game_card.name, game_card.exec_line)
                )
                menu_path = self._get_menu_shortcut_path(game_card.name)
                menu_exists = os.path.exists(menu_path)
                menu_action = menu.addAction(
                    self._get_safe_icon("delete" if menu_exists else "menu"),
                    _("Remove from Menu") if menu_exists else _("Add to Menu"),
                )
                menu_action.triggered.connect(
                    lambda: self.remove_from_menu(game_card.name)
                    if menu_exists
                    else self.add_to_menu(game_card.name, game_card.exec_line)
                )
                update_action = menu.addAction(
                    self._get_safe_icon("update"), _("Update")
                )
                update_action.triggered.connect(
                    lambda: self.parent._update_egs_game(app_id)
                )
                repair_action = menu.addAction(
                    self._get_safe_icon("update"), _("Repair")
                )
                repair_action.triggered.connect(
                    lambda: self.parent._repair_egs_game(app_id)
                )
                eos_enabled = self.parent._is_egs_overlay_enabled(app_id)
                eos_action = menu.addAction(
                    self._get_safe_icon("update"),
                    _("Disable EOS Overlay")
                    if eos_enabled else _("Enable EOS Overlay"),
                )
                eos_action.triggered.connect(
                    lambda: self.parent._enable_egs_overlay(app_id)
                )
                delete_action = menu.addAction(
                    self._get_safe_icon("delete"), _("Delete")
                )
                delete_action.triggered.connect(
                    lambda: self.parent._delete_egs_game(app_id)
                )
            else:
                import_action = menu.addAction(
                    self._get_safe_icon("folder"), _("Import")
                )
                import_action.triggered.connect(
                    lambda: self.parent._import_egs_game(app_id)
                )

        if game_card.game_source == "steam":
            desktop_dir = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DesktopLocation
            )
            desktop_path = self._get_steam_shortcut_path(game_card.name, desktop_dir)
            icon_name = "delete" if os.path.exists(desktop_path) else "desktop"
            text = _("Remove from Desktop") if os.path.exists(desktop_path) else _("Add to Desktop")
            desktop_action = menu.addAction(self._get_safe_icon(icon_name), text)
            desktop_action.triggered.connect(
                lambda: self.remove_steam_from_desktop(game_card.name)
                if os.path.exists(desktop_path)
                else self.add_steam_to_desktop(game_card.name, game_card.appid)
            )
            menu_path = self._get_steam_menu_shortcut_path(game_card.name)
            icon_name = "delete" if os.path.exists(menu_path) else "menu"
            text = _("Remove from Menu") if os.path.exists(menu_path) else _("Add to Menu")
            menu_action = menu.addAction(self._get_safe_icon(icon_name), text)
            menu_action.triggered.connect(
                lambda: self.remove_steam_from_menu(game_card.name)
                if os.path.exists(menu_path)
                else self.add_steam_to_menu(game_card.name, game_card.appid)
            )
            open_folder_action = menu.addAction(self._get_safe_icon("search"), _("Open Game Folder"))
            open_folder_action.triggered.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self.open_steam_game_folder(game_card.appid)
                )
            )
            edit_action = menu.addAction(self._get_safe_icon("edit"), _("Edit Shortcut"))
            edit_action.triggered.connect(
                lambda: self.edit_game_shortcut(
                    game_card.name,
                    game_card.exec_line,
                    game_card.cover_path,
                    game_card.appid,
                )
            )

        if game_card.game_source == "portproton":
            desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            desktop_path = self._get_shortcut_path(game_card.name, desktop_dir)
            icon_name = "delete" if os.path.exists(desktop_path) else "desktop"
            text = _("Remove from Desktop") if os.path.exists(desktop_path) else _("Add to Desktop")
            desktop_action = menu.addAction(self._get_safe_icon(icon_name), text)
            desktop_action.triggered.connect(
                lambda: self.remove_from_desktop(game_card.name)
                if os.path.exists(desktop_path)
                else self.add_to_desktop(game_card.name, game_card.exec_line)
            )
            edit_action = menu.addAction(self._get_safe_icon("edit"), _("Edit Shortcut"))
            edit_action.triggered.connect(
                lambda: self.edit_game_shortcut(game_card.name, game_card.exec_line, game_card.cover_path)
            )
            delete_action = menu.addAction(self._get_safe_icon("delete"), _("Delete from PortProton"))
            delete_action.triggered.connect(lambda: self.delete_game(game_card.name, game_card.exec_line))
            open_folder_action = menu.addAction(self._get_safe_icon("search"), _("Open Game Folder"))
            open_folder_action.triggered.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self.open_game_folder(game_card.name, game_card.exec_line)
                )
            )
            menu_path = self._get_menu_shortcut_path(game_card.name)
            icon_name = "delete" if os.path.exists(menu_path) else "menu"
            text = _("Remove from Menu") if os.path.exists(menu_path) else _("Add to Menu")
            menu_action = menu.addAction(self._get_safe_icon(icon_name), text)
            menu_action.triggered.connect(
                lambda: self.remove_from_menu(game_card.name)
                if os.path.exists(menu_path)
                else self.add_to_menu(game_card.name, game_card.exec_line)
            )
            if get_steam_home() is not None:
                is_in_steam = is_game_in_steam(game_card.name)
                steam_icon_name = "delete" if is_in_steam else "menu_steam"
                steam_text = _("Remove from Steam") if is_in_steam else _("Add to Steam")
                steam_action = menu.addAction(self._get_safe_icon(steam_icon_name), steam_text)
                steam_action.triggered.connect(
                    lambda: self.remove_from_steam(game_card.name, game_card.exec_line, game_card.game_source)
                    if is_in_steam
                    else self.add_to_steam(game_card.name, game_card.exec_line, game_card.cover_path)
                )

        # Set focus to the first menu item
        actions = menu.actions()
        if actions:
            menu.setActiveAction(actions[0])

            menu.popup(game_card.mapToGlobal(pos))

    def _launch_game(self, game_card):
        """
        Launch or stop a game based on its current state.

        Args:
            game_card: The GameCard instance containing game data.
        """
        if not self._check_portproton():
            return

        # Check if the game is running
        if self._is_game_running(game_card):
            if not (hasattr(self.parent, "stop_running_game") and self.parent.stop_running_game()):
                self.signals.show_warning_dialog.emit(_("Error"), _("Failed to stop game"))
            return

        exec_line = self._get_exec_line(game_card.name, game_card.exec_line)
        if not exec_line:
            return
        self.parent.toggleGame(exec_line, game_name=game_card.name)

    def toggle_favorite(self, game_card, add: bool):
        """
        Toggle the favorite status of a game and update its icon.

        Args:
            game_card: The GameCard instance to toggle.
            add: True to add to favorites, False to remove.
        """
        favorites = favorites_config.get_games()
        if add and game_card.name not in favorites:
            favorites.append(game_card.name)
            game_card.is_favorite = True
        elif not add and game_card.name in favorites:
            favorites.remove(game_card.name)
            game_card.is_favorite = False
        else:
            return
        favorites_config.set_games(favorites)
        game_card.update_favorite_icon()

    def _get_desktop_path(self, game_name):
        """Construct the .desktop file path, trying direct and fallback matching."""
        desktop_path = os.path.join(self.portproton_location, f"{game_name}.desktop")
        if os.path.exists(desktop_path):
            return desktop_path

        sanitized_name = game_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        desktop_path = os.path.join(self.portproton_location, f"{sanitized_name}.desktop")
        if os.path.exists(desktop_path):
            return desktop_path

        normalized_game_name = "".join(ch for ch in game_name.lower() if ch.isalnum())
        desktop_files = glob.glob(os.path.join(self.portproton_location, "*.desktop"))

        if normalized_game_name:
            xdg_data_home = os.getenv(
                "XDG_DATA_HOME",
                os.path.join(os.path.expanduser("~"), ".local", "share")
            )
            custom_roots = [os.path.join(xdg_data_home, "PortProtonQt", "custom_data")]
            for custom_root in custom_roots:
                if not os.path.isdir(custom_root):
                    continue
                metadata_files = glob.glob(
                    os.path.join(custom_root, "**", "metadata.txt"),
                    recursive=True,
                )
                for metadata_path in metadata_files:
                    try:
                        metadata_name = ""
                        with open(metadata_path, encoding="utf-8") as metadata_file:
                            for line in metadata_file:
                                if line.startswith("name="):
                                    metadata_name = line[5:].strip()
                                    break
                        if not metadata_name:
                            continue
                        normalized_metadata_name = "".join(
                            ch for ch in metadata_name.lower() if ch.isalnum()
                        )
                        if normalized_metadata_name != normalized_game_name:
                            continue
                        script_name = os.path.basename(os.path.dirname(metadata_path))
                        for file_path in desktop_files:
                            entry = parse_desktop_entry(file_path)
                            if not entry:
                                continue
                            exec_line = entry.get("Exec", entry.get("exec", ""))
                            if script_name.lower() in exec_line.lower():
                                return file_path
                    except OSError:
                        continue

        for file_path in desktop_files:
            entry = parse_desktop_entry(file_path)
            if entry:
                entry_name = entry.get("Name", entry.get("name", "")).strip()
                normalized_entry_name = "".join(ch for ch in entry_name.lower() if ch.isalnum())
                if normalized_entry_name and (
                    normalized_entry_name == normalized_game_name
                    or normalized_entry_name in normalized_game_name
                    or normalized_game_name in normalized_entry_name
                ):
                    return file_path

            stem = os.path.splitext(os.path.basename(file_path))[0]
            normalized_stem = "".join(ch for ch in stem.lower() if ch.isalnum())
            if normalized_stem and (
                normalized_stem == normalized_game_name
                or normalized_stem in normalized_game_name
                or normalized_game_name in normalized_stem
            ):
                return file_path

        return desktop_path

    def _get_shortcut_path(self, game_name: str, target_dir: str) -> str:
        """Return target shortcut path using the source .desktop filename."""
        desktop_path = self._get_desktop_path(game_name)
        if os.path.exists(desktop_path):
            return os.path.join(target_dir, os.path.basename(desktop_path))
        return os.path.join(target_dir, f"{game_name}.desktop")

    def _get_steam_shortcut_path(self, game_name: str, target_dir: str) -> str:
        """Return sanitized Steam shortcut path in target directory."""
        safe_name = (
            game_name.replace("/", "_").replace(":", "_").replace("\0", "_").strip()
        )
        if not safe_name:
            safe_name = "Steam Game"
        return os.path.join(target_dir, f"{safe_name}.desktop")

    @staticmethod
    def _get_applications_dir() -> str:
        """Return XDG applications directory."""
        data_home = os.getenv(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        return os.path.join(data_home, "applications")

    def _update_desktop_database(self) -> None:
        """Update the desktop entry database asynchronously."""
        applications_dir = self._get_applications_dir()
        result = QProcess.startDetached(
            "update-desktop-database", [applications_dir]
        )
        started = result[0] if isinstance(result, tuple) else result
        if not started:
            logger.warning(
                "Failed to start desktop database update for %s",
                applications_dir,
            )

    def _get_menu_shortcut_path(self, game_name: str) -> str:
        """Return PortProton shortcut path in the applications directory."""
        return self._get_shortcut_path(game_name, self._get_applications_dir())

    def _get_steam_menu_shortcut_path(self, game_name: str) -> str:
        """Return Steam shortcut path in the applications directory."""
        return self._get_steam_shortcut_path(game_name, self._get_applications_dir())

    def _get_exec_line(self, game_name, exec_line):
        """Retrieve and validate exec_line from .desktop file if necessary."""
        if exec_line and exec_line.strip() != "full":
            return exec_line
        desktop_path = self._get_desktop_path(game_name)
        if os.path.exists(desktop_path):
            try:
                entry = parse_desktop_entry(desktop_path)
                if entry:
                    exec_line = entry.get("Exec", entry.get("exec", "")).strip()
                    if not exec_line:
                        self.signals.show_warning_dialog.emit(
                            _("Error"),
                            _("No executable command found in .desktop file for '{game_name}'").format(game_name=game_name)
                        )
                        return None
                else:
                    self.signals.show_warning_dialog.emit(
                        _("Error"),
                        _("Failed to parse .desktop file for '{game_name}'").format(game_name=game_name)
                    )
                    return None
            except Exception as e:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _("Error reading .desktop file: {error}").format(error=str(e))
                )
                return None
        else:
            for file in glob.glob(os.path.join(self.portproton_location, "*.desktop")):
                entry = parse_desktop_entry(file)
                if entry:
                    exec_line = entry.get("Exec", entry.get("exec", "")).strip()
                    if exec_line:
                        return exec_line
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("No .desktop file found for '{game_name}'").format(game_name=game_name)
            )
            return None
        return exec_line

    def _parse_exe_path(self, exec_line: str, game_name: str) -> str | None:
        """Parse the executable path from exec_line."""
        try:
            exe_path = extract_exec_target_path(exec_line)
            if not exe_path:
                logger.debug("Executable not found in command for game '%s': %s", game_name, exec_line)
                return None
            if not exe_path or not os.path.exists(exe_path):
                logger.debug("Executable not found for game '%s': %s", game_name, exe_path or "None")
                return None
            return exe_path
        except Exception as e:
            logger.debug("Error parsing executable for game '%s': %s", game_name, e)
            return None

    def _remove_file(self, file_path, error_message, success_message, game_name, location=""):
        """Remove a file and handle errors."""
        try:
            os.remove(file_path)
            return True
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _(error_message).format(game_name=game_name, location=location, error=str(e))
            )
            return False

    def _get_installed_shortcut_paths(self, game_name: str) -> list[str]:
        """Return menu and desktop shortcut paths for a PortProton game."""
        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        return [
            self._get_menu_shortcut_path(game_name),
            self._get_shortcut_path(game_name, desktop_dir),
        ]

    def _remove_installed_shortcuts(self, game_name: str, shortcut_paths: list[str]) -> None:
        """Remove existing menu and desktop shortcuts."""
        removed_paths = set()
        menu_shortcut_removed = False
        applications_dir = os.path.normpath(self._get_applications_dir())
        for shortcut_path in shortcut_paths:
            if shortcut_path in removed_paths or not os.path.exists(shortcut_path):
                continue
            removed_paths.add(shortcut_path)
            try:
                os.remove(shortcut_path)
                if os.path.dirname(os.path.normpath(shortcut_path)) == applications_dir:
                    menu_shortcut_removed = True
            except OSError as e:
                logger.warning("Failed to remove shortcut for '%s': %s", game_name, e)
        if menu_shortcut_removed:
            self._update_desktop_database()

    def _remove_statistics_entry(self, exe_path, game_name):
        """Remove statistics entry for exact executable path."""
        if not exe_path:
            return

        from portprotonqt.time_utils import get_statistics_path, remove_last_launch
        statistics_file = get_statistics_path()
        target_path = os.path.normpath(exe_path)
        exe_name = os.path.splitext(os.path.basename(target_path))[0]
        remove_last_launch(exe_name)
        if not os.path.exists(statistics_file):
            return

        kept_lines = []
        removed = False

        try:
            with open(statistics_file, encoding="utf-8") as f:
                for line in f:
                    token = line.strip().split(maxsplit=1)
                    if not token:
                        kept_lines.append(line)
                        continue
                    stat_path = os.path.normpath(token[0].replace("#@_@#", " "))
                    if stat_path == target_path:
                        removed = True
                        continue
                    kept_lines.append(line)

            if removed:
                with open(statistics_file, "w", encoding="utf-8") as f:
                    f.writelines(kept_lines)
                logger.info("Removed statistics entry for '%s' (%s)", game_name, exe_path)
        except OSError as e:
            logger.warning("Failed to clean statistics for '%s': %s", game_name, e)

    def _delete_game_without_confirm(self, game_name: str, exec_line: str) -> None:
        card_exec_line = exec_line
        if not self._check_portproton():
            return
        desktop_path = self._get_desktop_path(game_name)
        if not os.path.exists(desktop_path):
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("No .desktop file found for '{game_name}'").format(game_name=game_name)
            )
            return
        resolved_exec_line = self._get_exec_line(game_name, exec_line)
        if not resolved_exec_line:
            return
        shortcut_paths = self._get_installed_shortcut_paths(game_name)
        exe_path = extract_exec_target_path(resolved_exec_line)
        if not self._remove_file(
            desktop_path,
            _("Failed to delete .desktop file: {error}"),
            _("Deleted '{game_name}' successfully"),
            game_name
        ):
            return
        self._remove_installed_shortcuts(game_name, shortcut_paths)
        self._remove_statistics_entry(exe_path, game_name)
        if exe_path:
            xdg_data_home = os.getenv(
                "XDG_DATA_HOME",
                os.path.join(os.path.expanduser("~"), ".local", "share")
            )
            custom_root = os.path.join(xdg_data_home, "PortProtonQt", "custom_data")
            custom_folder = resolve_custom_data_dir(custom_root, exe_path)
            if os.path.exists(custom_folder):
                try:
                    shutil.rmtree(custom_folder)
                except OSError as e:
                    self.signals.show_warning_dialog.emit(
                        _("Error"),
                        _("Failed to delete custom data: {error}").format(error=str(e))
                    )

        self.game_library_manager.remove_game_incremental(game_name, card_exec_line or resolved_exec_line)

    def delete_game(self, game_name, exec_line):
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Deletion"))
        msg_box.setText(_("Are you sure you want to delete '{game_name}'? This will remove the .desktop file and custom data.").format(game_name=game_name))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._delete_game_without_confirm(game_name, exec_line)

    def add_game_incremental(self, game_data: tuple):
        """Add game after .desktop creation."""
        if not self._check_portproton():
            return
        # Assume game_data is built from new .desktop (name, desc, cover, etc.)
        self.game_library_manager.add_game_incremental(game_data)

    def add_to_menu(self, game_name, exec_line):
        """Add the game desktop entry to the XDG applications directory."""
        if not self._check_portproton():
            return
        is_store_uri = str(exec_line).startswith(("gog://launch/", "egs://launch/"))
        desktop_path = self._get_desktop_path(game_name)
        if not is_store_uri and not os.path.exists(desktop_path):
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("No .desktop file found for '{game_name}'").format(game_name=game_name)
            )
            return
        if not is_store_uri:
            exec_line = self._get_exec_line(game_name, exec_line)
            if not exec_line:
                return
            exec_line = self._parse_exe_path(exec_line, game_name)
            if not exec_line:
                return
        icon_source = None
        if is_store_uri:
            source, app_id = exec_line.split("://", 1)[0], str(exec_line).rsplit("/", 1)[-1]
            icon_source = getattr(self.parent, f"{source}_api").get_launch_target(app_id)
        shortcut = create_desktop_file(exec_line, game_name, icon_source)
        if not shortcut:
            return
        desktop_entry = shortcut[0]
        icon_path = shortcut[2]
        if icon_source and not os.path.exists(icon_path):
            if not generate_thumbnail(icon_source, icon_path, size=128):
                logger.error("Failed to generate thumbnail for game: %s", icon_source)
        applications_dir = self._get_applications_dir()
        os.makedirs(applications_dir, exist_ok=True)
        dest_path = self._get_menu_shortcut_path(game_name)
        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(desktop_entry)
            os.chmod(dest_path, 0o755)
            self._update_desktop_database()
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to add '{game_name}' to {location}: {error}").format(
                    game_name=game_name, location=_("Menu"), error=str(e)
                )
            )

    def remove_from_menu(self, game_name):
        """
        Removes the game from the menu by removing its .desktop file.

        Args:
            game_name: The display name of the game.
        """
        menu_path = self._get_menu_shortcut_path(game_name)
        if self._remove_file(
            menu_path,
            _("Failed to remove '{game_name}' from {location}: {error}"),
            _("Removed '{game_name}' from {location}"),
            game_name,
            location=_("Menu")
        ):
            self._update_desktop_database()

    def add_to_desktop(self, game_name, exec_line):
        """
        Add the game desktop entry to the user's Desktop folder.

        Args:
            game_name: The display name of the game.
            exec_line: The executable command line.
        """

        if not self._check_portproton():
            return
        is_store_uri = str(exec_line).startswith(("gog://launch/", "egs://launch/"))
        desktop_path = self._get_desktop_path(game_name)
        if not is_store_uri and not os.path.exists(desktop_path):
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("No .desktop file found for '{game_name}'").format(game_name=game_name)
            )
            return
        # Ensure icon exists
        if not is_store_uri:
            exec_line = self._get_exec_line(game_name, exec_line)
            if not exec_line:
                return
            exec_line = self._parse_exe_path(exec_line, game_name)
            if not exec_line:
                return
        icon_source = None
        if is_store_uri:
            source, app_id = exec_line.split("://", 1)[0], str(exec_line).rsplit("/", 1)[-1]
            icon_source = getattr(self.parent, f"{source}_api").get_launch_target(app_id)
        shortcut = create_desktop_file(exec_line, game_name, icon_source)
        if not shortcut:
            return
        desktop_entry = shortcut[0]
        icon_path = shortcut[2]
        thumbnail_source = icon_source or exec_line
        if icon_path != "applications-games" and not os.path.exists(icon_path):
            if not generate_thumbnail(thumbnail_source, icon_path, size=128):
                logger.error("Failed to generate thumbnail for game: %s", thumbnail_source)

        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        os.makedirs(desktop_dir, exist_ok=True)
        dest_path = self._get_shortcut_path(game_name, desktop_dir)
        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(desktop_entry)
            os.chmod(dest_path, 0o755)
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to add '{game_name}' to {location}: {error}").format(
                    game_name=game_name, location=_("Desktop"), error=str(e)
                )
            )

    def remove_from_desktop(self, game_name):
        """
        Removes the game from the Desktop folder by removing its .desktop file.

        Args:
            game_name: The display name of the game.
        """
        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        desktop_path = self._get_shortcut_path(game_name, desktop_dir)
        self._remove_file(
            desktop_path,
            _("Failed to remove '{game_name}' from {location}: {error}"),
            _("Removed '{game_name}' from {location}"),
            game_name,
            location=_("Desktop")
        )

    def _add_steam_shortcut(
        self,
        game_name: str,
        appid: int | str,
        shortcut_target: tuple[str, str],
    ) -> None:
        """Create a shortcut for an installed Steam game."""
        appid_str = str(appid).strip()
        if not appid_str.isdigit():
            logger.warning("Invalid Steam appid for desktop shortcut: %s", appid)
            return

        target_dir, location = shortcut_target
        os.makedirs(target_dir, exist_ok=True)
        dest_path = self._get_steam_shortcut_path(game_name, target_dir)
        display_name = game_name.replace("\n", " ").replace("\r", " ").strip()

        def write_shortcut(icon_path: str) -> None:
            icon = icon_path or "steam"
            desktop_entry = (
                "[Desktop Entry]\n"
                f"Name={display_name}\n"
                f"Comment={_('Play this game on Steam')}\n"
                f"Exec=xdg-open steam://rungameid/{appid_str}\n"
                "Terminal=false\n"
                "Type=Application\n"
                "Categories=Game;\n"
                "StartupNotify=true\n"
                f"Icon={icon}\n"
            )
            try:
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(desktop_entry)
                os.chmod(dest_path, 0o755)
                if os.path.normpath(target_dir) == os.path.normpath(
                    self._get_applications_dir()
                ):
                    self._update_desktop_database()
            except OSError as e:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _("Failed to add '{game_name}' to {location}: {error}").format(
                        game_name=game_name, location=location, error=str(e)
                    )
                )

        fetch_client_icon_async(appid_str, write_shortcut)

    def remove_gog_shortcuts(self, game_name: str) -> None:
        """Remove desktop and application menu shortcuts for a GOG game."""
        shortcut_paths = self._get_installed_shortcut_paths(game_name)
        self._remove_installed_shortcuts(game_name, shortcut_paths)

    def add_steam_to_desktop(self, game_name: str, appid: int | str) -> None:
        """Create a desktop shortcut for an installed Steam game."""
        desktop_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        self._add_steam_shortcut(game_name, appid, (desktop_dir, _("Desktop")))

    def remove_steam_from_desktop(self, game_name: str) -> None:
        """Remove a Steam game desktop shortcut."""
        desktop_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        desktop_path = self._get_steam_shortcut_path(game_name, desktop_dir)
        self._remove_file(
            desktop_path,
            _("Failed to remove '{game_name}' from {location}: {error}"),
            _("Removed '{game_name}' from {location}"),
            game_name,
            location=_("Desktop")
        )

    def add_steam_to_menu(self, game_name: str, appid: int | str) -> None:
        """Create an application menu shortcut for an installed Steam game."""
        applications_dir = self._get_applications_dir()
        self._add_steam_shortcut(game_name, appid, (applications_dir, _("Menu")))

    def remove_steam_from_menu(self, game_name: str) -> None:
        """Remove a Steam game application menu shortcut."""
        menu_path = self._get_steam_menu_shortcut_path(game_name)
        if self._remove_file(
            menu_path,
            _("Failed to remove '{game_name}' from {location}: {error}"),
            _("Removed '{game_name}' from {location}"),
            game_name,
            location=_("Menu")
        ):
            self._update_desktop_database()

    def _edit_steam_shortcut(self, game_name: str, appid: int | str, cover_path: str) -> None:
        appid_str = str(appid).strip()
        if not appid_str.isdigit():
            logger.warning("Invalid Steam appid for shortcut editing: %s", appid)
            return
        dialog = AddGameDialog(parent=self.parent, theme=self.theme, edit_mode=True,
                               game_name=game_name, cover_path=cover_path, steam_appid=appid_str)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dialog.nameEdit.text().strip()
        if not new_name:
            return
        selected_cover = dialog.coverEdit.text().strip()
        if not os.path.isfile(selected_cover) and dialog.last_cover_path and os.path.isfile(dialog.last_cover_path):
            selected_cover = dialog.last_cover_path
        xdg_data_home = os.getenv(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        game_dir = os.path.join(xdg_data_home, "PortProtonQt", "custom_data", appid_str)
        try:
            os.makedirs(game_dir, exist_ok=True)
            clean_name = new_name.replace("\r", " ").replace("\n", " ").strip()
            with open(os.path.join(game_dir, "metadata.txt"), "w", encoding="utf-8") as metadata_file:
                metadata_file.write(f"name={clean_name}\n")
            if selected_cover and os.path.isfile(selected_cover):
                extension = os.path.splitext(selected_cover)[1].lower()
                if extension not in COVER_IMAGE_EXTENSIONS:
                    return
                target_cover = os.path.join(game_dir, f"cover{extension}")
                if os.path.abspath(selected_cover) != os.path.abspath(target_cover):
                    self._remove_old_cover_files(game_dir)
                    shutil.copyfile(selected_cover, target_cover)
                cover_path = target_cover
        except OSError as e:
            self.signals.show_warning_dialog.emit(
                _("Error"), _("Failed to save custom data: {error}").format(error=str(e))
            )
            return
        for game in self.game_library_manager.games:
            if str(game[3]) != appid_str or game[12] != "steam":
                continue
            updated_game = list(game)
            updated_game[0] = new_name
            updated_game[2] = cover_path
            self.game_library_manager.replace_game_incremental(
                game[0], game[5], tuple(updated_game)
            )
            QTimer.singleShot(0, self.game_library_manager.load_visible_images)
            return

    def handle_missing_executable(self, game_card: "GameCard") -> None:
        """Offer removal or shortcut repair when the launch file is missing."""
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Executable not found"))
        msg_box.setText(_("Executable not found: {0}").format(game_card.missing_executable_path))
        delete_button = msg_box.addButton(_("Delete from PortProton"), QMessageBox.ButtonRole.DestructiveRole)
        edit_button = msg_box.addButton(_("Select another executable"), QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton(QMessageBox.StandardButton.Cancel)
        for button in msg_box.buttons():
            button.ensurePolished()
            button.setMinimumWidth(button.sizeHint().width())
        msg_box.exec()
        if msg_box.clickedButton() == delete_button:
            self.delete_game(game_card.name, game_card.exec_line)
        elif msg_box.clickedButton() == edit_button:
            self.edit_game_shortcut(game_card.name, game_card.exec_line, game_card.cover_path)

    def _relocate_shortcut_data(self, old_exe: str, new_exe: str) -> list[tuple[str, str]]:
        """Move path-specific data, refusing to overwrite another game's data."""
        if os.path.abspath(old_exe) == os.path.abspath(new_exe):
            return []
        data_home = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        custom_root = os.path.join(data_home, "PortProtonQt", "custom_data")
        old_folder = resolve_custom_data_dir(custom_root, old_exe)
        new_folder = os.path.join(custom_root, get_custom_data_dir_name(new_exe))
        paths = [(old_folder, new_folder), (old_exe + ".ppdb", new_exe + ".ppdb")]
        moves = [(source, target) for source, target in paths if os.path.exists(source)]
        for _source, target in moves:
            if os.path.lexists(target):
                raise FileExistsError(_("File already exists: {file_name}").format(file_name=target))
        completed = []
        try:
            for source, target in moves:
                shutil.move(source, target)
                completed.append((source, target))
        except OSError:
            for source, target in reversed(completed):
                shutil.move(target, source)
            raise
        return completed

    def _relocate_shortcut_statistics(self, old_exe: str, new_exe: str) -> None:
        """Keep playtime and last launch associated with a repaired shortcut."""
        from portprotonqt.time_utils import get_last_launch_path, get_statistics_path

        old_name = os.path.splitext(os.path.basename(old_exe))[0]
        new_name = os.path.splitext(os.path.basename(new_exe))[0]
        last_launch_path = get_last_launch_path()
        records = (
            (get_statistics_path(), os.path.normpath(old_exe).replace(" ", "#@_@#"), new_exe.replace(" ", "#@_@#")),
            (last_launch_path, old_name, new_name),
        )
        for path, old_key, new_key in records:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as stream:
                    lines = stream.readlines()
                updated = []
                for line in lines:
                    parts = line.rsplit(maxsplit=1) if path == last_launch_path else line.split(maxsplit=1)
                    if len(parts) == 2 and parts[0] == old_key:
                        line = f"{new_key} {parts[1].rstrip()}\n"
                    updated.append(line)
                if updated != lines:
                    with open(path, "w", encoding="utf-8") as stream:
                        stream.writelines(updated)
            except OSError as error:
                logger.warning("Failed to relocate statistics for %s: %s", old_exe, error)

    def edit_game_shortcut(self, game_name, exec_line, cover_path, appid=None):
        """
        Opens a dialog allowing the user to edit a game shortcut in edit mode to modify an existing .desktop file.

        Args:
            game_name: The display name of the game.
            exec_line: The executable command line of the game.
            cover_path: The path to the game's cover image.
        """
        if appid is not None:
            self._edit_steam_shortcut(game_name, appid, cover_path)
            return
        if not self._check_portproton():
            return
        exec_line = self._get_exec_line(game_name, exec_line)
        if not exec_line:
            return
        old_exec_line = exec_line
        exe_path = extract_exec_target_path(exec_line)
        if not exe_path:
            return
        dialog = AddGameDialog(
            parent=self.parent,
            theme=self.theme,
            edit_mode=True,
            game_name=game_name,
            exe_path=exe_path,
            cover_path=cover_path,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.nameEdit.text().strip()
            new_exe_path = dialog.exeEdit.text().strip()
            new_cover_path = dialog.coverEdit.text().strip()
            if not new_name or not new_exe_path:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _("Game name and executable path are required")
                )
                return
            desktop_entry, new_desktop_path = dialog.getDesktopEntryData()
            if not desktop_entry or not new_desktop_path:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _("Failed to generate .desktop file data")
                )
                return

            old_path = self._get_desktop_path(game_name)
            moved_paths = []
            try:
                moved_paths = self._relocate_shortcut_data(exe_path, new_exe_path)
                with open(new_desktop_path, "w", encoding="utf-8") as f:
                    f.write(desktop_entry)
                os.chmod(new_desktop_path, 0o755)
            except OSError as e:
                for source, target in reversed(moved_paths):
                    shutil.move(target, source)
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _("Failed to save .desktop file: {error}").format(error=str(e))
                )
                return
            for source, target in moved_paths:
                if new_cover_path.startswith(source + os.sep):
                    new_cover_path = target + new_cover_path[len(source):]
                if dialog.last_cover_path and dialog.last_cover_path.startswith(source + os.sep):
                    dialog.last_cover_path = target + dialog.last_cover_path[len(source):]
            if exe_path != new_exe_path:
                self._relocate_shortcut_statistics(exe_path, new_exe_path)
            if game_name != new_name and os.path.exists(old_path):
                self._remove_file(
                    old_path,
                    _("Failed to delete old .desktop file: {error}"),
                    _("Removed old .desktop file for '{game_name}'"),
                    game_name
                )
            saved_entry = parse_desktop_entry(new_desktop_path)
            updated_exec_line = new_exe_path
            if saved_entry:
                parsed_exec = saved_entry.get("Exec", saved_entry.get("exec", "")).strip()
                if parsed_exec:
                    updated_exec_line = parsed_exec

            # Check if new_cover_path is a URL by checking for common image extensions
            has_image_extension = any(new_cover_path.lower().endswith(ext) for ext in COVER_IMAGE_EXTENSIONS)

            # Consider it a URL if it has image extension and is not a local file
            is_url = has_image_extension and not os.path.isfile(new_cover_path)

            # Use the downloaded file path if we have a URL and the file was downloaded, otherwise use the local file
            if os.path.isfile(new_cover_path) or (is_url and dialog.last_cover_path and os.path.isfile(dialog.last_cover_path)):
                xdg_data_home = os.getenv(
                    "XDG_DATA_HOME",
                    os.path.join(os.path.expanduser("~"), ".local", "share")
                )
                custom_folder = os.path.join(
                    xdg_data_home,
                    "PortProtonQt",
                    "custom_data",
                    get_custom_data_dir_name(new_exe_path),
                )
                os.makedirs(custom_folder, exist_ok=True)

                # Use the actual cover file path (either from URL download or local file)
                cover_to_copy = dialog.last_cover_path if is_url and dialog.last_cover_path and os.path.isfile(dialog.last_cover_path) else new_cover_path
                ext = os.path.splitext(cover_to_copy)[1].lower()
                if ext in COVER_IMAGE_EXTENSIONS:
                    target_cover_path = os.path.join(custom_folder, f"cover{ext}")
                    temp_cover_path = None
                    try:
                        if os.path.dirname(os.path.abspath(cover_to_copy)) == os.path.abspath(custom_folder):
                            fd, temp_cover_path = tempfile.mkstemp(suffix=ext, dir=custom_folder)
                            os.close(fd)
                            shutil.copyfile(cover_to_copy, temp_cover_path)
                            cover_to_copy = temp_cover_path
                        self._remove_old_cover_files(custom_folder)
                        shutil.copyfile(cover_to_copy, target_cover_path)
                    except OSError as e:
                        self.signals.show_warning_dialog.emit(
                            _("Error"),
                            _("Failed to copy cover image: {error}").format(error=str(e))
                        )
                        return
                    finally:
                        if temp_cover_path and os.path.exists(temp_cover_path):
                            os.remove(temp_cover_path)
                else:
                    self.signals.show_warning_dialog.emit(
                        _("Error"),
                        _("Unsupported image format: {extension}").format(extension=ext)
                    )
                    return

            old_menu_path = self._get_menu_shortcut_path(game_name)
            new_menu_path = self._get_menu_shortcut_path(new_name)
            desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            old_desktop_path = self._get_shortcut_path(game_name, desktop_dir)
            new_desktop_path_target = self._get_shortcut_path(new_name, desktop_dir)

            if game_name != new_name:
                if os.path.exists(old_menu_path):
                    self.remove_from_menu(game_name)
                if os.path.exists(old_desktop_path):
                    self.remove_from_desktop(game_name)
                if is_game_in_steam(game_name):
                    self.remove_from_steam(game_name, new_exe_path, "portproton")

            if dialog.add_to_menu_checkbox.isChecked():
                if exe_path != new_exe_path or not os.path.exists(new_menu_path):
                    self.add_to_menu(new_name, updated_exec_line)
            elif os.path.exists(new_menu_path):
                self.remove_from_menu(new_name)

            if dialog.add_to_desktop_checkbox.isChecked():
                if exe_path != new_exe_path or not os.path.exists(new_desktop_path_target):
                    self.add_to_desktop(new_name, updated_exec_line)
            elif os.path.exists(new_desktop_path_target):
                self.remove_from_desktop(new_name)

            is_in_steam = is_game_in_steam(new_name)
            if dialog.add_to_steam_checkbox.isChecked():
                if is_in_steam and exe_path != new_exe_path:
                    self.remove_from_steam(new_name, old_exec_line, "portproton")
                    is_in_steam = False
                if not is_in_steam:
                    self.add_to_steam(new_name, updated_exec_line, new_cover_path)
            elif is_in_steam:
                self.remove_from_steam(new_name, updated_exec_line, "portproton")

            if hasattr(self.parent, "_replace_game_from_desktop_file"):
                self.parent._replace_game_from_desktop_file(
                    new_desktop_path,
                    game_name,
                    old_exec_line
                )

    def add_to_steam(self, game_name, exec_line, cover_path):
        """
        Adds a non-Steam game to Steam using steam_api.

        Args:
            game_name: The display name of the game.
            exec_line: The executable command line.
            cover_path: Path to the cover image.
        """
        if not self._check_portproton():
            return
        exec_line = self._get_exec_line(game_name, exec_line)
        if not exec_line:
            return
        exe_path = self._parse_exe_path(exec_line, game_name)
        if not exe_path:
            return
        logger.debug("Adding game '%s' to Steam", game_name)
        try:
            success, message = add_to_steam(game_name, exec_line, cover_path)
            if success:
                if "restart" in message.lower():
                    self.signals.show_info_dialog.emit(
                        _("Success"),
                        _("'{game_name}' was added to Steam. Please restart Steam for changes to take effect.").format(game_name=game_name)
                    )
                else:
                    self.signals.show_info_dialog.emit(
                        _("Success"),
                        _("'{game_name}' was added to Steam.").format(game_name=game_name)
                    )
            else:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _(message).format(game_name=game_name)
                )
        except Exception as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to add '{game_name}' to Steam: {error}").format(
                    game_name=game_name, error=str(e)
                )
            )

    def remove_from_steam(self, game_name, exec_line, game_source):
        """Handle removing a game from Steam via steam_api."""
        if not self._check_portproton():
            return

        def on_remove_from_steam_result(result: tuple[bool, str]):
            success, message = result
            if success:
                if "restart" in message.lower():
                    self.signals.show_info_dialog.emit(
                        _("Success"),
                        _("'{game_name}' was removed from Steam. Please restart Steam for changes to take effect.").format(game_name=game_name)
                    )
                else:
                    self.signals.show_info_dialog.emit(
                        _("Success"),
                        _("'{game_name}' was removed from Steam.").format(game_name=game_name)
                    )
            else:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _(message).format(game_name=game_name)
                )

        exec_line = self._get_exec_line(game_name, exec_line)
        if not exec_line:
            return
        exe_path = extract_exec_target_path(exec_line)
        if not exe_path:
            return
        logger.debug("Removing game '%s' from Steam", game_name)
        try:
            success, message = remove_from_steam(game_name, exec_line)
            if success:
                on_remove_from_steam_result((success, message))
            else:
                self.signals.show_warning_dialog.emit(
                    _("Error"),
                    _(message).format(game_name=game_name)
                )
        except Exception as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to remove game '{game_name}' from Steam: {error}").format(
                    game_name=game_name, error=str(e)
                )
            )

    def open_game_folder(self, game_name, exec_line):
        """
        Opens the folder containing the game's executable.

        Args:
            game_name: The display name of the game.
            exec_line: The executable command line.
        """
        if not self._check_portproton():
            return
        exec_line = self._get_exec_line(game_name, exec_line)
        if not exec_line:
            return
        exe_path = self._parse_exe_path(exec_line, game_name)
        if not exe_path:
            return
        try:
            folder_path = os.path.dirname(os.path.abspath(exe_path))
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
        except Exception as e:
            self.signals.show_warning_dialog.emit(
                _("Error"),
                _("Failed to open folder: {error}").format(error=str(e))
            )

    def open_steam_game_folder(self, appid: int | str) -> None:
        """Open Steam game installation folder by appid."""
        appid_str = str(appid).strip()
        if not appid_str:
            return
        steam_home = get_steam_home()
        if steam_home is None:
            return
        for lib in get_steam_libs(steam_home):
            manifest = lib / "steamapps" / f"appmanifest_{appid_str}.acf"
            if not manifest.exists():
                continue
            data = safe_vdf_load(manifest)
            install_dir = data.get("AppState", {}).get("installdir")
            if not install_dir:
                return
            folder_path = lib / "steamapps" / "common" / install_dir
            if not folder_path.exists():
                return
            linux_subdir = folder_path / f"{install_dir}_linux"
            if linux_subdir.exists():
                folder_path = linux_subdir
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
            return

class CustomLineEdit(QLineEdit):

    def __init__(self, *args, theme=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.theme = theme

    def contextMenuEvent(self, event):
        show_themed_line_edit_context_menu(self, event.globalPos(), self.theme)

    def _delete_selected_text(self):
        cursor_pos = self.cursorPosition()
        self.backspace()
        self.setCursorPosition(cursor_pos)

def show_themed_line_edit_context_menu(line_edit: QLineEdit, global_pos: QPoint, theme=None) -> None:
    """Show a themed context menu for any line edit widget."""
    theme_manager = ThemeManager()

    def add_action(menu: QMenu, text: str, shortcut: QKeySequence.StandardKey,
                   icon_name: str, slot, enabled: bool = True) -> None:
        raw_icon = theme_manager.get_icon(icon_name)
        icon = raw_icon if isinstance(raw_icon, QIcon) else QIcon(raw_icon) if isinstance(raw_icon, str) else QIcon()
        shortcut_str = QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)
        action = menu.addAction(icon, f"{text}\t{shortcut_str}")
        action.triggered.connect(slot)
        action.setEnabled(enabled)

    menu = QMenu(line_edit)
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    current_theme = theme if theme is not None else getattr(line_edit, "theme", None)
    if current_theme and hasattr(current_theme, "CONTEXT_MENU_STYLE"):
        menu.setStyleSheet(current_theme.CONTEXT_MENU_STYLE)

    add_action(menu, _("Undo"), QKeySequence.StandardKey.Undo, "undo", line_edit.undo, line_edit.isUndoAvailable())
    add_action(menu, _("Redo"), QKeySequence.StandardKey.Redo, "redo", line_edit.redo, line_edit.isRedoAvailable())
    menu.addSeparator()
    add_action(menu, _("Cut"), QKeySequence.StandardKey.Cut, "cut", line_edit.cut, line_edit.hasSelectedText())
    add_action(menu, _("Copy"), QKeySequence.StandardKey.Copy, "copy", line_edit.copy, line_edit.hasSelectedText())
    add_action(menu, _("Paste"), QKeySequence.StandardKey.Paste, "paste", line_edit.paste,
               QApplication.clipboard().mimeData().hasText())
    add_action(menu, _("Delete"), QKeySequence.StandardKey.Delete, "delete", lambda: line_edit.backspace(),
               line_edit.hasSelectedText())
    menu.addSeparator()
    add_action(menu, _("Select All"), QKeySequence.StandardKey.SelectAll, "select_all", line_edit.selectAll,
               bool(line_edit.text()))

    menu.exec(global_pos)
