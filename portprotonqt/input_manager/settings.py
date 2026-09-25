from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

from portprotonqt.input_manager.constants import (
    BUTTONS,
    PAD_AXIS_LEFT_X,
    PAD_AXIS_LEFT_Y,
    PAD_DPAD_X,
    PAD_DPAD_Y,
)
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager

logger = get_logger(__name__)


class SettingsInputMixin(InputMixin):
    # SETTINGS MODE
    def enable_settings_mode(self, settings_dialog):
        """Setup gamepad handling for ExeSettingsDialog"""
        try:
            self._setup_mode_handlers(
                settings_dialog,
                self.handle_settings_button,
                self.handle_settings_dpad,
                'settings_dialog'
            )
            logger.debug("Gamepad handling successfully connected for SettingsDialog")
        except Exception as e:
            logger.error(f"Error connecting gamepad handlers for SettingsDialog: {e}")

    def disable_settings_mode(self):
        """Restore original main window handlers"""
        try:
            if self.settings_dialog:
                self._restore_original_handlers('settings_dialog')
                logger.debug("Gamepad handling successfully restored from Settings")
        except Exception as e:
            logger.error(f"Error restoring gamepad handlers from Settings: {e}")

    def handle_settings_button(self, button_code, value):
        if self.settings_dialog is None:
            return

        try:
            # 1. Virtual Keyboard Handling
            kb = getattr(self.settings_dialog, 'keyboard', None)
            if kb and kb.isVisible():
                if button_code in BUTTONS['back']:
                    if value != 0:  # Only handle press, not release
                        kb.hide()
                        if kb.current_input_widget:
                            kb.current_input_widget.setFocus()
                    return  # Return early to avoid dialog closing logic
                elif button_code in (BUTTONS['confirm'] | BUTTONS['context_menu']):
                    if value != 0:  # Only handle press, not release
                        kb.activateFocusedKey()
                    return
                elif button_code in BUTTONS['prev_tab']:
                    if value != 0:  # Only handle press, not release
                        kb.on_lang_click()
                    return
                elif button_code in BUTTONS['next_tab']:
                    if value != 0:  # Only handle press, not release
                        kb.on_shift_click(not kb.shift_pressed)
                    return
                elif button_code in BUTTONS['add_game']:
                    if value != 0:  # Press event
                        kb.on_backspace_pressed()
                    else:  # Release event
                        kb.stop_backspace_repeat()
                    return

            # Handle common UI elements like QMessageBox, QMenu, etc.
            # Only handle press events (value != 0), ignore release events
            if value != 0 and self._handle_common_ui_elements(button_code):
                return

            # Handle other QDialogs
            if value != 0:  # Only handle press events, not releases
                popup = QApplication.activePopupWidget()
                if isinstance(popup, QDialog):
                    if button_code in BUTTONS['confirm']:
                        popup.accept()
                    elif button_code in BUTTONS['back']:
                        popup.reject()
                    return

                # 3. Combo Box popup handling in settings (Advanced + MangoHud)
                table = self._get_current_settings_table()
                open_combo = self._get_open_settings_combo()

                # B Button - Close combo or dialog
                if button_code in BUTTONS['back']:
                    if open_combo:
                        open_combo.hidePopup()
                        if open_combo.isEditable() and open_combo.lineEdit() is not None:
                            open_combo.lineEdit().setFocus()
                        else:
                            open_combo.setFocus()
                    else:
                        self.settings_dialog.reject()
                    return

                if button_code in BUTTONS['context_menu']:
                    handler = getattr(self.settings_dialog, "handle_settings_context_menu", None)
                    if callable(handler) and handler():
                        return

                # A Button - Confirm
                if button_code in BUTTONS['confirm']:
                    if open_combo:
                        view = open_combo.view()
                        if view.currentIndex().isValid():
                            open_combo.setCurrentIndex(view.currentIndex().row())
                        open_combo.hidePopup()
                        if open_combo.isEditable() and open_combo.lineEdit() is not None:
                            open_combo.lineEdit().setFocus()
                        else:
                            open_combo.setFocus()
                        return

                    # Standard interaction
                    focused = QApplication.focusWidget()
                    if isinstance(focused, QCheckBox) and focused.isEnabled():
                        focused.setChecked(not focused.isChecked())
                        return
                    if isinstance(focused, QPushButton) and focused.isEnabled():
                        focused.click()
                        return
                    combo_from_focus = None
                    if isinstance(focused, QComboBox):
                        combo_from_focus = focused
                    else:
                        parent = focused.parentWidget() if focused else None
                        if isinstance(parent, QComboBox):
                            combo_from_focus = parent
                    if combo_from_focus and combo_from_focus.isEnabled():
                        combo_from_focus.showPopup()
                        combo_from_focus.setFocus()
                        return
                    if isinstance(focused, QTableWidget) and table and focused.currentRow() >= 0:
                        # Main settings (checkboxes)
                        if self.settings_dialog and table == self.settings_dialog.settings_table:
                            self.handle_table_confirm(focused)
                            return

                        # Advanced settings
                        cell = focused.cellWidget(focused.currentRow(), 1)
                        if isinstance(cell, QComboBox) and cell.isEnabled():
                            cell.showPopup()
                            cell.setFocus()
                            return
                        if isinstance(cell, QLineEdit):
                            cell.setFocus()
                            self.settings_dialog.show_virtual_keyboard(cell)
                            return

                    if isinstance(focused, QLineEdit):
                        self.settings_dialog.show_virtual_keyboard(focused)
                        return
                    if self._is_current_settings_tool_tab():
                        if isinstance(focused, QCheckBox):
                            focused.toggle()
                            return
                        if isinstance(focused, QPushButton):
                            focused.click()
                            return
                        if isinstance(focused, QComboBox):
                            focused.showPopup()
                            return
                        self._parent.activateFocusedWidget()
                    return

                # 4. Global Shortcuts
                if button_code in BUTTONS['add_game']:  # X: Apply
                    self.settings_dialog.apply_changes()

                elif button_code in BUTTONS['prev_dir']:  # Y: Search + Keyboard
                    focused = QApplication.focusWidget()
                    focused_combo = None
                    if isinstance(focused, QTableWidget) and self.settings_dialog:
                        table = self._get_current_settings_table()
                        if table is not None and table == self.settings_dialog.advanced_table:
                            row = focused.currentRow()
                            if row >= 0:
                                cell_widget = focused.cellWidget(row, 1)
                                if isinstance(cell_widget, QComboBox):
                                    focused_combo = cell_widget
                    if focused_combo is None:
                        if isinstance(focused, QComboBox):
                            focused_combo = focused
                        else:
                            parent = focused.parentWidget() if focused else None
                            if isinstance(parent, QComboBox):
                                focused_combo = parent
                    if focused_combo and focused_combo.isEditable() and focused_combo.isEnabled():
                        line_edit = focused_combo.lineEdit()
                        if line_edit is not None:
                            line_edit.setFocus()
                            self.settings_dialog.show_virtual_keyboard(line_edit)
                            return
                    self.settings_dialog.search_edit.setFocus()
                    self.settings_dialog.show_virtual_keyboard(self.settings_dialog.search_edit)

                elif button_code in BUTTONS['prev_tab']:  # LB
                    current_index = self.settings_dialog.tab_widget.currentIndex()
                    idx = max(0, current_index - 1)
                    self.settings_dialog.tab_widget.setCurrentIndex(idx)
                    if idx != current_index:
                        SoundManager().play("tab_switch")
                    self._focus_first_row_in_current_settings_table()

                elif button_code in BUTTONS['next_tab']:  # RB
                    current_index = self.settings_dialog.tab_widget.currentIndex()
                    idx = min(self.settings_dialog.tab_widget.count() - 1, current_index + 1)
                    self.settings_dialog.tab_widget.setCurrentIndex(idx)
                    if idx != current_index:
                        SoundManager().play("tab_switch")
                    self._focus_first_row_in_current_settings_table()

                else:
                    self._parent.activateFocusedWidget()

        except Exception as e:
            logger.error(f"Error in handle_settings_button: {e}")

    def handle_settings_dpad(self, code, value, now):
        if self.settings_dialog is None:
            return

        try:
            # 1. Virtual Keyboard Navigation
            kb = getattr(self.settings_dialog, 'keyboard', None)
            if kb and kb.isVisible():
                normalized_value = 0

                # Normalize Stick vs D-pad
                if code in (PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y):  # Sticks
                    if abs(value) < self.dead_zone:
                        self.current_dpad_code = None
                        self.current_dpad_value = 0
                        self.dpad_timer.stop()
                        return
                    normalized_value = 1 if value > self.dead_zone else -1
                else:  # D-pad
                    normalized_value = value

                if normalized_value != 0:
                    if code in (PAD_DPAD_X, PAD_AXIS_LEFT_X):
                        if normalized_value > 0:
                            kb.move_focus_right()
                        else:
                            kb.move_focus_left()
                    elif code in (PAD_DPAD_Y, PAD_AXIS_LEFT_Y):
                        if normalized_value > 0:
                            kb.move_focus_down()
                        else:
                            kb.move_focus_up()
                return

            if self._is_current_settings_tool_tab():
                focused = QApplication.focusWidget()
                open_combo = self._get_open_settings_combo()
                if open_combo:
                    if code == PAD_DPAD_Y and value != 0:
                        view = open_combo.view()
                        model = view.model()
                        current_index = view.currentIndex()
                        if model and current_index.isValid():
                            row_count = model.rowCount()
                            current_row = current_index.row()
                            if value > 0:
                                next_row = min(current_row + 1, row_count - 1)
                            else:
                                next_row = max(current_row - 1, 0)
                            new_index = model.index(next_row, current_index.column())
                            view.setCurrentIndex(new_index)
                            view.scrollTo(new_index, QAbstractItemView.ScrollHint.PositionAtCenter)
                    return

                if code not in (PAD_DPAD_X, PAD_DPAD_Y, PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y):
                    return

                normalized_value = value
                if code in (PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y):
                    if abs(value) < self.dead_zone:
                        normalized_value = 0
                    else:
                        normalized_value = 1 if value > 0 else -1

                if normalized_value == 0:
                    self.dpad_timer.stop()
                    self.current_dpad_code = None
                    self.current_dpad_value = 0
                    return

                if code in (PAD_DPAD_X, PAD_DPAD_Y):
                    if self.current_dpad_code != code or self.current_dpad_value != normalized_value:
                        self.dpad_timer.stop()
                        self.dpad_timer.setInterval(120 if self.dpad_timer.isActive() else 220)
                        self.dpad_timer.start()
                        self.current_dpad_code = code
                        self.current_dpad_value = normalized_value

                sections = self._get_mangohud_nav_sections()
                if not sections:
                    return

                if not focused or not self._find_widget_in_sections(focused, sections):
                    self._focus_first_row_in_current_settings_table()
                    return

                if code in (PAD_DPAD_X, PAD_AXIS_LEFT_X):
                    self._move_mangohud_horizontal(focused, normalized_value, sections)
                elif code in (PAD_DPAD_Y, PAD_AXIS_LEFT_Y):
                    self._move_mangohud_vertical(focused, normalized_value, sections)
                return

            # 2. Combo Box Navigation (within Advanced and Main Tables)
            table = self._get_current_settings_table()
            if not table or table.rowCount() == 0:
                return

            combo_tables = (
                self.settings_dialog.advanced_table,
                self.settings_dialog.settings_table,
            )
            if self.settings_dialog and table in combo_tables and table.currentRow() >= 0:
                cell_widget = table.cellWidget(table.currentRow(), 1)
                if isinstance(cell_widget, QComboBox) and cell_widget.view().isVisible():
                    if code == PAD_DPAD_Y and value != 0:
                        idx = cell_widget.currentIndex()
                        new_idx = max(0, idx - 1) if value < 0 else min(cell_widget.count() - 1, idx + 1)
                        if new_idx != idx:
                            cell_widget.setCurrentIndex(new_idx)
                    return  # Consume event

            # 3. Standard Table Navigation
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

            current_row = table.currentRow()

            if code == PAD_DPAD_Y:  # Up/Down
                step = -1 if value < 0 else 1
                new_row = current_row + step

                while 0 <= new_row < table.rowCount() and table.isRowHidden(new_row):
                    new_row += step

                if 0 <= new_row < table.rowCount():
                    focus_column = 1
                    table.setCurrentCell(new_row, focus_column)
                    self._focus_settings_advanced_value_widget(table, new_row)

            elif code == PAD_DPAD_X:  # Left/Right
                if self._move_settings_inline_button_focus(table, value):
                    return
                current_col = table.currentColumn()
                if value < 0:  # Left
                    if current_col > 0:
                        new_col = max(0, current_col - 1)
                        table.setCurrentCell(current_row, new_col)
                        if new_col == 1:
                            self._focus_settings_advanced_value_widget(table, current_row)
                        else:
                            table.setFocus(Qt.FocusReason.OtherFocusReason)
                else:  # Right
                    if current_col < table.columnCount() - 1:
                        new_col = min(table.columnCount() - 1, current_col + 1)
                        table.setCurrentCell(current_row, new_col)
                        if new_col == 1:
                            self._focus_settings_advanced_value_widget(table, current_row)
                        else:
                            table.setFocus(Qt.FocusReason.OtherFocusReason)

        except Exception as e:
            logger.error(f"Error in handle_settings_dpad: {e}")

    def _get_current_settings_table(self) -> QTableWidget | None:
        if not self.settings_dialog:
            return None
        getter = getattr(self.settings_dialog, "_get_current_settings_table", None)
        if callable(getter):
            table = getter()
            if isinstance(table, QTableWidget):
                return table
        return None

    def _is_current_settings_tool_tab(self):
        if not self.settings_dialog:
            return False
        current_tab = self.settings_dialog.tab_widget.currentWidget()
        return current_tab in (
            getattr(self.settings_dialog, "mangohud_tab", None),
            getattr(self.settings_dialog, "vkbasalt_tab", None),
            getattr(self.settings_dialog, "gamescope_tab", None),
        )

    def _get_open_settings_combo(self):
        """Return currently opened combo popup in settings dialog if any."""
        if not self.settings_dialog:
            return None
        for combo in self.settings_dialog.findChildren(
            QComboBox, options=Qt.FindChildOption.FindChildrenRecursively
        ):
            if combo.isVisible() and combo.view().isVisible():
                return combo
        return None

    def _focus_settings_advanced_value_widget(self, table, row):
        """Focus value widget in settings row when available."""
        if not self.settings_dialog:
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        if table == self.settings_dialog.settings_table:
            cell_widget = table.cellWidget(row, 1)
            if isinstance(cell_widget, QComboBox) and cell_widget.isEnabled():
                cell_widget.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            if cell_widget is not None:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox and checkbox.isEnabled():
                    checkbox.setFocus(Qt.FocusReason.OtherFocusReason)
                    return
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        if table == getattr(self.settings_dialog, "favorites_table", None):
            cell_widget = table.cellWidget(row, 1)
            if isinstance(cell_widget, (QCheckBox, QComboBox, QLineEdit)):
                cell_widget.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            if cell_widget is not None:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox and checkbox.isEnabled():
                    checkbox.setFocus(Qt.FocusReason.OtherFocusReason)
                    return
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        if table != self.settings_dialog.advanced_table:
            table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        cell_widget = table.cellWidget(row, 1)
        if isinstance(cell_widget, QComboBox):
            line_edit = cell_widget.lineEdit()
            if cell_widget.isEditable() and line_edit is not None:
                line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                cell_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if isinstance(cell_widget, QLineEdit):
            cell_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if (
            cell_widget is not None
            and cell_widget.property("ppqt_run_after_exe_widget")
        ):
            line_edit = cell_widget.findChild(QLineEdit)
            if line_edit and line_edit.isEnabled():
                line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
                return
        table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _move_settings_inline_button_focus(self, table: QTableWidget, value: int) -> bool:
        """Move focus between inline line edit and button in settings cell."""
        if not self.settings_dialog or table != self.settings_dialog.advanced_table:
            return False
        if table.currentColumn() != 1:
            return False

        cell_widget = table.cellWidget(table.currentRow(), 1)
        if cell_widget is None or not cell_widget.property("ppqt_run_after_exe_widget"):
            return False

        line_edit = cell_widget.findChild(QLineEdit)
        button = cell_widget.findChild(QPushButton)
        focused = QApplication.focusWidget()
        if value > 0 and focused == line_edit and button and button.isEnabled():
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        if value < 0 and focused == button and line_edit and line_edit.isEnabled():
            line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        return False

    def _focus_first_row_in_current_settings_table(self):
        table = self._get_current_settings_table()
        if table and table.rowCount() > 0:
            col = 1
            table.setCurrentCell(0, col)
            self._focus_settings_advanced_value_widget(table, 0)
            return

        if self._is_current_settings_tool_tab():
            sections = self._get_mangohud_nav_sections()
            if sections and sections[0]:
                self._focus_mangohud_widget(sections[0][0])
