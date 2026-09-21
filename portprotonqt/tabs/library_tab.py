import os
import shutil
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QAbstractAnimation, QPoint, QStandardPaths, Qt, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.animations import ExpandingSearchAnimation, LibraryControlsAnimation
from portprotonqt.cli import is_autoinstall_file
from portprotonqt.config import (
    LAUNCH_FILE_EXTENSIONS,
    extract_exec_target_path,
    game_config,
    get_custom_data_dir_name,
    parse_desktop_entry,
    ui_config,
)
from portprotonqt.context_menu_manager import CustomLineEdit
from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox
from portprotonqt.dialogs import AddGameDialog, FileExplorer
from portprotonqt.dialogs.proton_manager import (
    WINE_ARCHIVE_EXTENSIONS,
    show_proton_manager,
)
from portprotonqt.image_utils import COVER_IMAGE_EXTENSIONS
from portprotonqt.localization import _, get_metadata_language, read_metadata_translations
from portprotonqt.logger import get_logger
from portprotonqt.scripts_utils.shortcut_tools import find_ext_ppdb
from portprotonqt.scripts_utils.prefix_backup import BACKUP_EXTENSION
from portprotonqt.steam_api import get_cached_steam_game_info, is_game_in_steam
from portprotonqt.time_utils import format_playtime

logger = get_logger(__name__)
PP_FILE_EXTENSIONS = (BACKUP_EXTENSION, ".ppai")

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class MainWindowLibraryTabMixin(_MainWindowTypingBase):
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    def _load_empty_library_on_tab_enter(self, index: int) -> None:
        if index == 0 and self.isVisible() and not self.games:
            self.loadGames(force_load=True)

    def _set_combo_current_key(self, combo: QComboBox, keys: list[str], current: str) -> None:
        try:
            idx = keys.index(current)
        except ValueError:
            idx = 0
        combo.setCurrentIndex(idx)

    def _create_library_combo(self, labels: list[str], tooltip: str) -> QComboBox:
        combo = CustomComboBox(theme=self.theme)
        combo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        combo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        combo.addItems(labels)
        combo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._register_gamepad_tooltip(combo, tooltip)
        return combo

    def _on_library_sort_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.sort_keys):
            return
        game_config.set_sort_method(self.sort_keys[index])
        if hasattr(self, "game_library_manager"):
            self.game_library_manager.update_game_grid(focus_first_card=False)

    def _on_library_filter_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.filter_keys):
            return
        display_filter = self.filter_keys[index]
        game_config.set_display_filter(display_filter)
        self.onlyInstalledCheckBox.setVisible(
            display_filter not in ("steam", "portproton")
        )
        self._position_library_controls_widget()
        self.searchEdit.clear()
        self.games = []
        self._preserve_library_focus_after_load = True
        self.loadGames(force_load=True)

    def _on_only_installed_changed(self, checked: bool) -> None:
        game_config.set_only_installed(checked)
        self.searchEdit.clear()
        self._preserve_library_focus_after_load = True
        display_filter = game_config.get_display_filter()
        cached_games = getattr(self, "_loaded_library_cache", {}).get(display_filter)
        if cached_games is None:
            self.games = []
            self.loadGames(force_load=True)
            return
        games = cached_games
        if checked:
            games = [
                game for game in games
                if not game[5].startswith(("gog://install/", "egs://install/"))
            ]
        self.games = games
        self._preserve_library_focus_after_load = False
        self.game_library_manager.games = games
        self.game_library_manager.filtered_games = games
        self.game_library_manager._build_search_indices(games)
        self.game_library_manager.update_game_grid(
            is_filter=True, focus_first_card=False
        )

    def _on_library_badge_view_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.badge_view_keys):
            return
        badge_view_mode = self.badge_view_keys[index]
        if ui_config.get_economy_mode():
            badge_view_mode = "hidden"
        ui_config.set_badge_view_mode(badge_view_mode)
        display_filter = game_config.get_display_filter()
        for card in self.game_library_manager.game_card_cache.values():
            card.update_badge_visibility(display_filter)
            card.update_badge_view_mode(badge_view_mode)

    def _toggle_library_controls(self) -> None:
        self._position_library_controls_widget()
        self.libraryControlsAnimation.toggle(self.libraryControlsButton.isChecked())

    def _close_library_controls(self) -> None:
        controls_button = getattr(self, "libraryControlsButton", None)
        if controls_button is not None:
            controls_button.setChecked(False)
        animation = getattr(self, "libraryControlsAnimation", None)
        if animation is not None:
            animation.group.stop()
            animation.opacity_effect.setOpacity(0)
        controls_widget = getattr(self, "libraryControlsWidget", None)
        if controls_widget is not None:
            controls_widget.hide()

    def _create_library_controls_widget(self) -> QGridLayout:
        self.libraryControlsWidget = QWidget(self)
        self.libraryControlsWidget.setObjectName("libraryControlsWidget")
        controls_layout = QGridLayout(self.libraryControlsWidget)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        controls_layout.setSpacing(10)
        self.libraryControlsWidget.setStyleSheet(self.theme.LIBRARY_CONTROL_STYLE)
        return controls_layout

    def _position_library_controls_widget(self) -> None:
        controls_layout = self.libraryControlsWidget.layout()
        if controls_layout is not None:
            controls_layout.invalidate()
            controls_layout.activate()
        size_hint = self.libraryControlsWidget.sizeHint()
        button_bottom = self.libraryControlsButton.mapTo(
            self,
            QPoint(0, self.libraryControlsButton.height()),
        )
        button_right = self.libraryControlsButton.mapTo(
            self,
            QPoint(self.libraryControlsButton.width(), 0),
        ).x()
        x = max(0, min(self.width() - size_hint.width(), button_right - size_hint.width()))
        self.libraryControlsWidget.setGeometry(x, button_bottom.y() + 10, size_hint.width(), size_hint.height())

    def _add_library_action_buttons(self, buttons_layout: QHBoxLayout) -> None:
        self.quickLaunchButton = AutoSizeButton(_("Quick Launch"), icon=self.theme_manager.get_icon("play", as_path=True))
        self.quickLaunchButton.setStyleSheet(self.theme.ADDGAME_BACK_BUTTON_STYLE)
        self.quickLaunchButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.quickLaunchButton.clicked.connect(self.quickLaunch)
        buttons_layout.addWidget(self.quickLaunchButton)

        self.addGameButton = AutoSizeButton(_("Add a shortcut"), icon=self.theme_manager.get_icon("addgame", as_path=True))
        self.addGameButton.setStyleSheet(self.theme.ADDGAME_BACK_BUTTON_STYLE)
        self.addGameButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.addGameButton.setProperty("sound_event", "open")
        self.addGameButton.clicked.connect(self.openAddGameDialog)
        buttons_layout.addWidget(self.addGameButton)
        buttons_layout.addStretch()

    def _add_library_search(self, buttons_layout: QHBoxLayout) -> None:
        self.searchEdit = CustomLineEdit(self, theme=self.theme)
        icon: QIcon = cast(QIcon, self.theme_manager.get_icon("search"))
        action_pos = cast(QLineEdit.ActionPosition, QLineEdit.ActionPosition.LeadingPosition)
        self.searchIconAction = self.searchEdit.addAction(icon, action_pos)
        self.searchEdit.setMaximumWidth(200)
        self.searchEdit.setPlaceholderText(_("Search…"))
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.setStyleSheet(self.theme.SEARCH_EDIT_STYLE)

        self.searchEdit.textChanged.connect(self.startSearchDebounce)
        self.searchDebounceTimer = QTimer(self)
        self.searchDebounceTimer.setSingleShot(True)
        self.searchDebounceTimer.setInterval(150)  # Reduced debounce time for better responsiveness
        self.searchDebounceTimer.timeout.connect(self.on_search_changed)
        self.searchEdit.focusInEvent = self._wrap_search_focus_event(
            self.searchEdit.focusInEvent,
            True,
        )
        self.searchEdit.focusOutEvent = self._wrap_search_focus_event(
            self.searchEdit.focusOutEvent,
            False,
        )
        self.searchEdit.resizeEvent = self._wrap_search_resize_event(self.searchEdit.resizeEvent)
        buttons_layout.addWidget(self.searchEdit)

    def _add_library_refresh_button(self, buttons_layout: QHBoxLayout) -> None:
        self.refreshButton = AutoSizeButton(icon=self.theme_manager.get_icon("update", as_path=True))
        self.refreshButton.setStyleSheet(self.theme.LIBRARY_CONTROLS_BUTTON_STYLE)
        self.refreshButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.refreshButton.clicked.connect(self.refreshGames)
        self._register_gamepad_tooltip(self.refreshButton, _("Refresh Grid"))
        buttons_layout.addWidget(self.refreshButton)

    def _add_library_delete_missing_button(self, buttons_layout: QHBoxLayout) -> None:
        self.deleteMissingExeButton = AutoSizeButton(
            icon=self.theme_manager.get_icon("delete", as_path=True)
        )
        self.deleteMissingExeButton.setStyleSheet(self.theme.LIBRARY_CONTROLS_BUTTON_STYLE)
        self.deleteMissingExeButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.deleteMissingExeButton.clicked.connect(self.deleteMissingExeCards)
        self._register_gamepad_tooltip(
            self.deleteMissingExeButton,
            _("Delete cards without executable"),
        )
        self.deleteMissingExeButton.setVisible(False)
        buttons_layout.addWidget(self.deleteMissingExeButton)

    def _add_library_controls_button(self, buttons_layout: QHBoxLayout) -> None:
        self.libraryControlsButton = AutoSizeButton(
            icon=self.theme_manager.get_icon("menu", as_path=True)
        )
        self.libraryControlsButton.setStyleSheet(self.theme.LIBRARY_CONTROLS_BUTTON_STYLE)
        self.libraryControlsButton.setCheckable(True)
        self.libraryControlsButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.libraryControlsButton.clicked.connect(self._toggle_library_controls)
        self._register_gamepad_tooltip(self.libraryControlsButton, _("Library Settings"))
        buttons_layout.addWidget(self.libraryControlsButton)

    def _setup_library_search_animation(self) -> None:
        self.searchAnimation = ExpandingSearchAnimation(
            self.searchEdit,
            self.theme,
            self.searchDebounceTimer.interval(),
        )
        collapsed_width = self.libraryControlsButton.sizeHint().width()
        expanded_width = self.searchEdit.maximumWidth()
        self.searchAnimation.setup(collapsed_width, expanded_width)
        QTimer.singleShot(0, self._center_collapsed_search_icon)

    def _wrap_search_focus_event(self, original_event: Callable, expand: bool) -> Callable:
        def handle_focus_event(event):
            original_event(event)
            if not hasattr(self, "searchAnimation"):
                return
            keyboard = getattr(self, "keyboard", None)
            if expand:
                self.searchAnimation.expand()
            elif not (
                keyboard
                and keyboard.isVisible()
                and getattr(keyboard, "current_input_widget", None) is self.searchEdit
            ):
                self.searchAnimation.collapse()
            QTimer.singleShot(0, self._center_collapsed_search_icon)
        return handle_focus_event

    def _wrap_search_resize_event(self, original_event: Callable) -> Callable:
        def handle_resize_event(event):
            original_event(event)
            self._center_collapsed_search_icon()
        return handle_resize_event

    def _center_collapsed_search_icon(self) -> None:
        animation = getattr(self, "searchAnimation", None)
        if animation is None or self.searchEdit.maximumWidth() != animation.collapsed_width:
            return
        for button in self.searchEdit.findChildren(QToolButton):
            if button.defaultAction() is self.searchIconAction:
                size = button.sizeHint()
                x = (self.searchEdit.width() - size.width()) // 2
                y = (self.searchEdit.height() - size.height()) // 2
                button.setGeometry(x, y, size.width(), size.height())
                return

    def _add_library_filter_controls(self, controls_layout: QGridLayout) -> None:
        self.sort_keys = ["last_launch", "playtime", "alphabetical"]
        self.sort_labels = [_("Last launch"), _("Time spent"), _("Alphabetical")]
        self.gamesSortCombo = self._create_library_combo(self.sort_labels, _("Sort Method:"))
        self._set_combo_current_key(
            self.gamesSortCombo,
            self.sort_keys,
            game_config.get_sort_method(),
        )
        self.gamesSortCombo.currentIndexChanged.connect(self._on_library_sort_changed)
        self.gamesSortCombo.activated.connect(self._delay_library_controls_hover_close)
        controls_layout.addWidget(self.gamesSortCombo, 0, 0)

        display_filter = game_config.get_display_filter()
        only_installed = game_config.get_only_installed()
        self.filter_keys = ["all", "steam", "gog", "egs", "portproton", "favorites"]
        self.filter_labels = [
            _("All"),
            "Steam",
            "GOG",
            "Epic Games",
            "PortProton",
            _("Favorites"),
        ]
        self.gamesDisplayCombo = self._create_library_combo(self.filter_labels, _("Display Filter:"))
        self._set_combo_current_key(
            self.gamesDisplayCombo,
            self.filter_keys,
            display_filter,
        )
        self.gamesDisplayCombo.currentIndexChanged.connect(self._on_library_filter_changed)
        self.gamesDisplayCombo.activated.connect(self._delay_library_controls_hover_close)

        self.onlyInstalledCheckBox = QCheckBox(_("Only Installed"))
        self.onlyInstalledCheckBox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        self.onlyInstalledCheckBox.setChecked(only_installed)
        self.onlyInstalledCheckBox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._register_gamepad_tooltip(self.onlyInstalledCheckBox, _("Only Installed"))
        self.onlyInstalledCheckBox.toggled.connect(self._on_only_installed_changed)

        controls_layout.addWidget(self.gamesDisplayCombo, 0, 1)
        controls_layout.addWidget(self.onlyInstalledCheckBox, 1, 1, 1, 2)
        self.onlyInstalledCheckBox.setVisible(
            display_filter not in ("steam", "portproton")
        )

        self.badge_view_keys = ["detailed", "compact", "hidden"]
        self.badge_view_labels = [_("Detailed"), _("Compact"), _("Hidden")]
        self.gamesBadgeViewCombo = self._create_library_combo(self.badge_view_labels, _("Badge View Type:"))
        self._set_combo_current_key(
            self.gamesBadgeViewCombo,
            self.badge_view_keys,
            ui_config.get_badge_view_mode(),
        )
        if ui_config.get_economy_mode():
            self.gamesBadgeViewCombo.setCurrentIndex(self.badge_view_keys.index("hidden"))
            self.gamesBadgeViewCombo.setEnabled(False)
        self.gamesBadgeViewCombo.currentIndexChanged.connect(self._on_library_badge_view_changed)
        self.gamesBadgeViewCombo.activated.connect(self._delay_library_controls_hover_close)
        controls_layout.addWidget(self.gamesBadgeViewCombo, 0, 2)

    def _delay_library_controls_hover_close(self, _index: int = -1) -> None:
        self._library_controls_hover_close_delayed = True
        QTimer.singleShot(350, self._allow_library_controls_hover_close)

    def _allow_library_controls_hover_close(self) -> None:
        self._library_controls_hover_close_delayed = False

    def createSearchWidget(self) -> tuple[QWidget, CustomLineEdit]:
        self.container = QWidget()
        self.container.setStyleSheet(self.theme.CONTAINER_STYLE)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        controls_layout = self._create_library_controls_widget()

        self._add_library_action_buttons(buttons_layout)
        self._add_library_search(buttons_layout)
        self._add_library_refresh_button(buttons_layout)
        self._add_library_delete_missing_button(buttons_layout)
        self.libraryControlsAnimation = LibraryControlsAnimation(
            self.libraryControlsWidget,
            self.theme,
            self.searchDebounceTimer.interval(),
        )
        self._add_library_controls_button(buttons_layout)
        self._setup_library_search_animation()
        self._add_library_filter_controls(controls_layout)
        self.libraryControlsAnimation.setup_hidden()
        layout.addLayout(buttons_layout)
        return self.container, self.searchEdit

    def refreshGames(self):
        """Refresh the game grid by reloading all games without restarting the application."""
        # Prevent multiple refreshes at once
        if hasattr(self, '_refresh_in_progress') and self._refresh_in_progress:
            return

        # Mark that a refresh is in progress
        self._refresh_in_progress = True
        self._loaded_library_cache = {}

        # Clear the search field to ensure all games are shown after refresh
        self.searchEdit.clear()

        # Disable the refresh button during refresh to prevent multiple clicks
        self.refreshButton.setEnabled(False)
        self._gamepad_tooltip_map[self.refreshButton] = _("Refreshing…")

        # Clear the game card cache and layout to force reload of custom data
        if hasattr(self, 'game_library_manager') and self.game_library_manager:
            # Clear the cache to ensure custom data is reloaded
            self.game_library_manager.game_card_cache.clear()
            self.game_library_manager.pending_images.clear()
            # Clear search indices to rebuild with fresh data
            if hasattr(self.game_library_manager, '_build_search_indices'):
                # Mark for full rebuild of search indices
                self.game_library_manager.dirty = True  # Force full update

            # Also clear the layout to ensure old widgets are removed
            if (hasattr(self.game_library_manager, 'gamesListLayout') and
                self.game_library_manager.gamesListLayout and
                hasattr(self.game_library_manager, 'gamesListWidget') and
                self.game_library_manager.gamesListWidget):
                # Remove all widgets from the layout
                self.game_library_manager.clear_layout(self.game_library_manager.gamesListLayout)

                # Force layout update to ensure UI changes are visible
                self.game_library_manager.gamesListWidget.updateGeometry()
                if hasattr(self.game_library_manager, 'gamesListLayout'):
                    self.game_library_manager.gamesListLayout.update()

        display_filter = game_config.get_display_filter()
        source_loader = getattr(
            self, f"_load_{display_filter}_games_async", None
        )
        source_refresh = getattr(
            self, f"_refresh_{display_filter}_library", None
        )
        if callable(source_refresh):
            source_refresh()

        if not callable(source_loader):
            if self.gog_api.auth_path.is_file():
                self._refresh_gog_library()
            if self.egs_api.user_path.is_file():
                self._refresh_egs_library()

        # Reload games using the existing loadGames functionality
        # Use a small delay to allow UI to update before starting the refresh
        QTimer.singleShot(50, lambda: self.loadGames(force_load=True))

    def _get_games_without_exe(self) -> list[tuple]:
        missing_games = []
        for game in self.game_library_manager.games:
            if len(game) <= 12 or game[12] != "portproton":
                continue
            exec_line = game[5] if len(game) > 5 else ""
            exe_path = extract_exec_target_path(exec_line) if exec_line else None
            if not exe_path or not os.path.exists(exe_path):
                missing_games.append(game)
        return missing_games

    def updateDeleteMissingExeButton(self) -> None:
        button = getattr(self, "deleteMissingExeButton", None)
        if button is None:
            return
        button.setVisible(bool(self._get_games_without_exe()))

    def deleteMissingExeCards(self) -> None:
        """Delete PortProton cards whose executable is missing."""
        if not getattr(self, "context_menu_manager", None):
            return
        missing_games = self._get_games_without_exe()
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Deletion"))
        msg_box.setText(
            _("Are you sure you want to delete {count} cards without executable? This will remove the .desktop files and custom data.")
            .format(count=len(missing_games))
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if msg_box.exec() != QMessageBox.StandardButton.Yes:
            return
        for game in missing_games:
            self.context_menu_manager._delete_game_without_confirm(game[0], game[5])
        self.updateDeleteMissingExeButton()

    def quickLaunch(self):
        """Open file manager to select executable and then open its detail page."""
        file_explorer = FileExplorer(self, self.theme, file_filter=LAUNCH_FILE_EXTENSIONS)
        file_explorer.file_signal.file_selected.connect(self.handle_launch_exe)

        parent_geometry = self.geometry()
        center_point = parent_geometry.center()
        file_explorer_geometry = file_explorer.geometry()
        file_explorer_geometry.moveCenter(center_point)
        file_explorer.setGeometry(file_explorer_geometry)

        file_explorer.show()

    def on_search_text_changed(self, text: str):
        """Search text change handler with debounce."""
        self.searchDebounceTimer.stop()
        self.searchDebounceTimer.start()

    @Slot()
    def on_search_changed(self):
        """Triggers filtering with delay."""
        if hasattr(self, 'game_library_manager'):
            self.game_library_manager.filter_games_delayed()

    def startSearchDebounce(self, text):
        self.searchDebounceTimer.start()

    def createInstalledTab(self):
        self.gamesLibraryWidget = self.game_library_manager.create_games_library_widget()
        self.stackedWidget.addWidget(self.gamesLibraryWidget)
        self.gamesListWidget = self.game_library_manager.gamesListWidget
        self.game_library_manager.update_game_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_animations') and self._animations:
            current_detail_page = getattr(self, "currentDetailPage", None)
            animation_type = self.theme.GAME_CARD_ANIMATION.get(
                "detail_page_animation_type", "fade"
            )
            for widget, animation in list(self._animations.items()):
                try:
                    if widget is current_detail_page and animation_type == "fade":
                        continue
                    if animation.state() == QAbstractAnimation.State.Running:
                        animation.stop()
                        widget.setWindowOpacity(1.0)
                        del self._animations[widget]
                except RuntimeError:
                    del self._animations[widget]
        if not hasattr(self, '_last_width'):
            self._last_width = self.width()
        if abs(self.width() - self._last_width) > 10:
            self._last_width = self.width()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile().lower()
                if path.endswith(
                    LAUNCH_FILE_EXTENSIONS + PP_FILE_EXTENSIONS + WINE_ARCHIVE_EXTENSIONS
                ):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        wine_archives = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            path_lower = path.lower()
            if path_lower.endswith(WINE_ARCHIVE_EXTENSIONS) and os.path.isfile(path):
                wine_archives.append(path)
                continue
            if path_lower.endswith(BACKUP_EXTENSION):
                self._perform_restore(path)
                event.acceptProposedAction()
                break
            if is_autoinstall_file(path):
                self.open_local_autoinstall_card(path)
                event.acceptProposedAction()
                break
            if path_lower.endswith(LAUNCH_FILE_EXTENSIONS):
                self.openAddGameDialog(path)
                event.acceptProposedAction()
                break
        if wine_archives:
            show_proton_manager(
                self,
                self.portproton_location,
                input_manager=self.input_manager,
                local_archives=wine_archives,
            )
            event.acceptProposedAction()

    def openAddGameDialog(self, exe_path=None):
        if self.current_add_game_dialog is not None and self.current_add_game_dialog.isVisible():
            self.current_add_game_dialog.activateWindow()
            self.current_add_game_dialog.raise_()
            return

        dialog = AddGameDialog(self, self.theme)
        dialog.setFocus(Qt.FocusReason.OtherFocusReason)
        self.current_add_game_dialog = dialog

        if exe_path:
            dialog.exeEdit.setText(exe_path)
            dialog.nameEdit.setText(os.path.splitext(os.path.basename(exe_path))[0])
            dialog.updatePreview()

        def on_dialog_finished():
            self.current_add_game_dialog = None

        dialog.finished.connect(on_dialog_finished)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.nameEdit.text().strip()
            exe_path = dialog.exeEdit.text().strip()
            user_cover = dialog.coverEdit.text().strip()

            if not name or not exe_path:
                return

            if ui_config.get_auto_download_ppdb() and exe_path.lower().endswith(".exe"):
                find_ext_ppdb(exe_path)

            desktop_entry, desktop_path = dialog.getDesktopEntryData()
            if desktop_entry and desktop_path:
                self._write_desktop_file(desktop_entry, desktop_path)

                xdg_data_home = os.getenv("XDG_DATA_HOME",
                    os.path.join(os.path.expanduser("~"), ".local", "share"))
                custom_folder = os.path.join(
                    xdg_data_home,
                    "PortProtonQt",
                    "custom_data",
                    get_custom_data_dir_name(exe_path),
                )

                # Handle user cover copy
                cover_path = None
                if user_cover:
                    ext = os.path.splitext(user_cover)[1].lower()
                    if os.path.isfile(user_cover) and ext in COVER_IMAGE_EXTENSIONS:
                        os.makedirs(custom_folder, exist_ok=True)
                        copied_cover = os.path.join(custom_folder, f"cover{ext}")
                        shutil.copyfile(user_cover, copied_cover)
                        cover_path = copied_cover

                # Parse .desktop (adapt from _process_desktop_file_async)
                entry = parse_desktop_entry(desktop_path)
                if not entry:
                    return
                self._known_portproton_desktops.add(desktop_path)
                description = entry.get("Comment", "")
                exec_line = entry.get("Exec", exe_path)
                cover_for_shortcut = dialog.last_cover_path if dialog.last_cover_path else user_cover
                self._sync_game_shortcuts_from_dialog(dialog, name, exec_line, cover_for_shortcut)

                # User cover fallback
                user_cover_path = cover_path  # Already set if user provided

                # Statistics (playtime, last launch - defaults for new)
                playtime_seconds = 0
                formatted_playtime = format_playtime(playtime_seconds)
                last_played_timestamp = 0
                last_launch = _("Never")

                # Language for translations
                language_code = get_metadata_language()

                # Read translations from metadata.txt
                user_metadata_file = os.path.join(custom_folder, "metadata.txt")

                translations = {'name': name, 'description': description}
                if os.path.exists(user_metadata_file):
                    translations = read_metadata_translations(user_metadata_file, language_code)

                final_name = translations['name']
                final_desc = translations['description']

                def on_steam_info(steam_info: dict):
                    nonlocal final_name, final_desc
                    # Adapt final_cover logic from _process_desktop_file_async
                    final_cover = (
                        user_cover_path
                        if user_cover_path
                        else steam_info.get("cover", "") or entry.get("Icon", "")
                    )

                    # Use Steam description as fallback if no translation
                    steam_desc = steam_info.get("description", "")
                    if steam_desc and steam_desc != final_desc:
                        final_desc = steam_desc

                    # Build full game_data tuple with all Steam data
                    game_data = (
                        final_name,
                        final_desc,
                        final_cover,
                        steam_info.get("appid", ""),
                        steam_info.get("controller_support", ""),
                        exec_line,
                        last_launch,
                        formatted_playtime,
                        steam_info.get("protondb_tier", ""),
                        steam_info.get("anticheat_status", ""),
                        last_played_timestamp,
                        playtime_seconds,
                        "portproton",
                        steam_info.get("anticheat_slug", ""),
                        steam_info.get("ppdb_id", ""),
                        steam_info.get("ppdb_rating", ""),
                    )

                    # Incremental add
                    self.game_library_manager.add_game_incremental(game_data)

                    # Trigger visible images load
                    QTimer.singleShot(200, self.game_library_manager.load_visible_images)

                from portprotonqt.steam_api import get_steam_game_info_async
                if ui_config.get_economy_mode():
                    cached_steam_info = get_cached_steam_game_info(final_name, exec_line)
                    game_data = (
                        final_name,
                        final_desc or cached_steam_info.get("description", ""),
                        user_cover_path or cached_steam_info.get("cover", "") or entry.get("Icon", ""),
                        cached_steam_info.get("appid", ""),
                        cached_steam_info.get("controller_support", ""),
                        exec_line,
                        last_launch,
                        formatted_playtime,
                        cached_steam_info.get("protondb_tier", ""),
                        cached_steam_info.get("anticheat_status", ""),
                        last_played_timestamp,
                        playtime_seconds,
                        "portproton",
                        cached_steam_info.get("anticheat_slug", ""),
                        cached_steam_info.get("ppdb_id", ""),
                        cached_steam_info.get("ppdb_rating", ""),
                    )
                    self.game_library_manager.add_game_incremental(game_data)
                    QTimer.singleShot(200, self.game_library_manager.load_visible_images)
                else:
                    get_steam_game_info_async(final_name, exec_line, on_steam_info)

    def _sync_game_shortcuts_from_dialog(self, dialog, game_name, exec_line, cover_path):
        """Apply shortcut options selected in add/edit game dialog."""
        applications_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
        menu_path = os.path.join(applications_dir, f"{game_name}.desktop")
        if dialog.add_to_menu_checkbox.isChecked():
            if not os.path.exists(menu_path):
                self.context_menu_manager.add_to_menu(game_name, exec_line)
        elif os.path.exists(menu_path):
            self.context_menu_manager.remove_from_menu(game_name)

        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        desktop_path = os.path.join(desktop_dir, f"{game_name}.desktop")
        if dialog.add_to_desktop_checkbox.isChecked():
            if not os.path.exists(desktop_path):
                self.context_menu_manager.add_to_desktop(game_name, exec_line)
        elif os.path.exists(desktop_path):
            self.context_menu_manager.remove_from_desktop(game_name)

        is_in_steam = is_game_in_steam(game_name)
        if dialog.add_to_steam_checkbox.isChecked():
            if not is_in_steam:
                self.context_menu_manager.add_to_steam(game_name, exec_line, cover_path)
        elif is_in_steam:
            self.context_menu_manager.remove_from_steam(game_name, exec_line, "portproton")
