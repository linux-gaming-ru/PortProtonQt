from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QListView,
    QListWidget,
    QMenu,
    QStackedWidget,
    QTableWidget,
    QWidget,
)

from portprotonqt.custom_widgets import AutoSizeButton
from portprotonqt.input_manager.constants import BUTTONS, PAD_DPAD_X, PAD_DPAD_Y
from portprotonqt.logger import get_logger
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.sound_manager import SoundManager

logger = get_logger(__name__)


@dataclass
class InputSurface:
    name: str
    dialog: Any
    button_handler: Callable[[int, int], None]
    dpad_handler: Callable[[int, int, float], None]
    connections: list[tuple[Any, Callable[..., Any]]] = field(default_factory=list)


class DialogInputModesMixin(InputMixin):
    # WINETRICKS MODE
    def enable_winetricks_mode(self, winetricks_dialog):
        """Setup gamepad handling for WinetricksDialog"""
        try:
            self._setup_mode_handlers(
                winetricks_dialog,
                self.handle_winetricks_button,
                self.handle_winetricks_dpad,
                'winetricks_dialog'
            )
            logger.debug("Gamepad handling successfully connected for WinetricksDialog")
        except Exception as e:
            logger.error(f"Error connecting gamepad handlers for Winetricks: {e}")

    def disable_winetricks_mode(self):
        """Restore original main window handlers"""
        try:
            if self.winetricks_dialog:
                self._restore_original_handlers('winetricks_dialog')
                logger.debug("Gamepad handling successfully restored from Winetricks")
        except Exception as e:
            logger.error(f"Error restoring gamepad handlers from Winetricks: {e}")

    def handle_winetricks_button(self, button_code, value):
        if self.winetricks_dialog is None or value == 0:
            return

        try:
            # Handle common UI elements like QMessageBox, QMenu, etc.
            if self._handle_common_ui_elements(button_code):
                return

            # Winetricks-specific button handling
            focused = QApplication.focusWidget()

            if button_code in BUTTONS['confirm']:  # A: Toggle checkbox
                if isinstance(focused, QTableWidget):
                    self.handle_table_confirm(focused)
                return

            elif button_code in BUTTONS['add_game']:  # X: Install
                self.winetricks_dialog.install_selected(force=False)

            elif button_code in BUTTONS['prev_dir']:  # Y: Force Install
                self.winetricks_dialog.install_selected(force=True)

            elif button_code in BUTTONS['back']:  # B: Cancel
                self.winetricks_dialog.reject()

            elif button_code in BUTTONS['prev_tab']:  # LB
                current_index = self.winetricks_dialog.tab_widget.currentIndex()
                new_index = max(0, current_index - 1)
                self.winetricks_dialog.tab_widget.setCurrentIndex(new_index)
                if new_index != current_index:
                    SoundManager().play("tab_switch")
                self._focus_first_row_in_current_table()

            elif button_code in BUTTONS['next_tab']:  # RB
                current_index = self.winetricks_dialog.tab_widget.currentIndex()
                new_index = min(self.winetricks_dialog.tab_widget.count() - 1, current_index + 1)
                self.winetricks_dialog.tab_widget.setCurrentIndex(new_index)
                if new_index != current_index:
                    SoundManager().play("tab_switch")
                self._focus_first_row_in_current_table()

            else:
                self._parent.activateFocusedWidget()

        except Exception as e:
            logger.error(f"Error in handle_winetricks_button: {e}")

    def handle_winetricks_dpad(self, code, value, now):
        if self.winetricks_dialog is None:
            return
        try:
            if value == 0:  # Release
                self.dpad_timer.stop()
                self.current_dpad_code = None
                self.current_dpad_value = 0
                return

            # Timer setup
            if self.current_dpad_code != code or self.current_dpad_value != value:
                self.dpad_timer.stop()
                self.dpad_timer.setInterval(150 if self.dpad_timer.isActive() else 300)
                self.dpad_timer.start()
                self.current_dpad_code = code
                self.current_dpad_value = value

            table = self._get_current_table()
            if not table or table.rowCount() == 0:
                return

            current_row = table.currentRow()

            if code == PAD_DPAD_Y:  # Up/Down
                step = -1 if value < 0 else 1
                new_row = current_row + step

                # Skip hidden rows
                while 0 <= new_row < table.rowCount() and table.isRowHidden(new_row):
                    new_row += step

                # Bounds check
                if new_row < 0:
                    new_row = current_row
                if new_row >= table.rowCount():
                    new_row = current_row

                if new_row != current_row:
                    table.setCurrentCell(new_row, 0)
                    table.setFocus(Qt.FocusReason.OtherFocusReason)

        except Exception as e:
            logger.error(f"Error in handle_winetricks_dpad: {e}")

    def _get_current_table(self):
        if self.winetricks_dialog:
            current_container = self.winetricks_dialog.tab_widget.currentWidget()
            if isinstance(current_container, QStackedWidget):
                current_table = current_container.widget(1)
                if isinstance(current_table, QTableWidget):
                    return current_table
        return None

    def _focus_first_row_in_current_table(self):
        table = self._get_current_table()
        if table and table.rowCount() > 0:
            table.setCurrentCell(0, 0)
            table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _get_navigable_menu_actions(self, menu: QMenu) -> list:
        return [
            action
            for action in menu.actions()
            if not action.isSeparator() and action.isEnabled() and action.isVisible()
        ]

    def _navigate_menu_actions(self, menu: QMenu, direction_down: bool) -> None:
        actions = self._get_navigable_menu_actions(menu)
        if not actions:
            return
        current_action = menu.activeAction()
        if current_action not in actions:
            target_index = 0 if direction_down else len(actions) - 1
            menu.setActiveAction(actions[target_index])
            SoundManager().play("navigate")
            return
        current_index = actions.index(current_action)
        step = 1 if direction_down else -1
        next_index = (current_index + step) % len(actions)
        menu.setActiveAction(actions[next_index])
        SoundManager().play("navigate")

    # TABLE NAVIGATION METHODS
    def handle_table_navigation(self, table: QTableWidget, code: int, value: int):
        """
        Handle navigation in table

        Args:
            table: QTableWidget for navigation handling
            code: Event code (usually ABS_HAT0X or ABS_HAT0Y)
            value: Event value (direction)
        """
        row_count = table.rowCount()
        if row_count <= 0:
            return
        current_row = table.currentRow()
        if current_row < 0:
            current_row = 0
            table.setCurrentCell(0, 0)

        if code == PAD_DPAD_Y and value != 0:
            # Vertical navigation
            if value > 0:  # Down
                new_row = min(current_row + 1, row_count - 1)
            elif value < 0:  # Up
                new_row = max(current_row - 1, 0)
            else:
                return

            table.setCurrentCell(new_row, table.currentColumn())
            item = table.item(new_row, table.currentColumn())
            if item:
                table.scrollToItem(
                    item,
                    QAbstractItemView.ScrollHint.PositionAtCenter
                )
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        elif code == PAD_DPAD_X and value != 0:
            # Horizontal navigation
            col_count = table.columnCount()
            current_col = table.currentColumn()
            if current_col < 0:
                current_col = 0

            if value < 0:  # Left
                new_col = max(current_col - 1, 0)
            elif value > 0:  # Right
                new_col = min(current_col + 1, col_count - 1)
            else:
                return

            table.setCurrentCell(table.currentRow(), new_col)
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return

    def handle_table_confirm(self, table: QTableWidget):
        """
        Handle confirmation (e.g., A press) for table

        Args:
            table: QTableWidget for confirmation handling
        """
        current_row = table.currentRow()
        current_col = table.currentColumn()
        if current_row >= 0 and current_col >= 0:
            cell_widget = table.cellWidget(current_row, current_col)
            if isinstance(cell_widget, QCheckBox) and cell_widget.isEnabled():
                cell_widget.setChecked(not cell_widget.isChecked())
                return True
            if cell_widget is not None:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox and checkbox.isEnabled():
                    checkbox.setChecked(not checkbox.isChecked())
                    return True

            # Check if the cell contains a checkbox
            item = table.item(current_row, current_col)
            if (item and item.data(Qt.ItemDataRole.CheckStateRole) is not None
                    and item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                # Toggle the checkbox state
                new_state = Qt.CheckState.Checked if item.checkState() == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
                item.setCheckState(new_state)
                return True

            # Call custom confirm callback if exists
            callback = getattr(table, '_on_confirm_callback', None)  # type: ignore
            if callback and callable(callback):
                callback(table, current_row, current_col)
                return True

    # WIDGET NAVIGATION METHODS
    def setup_widget_navigation(self, widget: QWidget, navigation_type: str = "default", **kwargs):
        """
        Set navigation for widget

        Args:
            widget: QWidget for navigation setup
            navigation_type: Navigation type ('table', 'list', 'combo', 'default')
            **kwargs: Additional parameters for navigation
        """
        widget.installEventFilter(cast(QObject, self))
        # Use direct assignment for custom navigation properties, with type ignore for pyright
        widget._navigation_type = navigation_type  # type: ignore
        for key, value in kwargs.items():
            setattr(widget, f'_{key}', value)

    def handle_widget_navigation(self, widget: QWidget, code: int, value: int):
        """
        Handle navigation in widget

        Args:
            widget: QWidget for navigation handling
            code: Event code (usually ABS_HAT0X or ABS_HAT0Y)
            value: Event value (direction)
        """
        nav_type = getattr(widget, '_navigation_type', 'default')  # type: ignore

        if nav_type == 'table' and isinstance(widget, QTableWidget):
            self.handle_table_navigation(widget, code, value)
        elif nav_type == 'list' and isinstance(widget, QListWidget):
            self.handle_list_navigation(widget, code, value)
        elif nav_type == 'combo' and isinstance(widget, QComboBox):
            self.handle_combo_navigation(widget, code, value)
        else:
            # Default navigation behavior
            if isinstance(widget, QTableWidget):
                self.handle_table_navigation(widget, code, value)
            elif isinstance(widget, QListWidget):
                self.handle_list_navigation(widget, code, value)
            elif isinstance(widget, QComboBox):
                self.handle_combo_navigation(widget, code, value)

    def handle_list_navigation(self, list_widget: QListWidget, code: int, value: int):
        """
        Handle navigation in list

        Args:
            list_widget: QListWidget for navigation handling
            code: Event code (usually ABS_HAT0X or ABS_HAT0Y)
            value: Event value (direction)
        """
        if code == PAD_DPAD_Y and value != 0:
            model = list_widget.model()
            current_index = list_widget.currentIndex()
            if model and current_index.isValid():
                row_count = model.rowCount()
                current_row = current_index.row()
                if value > 0:  # Down
                    next_row = min(current_row + 1, row_count - 1)
                    list_widget.setCurrentIndex(model.index(next_row, current_index.column()))
                elif value < 0:  # Up
                    prev_row = max(current_row - 1, 0)
                    list_widget.setCurrentIndex(model.index(prev_row, current_index.column()))
                list_widget.scrollTo(list_widget.currentIndex(), QListView.ScrollHint.PositionAtCenter)

    def handle_combo_navigation(self, combo_widget: QComboBox, code: int, value: int):
        """
        Handle navigation in combo widget

        Args:
            combo_widget: QComboBox for navigation handling
            code: Event code (usually ABS_HAT0X or ABS_HAT0Y)
            value: Event value (direction)
        """
        if code == PAD_DPAD_Y and value != 0:
            current_index = combo_widget.currentIndex()
            if value > 0:  # Down
                new_index = min(current_index + 1, combo_widget.count() - 1)
            elif value < 0:  # Up
                new_index = max(current_index - 1, 0)
            else:
                return

            if new_index != current_index:
                combo_widget.setCurrentIndex(new_index)

    def _setup_mode_handlers(self, dialog_instance, button_handler, dpad_handler, dialog_attr_name):
        """Register a dialog as the active input surface."""
        if not self._input_surfaces:
            self._input_surface_base_state = self._gamepad_handling_enabled
        previous_surface = next(
            (surface for surface in self._input_surfaces if surface.name == dialog_attr_name),
            None,
        )
        if previous_surface is not None:
            for signal, callback in previous_surface.connections:
                signal.disconnect(callback)
        self._input_surfaces = [
            surface for surface in self._input_surfaces
            if surface.name != dialog_attr_name
        ]
        surface = InputSurface(
            dialog_attr_name,
            dialog_instance,
            button_handler,
            dpad_handler,
        )
        self._input_surfaces.append(surface)
        setattr(self, dialog_attr_name, dialog_instance)
        self._gamepad_handling_enabled = True
        self._reset_surface_navigation()

    def _restore_original_handlers(self, dialog_attr_name):
        """Remove a dialog input surface and restore the preceding surface."""
        surface = next(
            (item for item in reversed(self._input_surfaces) if item.name == dialog_attr_name),
            None,
        )
        if surface is None:
            logger.warning("Cannot restore input surface: %s is not registered", dialog_attr_name)
            return
        for signal, callback in surface.connections:
            signal.disconnect(callback)
        self._input_surfaces.remove(surface)
        setattr(self, dialog_attr_name, None)
        if not self._input_surfaces and self._input_surface_base_state is not None:
            self._gamepad_handling_enabled = self._input_surface_base_state
            self._input_surface_base_state = None
        self._reset_surface_navigation()

    def connect_surface_updates(
        self,
        dialog_attr_name: str,
        callback: Callable[..., Any],
    ) -> None:
        """Connect a callback for the lifetime of a dialog input surface."""
        surface = next(
            (item for item in reversed(self._input_surfaces) if item.name == dialog_attr_name),
            None,
        )
        if surface is None:
            logger.warning("Cannot connect input surface: %s is not registered", dialog_attr_name)
            return
        for signal in (self.button_event, self.dpad_moved):
            signal.connect(callback)
            surface.connections.append((signal, callback))

    def connect_surface_signal(
        self,
        dialog_attr_name: str,
        signal: Any,
        callback: Callable[..., Any],
    ) -> None:
        """Connect one signal for the lifetime of a dialog input surface."""
        surface = next(
            (item for item in reversed(self._input_surfaces) if item.name == dialog_attr_name),
            None,
        )
        if surface is None:
            logger.warning("Cannot connect input surface: %s is not registered", dialog_attr_name)
            return
        signal.connect(callback)
        surface.connections.append((signal, callback))

    def _reset_surface_navigation(self) -> None:
        self.dpad_timer.stop()
        self.current_dpad_code = None
        self.current_dpad_value = 0

    def _route_surface_button(self, button_code: int, value: int) -> bool:
        if not self._input_surfaces:
            return False
        self._input_surfaces[-1].button_handler(button_code, value)
        return True

    def _route_surface_dpad(self, code: int, value: int, current_time: float) -> bool:
        if not self._input_surfaces:
            return False
        self._input_surfaces[-1].dpad_handler(code, value, current_time)
        return True

    # PROTON MANAGER SUPPORT
    def enable_proton_manager_mode(self, proton_manager_dialog):
        """Setup gamepad handling for ProtonManagerDialog"""
        try:
            self._setup_mode_handlers(
                proton_manager_dialog,
                self.handle_proton_manager_button,
                self.handle_proton_manager_dpad,
                'proton_manager_dialog'
            )
            logger.debug("Gamepad handling successfully connected for ProtonManager")
        except Exception as e:
            logger.error(f"Error connecting gamepad handlers for ProtonManager: {e}")

    def disable_proton_manager_mode(self):
        """Restore original main window handlers"""
        try:
            if self.proton_manager_dialog:
                self._restore_original_handlers('proton_manager_dialog')
                logger.debug("Gamepad handling successfully restored from ProtonManager")
        except Exception as e:
            logger.error(f"Error restoring gamepad handlers from ProtonManager: {e}")

    def handle_proton_manager_button(self, button_code, value):
        if self.proton_manager_dialog is None or value == 0:
            return

        try:
            # Handle common UI elements like QMessageBox, QMenu, etc.
            if self._handle_common_ui_elements(button_code):
                return

            # ProtonManager-specific button handling
            focused = QApplication.focusWidget()

            if button_code in BUTTONS['confirm']:  # A: Toggle checkbox
                if isinstance(focused, QTableWidget):
                    current_row = focused.currentRow()
                    if current_row >= 0:
                        checkbox_widget = focused.cellWidget(current_row, 0)
                        if checkbox_widget:
                            checkbox = checkbox_widget.findChild(QCheckBox)
                            if checkbox and checkbox.isEnabled():
                                checkbox.setChecked(not checkbox.isChecked())
                return

            elif button_code in BUTTONS['add_game']:  # X: Download
                self.proton_manager_dialog.download_selected()

            elif button_code in BUTTONS['prev_dir']:  # Y: Clear
                self.proton_manager_dialog.clear_selection()

            elif button_code in BUTTONS['back']:  # B: Cancel/Close
                # Cancel any active downloads/extractions before closing
                if (self.proton_manager_dialog.current_extraction_thread and
                    self.proton_manager_dialog.current_extraction_thread.isRunning()) or \
                   (self.proton_manager_dialog.current_download_thread and
                    hasattr(self.proton_manager_dialog.current_download_thread, 'isRunning') and
                    self.proton_manager_dialog.current_download_thread.isRunning()):
                    # If there's an active download/extraction, cancel it
                    self.proton_manager_dialog.cancel_current_download()
                else:
                    # If no active processes, just close the dialog
                    self.proton_manager_dialog.reject()

            elif button_code in BUTTONS['prev_tab']:  # LB: Previous tab
                current_index = self.proton_manager_dialog.tab_widget.currentIndex()
                new_index = max(0, current_index - 1)
                self.proton_manager_dialog.tab_widget.setCurrentIndex(new_index)
                if new_index != current_index:
                    SoundManager().play("tab_switch")
                self._focus_first_row_in_current_proton_manager_table()

            elif button_code in BUTTONS['next_tab']:  # RB: Next tab
                current_index = self.proton_manager_dialog.tab_widget.currentIndex()
                new_index = min(self.proton_manager_dialog.tab_widget.count() - 1, current_index + 1)
                self.proton_manager_dialog.tab_widget.setCurrentIndex(new_index)
                if new_index != current_index:
                    SoundManager().play("tab_switch")
                self._focus_first_row_in_current_proton_manager_table()

            else:
                self._parent.activateFocusedWidget()

        except Exception as e:
            logger.error(f"Error in handle_proton_manager_button: {e}")

    def handle_proton_manager_dpad(self, code, value, now):
        if self.proton_manager_dialog is None:
            return

        try:
            if value == 0:  # Release
                self.dpad_timer.stop()
                self.current_dpad_code = None
                self.current_dpad_value = 0
                return

            # Timer setup
            if self.current_dpad_code != code or self.current_dpad_value != value:
                self.dpad_timer.stop()
                self.dpad_timer.setInterval(150 if self.dpad_timer.isActive() else 300)
                self.dpad_timer.start()
                self.current_dpad_code = code
                self.current_dpad_value = value

            table = self._get_current_proton_manager_table()
            if not table or table.rowCount() == 0:
                return

            current_row = table.currentRow()

            if code == PAD_DPAD_Y:  # Up/Down
                step = -1 if value < 0 else 1
                new_row = current_row + step

                # Skip hidden rows
                while 0 <= new_row < table.rowCount() and table.isRowHidden(new_row):
                    new_row += step

                # Bounds check
                if new_row < 0:
                    new_row = current_row
                if new_row >= table.rowCount():
                    new_row = current_row

                if new_row != current_row:
                    table.setCurrentCell(new_row, 0)
                    table.setFocus(Qt.FocusReason.OtherFocusReason)

        except Exception as e:
            logger.error(f"Error in handle_proton_manager_dpad: {e}")

    def _get_current_proton_manager_table(self):
        if self.proton_manager_dialog:
            current_container = self.proton_manager_dialog.tab_widget.currentWidget()
            if current_container:
                table = current_container.findChild(QTableWidget)
                return table
        return None

    def _focus_first_row_in_current_proton_manager_table(self):
        table = self._get_current_proton_manager_table()
        if table and table.rowCount() > 0:
            table.setCurrentCell(0, 0)
            table.setFocus(Qt.FocusReason.OtherFocusReason)

    def enable_appimage_update_mode(self, appimage_update_dialog):
        """Setup gamepad handling for AppImageUpdateDialog"""
        try:
            self._setup_mode_handlers(
                appimage_update_dialog,
                self.handle_appimage_update_button,
                self.handle_appimage_update_dpad,
                'appimage_update_dialog'
            )
            logger.debug("Gamepad handling successfully connected for AppImageUpdateDialog")
        except Exception as e:
            logger.error(f"Error connecting gamepad handlers for AppImageUpdateDialog: {e}")

    def disable_appimage_update_mode(self):
        """Restore original main window handlers"""
        try:
            if self.appimage_update_dialog:
                self._restore_original_handlers('appimage_update_dialog')
                logger.debug("Gamepad handling successfully restored from AppImageUpdateDialog")
        except Exception as e:
            logger.error(f"Error restoring gamepad handlers from AppImageUpdateDialog: {e}")

    def handle_appimage_update_button(self, button_code, value):
        if self.appimage_update_dialog is None or value == 0:
            return

        try:
            if self._handle_common_ui_elements(button_code):
                return

            focused = QApplication.focusWidget()

            if button_code in BUTTONS['confirm']:
                if isinstance(focused, AutoSizeButton):
                    focused.click()
                return

            elif button_code in BUTTONS['back']:
                self.appimage_update_dialog.reject()
                return

            self._parent.activateFocusedWidget()

        except Exception as e:
            logger.error(f"Error in handle_appimage_update_button: {e}")

    def handle_appimage_update_dpad(self, code, value, now):
        if self.appimage_update_dialog is None:
            return

        try:
            if value == 0:
                self.dpad_timer.stop()
                self.current_dpad_code = None
                self.current_dpad_value = 0
                return

            if self.current_dpad_code != code or self.current_dpad_value != value:
                self.dpad_timer.stop()
                self.dpad_timer.setInterval(150 if self.dpad_timer.isActive() else 300)
                self.dpad_timer.start()
                self.current_dpad_code = code
                self.current_dpad_value = value

            changelog = self.appimage_update_dialog.changelog_text
            buttons = self.appimage_update_dialog.action_buttons

            if changelog and changelog.hasFocus():
                if code == PAD_DPAD_Y and value != 0:
                    scrollbar = changelog.verticalScrollBar()
                    at_bottom = scrollbar.value() >= scrollbar.maximum()
                    at_top = scrollbar.value() <= scrollbar.minimum()
                    if value > 0 and at_bottom:
                        if buttons:
                            buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)
                        return
                    if value < 0 and at_top:
                        return
                    step = 40
                    scrollbar.setValue(scrollbar.value() + (step if value > 0 else -step))
                return

            if code == PAD_DPAD_Y and value != 0 and buttons:
                focused = QApplication.focusWidget()
                if focused in buttons:
                    if value < 0 and focused == buttons[0]:
                        if changelog:
                            changelog.setFocus(Qt.FocusReason.OtherFocusReason)
                        return

            if code == PAD_DPAD_X and value != 0 and buttons:
                focused = QApplication.focusWidget()
                if focused in buttons:
                    idx = buttons.index(focused)
                    if value < 0:
                        new_idx = max(0, idx - 1)
                    else:
                        new_idx = min(len(buttons) - 1, idx + 1)
                    buttons[new_idx].setFocus(Qt.FocusReason.OtherFocusReason)
                else:
                    buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)

        except Exception as e:
            logger.error(f"Error in handle_appimage_update_dpad: {e}")
