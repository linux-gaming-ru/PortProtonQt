import os
import re
import shutil
from typing import TYPE_CHECKING, Any

import psutil
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox
from portprotonqt.dialogs import FileExplorer, WinetricksDialog
from portprotonqt.dialogs.prefix_backup import PrefixBackupDialog, PrefixBackupJob, PrefixBackupThread
from portprotonqt.dialogs.proton_manager import show_proton_manager
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.portproton_api import get_user_conf_setting
from portprotonqt.scripts_utils.prefix_backup import is_legacy_squashfs_backup
from portprotonqt.settings_manager import get_available_prefix_options, get_available_wine_options

logger = get_logger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class MainWindowWineTabMixin(_MainWindowTypingBase):
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    def createWineTab(self):
        """Wine Settings tab."""
        self.wineWidget = QWidget()
        self.wineWidget.setProperty("theme_style_name", "OTHER_PAGES_WIDGET_STYLE")
        self.wineWidget.setStyleSheet(self.theme.OTHER_PAGES_WIDGET_STYLE)
        layout = QVBoxLayout(self.wineWidget)
        layout.setContentsMargins(10, 18, 10, 10)

        self.wineTitle = QLabel(_("Wine Settings"))
        self.wineTitle.setStyleSheet(self.theme.TAB_TITLE_STYLE)
        self.wineTitle.setObjectName("tabTitle")
        layout.addWidget(self.wineTitle)
        self.stackedWidget.addWidget(self.wineWidget)

        if self.portproton_location is None:
            return

        formLayout = QFormLayout()
        formLayout.setContentsMargins(0, 10, 0, 0)
        formLayout.setSpacing(self.theme.wineSettingsSetSpacing)
        formLayout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.wine_versions = get_available_wine_options(
            self.portproton_location, include_lg_aliases=True
        )
        self.wineCombo = CustomComboBox(theme=self.theme)
        self.wineCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.wineCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.wineCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wineCombo.addItems(self.wine_versions)
        self.wineCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.wineCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.wineTitleLabel = QLabel("WINE/Proton:")
        self.wineTitleLabel.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        self.wineTitleLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self.wine_versions:
            self.wineCombo.setCurrentIndex(0)
        default_wine = get_user_conf_setting('PW_DEFAULT_WINE_USE')
        if default_wine:
            if self.wineCombo.findText(default_wine) == -1:
                self.wineCombo.addItem(default_wine)
            self.wineCombo.setCurrentText(default_wine)
        formLayout.addRow(self.wineTitleLabel, self.wineCombo)

        self.prefixes = get_available_prefix_options(self.portproton_location)
        self.prefixCombo = CustomComboBox(theme=self.theme)
        self.prefixCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.prefixCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.prefixCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.prefixCombo.addItems(self.prefixes)
        self.prefixCombo.setEditable(True)
        self.prefixCombo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        prefix_line_edit = self.prefixCombo.lineEdit()
        if prefix_line_edit is not None:
            prefix_line_edit.setPlaceholderText(_("Enter prefix name"))
        self.prefixCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.prefixCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.prefixTitleLabel = QLabel(_("Prefix:"))
        self.prefixTitleLabel.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        self.prefixTitleLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self.prefixes:
            self.prefixCombo.setCurrentIndex(0)
        default_prefix = get_user_conf_setting('PW_DEFAULT_PREFIX_NAME')
        if default_prefix:
            self.prefixCombo.setCurrentText(default_prefix)
        formLayout.addRow(self.prefixTitleLabel, self.prefixCombo)

        self.defaultVulkanCombo = CustomComboBox(theme=self.theme)
        self.defaultVulkanCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.defaultVulkanCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.defaultVulkanCombo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.defaultVulkanCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.defaultVulkanCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        default_vulkan_from_var = self._get_var_default_setting("PW_VULKAN_USE", "6")
        vulkan_options = [
            (_("Newest"), "6"),
            (_("Stable"), "2"),
            ("Sarek", "1"),
            ("WINED3D - OpenGL", "0"),
        ]
        for vulkan_name, vulkan_value in vulkan_options:
            if vulkan_value == default_vulkan_from_var:
                self.defaultVulkanCombo.addItem(vulkan_name, "")
                break
        if self.defaultVulkanCombo.count() == 0:
            self.defaultVulkanCombo.addItem(default_vulkan_from_var, "")
        for vulkan_name, vulkan_value in vulkan_options:
            if vulkan_value != default_vulkan_from_var:
                self.defaultVulkanCombo.addItem(vulkan_name, vulkan_value)
        self._set_combo_current_data(
            self.defaultVulkanCombo, get_user_conf_setting('PW_DEFAULT_VULKAN_USE') or ""
        )
        self.defaultVulkanTitleLabel = QLabel(_("Vulkan Backend") + ":")
        self.defaultVulkanTitleLabel.setStyleSheet(self.theme.PARAMS_TITLE_STYLE)
        self.defaultVulkanTitleLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        formLayout.addRow(self.defaultVulkanTitleLabel, self.defaultVulkanCombo)

        layout.addLayout(formLayout)

        # --- Wine Tools ---
        tools_grid = QGridLayout()
        tools_grid.setSpacing(6)

        tools = [
            ("--winecfg", _("Wine Configuration")),
            ("--winereg", _("Registry Editor")),
            ("--winefile", _("File Explorer")),
            ("--winecmd", _("Command Prompt")),
            ("--wine_uninstaller", _("Uninstaller")),
        ]

        for i, (tool_cmd, tool_name) in enumerate(tools):
            row = i // 3
            col = i % 3
            btn = AutoSizeButton(tool_name, update_size=False)
            btn.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
            btn.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.clicked.connect(lambda checked, t=tool_cmd: self.launch_generic_tool(t))
            tools_grid.addWidget(btn, row, col)

        for col in range(3):
            tools_grid.setColumnStretch(col, 1)

        layout.addLayout(tools_grid)

        # --- Additional Tools ---
        additional_grid = QGridLayout()
        additional_grid.setSpacing(6)

        additional_buttons = [
            ("Winetricks", self.open_winetricks),
            (_("Create Prefix Backup"), self.create_prefix_backup),
            (_("Load Prefix Backup"), self.load_prefix_backup),
            (_("Delete Prefix"), self.delete_prefix),
            (_("Clear Prefix"), self.clear_prefix),
            (_("Manage WINE versions"), self.show_proton_manager),
        ]

        for i, (text, callback) in enumerate(additional_buttons):
            row = i // 2
            col = i % 2
            btn = AutoSizeButton(text, update_size=False)
            btn.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
            btn.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if callback:
                btn.clicked.connect(callback)
            additional_grid.addWidget(btn, row, col)

        for col in range(2):
            additional_grid.setColumnStretch(col, 1)

        layout.addLayout(additional_grid)
        tools_grid.setContentsMargins(10, 4, 10, 0)
        additional_grid.setContentsMargins(10, 6, 10, 0)
        layout.addStretch(1)

        self.wine_progress_bar = QProgressBar(self.wineWidget)
        self.wine_progress_bar.setStyleSheet(self.theme.PROGRESS_BAR_STYLE)
        self.wine_progress_bar.setMaximumWidth(200)
        self.wine_progress_bar.setTextVisible(True)
        self.wine_progress_bar.setVisible(False)
        self.wine_progress_bar.setRange(0, 0)

        wine_progress_layout = QHBoxLayout()
        wine_progress_layout.addStretch(1)
        wine_progress_layout.addWidget(self.wine_progress_bar)
        layout.addLayout(wine_progress_layout)

    def launch_generic_tool(self, cli_arg):
        wine = self.wineCombo.currentText()
        raw_prefix = self.prefixCombo.currentText().strip()
        prefix = re.sub(r"[ \t]", "_", raw_prefix).upper() if raw_prefix else ""
        if not wine or not prefix:
            return
        if not self.portproton_location or not self.start_sh:
            return
        env_vars = os.environ.copy()
        self._check_missing_prefix_by_name_before_launch(prefix, env_vars)
        start_sh = self.start_sh
        cmd = start_sh + ["cli", cli_arg, wine, prefix]

        # Show progress bar before launch
        self.wine_progress_bar.setVisible(True)

        proc = QProcess(self)
        process_env = QProcessEnvironment.systemEnvironment()
        if env_vars.get("DISABLE_CP_DEFPFX") == "1":
            process_env.insert("DISABLE_CP_DEFPFX", "1")
        else:
            process_env.remove("DISABLE_CP_DEFPFX")
        proc.setProcessEnvironment(process_env)
        proc.finished.connect(lambda exitCode: self._on_wine_tool_finished(exitCode, cli_arg))
        proc.errorOccurred.connect(lambda error: self._on_wine_tool_error(error, cli_arg))
        proc.start(cmd[0], cmd[1:])

        if not proc.waitForStarted(5000):
            self.wine_progress_bar.setVisible(False)
            QMessageBox.warning(self, _("Error"), _("Failed to start process."))
            return

        self._start_wine_process_monitor(cli_arg)

    def _start_wine_process_monitor(self, cli_arg):
        """Start timer for Wine utility launch monitoring."""
        self.wine_monitor_timer = QTimer(self)
        self.wine_monitor_timer.setInterval(500)
        self.wine_monitor_timer.timeout.connect(lambda: self._check_wine_process(cli_arg))
        self.wine_monitor_timer.start()

    def _check_wine_process(self, cli_arg):
        """Check if target .exe process started."""
        exe_map = {
            "--winecfg": "winecfg.exe",
            "--winereg": "regedit.exe",
            "--winefile": "winefile.exe",
            "--winecmd": "cmd.exe",
            "--wine_uninstaller": "uninstaller.exe",
        }
        target_exe = exe_map.get(cli_arg, "")
        if not target_exe:
            return

        # Check processes via psutil
        for proc in psutil.process_iter(attrs=["name"]):
            if proc.info["name"].lower() == target_exe.lower():
                # Process started - hide progress bar and stop monitoring
                self.wine_progress_bar.setVisible(False)
                if hasattr(self, 'wine_monitor_timer') and self.wine_monitor_timer is not None:
                    self.wine_monitor_timer.stop()
                    self.wine_monitor_timer.deleteLater()
                    self.wine_monitor_timer = None
                logger.info(f"Wine tool {target_exe} started successfully")
                return

    def _on_wine_tool_finished(self, exitCode, cli_arg):
        """Handle Wine utility completion."""
        self.wine_progress_bar.setVisible(False)
        # Stop monitoring if active
        if hasattr(self, 'wine_monitor_timer') and self.wine_monitor_timer is not None:
            self.wine_monitor_timer.stop()
            self.wine_monitor_timer.deleteLater()
            self.wine_monitor_timer = None
        if exitCode == 0:
            logger.info(f"Wine tool {cli_arg} finished successfully")
        else:
            logger.warning(f"Wine tool {cli_arg} finished with exit code {exitCode}")

    def _on_wine_tool_error(self, error, cli_arg):
        """Handle Wine utility launch error."""
        self.wine_progress_bar.setVisible(False)
        # Stop monitoring if active
        if hasattr(self, 'wine_monitor_timer') and self.wine_monitor_timer is not None:
            self.wine_monitor_timer.stop()
            self.wine_monitor_timer.deleteLater()
            self.wine_monitor_timer = None
        logger.error(f"Wine tool {cli_arg} error: {error}")
        QMessageBox.warning(self, _("Error"), f"Failed to launch tool: {error}")

    def show_proton_manager(self):
        """Shows the Proton/WINE manager for downloading other WINE versions"""
        show_proton_manager(self, self.portproton_location, input_manager=self.input_manager)

    def clear_prefix(self):
        """Clear prefix"""
        selected_prefix = self.prefixCombo.currentText().strip()
        selected_wine = self.wineCombo.currentText()

        if not selected_prefix or not selected_wine:
            return
        if not self.portproton_location or not self.start_sh:
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Clear"))
        msg_box.setText(_("Are you sure you want to clear prefix '{}'?").format(selected_prefix))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        start_sh = self.start_sh

        self.wine_progress_bar.setVisible(True)

        self.clear_process = QProcess(self)
        self.clear_process.finished.connect(lambda exitCode: self._on_clear_prefix_finished(exitCode))
        self.clear_process.errorOccurred.connect(lambda error: self._on_clear_prefix_error(error))
        cmd = start_sh + ["cli", "--clear_pfx", selected_wine, selected_prefix]
        self.clear_process.start(cmd[0], cmd[1:])

        if not self.clear_process.waitForStarted(5000):
            self.wine_progress_bar.setVisible(False)
            QMessageBox.warning(self, _("Error"), _("Failed to start prefix clear process."))
            return

    def _on_clear_prefix_finished(self, exitCode):
        self.wine_progress_bar.setVisible(False)
        if exitCode == 0:
            QMessageBox.information(self, _("Success"), _("Prefix cleared successfully."))
        else:
            QMessageBox.warning(self, _("Error"), _("Prefix clear failed with exit code {}.").format(exitCode))

    def _on_clear_prefix_error(self, error):
        self.wine_progress_bar.setVisible(False)
        QMessageBox.warning(self, _("Error"), _("Failed to run clear prefix command: {}").format(error))

    def create_prefix_backup(self):
        selected_prefix = self.prefixCombo.currentText().strip()
        if not selected_prefix:
            return
        file_explorer = FileExplorer(self, directory_only=True)
        file_explorer.file_signal.file_selected.connect(lambda path: self._perform_backup(path, selected_prefix))
        file_explorer.exec()

    def _perform_backup(self, backup_dir, prefix_name):
        os.makedirs(backup_dir, exist_ok=True)
        if not self.portproton_location:
            return
        job = PrefixBackupJob("backup", self.portproton_location, prefix_name, backup_dir)
        worker = PrefixBackupThread(job)
        dialog = PrefixBackupDialog(self, worker, self.theme)
        dialog.start()
        self._on_backup_finished(0 if worker.success else 1)

    def load_prefix_backup(self):
        file_explorer = FileExplorer(self, file_filter='.ppack')
        file_explorer.file_signal.file_selected.connect(self._perform_restore)
        file_explorer.exec()

    def _perform_restore(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return
        if not self.portproton_location:
            return
        if is_legacy_squashfs_backup(file_path):
            self._perform_legacy_restore(file_path)
            return
        job = PrefixBackupJob("restore", self.portproton_location, file_path)
        worker = PrefixBackupThread(job)
        dialog = PrefixBackupDialog(self, worker, self.theme)
        dialog.start()
        self._on_restore_finished(0 if worker.success else 1)

    def _perform_legacy_restore(self, file_path: str) -> None:
        if not self.start_sh:
            return
        cmd = self.start_sh + ["--restore-prefix", file_path]
        if not QProcess.startDetached(cmd[0], cmd[1:]):
            QMessageBox.warning(self, _("Error"), _("Failed to start restore process."))

    def _on_backup_finished(self, exitCode):
        if exitCode == 0:
            QMessageBox.information(self, _("Success"), _("Prefix backup completed."))
        else:
            QMessageBox.warning(self, _("Error"), _("Prefix backup failed."))

    def _on_restore_finished(self, exitCode):
        if exitCode == 0:
            self.refreshGames()
            QMessageBox.information(self, _("Success"), _("Prefix restore completed."))
        else:
            QMessageBox.warning(self, _("Error"), _("Prefix restore failed."))

    def delete_prefix(self):
        selected_prefix = self.prefixCombo.currentText().strip()
        if not self.portproton_location:
            return

        if not selected_prefix:
            return

        prefix_path = os.path.join(self.portproton_location, "data", "prefixes", selected_prefix)
        if not os.path.exists(prefix_path):
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(_("Confirm Deletion"))
        msg_box.setText(_("Are you sure you want to delete prefix '{}'?").format(selected_prefix))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        msg_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        reply = msg_box.exec()

        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(prefix_path)
                QMessageBox.information(self, _("Success"), _("Prefix '{}' deleted.").format(selected_prefix))
            except Exception as e:
                QMessageBox.warning(self, _("Error"), _("Failed to delete prefix: {}").format(str(e)))

    def refresh_wine_combo(self):
        """Refresh the wine combo box after deletion."""
        if not self.portproton_location:
            return

        self.wine_versions = get_available_wine_options(
            self.portproton_location, include_lg_aliases=True
        )
        self.wineCombo.clear()
        self.wineCombo.addItems(self.wine_versions)

    def refresh_prefix_combo(self):
        """Refresh the prefix combo box when prefixes directory changes."""
        if not self.portproton_location:
            return

        current_prefix = self.prefixCombo.currentText().strip()
        normalized_current_prefix = re.sub(r"[ \t]", "_", current_prefix).upper() if current_prefix else ""
        prefixes_path = os.path.join(self.portproton_location, "data", "prefixes")
        if os.path.exists(prefixes_path):
            self._normalize_prefix_directories(prefixes_path)

        self.prefixes = get_available_prefix_options(self.portproton_location)
        self.prefixCombo.clear()
        self.prefixCombo.addItems(self.prefixes)
        if normalized_current_prefix:
            self.prefixCombo.setCurrentText(normalized_current_prefix)

    def _normalize_prefix_directories(self, prefixes_path):
        if not os.path.isdir(prefixes_path):
            return

        for prefix_name in os.listdir(prefixes_path):
            current_path = os.path.join(prefixes_path, prefix_name)
            if not os.path.isdir(current_path):
                continue

            normalized_name = re.sub(r"[ \t]", "_", prefix_name).upper()
            if normalized_name == prefix_name:
                continue

            normalized_path = os.path.join(prefixes_path, normalized_name)
            if os.path.isdir(normalized_path):
                logger.warning(
                    "Cannot rename prefix %s to %s: target already exists",
                    prefix_name,
                    normalized_name
                )
                continue

            try:
                os.rename(current_path, normalized_path)
            except OSError as exc:
                logger.warning("Failed to rename prefix %s: %s", prefix_name, exc)

    def open_winetricks(self):
        """Open the Winetricks dialog for the selected prefix and wine."""
        selected_prefix = self.prefixCombo.currentText().strip()
        if not selected_prefix:
            return

        selected_wine = self.wineCombo.currentText()
        if not selected_wine:
            return

        assert self.portproton_location is not None
        prefix_path = os.path.join(self.portproton_location, "data", "prefixes", selected_prefix)

        # Open Winetricks dialog
        dialog = WinetricksDialog(self, self.theme, prefix_path, selected_wine)
        dialog.exec()
