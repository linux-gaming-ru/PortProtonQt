"""Tests for local Wine/Proton archive installation."""

import io
import tarfile
from types import SimpleNamespace
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QWidget

from portprotonqt.dialogs.proton_manager import ProtonManager
from portprotonqt.dialogs.wine_extractor import ExtractionThread
from portprotonqt.tabs import library_tab


def test_nested_manager_registers_input_before_connecting_hints(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QDialog, QPushButton
    from portprotonqt.theme_manager import ThemeWrapper, load_theme
    import portprotonqt.dialogs.proton_manager as module

    app = QApplication.instance() or QApplication([])
    main = cast(Any, QWidget())
    main.get_button_icon = MagicMock(return_value="placeholder")
    main.get_nav_icon = MagicMock(return_value="placeholder")
    settings = cast(Any, QDialog(main))
    events = []
    inputs = SimpleNamespace(
        gamepad=object(), gamepad_type="xbox",
        enable_proton_manager_mode=lambda dialog: events.append(("enable", dialog)),
        disable_proton_manager_mode=lambda: None,
        connect_surface_updates=lambda name, callback: events.append((name, callback)),
    )
    settings.input_manager = inputs
    monkeypatch.setattr(module.ProtonManager, "start_loading_wine_data", lambda self: None)
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **_kwargs: QPushButton(text))
    manager = module.ProtonManager(settings, theme=ThemeWrapper(load_theme("standart")), input_manager=inputs)

    assert manager.main_window is main
    assert events[0] == ("enable", manager)
    assert events[1][0] == "proton_manager_dialog"
    assert main.get_button_icon.called and main.get_nav_icon.called
    manager.close()
    settings.deleteLater()
    main.deleteLater()
    app.processEvents()


def test_cachyos_v3_builds_require_supported_cpu_level(monkeypatch) -> None:
    manager = ProtonManager.__new__(ProtonManager)
    manager.cpu_level = 2
    monkeypatch.setattr(
        "portprotonqt.dialogs.proton_manager.platform.machine", lambda: "x86_64"
    )
    entries = [
        {
            "name": "proton-wineland-11.0-20260930-x86_64",
            "url": "https://example.com/proton-wineland-11.0-20260930-x86_64.tar.xz",
        },
        {
            "name": "proton-wineland-11.0-20260930-x86_64_v3",
            "url": "https://example.com/proton-wineland-11.0-20260930-x86_64_v3.tar.xz",
        },
    ]

    assert manager.filter_entries_by_cpu_level(entries, "proton_wineland") == entries[:1]


def test_wine_entries_match_host_architecture(monkeypatch) -> None:
    manager = ProtonManager.__new__(ProtonManager)
    manager.cpu_level = 4
    entries = [
        {"name": "GE-Proton11-6", "url": "https://example.com/x86.tar.gz"},
        {
            "name": "GE-Proton11-6-aarch64",
            "url": "https://example.com/aarch64.tar.gz",
        },
        {"name": "CachyOS", "url": "https://example.com/proton-arm64.tar.xz"},
    ]

    monkeypatch.setattr(
        "portprotonqt.dialogs.proton_manager.platform.machine", lambda: "x86_64"
    )
    filtered = manager.filter_entries_by_cpu_level(entries, "proton_ge")
    assert [entry["name"] for entry in filtered] == ["GE-Proton11-6"]

    monkeypatch.setattr(
        "portprotonqt.dialogs.proton_manager.platform.machine", lambda: "aarch64"
    )
    filtered = manager.filter_entries_by_cpu_level(entries, "proton_ge")
    assert [entry["name"] for entry in filtered] == [
        "GE-Proton11-6-aarch64",
        "CachyOS",
    ]


def test_dropped_wine_archives_accepts_supported_local_files(tmp_path) -> None:
    wine_archive = tmp_path / "WINE_LG_11-10.tar.xz"
    wine_archive.touch()
    unsupported = tmp_path / "wine.zip"
    unsupported.touch()
    mime_data = QMimeData()
    mime_data.setUrls(
        [QUrl.fromLocalFile(str(wine_archive)), QUrl.fromLocalFile(str(unsupported))]
    )

    archives = ProtonManager._get_dropped_wine_archives(mime_data)

    assert archives == [str(wine_archive)]


def test_extraction_rejects_path_traversal(tmp_path) -> None:
    archive_path = tmp_path / "WINE_LG.tar.gz"
    outside_path = tmp_path / "escaped"
    with tarfile.open(archive_path, "w:gz") as archive:
        entry = tarfile.TarInfo("../escaped")
        entry.size = 7
        archive.addfile(entry, io.BytesIO(b"escaped"))
    errors = []
    thread = ExtractionThread(str(archive_path), str(tmp_path / "dist"))
    thread.error.connect(errors.append)

    thread.run()

    assert errors
    assert not outside_path.exists()


def test_extraction_does_not_change_process_directory(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "WINE_LG.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        entry = tarfile.TarInfo("WINE_LG/version")
        entry.size = 2
        archive.addfile(entry, io.BytesIO(b"11"))
    monkeypatch.setattr("os.chdir", lambda _path: (_ for _ in ()).throw(AssertionError()))
    errors = []
    thread = ExtractionThread(str(archive_path), str(tmp_path / "dist"))
    thread.error.connect(errors.append)

    thread.run()

    assert not errors
    assert (tmp_path / "dist/WINE_LG/version").read_bytes() == b"11"


def test_library_drop_opens_manager_for_wine_archive(tmp_path, monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    archive_path = tmp_path / "PROTON_LG_10-30.tar.xz"
    archive_path.touch()
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(archive_path))])
    calls = []

    class Event:
        accepted = False

        def mimeData(self):
            return mime_data

        def acceptProposedAction(self):
            self.accepted = True

    class Window(QWidget):
        portproton_location = "/tmp/PortProtonQt"
        input_manager = None
        _on_dropped_theme_installed = library_tab.MainWindowLibraryTabMixin._on_dropped_theme_installed
        _on_dropped_theme_failed = library_tab.MainWindowLibraryTabMixin._on_dropped_theme_failed
        _on_dropped_wine_archives = library_tab.MainWindowLibraryTabMixin._on_dropped_wine_archives
        _install_dropped_theme_archives = library_tab.MainWindowLibraryTabMixin._install_dropped_theme_archives
        theme = SimpleNamespace(MESSAGE_BOX_STYLE="", PROGRESS_BAR_STYLE="")

    from portprotonqt.tabs.theme_store_workers import ThemeArchiveInstallWorker

    monkeypatch.setattr(ThemeArchiveInstallWorker, "start", lambda self: self.wine_archives.emit(self.paths))

    monkeypatch.setattr(
        library_tab, "show_proton_manager", lambda *args, **kwargs: calls.append(kwargs)
    )
    event = Event()

    library_tab.MainWindowLibraryTabMixin.dropEvent(cast(Any, Window()), event)

    assert event.accepted
    assert calls[0]["local_archives"] == [str(archive_path)]


def test_open_wine_folder_creates_and_opens_dist(tmp_path, monkeypatch) -> None:
    opened_urls = []
    manager = cast(Any, ProtonManager.__new__(ProtonManager))
    manager.portproton_location = str(tmp_path)
    monkeypatch.setattr(
        "portprotonqt.dialogs.proton_manager.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    manager._open_wine_folder()

    wine_folder = tmp_path / "data" / "dist"
    assert wine_folder.is_dir()
    assert opened_urls[0].toLocalFile() == str(wine_folder)


def test_disabled_steam_proton_scanning_keeps_local_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ProtonManager.__new__(ProtonManager)
    manager.portproton_location = str(tmp_path)
    local_wine = tmp_path / "data" / "dist" / "LocalWine"
    wine_binary = local_wine / "bin" / "wine"
    wine_binary.parent.mkdir(parents=True)
    wine_binary.touch()
    monkeypatch.setattr("portprotonqt.dialogs.proton_manager.ui_config.get_disable_steam_proton_scanning", lambda: True)
    from unittest.mock import patch

    with patch("portprotonqt.dialogs.proton_manager.get_steam_compatibilitytools_dir") as compat:
        with patch("portprotonqt.dialogs.proton_manager.get_steam_home") as home:
            assert manager.get_installed_versions() == [("LocalWine", str(local_wine))]
    compat.assert_not_called()
    home.assert_not_called()


def test_metadata_error_preserves_local_versions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel, QStackedWidget, QTabWidget
    import portprotonqt.dialogs.proton_manager as module

    app = QApplication.instance() or QApplication([])
    local_version = tmp_path / "GE-Proton"
    local_version.mkdir()
    manager = SimpleNamespace(
        content_stack=QStackedWidget(),
        tab_widget=QTabWidget(),
        theme=SimpleNamespace(GETWINE_WINDOW_STYLE=""),
    )
    manager.content_stack.addWidget(QWidget())
    manager.content_stack.addWidget(QWidget())
    manager.tab_widget.addTab(QWidget(), "Loading")

    def create_installed_tab() -> None:
        assert local_version.is_dir()
        manager.tab_widget.addTab(QLabel(local_version.name), "Installed")

    manager.create_installed_tab = create_installed_tab
    monkeypatch.setattr(module, "_", lambda text: text)
    module.ProtonManager.on_wine_data_load_error(cast(Any, manager), "ConnectionError: " + "x" * 2000)

    assert manager.content_stack.currentIndex() == 1
    assert manager.tab_widget.count() == 1
    assert manager.tab_widget.currentIndex() == 0
    assert manager.tab_widget.widget(0).text() == local_version.name
    manager.tab_widget.deleteLater()
    manager.content_stack.deleteLater()
    app.processEvents()


def test_installed_sizes_update_after_metadata_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QPushButton, QTableWidget
    from portprotonqt.theme_manager import ThemeWrapper, load_theme
    import portprotonqt.dialogs.proton_manager as module

    app = QApplication.instance() or QApplication([])
    version = tmp_path / "GE-Proton"
    version.mkdir()
    (version / "wine").write_bytes(b"x" * 2048)
    monkeypatch.setattr(module.ProtonManager, "start_loading_wine_data", lambda self: None)
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **kwargs: QPushButton(text))
    monkeypatch.setattr(module.ProtonManager, "get_installed_versions", lambda self: [("GE-Proton", str(version))])
    manager = module.ProtonManager(portproton_location=str(tmp_path), theme=ThemeWrapper(load_theme("standart")))
    manager.on_wine_data_load_error("Offline")
    workers = list(manager._installed_size_tables)
    loop = QEventLoop()
    workers[0].finished.connect(loop.quit)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()
    try:
        installed_tab = manager.tab_widget.widget(0)
        assert installed_tab is not None
        table = installed_tab.findChild(QTableWidget)
        assert table is not None
        size_item = table.item(0, 2)
        assert size_item is not None
        assert size_item.text() == "2.0 KiB"
    finally:
        from shiboken6 import isValid
        for worker in workers:
            if isValid(worker):
                worker.wait()
        manager.close()
        app.processEvents()
