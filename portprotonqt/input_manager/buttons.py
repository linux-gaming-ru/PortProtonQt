import time

from PySide6.QtCore import QPoint, QTimer, Slot, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLineEdit,
    QListView,
    QMenu,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QWidget,
)

from portprotonqt.dialogs import AddGameDialog
from portprotonqt.game_card import GameCard
from portprotonqt.image_utils import FullscreenDialog
from portprotonqt.input_manager.constants import (
    BUTTONS,
    SIZE_SLIDER_STEP,
    SYSTEM_AUDIO_SECTION_INDEX,
    SYSTEM_VOLUME_STEP,
)
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager
from portprotonqt.virtual_keyboard import VirtualKeyboard

logger = get_logger(__name__)


class ButtonInputMixin(InputMixin):
    @Slot(int, int)
    def handle_button_slot(self, button_code: int, value: int) -> None:
        if self._route_surface_button(button_code, value):
            return
        self._handle_default_button(button_code, value)

    def _handle_default_button(self, button_code: int, value: int) -> None:
        if value == 1 and self._handle_common_ui_elements(button_code):
            return

        active_window = QApplication.activeWindow()
        if self._route_button_to_keyboard(active_window, button_code, value):
            return

        if value == 0:
            return

        if not self._gamepad_handling_enabled:
            return
        try:
            app = QApplication.instance()
            active = QApplication.activeWindow()
            focused = QApplication.focusWidget()
            if not app or not active:
                return

            if self._route_button_to_text_input(active, focused, button_code):
                return

            if self._handle_guide_combination(button_code, time.time()):
                return

            if self._handle_combo_button(focused, button_code):
                return

            if self._handle_list_view_button(focused, button_code):
                return

            if self._handle_popup_menu_button(QApplication.activePopupWidget(), button_code):
                return

            if self._handle_active_window_button(active, button_code):
                return

            if self._open_focused_context_menu(focused, button_code):
                return

            if self._handle_system_table_button(focused, button_code):
                return

            if self._handle_table_button(focused, button_code):
                return

            if self._handle_system_quick_button(button_code):
                return

            self._handle_standard_button(focused, button_code, value)
        except Exception as e:
            logger.error(f"Error in handle_button_slot: {e}", exc_info=True)

    def _handle_table_button(self, focused: QWidget | None, button_code: int) -> bool:
        if not isinstance(focused, QTableWidget) or button_code not in BUTTONS['confirm']:
            return False
        if not self.handle_table_confirm(focused):
            return False
        SoundManager().play("click")
        return True

    def _open_focused_context_menu(self, focused: QWidget | None, button_code: int) -> bool:
        if button_code not in BUTTONS['context_menu'] or focused is None:
            return False
        if isinstance(focused, QTableWidget):
            current_row = focused.currentRow()
            current_col = max(focused.currentColumn(), 0)
            item = focused.item(current_row, current_col) if current_row >= 0 else None
            if item is None and current_row >= 0:
                item = focused.item(current_row, 0)
            point = (
                focused.visualItemRect(item).center()
                if item is not None
                else focused.viewport().rect().center()
            )
            focused.customContextMenuRequested.emit(point)
            return True
        if focused.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu:
            focused.customContextMenuRequested.emit(focused.rect().center())
            return True
        if not isinstance(focused, GameCard):
            return False
        position = QPoint(focused.width() // 2, focused.height() // 2)
        menu = focused._show_context_menu(position)
        if menu:
            menu.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _handle_combo_button(self, focused: QWidget | None, button_code: int) -> bool:
        if not isinstance(focused, QComboBox):
            return False
        if button_code in BUTTONS['confirm']:
            focused.showPopup()
            return True
        if button_code in BUTTONS['back'] and focused.view().isVisible():
            focused.hidePopup()
            return True
        return False

    def _handle_popup_menu_button(self, popup: QWidget | None, button_code: int) -> bool:
        if not isinstance(popup, QMenu):
            return False
        if button_code in BUTTONS['confirm']:
            action = popup.activeAction()
            if action is not None and action.isEnabled():
                action.trigger()
                popup.close()
            return True
        if button_code in BUTTONS['back']:
            popup.close()
            return True
        return False

    def _route_button_to_text_input(
        self, active: QWidget, focused: QWidget | None, button_code: int
    ) -> bool:
        keyboard = (
            getattr(active, 'keyboard', None)
            if isinstance(active, AddGameDialog)
            else getattr(self._parent, 'keyboard', None)
        )
        if button_code in BUTTONS['confirm'] and isinstance(focused, QLineEdit):
            if keyboard:
                keyboard.show_for_widget(focused)
                return True
        if button_code not in BUTTONS['prev_dir']:
            return False
        combo = focused if isinstance(focused, QComboBox) else None
        if combo is None and focused is not None:
            combo = self._find_parent_combo(focused)
        if combo is not None and combo.isEditable():
            line_edit = combo.lineEdit()
            if line_edit is not None and keyboard:
                line_edit.setFocus()
                keyboard.show_for_widget(line_edit)
                return True
        current_tab = self._parent.stackedWidget.currentIndex()
        search_name = 'searchEdit' if current_tab == 0 else 'autoInstallSearchLineEdit'
        search_edit = getattr(self._parent, search_name, None) if current_tab in (0, 1) else None
        if search_edit is None:
            return False
        search_edit.setFocus()
        return True

    def _find_parent_combo(self, widget: QWidget) -> QComboBox | None:
        parent = widget.parentWidget()
        while parent:
            if isinstance(parent, QComboBox):
                return parent
            parent = parent.parentWidget()
        return None

    def _activate_list_view_selection(self, view: QListView) -> None:
        index = view.currentIndex()
        if not index.isValid():
            return
        combo = self._find_parent_combo(view)
        if combo:
            combo.setCurrentIndex(index.row())
            combo.hidePopup()
            combo.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        view.activated.emit(index)
        view.clicked.emit(index)
        view.hide()

    def _handle_list_view_button(self, focused: QWidget | None, button_code: int) -> bool:
        if not isinstance(focused, QListView):
            return False
        if button_code in BUTTONS['confirm']:
            self._activate_list_view_selection(focused)
            return True
        if button_code not in BUTTONS['back']:
            return False
        combo = self._find_parent_combo(focused)
        if combo:
            combo.hidePopup()
            combo.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            focused.clearSelection()
            focused.hide()
        return False

    def _handle_system_table_button(self, focused: QWidget | None, button_code: int) -> bool:
        if not isinstance(focused, QTableWidget):
            return False
        handler = getattr(self._parent, "handleSystemTableGamepadAction", None)
        if not callable(handler):
            return False
        routes = (
            ('confirm', "confirm", "click"),
            ('back', "back", "back"),
            ('prev_dir', "prev_dir", "click"),
            ('add_game', "add_game", "click"),
        )
        for button_name, action, sound in routes:
            if button_code in BUTTONS[button_name] and handler(focused, action):
                SoundManager().play(sound)
                return True
        return False

    def _handle_active_window_button(self, active: QWidget, button_code: int) -> bool:
        if button_code in BUTTONS['back'] and isinstance(active, QDialog):
            active.reject()
            return True
        if not isinstance(active, FullscreenDialog):
            return False
        if button_code in BUTTONS['prev_tab']:
            active.show_prev()
        elif button_code in BUTTONS['next_tab']:
            active.show_next()
        elif button_code in BUTTONS['back']:
            active.close()
        return True

    def _handle_system_quick_button(self, button_code: int) -> bool:
        handler = getattr(self._parent, "handleSystemGamepadAction", None)
        if not callable(handler) or button_code not in BUTTONS['add_game']:
            return False
        if not handler("add_game"):
            return False
        SoundManager().play("open")
        return True

    def _handle_standard_button(
        self, focused: QWidget | None, button_code: int, value: int
    ) -> None:
        if button_code in BUTTONS['confirm']:
            if not isinstance(focused, GameCard):
                SoundManager().play_widget_sound(focused)
            QTimer.singleShot(0, self._parent.activateFocusedWidget)
        elif button_code in BUTTONS['back']:
            self._handle_standard_back()
        elif button_code in BUTTONS['add_game']:
            if self._parent.stackedWidget.currentIndex() == 0:
                SoundManager().play("open")
                self._parent.openAddGameDialog()
        elif button_code in BUTTONS['prev_tab']:
            self._switch_visible_tab(-1)
        elif button_code in BUTTONS['next_tab']:
            self._switch_visible_tab(1)
        elif button_code in BUTTONS['increase_size'] and value > 0:
            self._adjust_active_slider(1)
        elif button_code in BUTTONS['decrease_size'] and value > 0:
            self._adjust_active_slider(-1)

    def _handle_standard_back(self) -> None:
        SoundManager().play("back")
        manager = getattr(self._parent, "game_library_manager", None)
        close_full_library = getattr(manager, "close_full_library", None)
        if callable(close_full_library) and close_full_library():
            return
        if self._is_theme_store_visible():
            store_stack = getattr(self._parent, "themeStoreStack", None)
            detail_page = getattr(self._parent, "themeStoreDetailPage", None)
            show_list = getattr(self._parent, '_show_theme_store_list', None)
            if store_stack is not None and store_stack.currentWidget() == detail_page:
                if callable(show_list):
                    show_list()
                    return
        self._parent.goBackDetailPage(getattr(self._parent, 'currentDetailPage', None))

    def _adjust_active_slider(self, direction: int) -> bool:
        current_tab = self._parent.stackedWidget.currentIndex()
        if current_tab == getattr(self._parent, "system_tab_index", -1):
            return self._adjust_system_volume(direction)
        if current_tab == 0:
            manager = getattr(self._parent, 'game_library_manager', None)
            slider = getattr(manager, 'sizeSlider', None)
            callback = getattr(self._parent, 'on_slider_released', None)
        elif current_tab == 1:
            slider = getattr(self._parent, 'auto_size_slider', None)
            callback = getattr(self._parent, 'on_auto_slider_released', None)
        elif current_tab == getattr(self._parent, "theme_tab_index", -1):
            slider = getattr(self._parent, 'themeStoreSizeSlider', None)
            callback = getattr(self._parent, '_on_theme_store_slider_released', None)
        else:
            return False
        if not isinstance(slider, QSlider):
            return False
        slider.setValue(slider.value() + direction * SIZE_SLIDER_STEP)
        if callable(callback):
            callback()
        return True

    def _adjust_system_volume(self, direction: int) -> bool:
        section_stack = getattr(self._parent, "systemSectionStack", None)
        slider = getattr(self._parent, "audioVolumeSlider", None)
        if (
            not isinstance(section_stack, QStackedWidget)
            or section_stack.currentIndex() != SYSTEM_AUDIO_SECTION_INDEX
        ):
            return False
        if not isinstance(slider, QSlider):
            return False
        slider.setValue(slider.value() + direction * SYSTEM_VOLUME_STEP)
        apply_volume = getattr(self._parent, "_applySelectedAudioVolume", None)
        if callable(apply_volume):
            apply_volume()
        return True

    def _handle_guide_combination(self, button_code: int, current_time: float) -> bool:
        if button_code in BUTTONS['guide']:
            self.guide_held = True
            self.guide_pressed_time = current_time
            self.in_guide_combination_attempt = True
            self.guide_timer.start(int(self.guide_combination_timeout * 1000))
            return True
        if button_code not in BUTTONS['menu'] or not self.guide_held:
            return False
        self.select_pressed_time = current_time
        if current_time - self.guide_pressed_time > self.guide_combination_timeout:
            self._reset_guide_combination()
            return False
        self.guide_timer.stop()
        logger.debug("Guide + Select combination detected, refreshing game grid")
        self._parent.refreshGames()
        self._reset_guide_combination()
        return True

    def _reset_guide_combination(self) -> None:
        self.guide_held = False
        self.in_guide_combination_attempt = False
        self.guide_pressed_time = 0
        self.select_pressed_time = 0

    def _route_button_to_keyboard(
        self, active_window: QWidget | None, button_code: int, value: int
    ) -> bool:
        if isinstance(active_window, AddGameDialog):
            focused = QApplication.focusWidget()
            if button_code in BUTTONS['confirm'] and value == 1 and isinstance(focused, QLineEdit):
                active_window.show_keyboard_for_widget(focused)
                return True
            keyboard = getattr(active_window, 'keyboard', None)
            if keyboard and keyboard.isVisible():
                self.handle_virtual_keyboard(button_code, value)
                return True
        dialog_keyboard = getattr(active_window, 'keyboard', None) if active_window else None
        if isinstance(dialog_keyboard, VirtualKeyboard) and dialog_keyboard.isVisible():
            self.handle_virtual_keyboard(button_code, value)
            return True
        keyboard = getattr(self._parent, 'keyboard', None)
        if keyboard and keyboard.isVisible():
            self.handle_virtual_keyboard(button_code, value)
            return True
        return False
