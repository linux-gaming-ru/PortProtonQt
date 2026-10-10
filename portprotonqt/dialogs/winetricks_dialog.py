"""Winetricks dialog for PortProtonQt."""

import os
import re
from typing import cast, TYPE_CHECKING
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTextEdit, QTabWidget,
    QTableWidget, QHeaderView, QTableWidgetItem, QAbstractItemView,
    QStackedWidget, QWidget, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment

if TYPE_CHECKING:
    from portprotonqt.main_window import MainWindow

from PySide6.QtGui import QTextCursor

from portprotonqt.config import get_portproton_location, ui_config
from portprotonqt.logger import get_logger
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.custom_widgets import AutoSizeButton
from portprotonqt.dialogs.base import DraggableDialog
from portprotonqt.preloader import Preloader
from portprotonqt.localization import _
from portprotonqt.dialogs.dialog_utils import create_dialog_hints_widget, update_dialog_hints

logger = get_logger(__name__)
theme_manager = ThemeManager()


class WinetricksDialog(DraggableDialog):
    """Dialog for managing Wine prefixes using winetricks."""

    def __init__(self, parent=None, theme=None, prefix_path: str | None = None, wine_use: str | None = None):
        super().__init__(parent)
        self.theme = theme if theme else theme_manager.apply_theme(ui_config.get_theme())
        self.prefix_path: str | None = prefix_path
        self.wine_use: str | None = wine_use
        self.start_sh: list[str] | None = None
        self.portproton_path = get_portproton_location()
        if self.portproton_path is None:
            logger.error("PortProton location not found")
            return
        if self.prefix_path is None:
            logger.error("Prefix path not provided")
            return
        self.log_path = os.path.join(self.prefix_path, "winetricks.log")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        if not os.path.exists(self.log_path):
            open(self.log_path, 'a').close()

        self.apply_process: QProcess | None = None
        self.list_processes: dict[str, QProcess] = {}
        parent_obj = self.parent()
        while parent_obj:
            if hasattr(parent_obj, 'start_sh'):
                self.start_sh = cast("MainWindow", parent_obj).start_sh
                break
            parent_obj = parent_obj.parent()

        self.setWindowTitle(_("Prefix Manager"))
        self.setModal(True)
        self.resize(700, 700)
        self.setStyleSheet(self.theme.MAIN_WINDOW_STYLE + self.theme.MESSAGE_BOX_STYLE)

        self.setup_ui()
        self.load_lists()

        self.input_manager = None
        self.main_window = None
        parent_obj = self.parent()
        while parent_obj:
            if hasattr(parent_obj, 'input_manager'):
                self.input_manager = cast("MainWindow", parent_obj).input_manager
                self.main_window = parent_obj
            parent_obj = parent_obj.parent()

        self.current_theme_name = ui_config.get_theme()

        if self.input_manager:
            self.input_manager.enable_winetricks_mode(self)

        self.hints_widget, self.hints_labels = create_dialog_hints_widget(
            self.theme, self.main_window, self.input_manager, context='winetricks'
        )
        self.main_layout.addWidget(self.hints_widget)

        if self.input_manager:
            def update_hints(*_args: object) -> None:
                update_dialog_hints(
                    self.hints_labels, self.main_window, self.input_manager,
                    theme_manager, self.current_theme_name,
                )
            self.input_manager.connect_surface_updates('winetricks_dialog', update_hints)
            update_dialog_hints(self.hints_labels, self.main_window, self.input_manager, theme_manager, self.current_theme_name)

    def setup_ui(self):
        """Set up the user interface with tabs and tables."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.log_output.setStyleSheet(self.theme.GETWINE_WINDOW_STYLE + self.theme.SCROLL_STYLE)
        self.main_layout.addWidget(self.log_output)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(self.theme.GETWINE_WINDOW_STYLE + self.theme.TAB_STYLE)

        table_base_style = self.theme.GETWINE_WINDOW_STYLE + self.theme.SCROLL_STYLE + self.theme.CHECKBOX_STYLE

        self.dll_table = QTableWidget()
        self.dll_table.setAlternatingRowColors(True)
        self.dll_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.dll_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dll_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dll_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dll_table.setColumnCount(3)
        self.dll_table.setHorizontalHeaderLabels([_("Set"), _("Libraries"), _("Information")])
        self.dll_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.dll_table.horizontalHeader().resizeSection(0, self.theme.WINETRICKS_CHECK_COLUMN_WIDTH)
        self.dll_table.verticalHeader().setDefaultSectionSize(self.theme.WINETRICKS_ROW_HEIGHT)
        self.dll_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dll_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.dll_table.setStyleSheet(table_base_style)

        self.dll_preloader = Preloader()
        dll_preloader_container = QWidget()
        dll_preloader_layout = QVBoxLayout(dll_preloader_container)
        dll_preloader_layout.addStretch()
        dll_preloader_hlayout = QHBoxLayout()
        dll_preloader_hlayout.addStretch()
        dll_preloader_hlayout.addWidget(self.dll_preloader)
        dll_preloader_hlayout.addStretch()
        dll_preloader_layout.addLayout(dll_preloader_hlayout)
        dll_preloader_layout.addStretch()
        dll_preloader_layout.setContentsMargins(0, 0, 0, 0)
        dll_preloader_layout.setSpacing(0)

        self.dll_container = QStackedWidget()
        self.dll_container.addWidget(dll_preloader_container)
        self.dll_container.addWidget(self.dll_table)
        self.tab_widget.addTab(self.dll_container, "DLLs")

        self.fonts_table = QTableWidget()
        self.fonts_table.setAlternatingRowColors(True)
        self.fonts_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.fonts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fonts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fonts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fonts_table.setColumnCount(3)
        self.fonts_table.setHorizontalHeaderLabels([_("Set"), _("Fonts"), _("Information")])
        self.fonts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.fonts_table.horizontalHeader().resizeSection(0, self.theme.WINETRICKS_CHECK_COLUMN_WIDTH)
        self.fonts_table.verticalHeader().setDefaultSectionSize(self.theme.WINETRICKS_ROW_HEIGHT)
        self.fonts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.fonts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.fonts_table.setStyleSheet(table_base_style)

        self.fonts_preloader = Preloader()
        fonts_preloader_container = QWidget()
        fonts_preloader_layout = QVBoxLayout(fonts_preloader_container)
        fonts_preloader_layout.addStretch()
        fonts_preloader_hlayout = QHBoxLayout()
        fonts_preloader_hlayout.addStretch()
        fonts_preloader_hlayout.addWidget(self.fonts_preloader)
        fonts_preloader_hlayout.addStretch()
        fonts_preloader_layout.addLayout(fonts_preloader_hlayout)
        fonts_preloader_layout.addStretch()
        fonts_preloader_layout.setContentsMargins(0, 0, 0, 0)
        fonts_preloader_layout.setSpacing(0)

        self.fonts_container = QStackedWidget()
        self.fonts_container.addWidget(fonts_preloader_container)
        self.fonts_container.addWidget(self.fonts_table)
        self.tab_widget.addTab(self.fonts_container, _("Fonts"))

        self.settings_table = QTableWidget()
        self.settings_table.setAlternatingRowColors(True)
        self.settings_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.settings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.settings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.settings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.settings_table.setColumnCount(3)
        self.settings_table.setHorizontalHeaderLabels([_("Set"), _("Settings"), _("Information")])
        self.settings_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.settings_table.horizontalHeader().resizeSection(0, self.theme.WINETRICKS_CHECK_COLUMN_WIDTH)
        self.settings_table.verticalHeader().setDefaultSectionSize(self.theme.WINETRICKS_ROW_HEIGHT)
        self.settings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.settings_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.settings_table.setStyleSheet(table_base_style)

        self.settings_preloader = Preloader()
        settings_preloader_container = QWidget()
        settings_preloader_layout = QVBoxLayout(settings_preloader_container)
        settings_preloader_layout.addStretch()
        settings_preloader_hlayout = QHBoxLayout()
        settings_preloader_hlayout.addStretch()
        settings_preloader_hlayout.addWidget(self.settings_preloader)
        settings_preloader_hlayout.addStretch()
        settings_preloader_layout.addLayout(settings_preloader_hlayout)
        settings_preloader_layout.addStretch()
        settings_preloader_layout.setContentsMargins(0, 0, 0, 0)
        settings_preloader_layout.setSpacing(0)

        self.settings_container = QStackedWidget()
        self.settings_container.addWidget(settings_preloader_container)
        self.settings_container.addWidget(self.settings_table)
        self.tab_widget.addTab(self.settings_container, _("Settings"))

        for table in (self.dll_table, self.fonts_table, self.settings_table):
            table.currentCellChanged.connect(
                lambda row, *_previous, table=table: table.setFocusProxy(
                    cast(QCheckBox, table.cellWidget(row, 0).findChild(QCheckBox))
                ) if table.cellWidget(row, 0) else None
            )

        self.containers = {
            "dlls": self.dll_container,
            "fonts": self.fonts_container,
            "settings": self.settings_container
        }

        self.main_layout.addWidget(self.tab_widget)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        self.cancel_button = AutoSizeButton(_("Cancel"), icon=theme_manager.get_icon("cancel", as_path=True))
        self.force_button = AutoSizeButton(_("Force Install"), icon=theme_manager.get_icon("apply", as_path=True))
        self.install_button = AutoSizeButton(_("Install"), icon=theme_manager.get_icon("apply", as_path=True))
        self.cancel_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.force_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.install_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.force_button)
        button_layout.addWidget(self.install_button)
        self.main_layout.addLayout(button_layout)

        self.cancel_button.clicked.connect(self.reject)
        self.force_button.clicked.connect(lambda: self.install_selected(force=True))
        self.install_button.clicked.connect(lambda: self.install_selected(force=False))

    def load_lists(self):
        """Load and populate the lists for DLLs, Fonts, and Settings."""
        if self.start_sh is None or self.wine_use is None:
            QMessageBox.warning(self, _("Error"), _("Winetricks not found. Please try again."))
            self.reject()
            return

        env = QProcessEnvironment.systemEnvironment()

        self.containers["dlls"].setCurrentIndex(0)
        self.containers["fonts"].setCurrentIndex(0)
        self.containers["settings"].setCurrentIndex(0)
        self._start_list_all_process(env)

    def _start_list_all_process(self, env: QProcessEnvironment) -> None:
        """Start QProcess for all winetricks lists."""
        assert self.prefix_path is not None
        assert self.start_sh is not None
        assert self.wine_use is not None
        process = QProcess(self)
        process.setProcessEnvironment(env)
        process.finished.connect(
            lambda exit_code, exit_status: self._on_list_all_finished(process, exit_code, exit_status)
        )
        prefix_name = os.path.basename(self.prefix_path.rstrip(os.sep))
        args = self.start_sh[1:] + ["cli", "--winetricks-list-all", self.wine_use, prefix_name]
        self.list_processes["all"] = process
        process.start(self.start_sh[0], args)

    def _on_list_all_finished(
        self, process: QProcess, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        """Handle all lists completion."""
        output = bytes(process.readAllStandardOutput().data()).decode('utf-8', 'ignore')
        error_output = bytes(process.readAllStandardError().data()).decode('utf-8', 'ignore')
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self._log_process_warnings(error_output)
            sections = self._split_list_output(output)
            self.populate_table(
                self.dll_table, sections.get("dlls", ""), self.get_dll_exclusions(), self.log_path
            )
            self.populate_table(
                self.fonts_table, sections.get("fonts", ""), self.get_fonts_exclusions(), self.log_path
            )
            self.populate_table(
                self.settings_table, sections.get("settings", ""), self.get_settings_exclusions(), self.log_path
            )
            for table in [self.dll_table, self.fonts_table, self.settings_table]:
                if table.rowCount() > 0:
                    table.setCurrentCell(0, 0)
        else:
            logger.error(f"Failed to list winetricks: {error_output}")

        self.list_processes.pop("all", None)
        process.deleteLater()
        for category in ["dlls", "fonts", "settings"]:
            self.containers[category].setCurrentIndex(1)

    def _log_process_warnings(self, error_output: str) -> None:
        """Log suspicious stderr lines from helper scripts."""
        patterns = ("error", "failed", "syntax", "ошибка", "синтакс")
        for line in error_output.splitlines():
            clean_line = line.strip()
            if not clean_line:
                continue
            if any(pattern in clean_line.lower() for pattern in patterns):
                logger.warning("Winetricks list warning: %s", clean_line)

    def _split_list_output(self, output: str) -> dict[str, str]:
        """Split combined winetricks output by category markers."""
        sections: dict[str, list[str]] = {}
        category = ""
        for line in output.splitlines():
            if line.startswith("__PORTPROTONQT_WINETRICKS_SECTION__:"):
                category = line.rsplit(":", 1)[1]
                sections[category] = []
                continue
            if category:
                sections[category].append(line)
        return {key: "\n".join(lines) for key, lines in sections.items()}

    def get_dll_exclusions(self):
        """Get regex pattern for DLL exclusions."""
        return r'(d3d|directx9|dont_use|dxvk|vkd3d|galliumnine|faudio1|Foundation)'

    def get_fonts_exclusions(self):
        """Get regex pattern for Fonts exclusions."""
        return r'dont_use'

    def get_settings_exclusions(self):
        """Get regex pattern for Settings exclusions."""
        return r'(vista|alldlls|autostart_|bad|good|win|videomemory|vd=|isolate_home)'

    def populate_table(self, table, output, exclusion_pattern, log_path):
        """Populate the table with items from output, checking installation status."""
        table.setRowCount(0)
        table.verticalHeader().setVisible(False)
        lines = output.strip().split('\n')
        installed = set()
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    installed.add(line.strip())

        line_re = re.compile(r"^\s*(?:\[(.)]\s+)?([^\s]+)\s*(.*)")

        for line in lines:
            line = line.strip()
            line = re.sub(r'(?:\x1b|\033)?\[[0-9;]*m', '', line).strip()
            if not line or re.search(exclusion_pattern, line, re.I):
                continue

            line = line.split('(', 1)[0].strip()

            match = line_re.match(line)
            if not match:
                continue

            _status, name, info = match.groups()
            info = re.sub(r'\[.*?\]', '', info).strip()

            if info.startswith(' '):
                info = info[1:].lstrip()

            if '/' in name or '\\' in name or name.lower() in ('executing', 'using', 'warning:') or name.endswith(':'):
                continue

            checked = name in installed

            row = table.rowCount()
            table.insertRow(row)

            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox = QCheckBox()
            checkbox.setChecked(checked)
            checkbox_layout.addWidget(checkbox)
            table.setCellWidget(row, 0, checkbox_widget)

            name_item = QTableWidgetItem(name)
            table.setItem(row, 1, name_item)

            info_item = QTableWidgetItem(info)
            table.setItem(row, 2, info_item)

    def install_selected(self, force=False):
        """Install selected components."""
        selected = []
        for table in [self.dll_table, self.fonts_table, self.settings_table]:
            for row in range(table.rowCount()):
                checkbox_widget = table.cellWidget(row, 0)
                checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
                if checkbox is not None and checkbox.isChecked():
                    name_item = table.item(row, 1)
                    if name_item is not None:
                        name = name_item.text()
                        if name and name not in selected:
                            selected.append(name)

        installed = set()
        if os.path.exists(self.log_path):
            with open(self.log_path) as f:
                for line in f:
                    installed.add(line.strip())

        new_selected = [name for name in selected if name not in installed]

        if not new_selected:
            QMessageBox.information(self, _("Warning"), _("No components selected."))
            return

        self.install_button.setEnabled(False)
        self.force_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

        self._start_install_process(new_selected, force)

    def _start_install_process(self, selected, force):
        """Start QProcess for install."""
        assert self.prefix_path is not None
        if self.start_sh is None or self.wine_use is None:
            return
        env = QProcessEnvironment.systemEnvironment()

        self.apply_process = QProcess(self)
        self.apply_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.apply_process.setProcessEnvironment(env)
        self.apply_process.readyReadStandardOutput.connect(self._on_ready_read)
        self.apply_process.finished.connect(
            lambda exit_code, exit_status: self._on_install_finished(exit_code, exit_status, selected)
        )
        prefix_name = os.path.basename(self.prefix_path.rstrip(os.sep))
        force_arg = "--force" if force else "--no-force"
        args = self.start_sh[1:] + [
            "cli",
            "--winetricks-install",
            self.wine_use,
            prefix_name,
            force_arg,
        ] + selected
        self.apply_process.start(self.start_sh[0], args)

    def _on_ready_read(self):
        """Handle ready read for install process."""
        if self.apply_process is None:
            return
        data = self.apply_process.readAllStandardOutput().data()
        message = bytes(data).decode('utf-8', 'ignore').strip()
        self._log(message)

    def _on_install_finished(self, exit_code, exit_status, selected):
        """Handle install completion."""
        error_message = ""
        if self.apply_process is not None:
            if self.apply_process.processChannelMode() == QProcess.ProcessChannelMode.MergedChannels:
                output_data = self.apply_process.readAllStandardOutput().data()
                error_message = bytes(output_data).decode('utf-8', 'ignore')
            else:
                error_data = self.apply_process.readAllStandardError().data()
                error_message = bytes(error_data).decode('utf-8', 'ignore')

        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            logger.error(f"Winetricks install failed: {error_message}")
            QMessageBox.warning(self, _("Error"), _("Installation failed. Check logs."))
        else:
            if os.path.exists(self.log_path):
                with open(self.log_path) as f:
                    existing = {line.strip() for line in f if line.strip()}
            else:
                existing = set()
            with open(self.log_path, 'a') as f:
                for name in selected:
                    if name not in existing:
                        f.write(f"{name}\n")
            logger.info("Winetricks installation completed successfully.")
            QMessageBox.information(self, _("Success"), _("Components installed successfully."))
            self.load_lists()

        self.install_button.setEnabled(True)
        self.force_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def _log(self, message):
        """Add to log."""
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)

    def _stop_processes(self):
        """Stop running child processes."""
        processes = list(self.list_processes.values())
        if self.apply_process is not None:
            processes.append(self.apply_process)

        for process in processes:
            if process.state() == QProcess.ProcessState.NotRunning:
                continue
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
        self.list_processes.clear()

    def closeEvent(self, event):
        """Disable mode on close."""
        self._stop_processes()
        if self.input_manager:
            self.input_manager.disable_winetricks_mode()
        super().closeEvent(event)

    def reject(self):
        """Disable mode on reject."""
        self._stop_processes()
        if self.input_manager:
            self.input_manager.disable_winetricks_mode()
        super().reject()
