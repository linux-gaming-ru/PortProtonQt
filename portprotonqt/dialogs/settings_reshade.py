"""ReShade settings support for executable settings dialog."""

import os
from typing import Any, cast

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox
from portprotonqt.localization import _
from portprotonqt.theme_manager import ThemeManager

RESHADE_ENV_KEYS = [
    'PW_RESHADE_EXE',
    'PW_RESHADE_API',
    'PW_RESHADE_FONT',
    'PW_RESHADE_SCREENSHOT_PATH',
    'PW_RESHADE_SCREENSHOT_KEY',
    'PW_RESHADE_OVERLAY_KEY',
]
RESHADE_API_OPTIONS = {
    "Auto": "auto",
    "DXGI": "dxgi.dll",
    "DirectX 8/9": "d3d9.dll",
    "OpenGL": "opengl32.dll",
    "Vulkan": "vulkan",
}
RESHADE_SPECIAL_KEYS = {
    Qt.Key.Key_Cancel: 3,
    Qt.Key.Key_Backspace: 8,
    Qt.Key.Key_Tab: 9,
    Qt.Key.Key_Clear: 12,
    Qt.Key.Key_Return: 13,
    Qt.Key.Key_Enter: 13,
    Qt.Key.Key_Pause: 19,
    Qt.Key.Key_CapsLock: 20,
    Qt.Key.Key_Escape: 27,
    Qt.Key.Key_Space: 32,
    Qt.Key.Key_PageUp: 33,
    Qt.Key.Key_PageDown: 34,
    Qt.Key.Key_End: 35,
    Qt.Key.Key_Home: 36,
    Qt.Key.Key_Left: 37,
    Qt.Key.Key_Up: 38,
    Qt.Key.Key_Right: 39,
    Qt.Key.Key_Down: 40,
    Qt.Key.Key_Print: 44,
    Qt.Key.Key_Insert: 45,
    Qt.Key.Key_Delete: 46,
    Qt.Key.Key_Help: 47,
    Qt.Key.Key_Meta: 91,
    Qt.Key.Key_Menu: 93,
    Qt.Key.Key_Sleep: 95,
    Qt.Key.Key_NumLock: 144,
    Qt.Key.Key_ScrollLock: 145,
    Qt.Key.Key_Semicolon: 186,
    Qt.Key.Key_Equal: 187,
    Qt.Key.Key_Comma: 188,
    Qt.Key.Key_Minus: 189,
    Qt.Key.Key_Period: 190,
    Qt.Key.Key_Slash: 191,
    Qt.Key.Key_QuoteLeft: 192,
    Qt.Key.Key_BracketLeft: 219,
    Qt.Key.Key_Backslash: 220,
    Qt.Key.Key_BracketRight: 221,
    Qt.Key.Key_Apostrophe: 222,
    Qt.Key.Key_Back: 166,
    Qt.Key.Key_Forward: 167,
    Qt.Key.Key_Refresh: 168,
    Qt.Key.Key_Stop: 169,
    Qt.Key.Key_Search: 170,
    Qt.Key.Key_Favorites: 171,
    Qt.Key.Key_HomePage: 172,
    Qt.Key.Key_VolumeMute: 173,
    Qt.Key.Key_VolumeDown: 174,
    Qt.Key.Key_VolumeUp: 175,
    Qt.Key.Key_MediaNext: 176,
    Qt.Key.Key_MediaPrevious: 177,
    Qt.Key.Key_MediaStop: 178,
    Qt.Key.Key_MediaPlay: 179,
    Qt.Key.Key_LaunchMail: 180,
    Qt.Key.Key_LaunchMedia: 181,
    Qt.Key.Key_Launch0: 182,
    Qt.Key.Key_Launch1: 183,
}
RESHADE_KEYPAD_KEYS = {
    Qt.Key.Key_Asterisk: 106,
    Qt.Key.Key_Plus: 107,
    Qt.Key.Key_Comma: 108,
    Qt.Key.Key_Minus: 109,
    Qt.Key.Key_Period: 110,
    Qt.Key.Key_Slash: 111,
}
RESHADE_FIRST_FUNCTION_KEY = 112
RESHADE_LAST_FUNCTION_KEY = 135
RESHADE_FIRST_NUMPAD_KEY = 96


class ReShadeSettingsMixin:
    """Mixin with ReShade settings UI and serialization logic."""

    theme: Any
    exe_path: str | None
    current_settings: dict[str, str]
    original_values: dict[str, str]
    reshade_tab: QWidget
    reshade_tab_layout: QVBoxLayout

    def init_reshade_state(self) -> None:
        self.reshade_original_values = {}
        self.reshade_key_target = None

    def setup_reshade_tab(self) -> None:
        """Create ReShade tab widgets."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setStyleSheet(self.theme.SCROLL_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(self.theme.exeSettingsGroupBoxBlockSpacing)

        actions = QGroupBox(_("Actions"))
        actions.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        actions_layout = QGridLayout(actions)
        self.reshade_enable_button = self._create_reshade_button("")
        self.reshade_enable_button.clicked.connect(self.toggle_reshade_enable)
        actions_layout.addWidget(self.reshade_enable_button, 0, 0)
        layout.addWidget(actions)

        self._add_reshade_settings_group(layout)
        layout.addStretch()

        scroll.setWidget(container)
        self.reshade_tab_layout.addWidget(scroll)

    def _add_reshade_settings_group(self, parent_layout: QVBoxLayout) -> None:
        self.reshade_settings_group = QGroupBox(_("Settings"))
        self.reshade_settings_group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        settings_layout = QGridLayout(self.reshade_settings_group)
        self.reshade_exe_edit = self._add_reshade_file_row(
            settings_layout, 0, "EXE", ".exe"
        )
        self.reshade_api_combo = CustomComboBox(theme=self.theme)
        self.reshade_api_combo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.reshade_api_combo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.reshade_api_combo.setStyleSheet(
            self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE
        )
        self.reshade_api_combo.addItems(list(RESHADE_API_OPTIONS))
        settings_layout.addWidget(QLabel("API"), 1, 0)
        settings_layout.addWidget(self.reshade_api_combo, 1, 1)
        self.reshade_font_combo = CustomComboBox(theme=self.theme)
        self.reshade_font_combo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.reshade_font_combo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.reshade_font_combo.setStyleSheet(
            self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE
        )
        self.reshade_font_combo.addItem(_("Default"), "")
        settings_layout.addWidget(QLabel(_("Font")), 2, 0)
        settings_layout.addWidget(self.reshade_font_combo, 2, 1)
        self.reshade_screenshot_edit = self._add_reshade_directory_row(
            settings_layout, 3, _("Screenshots")
        )
        self.reshade_screenshot_key_button = self._create_reshade_key_button(
            "screenshot"
        )
        settings_layout.addWidget(QLabel(_("Screenshot key")), 4, 0)
        settings_layout.addWidget(self.reshade_screenshot_key_button, 4, 1)
        self.reshade_overlay_key_button = self._create_reshade_key_button("overlay")
        settings_layout.addWidget(QLabel(_("Overlay key")), 5, 0)
        settings_layout.addWidget(self.reshade_overlay_key_button, 5, 1)
        parent_layout.addWidget(self.reshade_settings_group)
        self._load_reshade_fonts()

    def _create_reshade_button(self, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    def _add_reshade_file_row(
        self, layout: QGridLayout, row: int, label: str, file_filter: str
    ) -> QLineEdit:
        line_edit = QLineEdit()
        line_edit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        button = AutoSizeButton(
            _("Browse…"), icon=ThemeManager().get_icon("folder", as_path=True)
        )
        button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        button.clicked.connect(
            lambda _checked=False: self._select_reshade_file(line_edit, file_filter)
        )
        field_layout = QHBoxLayout()
        field_layout.addWidget(line_edit)
        field_layout.addWidget(button)
        layout.addWidget(QLabel(label), row, 0)
        layout.addLayout(field_layout, row, 1)
        return line_edit

    def _select_reshade_file(self, line_edit: QLineEdit, file_filter: str) -> None:
        from portprotonqt.dialogs.file_explorer import FileExplorer

        current_path = line_edit.text().strip()
        initial_path = os.path.dirname(current_path) if os.path.isfile(current_path) else None
        explorer = FileExplorer(
            self, theme=self.theme, file_filter=file_filter, initial_path=initial_path
        )
        explorer.file_signal.file_selected.connect(line_edit.setText)
        explorer.exec()

    def _add_reshade_directory_row(
        self, layout: QGridLayout, row: int, label: str
    ) -> QLineEdit:
        line_edit = QLineEdit()
        line_edit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        button = AutoSizeButton(
            _("Browse…"), icon=ThemeManager().get_icon("folder", as_path=True)
        )
        button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        button.clicked.connect(
            lambda _checked=False: self._select_reshade_directory(line_edit)
        )
        field_layout = QHBoxLayout()
        field_layout.addWidget(line_edit)
        field_layout.addWidget(button)
        layout.addWidget(QLabel(label), row, 0)
        layout.addLayout(field_layout, row, 1)
        return line_edit

    def _select_reshade_directory(self, line_edit: QLineEdit) -> None:
        from portprotonqt.dialogs.file_explorer import FileExplorer

        initial_path = line_edit.text().strip() or os.path.dirname(self.exe_path or "")
        explorer = FileExplorer(
            self, theme=self.theme, initial_path=initial_path, directory_only=True
        )
        explorer.file_signal.file_selected.connect(line_edit.setText)
        explorer.exec()

    def _create_reshade_key_button(self, target: str) -> QPushButton:
        button = self._create_reshade_button("")
        button.clicked.connect(lambda _checked=False: self._capture_reshade_key(target))
        button.installEventFilter(cast(QWidget, self))
        return button

    def _capture_reshade_key(self, target: str) -> None:
        self.reshade_key_target = target
        button = self._get_reshade_key_button(target)
        button.setText(_("Press a button to choose"))
        button.grabKeyboard()

    def _get_reshade_key_button(self, target: str) -> QPushButton:
        if target == "screenshot":
            return self.reshade_screenshot_key_button
        return self.reshade_overlay_key_button

    def _handle_reshade_key_button_event(self, obj: QWidget, event: QEvent) -> bool:
        target = self.reshade_key_target
        if target is None or obj is not self._get_reshade_key_button(target):
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        key_event = cast(QKeyEvent, event)
        key_value = self._reshade_virtual_key(
            key_event.key(), key_event.modifiers()
        )
        if key_value is None:
            return True
        modifiers = key_event.modifiers()
        value = ",".join(str(item) for item in (
            key_value,
            int(bool(modifiers & Qt.KeyboardModifier.ControlModifier)),
            int(bool(modifiers & Qt.KeyboardModifier.ShiftModifier)),
            int(bool(modifiers & Qt.KeyboardModifier.AltModifier)),
        ))
        self.current_settings[f'PW_RESHADE_{target.upper()}_KEY'] = value
        button = self._get_reshade_key_button(target)
        button.setText(QKeySequence(key_event.keyCombination()).toString())
        button.releaseKeyboard()
        self.reshade_key_target = None
        return True

    def _reshade_virtual_key(
        self, key: int, modifiers: Qt.KeyboardModifier
    ) -> int | None:
        is_keypad = bool(modifiers & Qt.KeyboardModifier.KeypadModifier)
        if is_keypad and Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
            return RESHADE_FIRST_NUMPAD_KEY + key - Qt.Key.Key_0.value
        if is_keypad:
            try:
                keypad_key = RESHADE_KEYPAD_KEYS.get(Qt.Key(key))
            except ValueError:
                keypad_key = None
            if keypad_key is not None:
                return keypad_key
        if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
            return key
        if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
            return key
        if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F24.value:
            return RESHADE_FIRST_FUNCTION_KEY + key - Qt.Key.Key_F1.value
        try:
            return RESHADE_SPECIAL_KEYS.get(Qt.Key(key))
        except ValueError:
            return None

    def _format_reshade_key(self, value: str) -> str:
        try:
            key, control, shift, alt = (int(item) for item in value.split(","))
        except ValueError:
            return value
        qt_key = next(
            (item for item, code in RESHADE_SPECIAL_KEYS.items() if code == key), None
        )
        if qt_key is not None:
            name = QKeySequence(qt_key).toString()
        elif RESHADE_FIRST_FUNCTION_KEY <= key <= RESHADE_LAST_FUNCTION_KEY:
            name = f"F{key - RESHADE_FIRST_FUNCTION_KEY + 1}"
        else:
            name = chr(key)
        modifiers = [
            label for active, label in (
                (control, "Ctrl"), (shift, "Shift"), (alt, "Alt")
            ) if active
        ]
        return "+".join([*modifiers, name])

    def _load_reshade_fonts(self) -> None:
        selected_family = self.current_settings.get('PW_RESHADE_FONT', '')
        font_options = cast(Any, self)._get_mangohud_font_options()
        families = {name for name, _path in font_options}
        self.reshade_font_combo.clear()
        self.reshade_font_combo.addItem(_("Default"), "")
        for family in sorted(families, key=str.casefold):
            self.reshade_font_combo.addItem(family, family)
        self._select_reshade_font(selected_family)

    def _select_reshade_font(self, family: str) -> None:
        for index in range(self.reshade_font_combo.count()):
            if self.reshade_font_combo.itemData(index) == family:
                self.reshade_font_combo.setCurrentIndex(index)
                return
        if family:
            self.reshade_font_combo.addItem(family, family)
            self.reshade_font_combo.setCurrentIndex(self.reshade_font_combo.count() - 1)

    def populate_reshade(self) -> None:
        """Populate ReShade tab from current settings."""
        reshade_exe = self.current_settings.get('PW_RESHADE_EXE', '') or self.exe_path or ''
        self.reshade_exe_edit.setText(reshade_exe)
        api_value = self.current_settings.get('PW_RESHADE_API', 'auto')
        api_label = next(
            (label for label, value in RESHADE_API_OPTIONS.items() if value == api_value),
            "Auto",
        )
        self.reshade_api_combo.setCurrentText(api_label)
        font_family = self.current_settings.get('PW_RESHADE_FONT', '')
        self._select_reshade_font(font_family)
        screenshot_path = self.current_settings.get('PW_RESHADE_SCREENSHOT_PATH', '')
        screenshot_key = self.current_settings.get(
            'PW_RESHADE_SCREENSHOT_KEY', '44,0,0,0'
        )
        overlay_key = self.current_settings.get(
            'PW_RESHADE_OVERLAY_KEY', '36,0,0,0'
        )
        self.reshade_screenshot_edit.setText(screenshot_path)
        self.reshade_screenshot_key_button.setText(
            self._format_reshade_key(screenshot_key)
        )
        self.reshade_overlay_key_button.setText(self._format_reshade_key(overlay_key))
        self.current_settings['PW_RESHADE_SCREENSHOT_KEY'] = screenshot_key
        self.current_settings['PW_RESHADE_OVERLAY_KEY'] = overlay_key
        self.reshade_original_values = {
            key: self.current_settings.get(key, '') for key in RESHADE_ENV_KEYS
        }
        self.reshade_original_values['PW_RESHADE_EXE'] = reshade_exe
        self.reshade_original_values['PW_RESHADE_SCREENSHOT_KEY'] = screenshot_key
        self.reshade_original_values['PW_RESHADE_OVERLAY_KEY'] = overlay_key
        self._update_reshade_widgets()

    def toggle_reshade_enable(self) -> None:
        enabled = self.current_settings.get('PW_USE_RESHADE') == '1'
        self.current_settings['PW_USE_RESHADE'] = '0' if enabled else '1'
        self._update_reshade_widgets()

    def _update_reshade_widgets(self) -> None:
        enabled = self.current_settings.get('PW_USE_RESHADE') == '1'
        self.reshade_enable_button.setText(
            _("Disable {0}").format("ReShade")
            if enabled else _("Enable {0}").format("ReShade")
        )
        self.reshade_enable_button.setStyleSheet(
            self.theme.ACTION_BUTTON_ACTIVE_STYLE if enabled else self.theme.ACTION_BUTTON_STYLE
        )
        self.reshade_settings_group.setVisible(enabled)

    def _collect_reshade_changes(self) -> list[str]:
        changes = []
        enabled = '1' if self.current_settings.get('PW_USE_RESHADE') == '1' else '0'
        original_enabled = '1' if self.original_values.get('PW_USE_RESHADE') == '1' else '0'
        if enabled != original_enabled:
            changes.append(f"PW_USE_RESHADE={enabled}")
        values = {
            'PW_RESHADE_EXE': self.reshade_exe_edit.text().strip(),
            'PW_RESHADE_API': RESHADE_API_OPTIONS[self.reshade_api_combo.currentText()],
            'PW_RESHADE_FONT': str(self.reshade_font_combo.currentData() or ''),
            'PW_RESHADE_SCREENSHOT_PATH': self.reshade_screenshot_edit.text().strip(),
            'PW_RESHADE_SCREENSHOT_KEY': self.current_settings['PW_RESHADE_SCREENSHOT_KEY'],
            'PW_RESHADE_OVERLAY_KEY': self.current_settings['PW_RESHADE_OVERLAY_KEY'],
        }
        for key, value in values.items():
            if value != self.reshade_original_values.get(key, ''):
                changes.append(f"{key}={value}")
        return changes

    def _filter_reshade_settings(self, search_text: str) -> None:
        enabled = self.current_settings.get('PW_USE_RESHADE') == '1'
        self.reshade_settings_group.setVisible(
            enabled and (
                not search_text
                or search_text in "exe api font screenshot overlay"
                or search_text in _("Settings").lower()
            )
        )
