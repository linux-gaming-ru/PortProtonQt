import sys
import subprocess
import signal
import psutil
import os
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMessageBox
from PySide6.QtGui import QIcon, QAction
from portprotonqt.logger import get_logger
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.localization import _
from portprotonqt.config import display_config, extract_exec_target_path, favorites_config, ui_config
from portprotonqt.dialogs import GameLaunchDialog

logger = get_logger(__name__)

PREFIX_BACKUP_EXTENSION = ".ppack"
RESTART_TRANSIENT_OPTIONS = {
    "--restore-prefix": 1,
    "--create-backup": 2,
}


def _is_prefix_backup_arg(arg: str) -> bool:
    path = arg
    if path.lower().startswith("file://"):
        path = path[7:].replace("%20", " ")
    return path.lower().endswith(PREFIX_BACKUP_EXTENSION)


def _restart_args(args: list[str]) -> list[str]:
    restart_args = [args[0]]
    skip_count = 0
    for arg in args[1:]:
        if skip_count:
            skip_count -= 1
            continue
        if arg in RESTART_TRANSIENT_OPTIONS:
            skip_count = RESTART_TRANSIENT_OPTIONS[arg]
            continue
        if _is_prefix_backup_arg(arg):
            continue
        if arg.lower().startswith("portprotonqt://theme/"):
            continue
        restart_args.append(arg)
    return restart_args


class TrayManager:
    """Tray management module for PortProtonQt.

    Provides:
    - Flat context menu with categories: Stop Game, Tabs, Recent, Exit.
    - Dynamic population of game lists without nested submenus.
    - Minimize to tray on window close, full exit via Exit.
    """

    def __init__(self, main_window, app_name: str | None = None, theme=None):
        self.app_name = app_name if app_name is not None else "PortProtonQt"
        self.theme_manager = ThemeManager()
        selected_theme = ui_config.get_theme()
        self.current_theme_name = selected_theme
        self.theme = self.theme_manager.apply_theme(selected_theme)
        self.main_window = main_window
        self.tray_icon = QSystemTrayIcon(self.main_window)

        icon = self.theme_manager.get_icon("tray_portproton", self.current_theme_name)
        if isinstance(icon, str):
            icon = QIcon(icon)
        elif icon is None:
            icon = QIcon()
        self.tray_icon.setIcon(icon)
        self.tray_icon.activated.connect(self.handle_tray_click)
        self.tray_icon.setToolTip(self.app_name)

        self.tray_menu = QMenu()
        self.minimal_mode = False

        self.stop_game_action = QAction(_("Stop Game"), self.main_window)
        self.stop_game_action.setEnabled(False)
        self.stop_game_action.triggered.connect(self.stop_game)

        self.pause_game_action = QAction(_("Pause Game"), self.main_window)
        self.pause_game_action.setEnabled(False)
        self.pause_game_action.triggered.connect(self.toggle_game_pause)

        self.tray_menu.addAction(self.pause_game_action)
        self.tray_menu.addAction(self.stop_game_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addSeparator()

        exit_action = QAction(_("Exit"), self.main_window)
        exit_action.triggered.connect(self.force_exit)
        self.tray_menu.addAction(exit_action)

        self.tray_menu.aboutToShow.connect(self.refresh_tray_menu)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

        self.launch_dialog = None

    def refresh_tray_menu(self):
        self.tray_menu.clear()

        self.tray_menu.addAction(self.pause_game_action)
        self.tray_menu.addAction(self.stop_game_action)
        self.update_game_actions()
        if self.minimal_mode:
            return
        self.tray_menu.addSeparator()

        if display_config.get_tray_menu_mode() == "compact":
            self._populate_compact_menu()
        else:
            self._populate_detailed_menu()
        self.tray_menu.addSeparator()

        exit_action = QAction(_("Exit"), self.main_window)
        exit_action.triggered.connect(self.force_exit)
        self.tray_menu.addAction(exit_action)

    def set_minimal_mode(self) -> None:
        """Show only the stop action in the tray menu."""
        self.minimal_mode = True
        self.refresh_tray_menu()

    def _populate_detailed_menu(self) -> None:
        self._populate_tabs_flat()
        self.tray_menu.addSeparator()
        self._populate_recent_flat()

    def _populate_compact_menu(self) -> None:
        tabs_menu = QMenu(_("Tabs"), self.main_window)
        self._populate_tabs_flat(tabs_menu)
        self.tray_menu.addMenu(tabs_menu)

        favorites_menu = QMenu(_("Favorites"), self.main_window)
        self._populate_favorites_menu(favorites_menu)
        self.tray_menu.addMenu(favorites_menu)

        recent_menu = QMenu(_("Recent Games"), self.main_window)
        self._populate_recent_flat(recent_menu)
        self.tray_menu.addMenu(recent_menu)

        themes_menu = QMenu(_("Themes"), self.main_window)
        self._populate_themes_menu(themes_menu)
        self.tray_menu.addMenu(themes_menu)

    def update_game_actions(self) -> None:
        processes = self._game_process_tree()
        game_processes = getattr(self.main_window, "game_processes", [])
        target_exe = getattr(self.main_window, "target_exe", None)
        has_running_game = bool(game_processes or target_exe)
        self.stop_game_action.setEnabled(has_running_game)
        self.pause_game_action.setEnabled(bool(processes))
        paused = self._are_processes_paused(processes)
        self.pause_game_action.setText(_("Resume Game") if paused else _("Pause Game"))

    def _are_processes_paused(self, processes: list[psutil.Process]) -> bool:
        if not processes:
            return False
        try:
            return all(
                process.status() == psutil.STATUS_STOPPED for process in processes
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _game_process_tree(self) -> list[psutil.Process]:
        processes = {}
        for launcher in getattr(self.main_window, "game_processes", []):
            try:
                parent = psutil.Process(launcher.pid)
                for process in parent.children(recursive=True):
                    processes[process.pid] = process
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        target = str(getattr(self.main_window, "target_exe", "") or "").lower()
        if not target:
            return list(processes.values())
        for process in psutil.process_iter(attrs=["name"]):
            try:
                if str(process.info.get("name") or "").lower() != target:
                    continue
                processes[process.pid] = process
                for child in process.children(recursive=True):
                    processes[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return list(processes.values())

    def toggle_game_pause(self) -> None:
        processes = self._game_process_tree()
        if not processes:
            self.update_game_actions()
            return
        paused = self._are_processes_paused(processes)
        pause_signal = signal.SIGCONT if paused else signal.SIGSTOP
        failures = 0
        for process in processes:
            try:
                process.send_signal(pause_signal)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
                failures += 1
                logger.warning(
                    "Failed to change pause state for process %s: %s",
                    process.pid,
                    error,
                )
        if failures == len(processes):
            QMessageBox.warning(self.main_window, _("Error"), _("Failed to pause game"))
        self.update_game_actions()

    def handle_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.refresh_tray_menu()
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window_action()

    def toggle_window_action(self):
        if self.main_window.isVisible():
            self.main_window.hide()
        else:
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _populate_tabs_flat(self, menu: QMenu | None = None) -> None:
        tab_buttons = getattr(self.main_window, "tabButtons", {})
        if not tab_buttons:
            return

        target_menu = menu if menu is not None else self.tray_menu
        current_index = self.main_window.stackedWidget.currentIndex()
        for index, button in sorted(tab_buttons.items()):
            if button.isHidden():
                continue
            action = QAction(button.text(), self.main_window)
            action.setCheckable(True)
            action.setChecked(index == current_index)
            action.triggered.connect(
                lambda checked=False, tab_index=index: self.switch_tab(tab_index)
            )
            target_menu.addAction(action)

    def switch_tab(self, index: int) -> None:
        if not self.main_window.isVisible():
            self.main_window.show()
        if self.main_window.isMinimized():
            self.main_window.showNormal()
        self.main_window.switchTab(index)
        self.main_window.raise_()
        self.main_window.activateWindow()

    def stop_game(self) -> None:
        if self.main_window.stop_running_game():
            self.update_game_actions()
            if self.minimal_mode:
                self.tray_icon.hide()
                QApplication.quit()
            return

        QMessageBox.warning(self.main_window, _("Error"), _("Failed to stop game"))

    def _populate_recent_flat(self, menu: QMenu | None = None) -> None:
        target_menu = menu if menu is not None else self.tray_menu
        if not self.main_window.games:
            no_recent_action = QAction(_("No recent games"), self.main_window)
            no_recent_action.setEnabled(False)
            target_menu.addAction(no_recent_action)
            return

        recent_games = sorted(self.main_window.games, key=lambda g: g[10], reverse=True)[:5]

        for game in recent_games:
            game_name = game[0]
            exec_line = game[5]
            source = game[12]
            action_text = f"{game_name} ({source})"
            action = QAction(action_text, self.main_window)
            action.triggered.connect(
                lambda checked=False, el=exec_line, name=game_name: self.launch_game_with_dialog(el, name)
            )
            target_menu.addAction(action)

    def _populate_favorites_menu(self, menu: QMenu) -> None:
        favorites = favorites_config.get_games()
        if not favorites:
            no_fav_action = QAction(_("No favorites"), self.main_window)
            no_fav_action.setEnabled(False)
            menu.addAction(no_fav_action)
            return

        game_map = {game[0]: (game[5], game[12]) for game in self.main_window.games}
        for fav in sorted(favorites):
            game_data = game_map.get(fav)
            if not game_data:
                logger.warning(f"Exec line not found for favorite: {fav}")
                continue
            exec_line, source = game_data
            action = QAction(f"{fav} ({source})", self.main_window)
            action.triggered.connect(
                lambda checked=False, el=exec_line, name=fav: self.launch_game_with_dialog(el, name)
            )
            menu.addAction(action)

    def _populate_themes_menu(self, menu: QMenu) -> None:
        available_themes = self.theme_manager.get_available_themes()
        for theme_name in sorted(available_themes):
            action = QAction(theme_name, self.main_window)
            action.setCheckable(True)
            action.setChecked(theme_name == self.current_theme_name)
            action.triggered.connect(
                lambda checked=False, tn=theme_name: self.switch_theme(tn)
            )
            menu.addAction(action)

    def launch_game_with_dialog(self, exec_line, game_name):
        """Launch a game with a modal dialog indicating progress."""
        try:
            target_exe = None
            if exec_line.startswith("steam://"):
                self.launch_dialog = GameLaunchDialog(
                    self.main_window, game_name=game_name, theme=self.theme
                )
            else:
                file_to_check = extract_exec_target_path(exec_line)

                if not file_to_check or not os.path.exists(file_to_check):
                    logger.error(f"File not found: {file_to_check}")
                    QMessageBox.warning(
                        self.main_window, _("Error"), _("File not found: {0}").format(file_to_check)
                    )
                    return

                target_exe = os.path.basename(file_to_check)
                self.launch_dialog = GameLaunchDialog(
                    self.main_window, game_name=game_name, theme=self.theme, target_exe=target_exe
                )

            self.launch_dialog.rejected.connect(lambda: self.cancel_game_launch(exec_line))
            self.launch_dialog.show()
            self.main_window.toggleGame(exec_line, game_name=game_name)

        except Exception as e:
            logger.error(f"Failed to launch game {game_name}: {e}")
            if self.launch_dialog:
                self.launch_dialog.reject()
                self.launch_dialog = None
            QMessageBox.warning(
                self.main_window, _("Error"), _("Failed to launch game: {0}").format(str(e))
            )

    def cancel_game_launch(self, exec_line):
        """Cancel the game launch and terminate the process."""
        if self.main_window.game_processes and self.main_window.target_exe:
            for proc in self.main_window.game_processes:
                try:
                    parent = psutil.Process(proc.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    psutil.wait_procs(children, timeout=5)
                    for child in children:
                        if child.is_running():
                            child.kill()
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except psutil.NoSuchProcess:
                    pass
            self.main_window.game_processes = []
            self.main_window.resetPlayButton()
            if self.launch_dialog:
                self.launch_dialog.reject()
                self.launch_dialog = None
            logger.info(f"Game launch cancelled for exec line: {exec_line}")

    def switch_theme(self, theme_name: str):
        try:
            self.main_window._apply_theme_live(theme_name)
        except Exception as e:
            logger.error(f"Failed to switch theme to {theme_name}: {e}")
            self.main_window._apply_theme_live("standart")

    def force_exit(self):
        self.main_window.close()
        sys.exit(0)

    def shutdown(self):
        if self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()


def restart_application_process():
    """Restart the application with the current Python executable."""
    executable = sys.executable
    args = _restart_args(sys.argv)
    QApplication.quit()
    subprocess.Popen([executable] + args)
