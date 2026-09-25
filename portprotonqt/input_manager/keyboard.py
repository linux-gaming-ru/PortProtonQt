import os
import time
from typing import cast

from shiboken6 import isValid
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QWidget,
)

from portprotonqt.custom_widgets import AutoSizeButton
from portprotonqt.game_card import AnimatedCard, GameCard
from portprotonqt.image_utils import FullscreenDialog
from portprotonqt.input_manager.constants import (
    BUTTONS,
    KEY_BACKSPACE,
    KEY_DOWN,
    KEY_E,
    KEY_ENTER,
    KEY_ESCAPE,
    KEY_F5,
    KEY_F10,
    KEY_F11,
    KEY_LEFT,
    KEY_Q,
    KEY_RETURN,
    KEY_RIGHT,
    KEY_UP,
    MOD_CTRL,
    MOD_SHIFT,
    PAD_DPAD_X,
    PAD_DPAD_Y,
)
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager
from portprotonqt.virtual_keyboard import VirtualKeyboard

logger = get_logger(__name__)


class KeyboardInputMixin(InputMixin):
    def handle_virtual_keyboard(self, button_code: int, value: int) -> None:
        active_window = QApplication.activeWindow()
        keyboard = getattr(active_window, 'keyboard', None) if active_window else None
        if keyboard is None:
            keyboard = getattr(self._parent, 'keyboard', None)

        if not keyboard or not isinstance(keyboard, VirtualKeyboard) or not keyboard.isVisible():
            return

        # Handle gamepad buttons
        if button_code in BUTTONS['confirm']:  # A/Cross button - confirm
            if value == 1:
                keyboard.activateFocusedKey()
        elif button_code in BUTTONS['back']:  # B/Circle button - hide keyboard
            if value == 1:
                keyboard.hide()
                # Return focus to input field
                if keyboard.current_input_widget:
                    keyboard.current_input_widget.setFocus()
        elif button_code in BUTTONS['prev_tab']:  # LB/L1 - switch layout
            if value == 1:
                keyboard.on_lang_click()
        elif button_code in BUTTONS['next_tab']:  # RB/R1 - toggle Shift
            if value == 1:
                keyboard.on_shift_click(not keyboard.shift_pressed)
        elif button_code in BUTTONS['context_menu']:  # Start button - confirm
            if value == 1:
                keyboard.activateFocusedKey()
        elif button_code in BUTTONS['menu']:  # Select button - hide keyboard
            if value == 1:
                keyboard.hide()
                # Return focus to input field
                if keyboard.current_input_widget:
                    keyboard.current_input_widget.setFocus()
        elif button_code in BUTTONS['add_game']:  # X button - Backspace (now holdable)
            if value == 1:
                keyboard.on_backspace_pressed()
            elif value == 0:
                keyboard.stop_backspace_repeat()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        app = QApplication.instance()
        if not app:
            return QObject.eventFilter(cast(QObject, self), obj, event)

        if event.type() == QEvent.Type.Show:
            if isinstance(obj, QMenu):
                SoundManager().play("open")
            elif isinstance(obj, QWidget) and obj.windowType() == Qt.WindowType.Popup:
                parent = obj.parent()
                while isinstance(parent, QObject):
                    if isinstance(parent, QComboBox):
                        if not parent.property("_sound_activated_connected"):
                            parent.activated.connect(
                                lambda _index: SoundManager().play("toggle"),
                            )
                            parent.setProperty("_sound_activated_connected", True)
                        break
                    parent = parent.parent()

        if event.type() == QEvent.Type.Wheel:
            combo = obj if isinstance(obj, QComboBox) else None
            parent = obj.parent() if isinstance(obj, QObject) else None
            while combo is None and isinstance(parent, QObject):
                if isinstance(parent, QComboBox):
                    combo = parent
                    break
                parent = parent.parent()
            if isinstance(combo, QComboBox) and not combo.view().isVisible():
                # Find parent scroll area
                scrollable = combo.parent()
                while scrollable:
                    if isinstance(scrollable, QAbstractScrollArea):
                        old_focus = QApplication.focusWidget()
                        QApplication.sendEvent(scrollable.viewport(), event)
                        if old_focus:
                            old_focus.setFocus()
                        return True
                    scrollable = scrollable.parent()
                return True

        if event.type() == QEvent.Type.KeyPress:
            if self._redirect_gamecard_input_to_search(event):
                return True
            key = self._qt_event_to_input_key(event)
            if key is not None:
                return self._handle_input_key_press(key, self._qt_modifiers_to_input(event))
        if event.type() == QEvent.Type.KeyRelease:
            key = self._qt_event_to_input_key(event)
            if key is not None:
                return self._handle_input_key_release(key)

        if event.type() == QEvent.Type.MouseButtonPress:
            button_method = getattr(event, "button", None)
            button = button_method() if callable(button_method) else None
            if button == Qt.MouseButton.ExtraButton1:
                self._handle_back_mouse_button()
                return True

        if event.type() == QEvent.Type.MouseButtonRelease:
            button_method = getattr(event, "button", None)
            button = button_method() if callable(button_method) else None
            if button == Qt.MouseButton.LeftButton:
                SoundManager().play_widget_sound(obj)

        # Ensure obj is a QObject
        if not isinstance(obj, QObject):
            logger.debug(f"Skipping event filter for non-QObject: {type(obj).__name__}")
            return False

        return QObject.eventFilter(cast(QObject, self), obj, event)

    def _qt_event_to_input_key(self, event: QEvent) -> int | None:
        native_key = self._native_scan_to_input_key(event)
        if native_key is not None:
            return native_key
        text_method = getattr(event, "text", None)
        text = text_method() if callable(text_method) else ""
        text = text if isinstance(text, str) else ""
        normalized_text = text.lower()
        if len(normalized_text) == 1 and normalized_text.isprintable():
            return ord(normalized_text)
        key_method = getattr(event, "key", None)
        key_value = key_method() if callable(key_method) else 0
        key = key_value if isinstance(key_value, int) else 0
        name = QKeySequence(key).toString()
        if len(name) == 1 and name.isprintable():
            return ord(name.lower())
        key_names = {
            "Backspace": KEY_BACKSPACE,
            "Down": KEY_DOWN,
            "Enter": KEY_ENTER,
            "Esc": KEY_ESCAPE,
            "F5": KEY_F5,
            "F10": KEY_F10,
            "F11": KEY_F11,
            "Left": KEY_LEFT,
            "Return": KEY_RETURN,
            "Right": KEY_RIGHT,
            "Up": KEY_UP,
        }
        return key_names.get(name)

    def _native_scan_to_input_key(self, event: QEvent) -> int | None:
        scan_method = getattr(event, "nativeScanCode", None)
        scan_value = scan_method() if callable(scan_method) else 0
        scan_code = scan_value if isinstance(scan_value, int) else 0
        scan_keys = {
            16: KEY_Q,
            18: KEY_E,
            24: KEY_Q,
            26: KEY_E,
        }
        return scan_keys.get(scan_code)

    def _qt_modifiers_to_input(self, event: QEvent) -> int:
        modifiers_method = getattr(event, "modifiers", None)
        modifiers = modifiers_method() if callable(modifiers_method) else None
        input_modifiers = 0
        if isinstance(modifiers, Qt.KeyboardModifier) and modifiers & Qt.KeyboardModifier.ControlModifier:
            input_modifiers |= MOD_CTRL
        if isinstance(modifiers, Qt.KeyboardModifier) and modifiers & Qt.KeyboardModifier.ShiftModifier:
            input_modifiers |= MOD_SHIFT
        return input_modifiers

    def _handle_back_mouse_button(self) -> None:
        active_win = QApplication.activeWindow()
        focused = self._focused_widget()
        if isinstance(focused, QLineEdit):
            return
        if isinstance(active_win, QDialog):
            SoundManager().play("back")
            active_win.reject()
            return
        self._parent.goBackDetailPage(self._parent.currentDetailPage)

    def _focused_widget(self) -> QWidget | None:
        focused = QApplication.focusWidget()
        if focused is None or not isValid(focused):
            return None
        return focused

    _GAMECARD_SEARCH_TABS: dict[int, str] = {
        0: 'searchEdit',
        1: 'autoInstallSearchLineEdit',
    }

    def _redirect_gamecard_input_to_search(self, event: QEvent) -> bool:
        focused = self._focused_widget()
        if not isinstance(focused, GameCard):
            return False
        tab_index = self._parent.stackedWidget.currentIndex()
        attr_name = self._GAMECARD_SEARCH_TABS.get(tab_index)
        if attr_name is None:
            return False
        text_method = getattr(event, "text", None)
        text = text_method() if callable(text_method) else ""
        text = text if isinstance(text, str) else ""
        if len(text) != 1 or not text.isprintable():
            return False
        search_edit = getattr(self._parent, attr_name, None)
        if not isinstance(search_edit, QLineEdit) or not isValid(search_edit):
            return False
        search_edit.setFocus()
        search_edit.insert(text)
        return True

    def _activate_focused_widget(self, focused: QWidget | None) -> None:
        if focused is None or not isValid(focused):
            return
        try:
            self._parent.activateFocusedWidget()
        except RuntimeError as e:
            logger.debug("Focused widget was deleted before activation: %s", e)

    def _handle_input_key_press(self, key: int, modifiers: int) -> bool:
        if self._handle_input_system_key(key, modifiers):
            return True
        if self._handle_input_file_explorer_key(key):
            return True
        if self._handle_input_text_key(key):
            return True
        if self._handle_input_dialog_key(key):
            return True
        if self._handle_input_tab_key(key):
            return True
        if self._handle_input_arrow_press(key):
            return True
        return self._handle_input_action_key(key, modifiers)

    def _handle_input_system_key(self, key: int, modifiers: int) -> bool:
        if key == KEY_F5:
            self._parent.refreshGames()
            return True
        if key == KEY_Q and modifiers & MOD_CTRL:
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return True
        if key == KEY_F11 and not self._is_gamescope_session:
            self.toggle_fullscreen.emit(not self._is_fullscreen)
            return True
        return False

    def _handle_input_file_explorer_key(self, key: int) -> bool:
        file_explorer = self.file_explorer
        if not file_explorer:
            return False
        focused = self._focused_widget()
        if isinstance(focused, QLineEdit) or self._focused_editable_combo(focused):
            return False
        if key in (KEY_RETURN, KEY_ENTER):
            self._activate_file_explorer_focus()
            return True
        if key == KEY_BACKSPACE:
            file_explorer.previous_dir()
            return True
        return False

    def _activate_file_explorer_focus(self) -> None:
        file_explorer = self.file_explorer
        if file_explorer is None:
            return
        focused = self._focused_widget()
        if (
            isinstance(focused, AutoSizeButton) and
            hasattr(file_explorer, 'drive_buttons') and
            focused in file_explorer.drive_buttons
        ):
            file_explorer.select_drive()
            return
        if file_explorer.file_list.count() > 0:
            self._activate_file_explorer_item(file_explorer.file_list)
            return
        self._activate_focused_widget(focused)

    def _activate_file_explorer_item(self, focused: QListWidget) -> None:
        file_explorer = self.file_explorer
        if file_explorer is None:
            return
        current_item = focused.currentItem()
        if current_item is None and focused.count() > 0:
            focused.setCurrentRow(0)
            current_item = focused.currentItem()
        if not current_item:
            return
        selected = current_item.text()
        full_path = os.path.join(file_explorer.current_path, selected)
        if os.path.isdir(full_path):
            if selected == "../":
                file_explorer.previous_dir()
            else:
                file_explorer.current_path = os.path.normpath(full_path)
                file_explorer.update_file_list()
        elif not file_explorer.directory_only:
            file_explorer.file_signal.file_selected.emit(os.path.normpath(full_path))
            file_explorer.accept()

    def _handle_input_text_key(self, key: int) -> bool:
        focused = self._focused_widget()
        if isinstance(focused, QLineEdit) and key in (KEY_LEFT, KEY_RIGHT):
            if key == KEY_LEFT:
                focused.cursorBackward(False, 1)
            else:
                focused.cursorForward(False, 1)
            return True
        return False

    def _focused_editable_combo(self, focused: QWidget | None) -> bool:
        if isinstance(focused, QComboBox) and focused.isEditable():
            return True
        parent = focused.parentWidget() if focused else None
        return isinstance(parent, QComboBox) and parent.isEditable()

    def _handle_input_dialog_key(self, key: int) -> bool:
        active_win = QApplication.activeWindow()
        focused = self._focused_widget()
        if isinstance(active_win, FullscreenDialog):
            return self._handle_input_fullscreen_dialog_key(active_win, key)
        if key != KEY_ESCAPE:
            return False
        settings_dialog = self.settings_dialog
        if settings_dialog is not None:
            open_combo = self._get_open_settings_combo()
            if open_combo:
                open_combo.hidePopup()
                settings_dialog.advanced_table.setFocus()
                return True
        if isinstance(focused, QLineEdit):
            return False
        if isinstance(active_win, QDialog):
            active_win.reject()
            return True
        return False

    def _handle_input_fullscreen_dialog_key(self, active_win: FullscreenDialog, key: int) -> bool:
        if key in (KEY_ESCAPE, KEY_RETURN, KEY_ENTER, KEY_BACKSPACE):
            active_win.close()
            return True
        if key == KEY_LEFT:
            active_win.show_prev()
            return True
        if key == KEY_RIGHT:
            active_win.show_next()
            return True
        return False

    def _handle_input_tab_key(self, key: int) -> bool:
        if key not in (KEY_LEFT, KEY_RIGHT):
            return False
        focused = self._focused_widget()
        active = QApplication.activeWindow()
        if self.file_explorer or isinstance(active, QMessageBox | QDialog):
            return False
        if isinstance(focused, AnimatedCard | QLineEdit | QTableWidget | AutoSizeButton | QCheckBox):
            return False
        return self._switch_visible_tab(-1 if key == KEY_LEFT else 1)

    def _focus_tab_from_search(self, current_index: int) -> bool:
        focused = self._focused_widget()
        search_edit = (
            getattr(self._parent, 'searchEdit', None)
            if current_index == 0
            else getattr(self._parent, 'autoInstallSearchLineEdit', None)
        )
        if focused is not search_edit:
            return False
        tab_button = self._parent.tabButtons.get(current_index)
        if tab_button is None or not tab_button.isVisible():
            return False
        tab_button.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _get_library_toolbar_widgets(self) -> list[QWidget]:
        widgets = []
        for attr_name in (
            "quickLaunchButton",
            "addGameButton",
            "searchEdit",
            "refreshButton",
            "deleteMissingExeButton",
            "libraryControlsButton",
        ):
            widget = getattr(self._parent, attr_name, None)
            if isinstance(widget, QWidget) and widget.isVisible() and widget.isEnabled():
                widgets.append(widget)
        return widgets

    def _get_library_filter_widgets(self) -> list[QWidget]:
        controls_widget = getattr(self._parent, "libraryControlsWidget", None)
        if not isinstance(controls_widget, QWidget) or not controls_widget.isVisible():
            return []
        widgets = []
        for attr_name in (
            "gamesSortCombo",
            "gamesDisplayCombo",
            "onlyInstalledCheckBox",
            "gamesBadgeViewCombo",
            "gamesLayoutCombo",
        ):
            widget = getattr(self._parent, attr_name, None)
            if isinstance(widget, QWidget) and widget.isVisible() and widget.isEnabled():
                widgets.append(widget)
        return widgets

    def _focus_library_filter_controls(self) -> bool:
        controls_button = getattr(self._parent, "libraryControlsButton", None)
        if not isinstance(controls_button, AutoSizeButton):
            return False
        if not controls_button.isChecked():
            controls_button.setChecked(True)
            toggle_controls = getattr(self._parent, "_toggle_library_controls", None)
            if callable(toggle_controls):
                toggle_controls()
        filter_widgets = self._get_library_filter_widgets()
        if not filter_widgets:
            return False
        filter_widgets[0].setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _focus_first_game_card(self, container: QWidget | None) -> bool:
        if container is None:
            return False
        for card in container.findChildren(AnimatedCard):
            if card.isVisible() and card.isEnabled():
                card.setFocus(Qt.FocusReason.OtherFocusReason)
                scroll_area = container.parentWidget()
                while scroll_area and not isinstance(scroll_area, QScrollArea):
                    scroll_area = scroll_area.parentWidget()
                if isinstance(scroll_area, QScrollArea):
                    scroll_area.ensureWidgetVisible(card, 50, 50)
                return True
        return False

    def _focus_first_library_card(self) -> bool:
        container = getattr(self._parent, "gamesListWidget", None)
        return self._focus_first_game_card(container)

    def _get_autoinstall_toolbar_widgets(self) -> list[QWidget]:
        widgets = []
        for attr_name in ("autoInstallSearchLineEdit", "autoInstallRefreshButton"):
            widget = getattr(self._parent, attr_name, None)
            if isinstance(widget, QWidget) and widget.isVisible() and widget.isEnabled():
                widgets.append(widget)
        return widgets

    def _focus_first_autoinstall_card(self) -> bool:
        container = getattr(self._parent, "autoInstallContainer", None)
        return self._focus_first_game_card(container)

    def _handle_toolbar_navigation(self, code: int, value: int) -> bool:
        current_index = self._parent.stackedWidget.currentIndex()
        if value == 0 or current_index not in (0, 1):
            return False
        if current_index == 0:
            toolbar_widgets = self._get_library_toolbar_widgets()
            focus_first_card = self._focus_first_library_card
        else:
            toolbar_widgets = self._get_autoinstall_toolbar_widgets()
            focus_first_card = self._focus_first_autoinstall_card
        focused = self._focused_widget()
        filter_widgets = self._get_library_filter_widgets() if current_index == 0 else []
        if focused in filter_widgets:
            if code == PAD_DPAD_X:
                widget_index = filter_widgets.index(cast(QWidget, focused))
                next_index = widget_index + (1 if value > 0 else -1)
                if 0 <= next_index < len(filter_widgets):
                    filter_widgets[next_index].setFocus(Qt.FocusReason.OtherFocusReason)
                return True
            if code != PAD_DPAD_Y:
                return False
            if value < 0:
                controls_button = getattr(self._parent, "libraryControlsButton", None)
                if isinstance(controls_button, QWidget):
                    controls_button.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
            return focus_first_card()
        if focused not in toolbar_widgets:
            return False
        if code == PAD_DPAD_X:
            widget_index = toolbar_widgets.index(cast(QWidget, focused))
            next_index = widget_index + (1 if value > 0 else -1)
            if 0 <= next_index < len(toolbar_widgets):
                toolbar_widgets[next_index].setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        if code != PAD_DPAD_Y:
            return False
        if value > 0:
            controls_button = getattr(self._parent, "libraryControlsButton", None)
            if focused is controls_button and self._focus_library_filter_controls():
                return True
            return focus_first_card()
        tab_button = self._parent.tabButtons.get(current_index)
        if tab_button is not None and tab_button.isVisible():
            tab_button.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _switch_visible_tab(self, step: int) -> bool:
        idx = self._parent.stackedWidget.currentIndex()
        visible = [i for i, btn in self._parent.tabButtons.items() if btn.isVisible()]
        visible.sort()
        if not visible:
            return False
        try:
            current_pos = visible.index(idx)
        except ValueError:
            current_pos = 0
        new_idx = visible[(current_pos + step) % len(visible)]
        self._parent.switchTab(new_idx)
        self._parent.tabButtons[new_idx].setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _handle_input_arrow_press(self, key: int) -> bool:
        dpad = {
            KEY_UP: (PAD_DPAD_Y, -1),
            KEY_DOWN: (PAD_DPAD_Y, 1),
            KEY_LEFT: (PAD_DPAD_X, -1),
            KEY_RIGHT: (PAD_DPAD_X, 1),
        }.get(key)
        if dpad is None:
            return False
        self.dpad_moved.emit(dpad[0], dpad[1], time.time())
        return True

    def _handle_input_action_key(self, key: int, modifiers: int) -> bool:
        focused = self._focused_widget()
        if isinstance(focused, GameCard) and key == KEY_F10 and modifiers & MOD_SHIFT:
            pos = QPoint(focused.width() // 2, focused.height() // 2)
            focused._show_context_menu(pos)
            return True
        if key in (KEY_RETURN, KEY_ENTER):
            if isinstance(focused, QTableWidget):
                self.handle_table_confirm(focused)
            else:
                self._activate_focused_widget(focused)
            return True
        elif key in (KEY_ESCAPE, KEY_BACKSPACE):
            return self._handle_input_back_key(focused)
        elif key == KEY_E and not isinstance(focused, QLineEdit):
            if self._parent.stackedWidget.currentIndex() == 0:
                self._parent.openAddGameDialog()
                return True
        return False

    def _handle_input_back_key(self, focused: QWidget | None) -> bool:
        if isinstance(focused, QLineEdit) or self._focused_editable_combo(focused):
            return False
        self._handle_standard_back()
        return True

    def _handle_input_key_release(self, key: int) -> bool:
        if key in (KEY_UP, KEY_DOWN):
            self.dpad_moved.emit(PAD_DPAD_Y, 0, time.time())
            return True
        elif key in (KEY_LEFT, KEY_RIGHT):
            self.dpad_moved.emit(PAD_DPAD_X, 0, time.time())
            return True
        return False
