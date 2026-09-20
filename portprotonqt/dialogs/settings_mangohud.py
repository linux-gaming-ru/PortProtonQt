"""MangoHud settings support for executable settings dialog."""

import configparser
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.config import CONFIG_FILE
from portprotonqt.config import get_portproton_scripts_path
from portprotonqt.debug_utils import get_cached_vk_gpu_info
from portprotonqt.custom_widgets import CustomComboBox
from portprotonqt.localization import _
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

MANGOHUD_ENV_KEYS = [
    'MANGOHUD_CONFIG',
    'FPS_LIMIT',
]

MANGOHUD_TOGGLE_SPECS = [
    ('arch', "Arch"),
    ('battery', "Battery"),
    ('battery_icon', "Battery icon"),
    ('battery_time', "Battery time"),
    ('battery_watt', "Battery watt"),
    ('bicubic', "Bicubic"),
    ('core_bars', "Core bars"),
    ('core_load', "Core load"),
    ('core_load_change', "Core load change"),
    ('core_type', "Core type"),
    ('cpu_efficiency', "CPU efficiency"),
    ('cpu_load_change', "CPU load change"),
    ('cpu_mhz', "CPU MHz"),
    ('cpu_power', "CPU power"),
    ('cpu_temp', "CPU temperature"),
    ('debug', "Debug"),
    ('device_battery_icon', "Device battery icon"),
    ('display_server', "Display server"),
    ('dynamic_frame_timing', "Dynamic frame timing"),
    ('engine_short_names', "Short engine names"),
    ('engine_version', "Engine version"),
    ('exec_name', "Executable name"),
    ('fan', "Fan"),
    ('fcat', "FCAT"),
    ('flip_efficiency', "Flip efficiency"),
    ('fps_color_change', "FPS color change"),
    ('fps_metrics', "FPS metrics"),
    ('fps_only', "FPS only"),
    ('frame_count', "Frame count"),
    ('frametime', "Frametime"),
    ('frame_timing_detailed', "Detailed frametime"),
    ('fsr', "FSR status"),
    ('full', "Full preset"),
    ('gamemode', "GameMode"),
    ('gpu_core_clock', "GPU core clock"),
    ('gpu_efficiency', "GPU efficiency"),
    ('gpu_fan', "GPU fan"),
    ('gpu_junction_temp', "GPU junction temp"),
    ('gpu_load_change', "GPU load change"),
    ('gpu_mem_clock', "GPU memory clock"),
    ('gpu_mem_temp', "GPU memory temp"),
    ('gpu_name', "GPU name"),
    ('gpu_power', "GPU power"),
    ('gpu_power_limit', "GPU power limit"),
    ('gpu_temp', "GPU temperature"),
    ('gpu_voltage', "GPU voltage"),
    ('hdr', "HDR status"),
    ('hide_fsr_sharpness', "Hide FSR sharpness"),
    ('histogram', "Histogram"),
    ('horizontal', "Horizontal"),
    ('horizontal_stretch', "Horizontal stretch"),
    ('hud_compact', "Compact HUD"),
    ('hud_no_margin', "No margins"),
    ('io_read', "IO read"),
    ('io_write', "IO write"),
    ('log_versioning', "Log versioning"),
    ('media_player', "Media player"),
    ('no_display', "Hidden by default"),
    ('no_small_font', "No small font"),
    ('permit_upload', "Permit upload"),
    ('present_mode', "Present mode"),
    ('proc_vram', "Process VRAM"),
    ('procmem', "Process memory"),
    ('procmem_shared', "Shared memory"),
    ('procmem_virt', "Virtual memory"),
    ('ram', "RAM"),
    ('ram_temp', "RAM temperature"),
    ('read_cfg', "Read config"),
    ('refresh_rate', "Refresh rate"),
    ('resolution', "Resolution"),
    ('retro', "Retro"),
    ('show_fps_limit', "Show FPS limit"),
    ('swap', "Swap"),
    ('temp_fahrenheit', "Fahrenheit"),
    ('text_outline', "Text outline"),
    ('throttling_status', "Throttling status"),
    ('throttling_status_graph', "Throttling graph"),
    ('time', "Time"),
    ('time_no_label', "Time without label"),
    ('trilinear', "Trilinear"),
    ('upload_logs', "Upload logs"),
    ('version', "Version"),
    ('vkbasalt', "vkBasalt"),
    ('vram', "VRAM"),
    ('vulkan_driver', "Vulkan driver"),
    ('wine', "Wine"),
    ('winesync', "Wine sync"),
]

MANGOHUD_FPS_OPTIONS = ['30', '40', '45', '48', '60', '75', '90', '120', '144', '165', '175', '240']

MANGOHUD_VALUE_SPECS = [
    {'key': 'position', 'label': _("Overlay position"), 'type': 'combo',
     'options': ['top-left', 'top-right', 'middle-left', 'middle-right',
                 'bottom-left', 'bottom-right', 'top-center', 'bottom-center']},
    {'key': 'device_battery', 'label': _("Device battery"), 'type': 'combo',
     'options': ['', 'gamepad', 'mouse', 'gamepad,mouse']},
    {'key': 'fps_limit_method', 'label': _("FPS limit method"), 'type': 'combo',
     'options': ['late', 'early']},
    {'key': 'af', 'label': _("Anisotropic filtering"), 'type': 'combo',
     'options': [str(value) for value in range(17)]},
    {'key': 'fcat_screen_edge', 'label': _("FCAT screen edge"), 'type': 'combo',
     'options': ['1', '2', '3', '4']},
    {'key': 'table_columns', 'label': _("Table columns"), 'type': 'combo',
     'options': ['1', '2', '3', '4', '5', '6']},
    {'key': 'network', 'label': _("Network (tx/rx kb/s)"), 'type': 'combo',
     'options': ['']},
    {'key': 'gpu_list', 'label': _("GPU list"), 'type': 'combo',
     'options': ['']},
    {'key': 'background_alpha', 'label': _("Background opacity"), 'type': 'combo',
     'options': [f'{i / 10:.1f}' for i in range(11)]},
    {'key': 'round_corners', 'label': _("Round corners (px)"), 'type': 'combo',
     'options': [str(i) for i in range(16)]},
    {'key': 'font_scale', 'label': _("Font scale"), 'type': 'combo',
     'options': ['', '0.5', '0.75', '1.0', '1.25', '1.5', '2.0']},
    {'key': 'font_size', 'label': _("Font size"), 'type': 'line'},
    {'key': 'font_file', 'label': _("Font"), 'type': 'combo', 'options': []},
]

MANGOHUD_FONT_KEYS = {'font_scale', 'font_size', 'font_file'}

MANGOHUD_VALUE_OPTION_TRANSLATIONS = {
    'position': {
        'top-left': _("Top-left"),
        'top-right': _("Top-right"),
        'middle-left': _("Middle-left"),
        'middle-right': _("Middle-right"),
        'bottom-left': _("Bottom-left"),
        'bottom-right': _("Bottom-right"),
        'top-center': _("Top-center"),
        'bottom-center': _("Bottom-center"),
    },
    'device_battery': {
        'gamepad': _("Gamepad"),
        'mouse': _("Mouse"),
        'gamepad,mouse': _("Gamepad, mouse"),
    },
    'fps_limit_method': {
        'late': _("Late"),
        'early': _("Early"),
    },
}

MANGOHUD_VALUE_DEFAULTS = {
    'position': 'top-left',
    'device_battery': '',
    'fps_limit_method': 'late',
    'af': '0',
    'fcat_screen_edge': '1',
    'table_columns': '3',
    'network': '',
    'gpu_list': '',
    'background_alpha': '0.5',
    'round_corners': '0',
}

MANGOHUD_HIDDEN_EXTRA_KEYS = {
    'font_size',
}

MANGOHUD_BUTTON_PRESETS = {
    'fps_only': {
        'config': 'position=top-left',
        'fps_limit': '',
        'toggles': {'show_fps_limit'},
    },
    'compact': {
        'config': 'position=top-right,hud_compact',
        'fps_limit': '',
        'toggles': {'frametime', 'cpu_temp', 'gpu_temp', 'ram', 'vram', 'wine', 'winesync'},
    },
    'extended': {
        'config': 'position=top-left',
        'fps_limit': '',
        'toggles': {
            'frametime', 'frame_count', 'cpu_mhz', 'cpu_power', 'cpu_temp',
            'gpu_power', 'gpu_temp', 'ram', 'vram', 'io_read', 'io_write',
            'resolution', 'engine_version', 'vulkan_driver', 'wine', 'winesync', 'gamemode'
        },
    },
    'clear': {
        'config': '',
        'fps_limit': '',
        'toggles': set(),
    },
    'custom': {
        'config': '',
        'fps_limit': '',
        'toggles': set(),
    },
    'rivatuner': {
        'config': (
            'background_alpha=0.5,round_corners=0,text_color=e07a30,'
            'position=top-left,table_columns=5,gpu_text=GPU,gpu_stats,'
            'gpu_load_value=50+90,gpu_load_color=FFFFFF+FFAA7F+CC0000,gpu_temp,gpu_fan,'
            'gpu_power,gpu_color=258640,cpu_text=CPU,vram,cpu_load_value=50+90,'
            'cpu_load_color=FFFFFF+FFAA7F+CC0000,cpu_mhz,cpu_temp,cpu_color=30708d,'
            'cpu_stats,vram_color=258640,vram_color=258640,ram,fps,ram_color=30708d,'
            'wine_color=EB4B4B,frametime_color=d88989,fps_color=ff0000+FDFD09+ffffff,'
            'media_player_color=FFFFFF,engine_short_names,'
            'frame_timing,engine_color=d88989,text_outline_thickness=1.9'
        ),
        'fps_limit': '',
        'toggles': set(),
    },
}

MANGOHUD_TOGGLE_CATEGORIES = {
    _("General"): [
        'arch', 'battery', 'battery_icon', 'battery_time', 'battery_watt',
        'device_battery_icon', 'display_server', 'exec_name', 'gamemode',
        'media_player', 'time', 'time_no_label', 'version', 'vkbasalt',
        'wine', 'winesync',
    ],
    _("Performance"): [
        'bicubic', 'dynamic_frame_timing', 'flip_efficiency', 'fps_color_change',
        'fps_metrics', 'fps_only', 'frametime', 'frame_timing_detailed',
        'full', 'hide_fsr_sharpness', 'histogram', 'present_mode',
        'read_cfg', 'retro', 'show_fps_limit', 'trilinear',
    ],
    _("CPU / GPU"): [
        'core_bars', 'core_load', 'core_load_change', 'core_type',
        'cpu_efficiency', 'cpu_load_change', 'cpu_mhz', 'cpu_power', 'cpu_temp',
        'gpu_core_clock', 'gpu_efficiency', 'gpu_fan', 'gpu_junction_temp',
        'gpu_load_change', 'gpu_mem_clock', 'gpu_mem_temp', 'gpu_name',
        'gpu_power', 'gpu_power_limit', 'gpu_temp', 'gpu_voltage',
        'ram', 'ram_temp', 'swap', 'vram',
    ],
    _("Overlay"): [
        'debug', 'engine_short_names', 'engine_version', 'fan', 'fcat', 'fsr',
        'frame_count', 'hdr', 'horizontal', 'horizontal_stretch', 'hud_compact',
        'hud_no_margin', 'io_read', 'io_write', 'log_versioning', 'no_display',
        'no_small_font', 'permit_upload', 'proc_vram', 'procmem',
        'procmem_shared', 'procmem_virt', 'refresh_rate', 'resolution',
        'temp_fahrenheit', 'text_outline', 'throttling_status',
        'throttling_status_graph', 'upload_logs', 'vulkan_driver',
    ],
}

MANGOHUD_TOGGLE_DESCRIPTIONS = {
    'arch': _("Application architecture (32/64-bit)"),
    'battery': _("Battery percent and energy consumption"),
    'battery_icon': _("Battery icon instead of percent"),
    'battery_time': _("Remaining battery time"),
    'battery_watt': _("Battery wattage"),
    'bicubic': _("Force bicubic filtering"),
    'core_bars': _("Core load as vertical bars"),
    'core_load': _("Per-core load and frequency"),
    'core_load_change': _("Core load color change"),
    'core_type': _("CPU core type (P/E/ARM)"),
    'cpu_efficiency': _("CPU efficiency (frames/joule)"),
    'cpu_load_change': _("CPU load color change"),
    'cpu_mhz': _("CPU frequency in MHz"),
    'cpu_power': _("CPU power draw (watts)"),
    'cpu_temp': _("CPU temperature"),
    'debug': _("Gamescope frametime graphs"),
    'device_battery_icon': _("Wireless device battery icon"),
    'display_server': _("Display server type (X11/Wayland)"),
    'dynamic_frame_timing': _("Dynamic frametime Y-axis"),
    'engine_short_names': _("Short engine names"),
    'engine_version': _("Engine version (OpenGL/Vulkan)"),
    'exec_name': _("Executable name"),
    'fan': _("Steam Deck fan RPM"),
    'fcat': _("Frame capture analysis"),
    'flip_efficiency': _("Flip efficiency (joules/frame)"),
    'fps_color_change': _("FPS text color by value"),
    'fps_metrics': _("FPS percentiles"),
    'fps_only': _("Show FPS only"),
    'frame_count': _("Frame counter"),
    'frametime': _("Frametime next to FPS"),
    'frame_timing_detailed': _("Detailed frame timing chart"),
    'fsr': _("FSR status (gamescope)"),
    'full': _("Enable most parameters"),
    'gamemode': _("GameMode status"),
    'gpu_core_clock': _("GPU core frequency"),
    'gpu_efficiency': _("GPU efficiency (frames/joule)"),
    'gpu_fan': _("GPU fan (RPM/%)"),
    'gpu_junction_temp': _("GPU junction temperature"),
    'gpu_load_change': _("GPU load color change"),
    'gpu_mem_clock': _("GPU memory frequency"),
    'gpu_mem_temp': _("GPU memory temperature"),
    'gpu_name': _("GPU name from pci.ids"),
    'gpu_power': _("GPU power draw (watts)"),
    'gpu_power_limit': _("GPU power limit"),
    'gpu_temp': _("GPU temperature"),
    'gpu_voltage': _("GPU voltage"),
    'hdr': _("HDR status (gamescope)"),
    'hide_fsr_sharpness': _("Hide FSR sharpness info"),
    'histogram': _("FPS histogram"),
    'horizontal': _("Horizontal HUD layout"),
    'horizontal_stretch': _("Stretch background horizontally"),
    'hud_compact': _("Compact HUD mode"),
    'hud_no_margin': _("Remove HUD margins"),
    'io_read': _("IO read rate (MiB/s)"),
    'io_write': _("IO write rate (MiB/s)"),
    'log_versioning': _("Add versioning to logs"),
    'media_player': _("Media player metadata"),
    'no_display': _("Hide HUD by default"),
    'no_small_font': _("Use primary font size"),
    'permit_upload': _("Allow log uploads"),
    'present_mode': _("Vulkan present mode"),
    'proc_vram': _("Process VRAM usage"),
    'procmem': _("Process memory (resident)"),
    'procmem_shared': _("Process shared memory"),
    'procmem_virt': _("Process virtual memory"),
    'ram': _("System RAM usage"),
    'ram_temp': _("RAM temperature (DDR5)"),
    'read_cfg': _("Load config file"),
    'refresh_rate': _("Refresh rate (gamescope)"),
    'resolution': _("Current resolution"),
    'retro': _("Retro filtering (unfiltered)"),
    'show_fps_limit': _("Show FPS limit"),
    'swap': _("Swap usage"),
    'temp_fahrenheit': _("Temperature in Fahrenheit"),
    'text_outline': _("Text outline"),
    'throttling_status': _("GPU throttling status"),
    'throttling_status_graph': _("Throttling in frame graph"),
    'time': _("Local time"),
    'time_no_label': _("Time without label"),
    'trilinear': _("Force trilinear filtering"),
    'upload_logs': _("Automatic log uploads"),
    'version': _("MangoHud version"),
    'vkbasalt': _("Status vkBasalt"),
    'vulkan_driver': _("Vulkan driver (radv/amdvlk)"),
    'wine': _("Wine/Proton version"),
    'winesync': _("Wine sync method"),
    'vram': _("VRAM usage"),
}


class MangoHudSettingsMixin:
    """Mixin with MangoHud settings UI and serialization logic."""
    theme: Any
    tab_widget: Any
    portproton_path: str | None
    current_settings: dict[str, str]
    mangohud_tab: QWidget
    mangohud_tab_layout: QVBoxLayout
    show_gamepad_tooltip: Any
    register_gamepad_tooltip: Any
    show_registered_gamepad_tooltip: Any
    start_sh: list[str] | None
    _get_process_args: Any
    sender: Any

    def init_mangohud_state(self):
        self.mangohud_widgets = {}
        self.mangohud_original_values = {}
        self.mangohud_hidden_extra_tokens = []
        self.mangohud_toggle_widgets = {}
        self.mangohud_toggle_widget_keys = {}
        self.mangohud_fps_widgets = {}
        self.mangohud_category_groups = {}
        self.mangohud_search_widget = None
        self.mangohud_gpu_options = []
        self.mangohud_actions_group = None
        self.mangohud_presets_group = None
        self.mangohud_toggle_group = None
        self.mangohud_values_group = None
        self.mangohud_fonts_group = None
        self.mangohud_fps_group = None
        self.mangohud_extra_group = None
        self.mangohud_action_buttons = []
        self.mangohud_preset_buttons = []

    def setup_mangohud_tab(self):
        """Create MangoHud tab widgets."""

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setStyleSheet(self.theme.SCROLL_STYLE + self.theme.TRANSPARENT_BACKGROUND_STYLE)
        container = QWidget()
        container.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.theme.exeSettingsGroupBoxBlockSpacing)

        self._add_mangohud_presets_group(layout)
        self._add_mangohud_toggle_group(layout)
        self._add_mangohud_values_group(layout)
        self._add_mangohud_fonts_group(layout)
        self._add_mangohud_fps_group(layout)
        self._add_mangohud_extra_group(layout)
        layout.addStretch()

        scroll.setWidget(container)

        self.mangohud_tab_layout.addWidget(scroll)

    def _add_mangohud_values_group(self, parent_layout):
        """Add MangoHud value controls."""
        group = QGroupBox(_("Layout and limiter"))
        group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        form = QFormLayout(group)
        form.setVerticalSpacing(self.theme.exeSettingsGroupBoxElementVerticalSpacing)
        form.setHorizontalSpacing(self.theme.exeSettingsGroupBoxElementHorizontalSpacing)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.mangohud_values_group = group
        self.mangohud_gpu_options = self._get_mangohud_gpu_options()
        gpu_count = sum(1 for _text, value in self.mangohud_gpu_options if value.isdigit())

        for spec in MANGOHUD_VALUE_SPECS:
            if spec['key'] in MANGOHUD_FONT_KEYS:
                continue
            if spec['key'] == 'fps_limit_method':
                continue
            if spec['key'] == 'gpu_list' and gpu_count < 2:
                continue
            form.addRow(spec['label'], self._create_mangohud_value_widget(spec))

        parent_layout.addWidget(group)

    def _add_mangohud_fonts_group(self, parent_layout):
        """Add MangoHud font controls."""
        group = QGroupBox(_("Fonts"))
        group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        form = QFormLayout(group)
        form.setVerticalSpacing(self.theme.exeSettingsGroupBoxElementVerticalSpacing)
        form.setHorizontalSpacing(self.theme.exeSettingsGroupBoxElementHorizontalSpacing)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.mangohud_fonts_group = group

        for spec in MANGOHUD_VALUE_SPECS:
            if spec['key'] in MANGOHUD_FONT_KEYS:
                form.addRow(spec['label'], self._create_mangohud_value_widget(spec))

        parent_layout.addWidget(group)

    def _create_mangohud_value_widget(self, spec):
        """Create a MangoHud value widget."""
        if spec['type'] == 'line':
            widget = QLineEdit()
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.installEventFilter(cast(QWidget, self))
            widget.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
            self.mangohud_widgets[spec['key']] = widget
            return widget

        widget = CustomComboBox(theme=self.theme)
        widget.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        widget.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        options = spec['options']
        placeholder_text = _("Default value")
        if spec['key'] == 'network':
            options = self._get_mangohud_network_options()
        if spec['key'] == 'gpu_list':
            gpu_options = self.mangohud_gpu_options or self._get_mangohud_gpu_options()
            for text, value in gpu_options:
                widget.addItem(text, value)
        elif spec['key'] == 'font_file':
            widget.addItem(placeholder_text, '')
            for text, value in self._get_mangohud_font_options():
                widget.addItem(text, value)
        else:
            value_translations = MANGOHUD_VALUE_OPTION_TRANSLATIONS.get(spec['key'], {})
            for option in options:
                display_text = placeholder_text if option == '' else value_translations.get(option, option)
                widget.addItem(display_text, option)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        widget.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        default_value = MANGOHUD_VALUE_DEFAULTS.get(spec['key'], '')
        default_index = widget.findData(default_value)
        if default_value and default_index >= 0:
            widget.setCurrentIndex(default_index)
        else:
            widget.setCurrentIndex(0)
        self.mangohud_widgets[spec['key']] = widget
        return widget

    def _get_mangohud_font_options(self) -> list[tuple[str, str]]:
        """Get installed font names and files from fontconfig."""
        try:
            result = subprocess.run(
                ['fc-list', '--format=%{family[0]} %{style[0]}\t%{file}\n'],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Failed to list system fonts: %s", exc)
            return []
        if result.returncode != 0:
            logger.warning("fc-list failed with exit code %s", result.returncode)
            return []

        fonts = set()
        for line in result.stdout.splitlines():
            name, separator, path = line.partition('\t')
            if separator and path.lower().endswith(('.ttf', '.otf')):
                fonts.add((name.strip(), path.strip()))
        return sorted(fonts, key=lambda font: font[0].lower())

    def _add_mangohud_presets_group(self, parent_layout):
        """Add preset buttons for common MangoHud layouts."""
        presets_group = QGroupBox(_("Presets"))
        presets_group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        presets_layout = QGridLayout(presets_group)
        presets_layout.setVerticalSpacing(self.theme.exeSettingsGroupBoxElementVerticalSpacing)
        presets_layout.setHorizontalSpacing(self.theme.exeSettingsGroupBoxElementHorizontalSpacing)
        self.mangohud_presets_group = presets_group

        actions_group = QGroupBox(_("Actions"))
        actions_group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        actions_layout = QGridLayout(actions_group)
        actions_layout.setVerticalSpacing(self.theme.exeSettingsGroupBoxElementVerticalSpacing)
        actions_layout.setHorizontalSpacing(self.theme.exeSettingsGroupBoxElementHorizontalSpacing)
        columns = self.theme.mangoHudPresetsColumns
        self.mangohud_actions_group = actions_group

        # Toggle buttons for PW_MANGOHUD and PW_MANGOHUD_USER_CONF
        self.mangohud_enable_button = QPushButton(_("Enable {0}").format("MangoHud"))
        self.mangohud_enable_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.mangohud_enable_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mangohud_enable_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mangohud_enable_button.clicked.connect(self.toggle_mangohud_enable)

        self.mangohud_user_conf_button = QPushButton(_("Use system config"))
        self.mangohud_user_conf_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.mangohud_user_conf_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mangohud_user_conf_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mangohud_user_conf_button.clicked.connect(self.toggle_mangohud_user_conf)

        actions_layout.addWidget(self.mangohud_enable_button, 0, 0)
        actions_layout.addWidget(self.mangohud_user_conf_button, 0, 1)

        preset_buttons = [
            ("PortProton", self.apply_portproton_default_mangohud),
            (_("FPS only"), lambda: self.apply_mangohud_button_preset('fps_only')),
            (_("Compact"), lambda: self.apply_mangohud_button_preset('compact')),
            (_("Extended"), lambda: self.apply_mangohud_button_preset('extended')),
            ("RivaTuner", lambda: self.apply_mangohud_button_preset('rivatuner')),
            (_("Custom"), lambda: self.apply_mangohud_button_preset('custom')),
            (_("Save custom"), self.save_custom_mangohud_preset),
            (_("Clear"), lambda: self.apply_mangohud_button_preset('clear')),
        ]

        action_buttons = [
            (_("Write system config"), self.write_system_mangohud_config),
            (_("Preview"), self.start_mangohud_preview),
        ]

        for index, (label, handler) in enumerate(preset_buttons):
            button = QPushButton(label)
            button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(handler)
            row = index // columns
            column = index % columns
            presets_layout.addWidget(button, row, column)
            self.mangohud_preset_buttons.append(button)

        for index, (label, handler) in enumerate(action_buttons):
            button = QPushButton(label)
            button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(handler)
            row = (index // columns) + 1
            column = index % columns
            actions_layout.addWidget(button, row, column)
            self.mangohud_action_buttons.append(button)

        parent_layout.addWidget(actions_group)
        parent_layout.addWidget(presets_group)

    def _add_mangohud_toggle_group(self, parent_layout):
        selector_group = QGroupBox(_("MangoHud switches"))
        selector_group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        selector_layout = QVBoxLayout(selector_group)
        self.mangohud_toggle_group = selector_group

        self.mangohud_category_combo = CustomComboBox(theme=self.theme)
        self.mangohud_category_combo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.mangohud_category_combo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.mangohud_category_combo.addItems(list(MANGOHUD_TOGGLE_CATEGORIES.keys()))
        self.mangohud_category_combo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.mangohud_category_combo.currentTextChanged.connect(self.on_mangohud_category_changed)
        selector_layout.addWidget(self.mangohud_category_combo)

        self.mangohud_category_stack = QStackedWidget()
        self.mangohud_category_stack.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)
        selector_layout.addWidget(self.mangohud_category_stack)

        toggle_lookup = dict(MANGOHUD_TOGGLE_SPECS)
        uncategorized = set(toggle_lookup.keys())
        columns = self.theme.mangoHudSwitchesColumns

        for category, keys in MANGOHUD_TOGGLE_CATEGORIES.items():
            inner_widget = QWidget()
            layout = QGridLayout(inner_widget)
            layout.setContentsMargins(0, 8, 0, 8)
            layout.setHorizontalSpacing(0)
            layout.setVerticalSpacing(self.theme.mangoHudSwitchesVerticalSpacing)

            num_real_columns = columns
            total_columns = num_real_columns * 2 + 1

            for col in range(total_columns):
                if col % 2 == 0:
                    layout.setColumnStretch(col, 1)
                else:
                    layout.setColumnStretch(col, 0)

            for index, key in enumerate(keys):
                if key not in toggle_lookup:
                    continue
                label = toggle_lookup[key]
                checkbox = self._create_mangohud_checkbox(label)
                row = index // num_real_columns
                col_in_row = index % num_real_columns
                real_col = col_in_row * 2 + 1
                layout.addWidget(checkbox, row, real_col)
                self.mangohud_toggle_widgets[key] = checkbox
                self.mangohud_toggle_widget_keys[checkbox] = key
                self.register_gamepad_tooltip(checkbox, MANGOHUD_TOGGLE_DESCRIPTIONS.get(key, ""))
                uncategorized.discard(key)

            self.mangohud_category_groups[category] = inner_widget
            self.mangohud_category_stack.addWidget(inner_widget)

        if uncategorized:
            inner_widget = QWidget()
            layout = QGridLayout(inner_widget)
            layout.setContentsMargins(0, 8, 0, 8)
            layout.setHorizontalSpacing(0)
            layout.setVerticalSpacing(self.theme.mangoHudSwitchesVerticalSpacing)

            num_real_columns = columns
            total_columns = num_real_columns * 2 + 1

            for col in range(total_columns):
                if col % 2 == 0:
                    layout.setColumnStretch(col, 1)
                else:
                    layout.setColumnStretch(col, 0)

            for index, key in enumerate(sorted(uncategorized)):
                label = toggle_lookup[key]
                checkbox = self._create_mangohud_checkbox(label)
                row = index // num_real_columns
                col_in_row = index % num_real_columns
                real_col = col_in_row * 2 + 1
                layout.addWidget(checkbox, row, real_col)
                self.mangohud_toggle_widgets[key] = checkbox
                self.mangohud_toggle_widget_keys[checkbox] = key
                self.register_gamepad_tooltip(checkbox, MANGOHUD_TOGGLE_DESCRIPTIONS.get(key, ""))

            self.mangohud_category_combo.addItem(_("Other"))
            self.mangohud_category_groups[_("Other")] = inner_widget
            self.mangohud_category_stack.addWidget(inner_widget)

        self._update_mangohud_category_stack_height()
        parent_layout.addWidget(selector_group)

    def _add_mangohud_fps_group(self, parent_layout):
        group = QGroupBox(_("FPS limit"))
        group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        layout = QVBoxLayout(group)
        layout.setSpacing(self.theme.exeSettingsGroupBoxElementHorizontalSpacing)
        self.mangohud_fps_group = group

        fps_limit_method_spec = next(
            (spec for spec in MANGOHUD_VALUE_SPECS if spec['key'] == 'fps_limit_method'),
            None,
        )
        if fps_limit_method_spec:
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            form.addRow(
                fps_limit_method_spec['label'],
                self._create_mangohud_value_widget(fps_limit_method_spec),
            )
            layout.addLayout(form)

        label = QLabel(_(
            "Select one or more FPS presets. The values are saved into FPS_LIMIT "
            "and MangoHud will also show the active FPS limit."
        ))
        label.setWordWrap(True)
        layout.addWidget(label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(self.theme.mangoHudFpsVerticalSpacing)

        num_real_columns = self.theme.mangoHudFpsColumns
        total_columns = num_real_columns * 2 + 1

        for col in range(total_columns):
            if col % 2 == 0:
                grid.setColumnStretch(col, 1)
            else:
                grid.setColumnStretch(col, 0)

        for index, fps in enumerate(MANGOHUD_FPS_OPTIONS):
            checkbox = QCheckBox(fps)
            checkbox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
            row = index // num_real_columns
            col_in_row = index % num_real_columns
            real_col = col_in_row * 2 + 1
            grid.addWidget(checkbox, row, real_col)
            self.mangohud_fps_widgets[fps] = checkbox

        layout.addLayout(grid)
        parent_layout.addWidget(group)

    def _add_mangohud_extra_group(self, parent_layout):
        """Add raw config field for unsupported MangoHud parameters."""
        group = QGroupBox(_("Extra args"))
        group.setStyleSheet(self.theme.QGROUP_BOX_STYLE)
        layout = QVBoxLayout(group)
        self.mangohud_extra_group = group
        label = QLabel(_("Additional comma-separated MangoHud options not covered by the GUI."))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.mangohud_extra_edit = QLineEdit()
        self.mangohud_extra_edit.setPlaceholderText(_("Example: battery,gpu_junction_temp,fps_color=39f900"))
        self.mangohud_extra_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mangohud_extra_edit.installEventFilter(cast(QWidget, self))
        self.mangohud_extra_edit.setStyleSheet(self.theme.ADDGAME_INPUT_STYLE)
        layout.addWidget(self.mangohud_extra_edit)
        parent_layout.addWidget(group)

    def _get_mangohud_network_options(self) -> list[str]:
        """Get available network interfaces for MangoHud network option."""
        options = ['']
        net_class_path = '/sys/class/net'
        try:
            if not os.path.isdir(net_class_path):
                return options

            interfaces = sorted(
                iface for iface in os.listdir(net_class_path)
                if iface and iface != 'lo'
            )
            options.extend(interfaces)
        except OSError as e:
            logger.warning("Failed to read network interfaces: %s", e)

        if len(options) == 1:
            options.append('eth0')
        return options

    def _get_mangohud_gpu_options(self) -> list[tuple[str, str]]:
        """Get available GPU options for MangoHud gpu_list value."""
        options = [(_("Default value"), '')]
        vk_gpu_info_output = get_cached_vk_gpu_info()
        if not vk_gpu_info_output:
            return options

        gpu_entries = []
        for gpu_block in vk_gpu_info_output.split("GPU #")[1:]:
            lines = [line.strip() for line in gpu_block.splitlines() if line.strip()]
            if not lines:
                continue
            gpu_id = lines[0].rstrip(':')
            if not gpu_id.isdigit():
                continue
            gpu_props = {
                key.strip(): value.strip()
                for line in lines[1:] if ':' in line
                for key, value in [line.split(':', 1)]
            }
            device_name = gpu_props.get('device_name', '').strip()
            device_type = gpu_props.get('device_type', '').strip()
            if device_type in {'CPU', 'VIRTUAL_GPU'}:
                continue
            if not device_name:
                continue
            gpu_entries.append((gpu_id, device_name))

        if not gpu_entries:
            return options

        if len(gpu_entries) > 1:
            all_gpu_ids = ','.join(gpu_id for gpu_id, _name in gpu_entries)
            options.append((_('All GPUs'), all_gpu_ids))
        for gpu_id, device_name in gpu_entries:
            options.append((device_name, gpu_id))

        return options

    def _create_mangohud_checkbox(self, label):
        """Create a styled MangoHud checkbox."""
        checkbox = QCheckBox(label)
        checkbox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        checkbox.installEventFilter(cast(QWidget, self))
        checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        return checkbox

    def on_mangohud_category_changed(self, category):
        """Switch visible MangoHud toggle category."""
        widget = self.mangohud_category_groups.get(category)
        if widget:
            self.mangohud_category_stack.setCurrentWidget(widget)
            self._update_mangohud_category_stack_height()

    def _on_focus_changed(self, _old, new):
        """Track focused MangoHud toggle checkbox and show tooltip."""
        if isinstance(new, QCheckBox) and self.show_registered_gamepad_tooltip(new):
            return
        current_tab = self.tab_widget.currentWidget()
        if current_tab in (
            self.mangohud_tab,
            getattr(self, "vkbasalt_tab", None),
            getattr(self, "gamescope_tab", None),
        ):
            self.show_gamepad_tooltip(show=False)

    def _update_mangohud_category_stack_height(self):
        """Update MangoHud category block height to current visible page."""
        current_widget = self.mangohud_category_stack.currentWidget()
        if not current_widget:
            return
        target_height = current_widget.sizeHint().height()
        if target_height > 0:
            self.mangohud_category_stack.setMinimumHeight(target_height)
            self.mangohud_category_stack.setMaximumHeight(target_height)

    def populate_mangohud(self):
        """Populate MangoHud tab from current settings."""
        parsed_config, raw_tokens = self._parse_mangohud_config(
            self.current_settings.get('MANGOHUD_CONFIG', '')
        )
        visible_raw_tokens, hidden_raw_tokens = self._split_mangohud_extra_tokens(raw_tokens)

        for spec in MANGOHUD_VALUE_SPECS:
            if spec['key'] not in self.mangohud_widgets:
                continue
            self._set_mangohud_value_widget(spec, parsed_config.get(spec['key']))

        for key, _label in MANGOHUD_TOGGLE_SPECS:
            checkbox = self.mangohud_toggle_widgets[key]
            checkbox.setChecked(self._mangohud_bool_value(parsed_config.get(key), False))

        fps_limit_values = self._get_mangohud_fps_values(parsed_config)
        for fps, checkbox in self.mangohud_fps_widgets.items():
            checkbox.setChecked(fps in fps_limit_values)

        self.mangohud_hidden_extra_tokens = hidden_raw_tokens
        self.mangohud_extra_edit.setText(', '.join(visible_raw_tokens))
        self.mangohud_original_values = {
            'MANGOHUD_CONFIG': self.current_settings.get('MANGOHUD_CONFIG', ''),
            'FPS_LIMIT': self.current_settings.get('FPS_LIMIT', ''),
        }
        self.mangohud_original_values['extra'] = ', '.join(visible_raw_tokens)
        self._update_mangohud_toggle_buttons()

    def _update_mangohud_toggle_buttons(self):
        """Update toggle button text and style based on current settings."""
        mangohud_enabled = self.current_settings.get('PW_MANGOHUD') == '1'
        mangohud_user_conf_enabled = self.current_settings.get('PW_MANGOHUD_USER_CONF') == '1'
        visible = mangohud_enabled
        config_visible = mangohud_enabled and not mangohud_user_conf_enabled

        if mangohud_enabled:
            self.mangohud_enable_button.setText(_("Disable {0}").format("MangoHud"))
            self.mangohud_enable_button.setStyleSheet(self.theme.ACTION_BUTTON_ACTIVE_STYLE)
        else:
            self.mangohud_enable_button.setText(_("Enable {0}").format("MangoHud"))
            self.mangohud_enable_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)

        self.mangohud_user_conf_button.setVisible(visible)
        if mangohud_user_conf_enabled:
            self.mangohud_user_conf_button.setText(_("Don't use system config"))
            self.mangohud_user_conf_button.setStyleSheet(self.theme.ACTION_BUTTON_ACTIVE_STYLE)
        else:
            self.mangohud_user_conf_button.setText(_("Use system config"))
            self.mangohud_user_conf_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)

        if self.mangohud_toggle_group is not None:
            self.mangohud_toggle_group.setVisible(config_visible)
        if self.mangohud_presets_group is not None:
            self.mangohud_presets_group.setVisible(config_visible)
        if self.mangohud_values_group is not None:
            self.mangohud_values_group.setVisible(config_visible)
        if self.mangohud_fonts_group is not None:
            self.mangohud_fonts_group.setVisible(config_visible)
        if self.mangohud_fps_group is not None:
            self.mangohud_fps_group.setVisible(config_visible)
        if self.mangohud_extra_group is not None:
            self.mangohud_extra_group.setVisible(config_visible)

        for button in self.mangohud_preset_buttons:
            button.setVisible(config_visible)
        for button in self.mangohud_action_buttons:
            button.setVisible(config_visible)

    def toggle_mangohud_enable(self):
        """Toggle PW_MANGOHUD setting."""
        current_val = self.current_settings.get('PW_MANGOHUD', '0')
        new_val = '0' if current_val == '1' else '1'
        self.current_settings['PW_MANGOHUD'] = new_val
        self._update_mangohud_toggle_buttons()

    def toggle_mangohud_user_conf(self):
        """Toggle PW_MANGOHUD_USER_CONF setting."""
        current_val = self.current_settings.get('PW_MANGOHUD_USER_CONF', '0')
        new_val = '0' if current_val == '1' else '1'
        self.current_settings['PW_MANGOHUD_USER_CONF'] = new_val
        self._update_mangohud_toggle_buttons()

    def apply_portproton_default_mangohud(self):
        """Apply MangoHud defaults from PortProton var file."""
        default_config = self._get_default_mangohud_config()
        if default_config is None:
            QMessageBox.warning(cast(QWidget, self), _("Error"), _("Failed to read default MangoHud config."))
            return
        self._apply_mangohud_config_to_widgets(default_config, '')

    def apply_mangohud_button_preset(self, preset_name):
        """Apply a built-in MangoHud preset button."""
        if preset_name == 'custom':
            preset = self._load_custom_mangohud_preset()
            if preset is None:
                QMessageBox.information(cast(QWidget, self), _("Information"), _("Custom preset is empty. Save one first."))
                return
            self._apply_mangohud_config_to_widgets(preset['config'], preset['fps_limit'])
            return
        preset = MANGOHUD_BUTTON_PRESETS[preset_name]
        self._apply_mangohud_config_to_widgets(preset['config'], preset['fps_limit'], preset['toggles'])

    def save_custom_mangohud_preset(self):
        """Save current MangoHud settings as custom preset."""
        preset = {
            'config': self._build_mangohud_config(),
            'fps_limit': '+'.join(
                fps for fps, checkbox in self.mangohud_fps_widgets.items() if checkbox.isChecked()
            ),
        }
        cp = configparser.ConfigParser()
        try:
            if CONFIG_FILE.exists():
                cp.read(CONFIG_FILE, encoding='utf-8')
            if 'MangoHudPresets' not in cp:
                cp['MangoHudPresets'] = {}
            cp['MangoHudPresets']['custom_config'] = preset['config']
            cp['MangoHudPresets']['custom_fps_limit'] = preset['fps_limit']
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                cp.write(f)
            QMessageBox.information(cast(QWidget, self), _("Success"), _("Custom preset saved."))
        except Exception as e:
            logger.warning("Failed to save custom MangoHud preset: %s", e)
            QMessageBox.warning(cast(QWidget, self), _("Error"), _("Failed to save custom preset."))

    def write_system_mangohud_config(self) -> None:
        """Write current MangoHud env config as system MangoHud.conf."""
        config_text = self._build_mangohud_config()
        parsed_config, raw_tokens = self._parse_mangohud_config(config_text)
        lines = []

        for key, value in parsed_config.items():
            if value is True:
                lines.append(key)
            else:
                line_value = str(value)
                if key == 'fps_limit':
                    line_value = line_value.replace('+', ',')
                lines.append(f"{key}={line_value}")

        lines.extend(raw_tokens)

        config_dir = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "MangoHud"
        config_path = config_dir / "MangoHud.conf"

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as file:
                file.write("\n".join(lines))
                file.write("\n")
            logger.info("MangoHud system config saved: %s", config_path)
            QMessageBox.information(
                cast(QWidget, self),
                _("Success"),
                _("System MangoHud config has been written."),
            )
        except OSError as e:
            logger.warning("Failed to write MangoHud system config %s: %s", config_path, e)
            QMessageBox.warning(
                cast(QWidget, self),
                _("Error"),
                _("Failed to write system MangoHud config."),
            )

    def start_mangohud_preview(self) -> None:
        """Start MangoHud preview using vkcube via PortProton CLI."""
        if not self.start_sh:
            logger.error("PortProton start command not found")
            return

        config_text = self._build_mangohud_config()

        process = QProcess(cast(QWidget, self))
        process.finished.connect(self._on_mangohud_preview_finished)
        process_args = ["cli", "--mangohud-preview", config_text]
        args = self._get_process_args(process_args)
        process.start(args[0], args[1:])
        if not process.waitForStarted(5000):
            QMessageBox.warning(cast(QWidget, self), _("Error"), _("Failed to run preview."))

    def _on_mangohud_preview_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """Show error if MangoHud preview process fails."""
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            return
        # vkcube/mangoapp may exit with SIGSEGV (139) on manual window close.
        if exit_code == 139:
            logger.info("MangoHud preview closed by user (exit code 139).")
            return
        process = cast(QProcess, self.sender())
        error_output = bytes(process.readAllStandardError().data()).decode('utf-8', 'ignore')
        if error_output:
            logger.warning("MangoHud preview failed: %s", error_output.strip())
        QMessageBox.warning(cast(QWidget, self), _("Error"), _("Failed to run preview."))

    def _load_custom_mangohud_preset(self):
        """Load custom MangoHud preset from config file."""
        cp = configparser.ConfigParser()
        try:
            if not CONFIG_FILE.exists():
                return None
            cp.read(CONFIG_FILE, encoding='utf-8')
            if not cp.has_section('MangoHudPresets'):
                return None
            custom_config = cp.get('MangoHudPresets', 'custom_config', fallback='').strip()
            custom_fps_limit = cp.get('MangoHudPresets', 'custom_fps_limit', fallback='').strip()
            if not custom_config and not custom_fps_limit:
                return None
            return {
                'config': custom_config,
                'fps_limit': custom_fps_limit,
            }
        except Exception as e:
            logger.warning("Failed to load custom MangoHud preset: %s", e)
            return None

    def _apply_mangohud_config_to_widgets(self, config_text, fps_limit, forced_toggles=None):
        """Apply MangoHud config text to the tab widgets."""
        parsed_config, raw_tokens = self._parse_mangohud_config(config_text)
        visible_raw_tokens, hidden_raw_tokens = self._split_mangohud_extra_tokens(raw_tokens)

        for spec in MANGOHUD_VALUE_SPECS:
            if spec['key'] not in self.mangohud_widgets:
                continue
            self._set_mangohud_value_widget(spec, parsed_config.get(spec['key']))

        enabled_toggles = forced_toggles if forced_toggles is not None else set()
        for key, _label in MANGOHUD_TOGGLE_SPECS:
            checkbox = self.mangohud_toggle_widgets[key]
            checkbox.setChecked(
                key in enabled_toggles or self._mangohud_bool_value(parsed_config.get(key), False)
            )

        fps_values = {value.strip() for value in fps_limit.replace('+', ',').split(',') if value.strip()}
        for fps, checkbox in self.mangohud_fps_widgets.items():
            checkbox.setChecked(fps in fps_values)

        self.mangohud_hidden_extra_tokens = hidden_raw_tokens
        self.mangohud_extra_edit.setText(', '.join(visible_raw_tokens))

    def _split_mangohud_extra_tokens(self, raw_tokens):
        """Split hidden MangoHud extra tokens from visible ones."""
        visible_tokens = []
        hidden_tokens = []
        for token in raw_tokens:
            key = token.split('=', 1)[0].strip()
            if key in MANGOHUD_HIDDEN_EXTRA_KEYS:
                hidden_tokens.append(token)
            else:
                visible_tokens.append(token)
        return visible_tokens, hidden_tokens

    def _set_mangohud_value_widget(self, spec, value):
        """Apply parsed value to a MangoHud value widget."""
        widget = self.mangohud_widgets.get(spec['key'])
        if widget is None:
            return
        text = value if isinstance(value, str) else ''
        if isinstance(widget, QLineEdit):
            widget.setText(text)
            return
        index = widget.findData(text)
        if text and index < 0:
            widget.addItem(text, text)
            index = widget.findData(text)
        if text:
            widget.setCurrentIndex(index)
        else:
            default_value = MANGOHUD_VALUE_DEFAULTS.get(spec['key'], '')
            default_index = widget.findData(default_value)
            if default_value and default_index >= 0:
                widget.setCurrentIndex(default_index)
            else:
                widget.setCurrentIndex(0)

    def _mangohud_bool_value(self, value, default_enabled):
        """Convert a MangoHud token to checkbox state."""
        if value is None:
            return default_enabled
        if value is True:
            return True
        return str(value).lower() not in {'0', 'false', 'no', 'off', 'disabled'}

    def _parse_mangohud_config(self, config_text):
        """Parse MANGOHUD_CONFIG into known values and raw tokens."""
        known_keys = {key for key, _label in MANGOHUD_TOGGLE_SPECS}
        known_keys.update(spec['key'] for spec in MANGOHUD_VALUE_SPECS)
        known_keys.add('fps_limit')
        bool_keys = {key for key, _label in MANGOHUD_TOGGLE_SPECS}
        parsed = {}
        raw_tokens = []
        current_key = None
        current_value = None

        for part in [token.strip() for token in config_text.split(',') if token.strip()]:
            if '=' in part:
                if current_key is not None:
                    self._store_mangohud_token(current_key, current_value, known_keys, parsed, raw_tokens)
                current_key, current_value = self._split_mangohud_token(part)
                continue

            if current_key is not None and part not in bool_keys:
                current_value = f"{current_value},{part}"
                continue

            if current_key is not None:
                self._store_mangohud_token(current_key, current_value, known_keys, parsed, raw_tokens)
                current_key = None
                current_value = None

            self._store_mangohud_token(part, True, known_keys, parsed, raw_tokens)

        if current_key is not None:
            self._store_mangohud_token(current_key, current_value, known_keys, parsed, raw_tokens)

        return parsed, raw_tokens

    def _split_mangohud_token(self, token):
        """Split a MangoHud token into key and value."""
        if '=' not in token:
            return token, True
        key, value = token.split('=', 1)
        return key.strip(), value.strip()

    def _store_mangohud_token(self, key, value, known_keys, parsed, raw_tokens):
        """Store a parsed MangoHud token in known or raw collections."""
        if key in known_keys:
            parsed[key] = value
            return
        raw_tokens.append(key if value is True else f"{key}={value}")

    def _build_mangohud_config(self):
        """Build MANGOHUD_CONFIG from the MangoHud tab."""
        tokens = []
        for spec in MANGOHUD_VALUE_SPECS:
            if spec['key'] not in self.mangohud_widgets:
                continue
            token = self._build_mangohud_value_token(spec)
            if token:
                tokens.append(token)

        for key, _label in MANGOHUD_TOGGLE_SPECS:
            token = self._build_mangohud_toggle_token(key)
            if token:
                tokens.append(token)

        fps_limit = '+'.join(
            fps for fps, checkbox in self.mangohud_fps_widgets.items() if checkbox.isChecked()
        )
        if fps_limit:
            if 'show_fps_limit' not in [
                key for key, _label in MANGOHUD_TOGGLE_SPECS if self.mangohud_toggle_widgets[key].isChecked()
            ]:
                tokens.append('show_fps_limit')
            tokens.append(f'fps_limit={fps_limit}')

        extra_text = self.mangohud_extra_edit.text().strip(' ,')
        if extra_text:
            tokens.append(extra_text)
        if self.mangohud_hidden_extra_tokens:
            tokens.extend(self.mangohud_hidden_extra_tokens)
        return ','.join(tokens)

    def _build_mangohud_toggle_token(self, key):
        """Build one MangoHud toggle token from a checkbox."""
        if self.mangohud_toggle_widgets[key].isChecked():
            return key
        return ''

    def _build_mangohud_value_token(self, spec):
        """Build one MangoHud value token."""
        widget = self.mangohud_widgets.get(spec['key'])
        if widget is None:
            return ''

        if isinstance(widget, QLineEdit):
            value = widget.text().strip()
        else:
            current_data = widget.currentData()
            value = '' if current_data is None else str(current_data).strip()
            if not value and current_data is None:
                value = widget.currentText().strip()
        if not value:
            return ''
        parsed_original, _raw_tokens = self._parse_mangohud_config(
            self.mangohud_original_values.get('MANGOHUD_CONFIG', '')
        )
        key = spec['key']
        default_value = MANGOHUD_VALUE_DEFAULTS.get(key, '')
        if key not in parsed_original and default_value and value == default_value:
            return ''
        return f"{spec['key']}={value}"

    def _get_mangohud_fps_values(self, parsed_config):
        """Get FPS limit values from settings."""
        fps_limit = self.current_settings.get('FPS_LIMIT', '').strip()
        if not fps_limit:
            fps_limit = parsed_config.get('fps_limit', '')
        return {value.strip() for value in fps_limit.replace('+', ',').split(',') if value.strip()}

    def _collect_mangohud_changes(self):
        """Collect MangoHud-specific changes."""
        changes = []
        original_values = cast(dict[str, str], getattr(self, 'original_values', {}))

        # Handle PW_MANGOHUD toggle
        mangohud_enabled = self.current_settings.get('PW_MANGOHUD') == '1'
        orig_mangohud = '1' if original_values.get('PW_MANGOHUD') == '1' else '0'
        new_mangohud = '1' if mangohud_enabled else '0'
        if new_mangohud != orig_mangohud:
            changes.append(f"PW_MANGOHUD={new_mangohud}")

        # Handle PW_MANGOHUD_USER_CONF toggle
        mangohud_user_conf_enabled = self.current_settings.get('PW_MANGOHUD_USER_CONF') == '1'
        orig_user_conf = '1' if original_values.get('PW_MANGOHUD_USER_CONF') == '1' else '0'
        new_user_conf = '1' if mangohud_user_conf_enabled else '0'
        if new_user_conf != orig_user_conf:
            changes.append(f"PW_MANGOHUD_USER_CONF={new_user_conf}")

        config_value = self._build_mangohud_config()
        if config_value != self.mangohud_original_values.get('MANGOHUD_CONFIG', ''):
            changes.append(f"MANGOHUD_CONFIG={config_value}")

        fps_limit = '+'.join(fps for fps, checkbox in self.mangohud_fps_widgets.items() if checkbox.isChecked())
        if fps_limit != self.mangohud_original_values.get('FPS_LIMIT', ''):
            changes.append(f"FPS_LIMIT={fps_limit}")

        return changes

    def _filter_mangohud_settings(self, search_text):
        """Filter MangoHud groups based on search text."""
        if not self.mangohud_category_groups:
            return
        config_visible = self.current_settings.get('PW_MANGOHUD') == '1' \
            and self.current_settings.get('PW_MANGOHUD_USER_CONF') != '1'
        for checkbox in self.mangohud_toggle_widgets.values():
            layout = checkbox.parentWidget().layout()
            if layout is not None:
                layout.removeWidget(checkbox)
        self._remove_mangohud_search_page()
        matching = []
        for key, checkbox in self.mangohud_toggle_widgets.items():
            description = MANGOHUD_TOGGLE_DESCRIPTIONS.get(key, '')
            matches = not search_text or search_text in f"{checkbox.text()} {description}".lower()
            checkbox.setVisible(matches)
            if matches:
                matching.append((key, checkbox))
        columns = self.theme.mangoHudSwitchesColumns
        if search_text:
            result_widget, result_layout = self._create_mangohud_search_page()
            for index, (_key, checkbox) in enumerate(matching):
                result_layout.addWidget(checkbox, index // columns, (index % columns) * 2 + 1)
            self.mangohud_category_combo.setVisible(False)
            self.mangohud_category_stack.setCurrentWidget(result_widget)
        else:
            category_positions = {}
            for key, checkbox in matching:
                category = next((name for name, keys in MANGOHUD_TOGGLE_CATEGORIES.items() if key in keys), _("Other"))
                widget = self.mangohud_category_groups[category]
                index = category_positions.get(category, 0)
                cast(QGridLayout, widget.layout()).addWidget(
                    checkbox, index // columns, (index % columns) * 2 + 1
                )
                category_positions[category] = index + 1
            self.mangohud_category_combo.setVisible(True)
            self.on_mangohud_category_changed(self.mangohud_category_combo.currentText())
        self._update_mangohud_category_stack_height()
        for group_box in self.mangohud_tab.findChildren(QGroupBox):
            if not config_visible:
                group_box.setVisible(group_box is self.mangohud_actions_group)
                continue
            if not search_text:
                group_box.setVisible(True)
                continue
            content_widgets = group_box.findChildren(QLabel) + group_box.findChildren(QCheckBox)
            content_match = any(search_text in widget.text().lower() for widget in content_widgets)
            group_box.setVisible(
                search_text in group_box.title().lower() or content_match
                or group_box is self.mangohud_toggle_group and bool(matching)
            )

    def _create_mangohud_search_page(self) -> tuple[QWidget, QGridLayout]:
        source_widget = next(iter(self.mangohud_category_groups.values()))
        source_layout = cast(QGridLayout, source_widget.layout())
        widget = QWidget()
        layout = QGridLayout(widget)
        margins = source_layout.contentsMargins()
        layout.setContentsMargins(margins.left(), margins.top(), margins.right(), margins.bottom())
        layout.setHorizontalSpacing(source_layout.horizontalSpacing())
        layout.setVerticalSpacing(source_layout.verticalSpacing())
        columns = self.theme.mangoHudSwitchesColumns
        for column in range(columns * 2 + 1):
            layout.setColumnStretch(column, source_layout.columnStretch(column))
        self.mangohud_category_stack.addWidget(widget)
        self.mangohud_search_widget = widget
        return widget, layout

    def _remove_mangohud_search_page(self) -> None:
        widget = getattr(self, 'mangohud_search_widget', None)
        if widget is None:
            return
        for checkbox in widget.findChildren(QCheckBox):
            checkbox.setParent(self.mangohud_toggle_group)
        self.mangohud_category_stack.removeWidget(widget)
        widget.deleteLater()
        self.mangohud_search_widget = None

    def _get_default_mangohud_config(self) -> str | None:
        """Read DEFAULT_MANGOHUD_CONFIG from scripts/var."""
        if not self.portproton_path:
            logger.warning("PortProton path not set")
            return None

        scripts_path = get_portproton_scripts_path()
        if not scripts_path:
            logger.warning("PortProton scripts path not set")
            return None

        var_path = os.path.join(scripts_path, "var")
        if not os.path.exists(var_path):
            logger.warning("var file not found: %s", var_path)
            return None

        try:
            with open(var_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("export DEFAULT_MANGOHUD_CONFIG="):
                        match = re.match(r'^export DEFAULT_MANGOHUD_CONFIG=(.*)$', line)
                        if match:
                            value = match.group(1).strip().strip('"\'')
                            if value.startswith("DEFAULT_"):
                                value = value[8:]
                            return value
        except Exception as e:
            logger.warning("Failed to read var file: %s", e)

        return None
