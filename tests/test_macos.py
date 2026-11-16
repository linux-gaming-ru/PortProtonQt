"""Native macOS Wine integration regressions, without a macOS host or network."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import orjson
import pytest

from portprotonqt import macos


@pytest.mark.parametrize("layout", [
    "bin/wine", "bin/wine64", "Wine.app/Contents/Resources/wine/bin/wine",
    "Contents/Resources/wine/bin/wine64", "wswine.bundle/bin/wine64",
    "wine-devel/bin/wine", "Wine.app/Contents/SharedSupport/wine/bin/wine64",
])
def test_find_wine_bundle_layouts(tmp_path: Path, layout: str) -> None:
    binary = tmp_path / layout
    binary.parent.mkdir(parents=True)
    binary.write_text("wine", encoding="utf-8")
    assert macos.find_wine(tmp_path) is None
    binary.chmod(0o755)
    assert macos.find_wine(tmp_path) == binary


@pytest.mark.parametrize("name", ["", "..", "../outside", "/tmp/wine", "nested/wine"])
def test_version_paths_reject_traversal(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        macos.version_directory(tmp_path, name)


def test_version_paths_reject_symlink_escape(tmp_path: Path) -> None:
    dist = tmp_path / "data/dist"
    dist.mkdir(parents=True)
    (dist / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        macos.version_directory(tmp_path, "escape")


def test_native_command_uses_selected_version_prefix_and_arguments(tmp_path: Path) -> None:
    binary = macos.version_directory(tmp_path, "Wine 1") / "wswine.bundle/bin/wine64"
    binary.parent.mkdir(parents=True)
    binary.write_text("wine", encoding="utf-8")
    binary.chmod(0o755)
    command, environment = macos.wine_command(tmp_path, ["/games/A game.exe", "a b"], {
        "PW_WINE_USE": "Wine 1", "PW_PREFIX_NAME": "GAME",
    })
    assert command == [str(binary), "/games/A game.exe", "a b"]
    assert environment["WINEPREFIX"] == str(tmp_path / "data/prefixes/GAME")
    assert environment["PATH"].split(":")[0] == str(binary.parent)


@pytest.mark.parametrize("server_mode", [None, 0o644, 0o755])
def test_managed_wine_prefers_executable_sibling_wineserver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_mode: int | None,
) -> None:
    binary = macos.version_directory(tmp_path, "Wine 1") / "wswine.bundle/bin/wine64"
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o755)
    server = binary.with_name("wineserver")
    if server_mode is not None:
        server.touch(mode=server_mode)
    inherited = str(tmp_path / "other wineserver")
    monkeypatch.setenv("WINESERVER", inherited)

    _, environment = macos.wine_command(tmp_path, ["winecfg"], {"PW_WINE_USE": "Wine 1"})

    assert environment["WINESERVER"] == (str(server) if server_mode == 0o755 else inherited)
    assert macos.os.environ["WINESERVER"] == inherited


def test_native_command_does_not_fallback_from_missing_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos.shutil, "which", lambda _name: "/usr/bin/wine")
    with pytest.raises(FileNotFoundError):
        macos.wine_command(tmp_path, ["game.exe"], {"PW_WINE_USE": "missing"})


@pytest.mark.parametrize("prefix", ["..", "../other", "/tmp/prefix"])
def test_native_command_rejects_prefix_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    monkeypatch.setattr(macos.shutil, "which", lambda _name: "/usr/bin/wine")
    with pytest.raises(ValueError):
        macos.wine_command(tmp_path, ["game.exe"], {"PW_PREFIX_NAME": prefix})


def test_settings_roundtrip_is_data_not_shell(tmp_path: Path) -> None:
    path = tmp_path / "game.exe.ppdb"
    values = {"PW_WINE_USE": "Wine Crossover", "PW_PREFIX_NAME": "GAME", "VALUE": "$(touch /tmp/not-run)"}
    macos.write_settings(path, values)
    assert macos.read_settings(path) == values


@pytest.mark.parametrize("values", [
    {"BAD;command": "value"}, {"BAD\nNAME": "value"},
    {"VALUE": "first\nsecond"}, {"VALUE": "first\rsecond"},
])
def test_invalid_settings_preserve_existing_file(tmp_path: Path, values: dict[str, str]) -> None:
    path = tmp_path / "game.exe.ppdb"
    original = 'export PW_PREFIX_NAME=GAME\n'
    path.write_text(original)
    with pytest.raises(ValueError):
        macos.write_settings(path, values)
    assert path.read_text() == original
    assert not path.with_name(path.name + ".tmp").exists()


def test_adapter_cli_edits_existing_ppdb_and_shows_dialog_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path))
    executable = str(tmp_path / "game.exe")
    assert macos.main(["cli", "--edit-db", executable, "PW_WINE_USE=Wine 1", "PW_PREFIX_NAME=GAME"]) == 0
    assert macos.main(["cli", "--show-ppdb", executable]) == 0
    assert 'PW_WINE_USE="Wine 1"' in capsys.readouterr().out
    assert macos.main(["cli", "--set-user-conf", "PW_DEFAULT_WINE_USE", "Wine 2"]) == 0
    assert macos.main(["cli", "--get-user-conf", "PW_DEFAULT_WINE_USE"]) == 0
    assert capsys.readouterr().out.strip() == "Wine 2"


def test_adapter_exec_preserves_owned_pid_and_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path))
    executable = tmp_path / "A game.exe"
    executable.touch()
    monkeypatch.setattr(macos.os, "chdir", Mock())
    macos.write_settings(Path(str(executable) + ".ppdb"), {"PW_PREFIX_NAME": "GAME"})
    monkeypatch.setattr(macos.shutil, "which", lambda _name: "/opt/homebrew/bin/wine")
    execute = Mock()
    monkeypatch.setattr(macos.os, "execvpe", execute)
    assert macos.main([str(executable), "a b"]) == 0
    assert execute.call_args.args[1] == ["/opt/homebrew/bin/wine", str(executable), "a b"]
    assert execute.call_args.args[2]["WINEPREFIX"] == str(tmp_path / "data/prefixes/GAME")


def test_adapter_tools_use_existing_wine_and_prefix_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path))
    binary = macos.version_directory(tmp_path, "Wine 1") / "bin/wine"
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o755)
    execute = Mock()
    monkeypatch.setattr(macos.os, "execvpe", execute)
    assert macos.main(["cli", "--winecfg", "Wine 1", "TEST"]) == 0
    assert execute.call_args.args[1] == [str(binary), "winecfg"]
    assert execute.call_args.args[2]["WINEPREFIX"].endswith("/TEST")
    assert macos.main(["cli", "--autoinstall", "linux.sh"]) == 1


def test_catalog_loader_uses_forgejo_and_completes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.dialogs import wine_loader
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(wine_loader.sys, "platform", "darwin")
    monkeypatch.setattr("portprotonqt.portproton_api.get_user_conf_setting", lambda _key: "GITHUB")
    metadata = {"wine-crossover": [{"name": "Wine 1", "url": "https://example.org/wine.tar.xz", "size_human": "1 MiB"}]}
    response = SimpleNamespace(raise_for_status=lambda: None, iter_content=lambda **_kwargs: [orjson.dumps(metadata)])
    get = Mock(return_value=response)
    monkeypatch.setattr(wine_loader, "get_requests_session", lambda: SimpleNamespace(get=get))
    worker = wine_loader.WineLoadingThread()
    success, failure = Mock(), Mock()
    worker.loading_complete.connect(success)
    worker.loading_error.connect(failure)
    worker.run()
    assert get.call_args.args[0] == macos.MACOS_WINE_METADATA_URL
    success.assert_called_once_with(metadata)
    failure.assert_not_called()


@pytest.mark.parametrize("entry", [{"name": "../escape", "url": "https://example.org/a"}, {"name": "Wine", "url": "http://example.org/a"}])
def test_catalog_rejects_unsafe_download_paths(entry: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        macos.validate_catalog({"wine-crossover": [entry]})


def test_manager_installs_and_detects_separate_bundle_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.dialogs import proton_manager
    monkeypatch.setattr(proton_manager.sys, "platform", "darwin")
    manager = SimpleNamespace(portproton_location=str(tmp_path))
    for name in ("Wine 1", "Wine 2"):
        destination = proton_manager.ProtonManager.get_download_extract_dir(cast(Any, manager), {"asset_name": name})
        binary = Path(destination) / "wswine.bundle/bin/wine64"
        binary.parent.mkdir(parents=True)
        binary.touch(mode=0o755)
        assert proton_manager.ProtonManager.is_asset_installed(cast(Any, manager), name, "sikarugir-engines")
        assert proton_manager.ProtonManager.is_installed_version_dir(cast(Any, manager), destination)
    assert proton_manager.ProtonManager.filter_entries_by_cpu_level(cast(Any, manager), [{"name": "x86_64"}], "wine-crossover") == [{"name": "x86_64"}]


def test_darwin_config_selects_native_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.config import portproton
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path / "data root"))
    monkeypatch.setattr(portproton.sys, "platform", "darwin")
    assert portproton.get_portproton_location() == str(tmp_path / "data root")
    command = portproton.get_portproton_start_command()
    assert command is not None
    assert command[1:] == ["-m", "portprotonqt.macos"]


def test_shutdown_waits_for_retained_wine_tools() -> None:
    from portprotonqt.tabs.workers import MainWindowWorkersMixin
    process = Mock()
    process.waitForFinished.side_effect = [False, True]
    window = SimpleNamespace(wine_tool_processes=[process], _stopWorkerThread=Mock(), _stopWorkerThreads=Mock())
    MainWindowWorkersMixin._stopBackgroundWorkers(cast(Any, window))
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.waitForFinished.call_count == 2
    assert window.wine_tool_processes == []


def test_macos_extraction_is_per_version_and_rejects_escape(tmp_path: Path) -> None:
    import io
    import tarfile
    from portprotonqt.dialogs.wine_extractor import ExtractionThread
    archive = tmp_path / "wine.tar"
    with tarfile.open(archive, "w") as stream:
        entry = tarfile.TarInfo("wswine.bundle/bin/wine64")
        entry.mode = 0o755
        entry.size = len(b"wine")
        stream.addfile(entry, io.BytesIO(b"wine"))
    destination = macos.version_directory(tmp_path, "Engine 1")
    worker = ExtractionThread(str(archive), str(destination))
    worker.run()
    assert macos.find_wine(destination) == destination / "wswine.bundle/bin/wine64"
    assert not macos.version_directory(tmp_path, "Engine 2").exists()
    with tarfile.open(archive, "w") as stream:
        entry = tarfile.TarInfo("../escape")
        entry.size = len(b"bad")
        stream.addfile(entry, io.BytesIO(b"bad"))
    worker = ExtractionThread(str(archive), str(destination))
    failure = Mock()
    worker.error.connect(failure)
    worker.run()
    failure.assert_called_once()
    assert not (destination.parent / "escape").exists()


def test_macos_shutdown_kills_only_owned_groups_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt import main_window
    monkeypatch.setattr(main_window.sys, "platform", "darwin")
    kill_group = Mock()
    monkeypatch.setattr(main_window.os, "killpg", kill_group)
    process = Mock(pid=1234)
    process.poll.return_value = 0
    window = SimpleNamespace(game_processes=[process])
    main_window.MainWindow._terminate_game_processes(cast(Any, window))
    kill_group.assert_called_once_with(1234, main_window.signal.SIGKILL)
    process.wait.assert_called_once_with(timeout=0)
    detached = Mock()
    monkeypatch.setattr(main_window.QProcess, "startDetached", detached)
    assert main_window.MainWindow._run_portproton_stop_command(cast(Any, window))
    detached.assert_not_called()


def test_macos_tool_shutdown_kills_session_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.tabs import workers
    monkeypatch.setattr(workers.sys, "platform", "darwin")
    kill_group = Mock()
    monkeypatch.setattr(workers.os, "killpg", kill_group)
    process = Mock()
    process.processId.return_value = 1234
    window = SimpleNamespace(wine_tool_processes=[process], _stopWorkerThread=Mock(), _stopWorkerThreads=Mock())
    workers.MainWindowWorkersMixin._stopBackgroundWorkers(cast(Any, window))
    kill_group.assert_called_once_with(1234, workers.signal.SIGKILL)
    process.waitForFinished.assert_called_once()


def test_macos_does_not_start_linux_virtual_mouse_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt import input_manager
    monkeypatch.setattr(input_manager.sys, "platform", "darwin")
    worker = Mock()
    monkeypatch.setattr(input_manager, "MouseEmulationThread", worker)
    manager = SimpleNamespace(mouse_emulation_enabled=True)
    input_manager.InputManager._async_enable_mouse_emulation(cast(Any, manager))
    assert manager.mouse_emulation_enabled is False
    worker.assert_not_called()


def test_macos_settings_offer_only_implemented_engine_and_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt import settings_manager
    monkeypatch.setattr(settings_manager.sys, "platform", "darwin")
    assert settings_manager.get_toggle_settings() == {}
    settings = settings_manager.get_advanced_settings("disabled", ["1"], [], {}, ["Wine"], ["DEFAULT"])
    assert {setting["key"] for setting in settings} == {"PW_WINE_USE", "PW_PREFIX_NAME"}


def test_explicit_system_wine_selection_uses_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos.shutil, "which", lambda _name: "/opt/homebrew/bin/wine")
    command, _environment = macos.wine_command(tmp_path, ["game.exe"], {"PW_WINE_USE": "USE_SYSTEM_WINE"})
    assert command == ["/opt/homebrew/bin/wine", "game.exe"]


def test_macos_wine_options_exclude_incomplete_engines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt import settings_manager
    monkeypatch.setattr(settings_manager.sys, "platform", "darwin")
    monkeypatch.setattr(settings_manager.shutil, "which", lambda _name: None)
    valid = macos.version_directory(tmp_path, "Wine") / "Wine.app/Contents/Resources/wine/bin/wine"
    valid.parent.mkdir(parents=True)
    valid.touch(mode=0o755)
    macos.version_directory(tmp_path, "incomplete").mkdir()
    assert settings_manager.get_available_wine_options(str(tmp_path)) == ["Wine"]


@pytest.mark.parametrize("method", ["_launch_egs_game", "_launch_gog_game"])
def test_macos_store_wrappers_fail_explicitly_before_linux_setup(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    from portprotonqt import main_window
    monkeypatch.setattr(main_window.sys, "platform", "darwin")
    warning = Mock()
    monkeypatch.setattr(main_window.QMessageBox, "warning", warning)
    window = SimpleNamespace(_finish_silent_launch=Mock(), egs_api=Mock(), gog_api=Mock())
    getattr(main_window.MainWindow, method)(cast(Any, window), "game")
    window._finish_silent_launch.assert_called_once()
    warning.assert_called_once()
    assert "macOS" in warning.call_args.args[2]
    assert "directly" in warning.call_args.args[2]
    assert window.egs_api.mock_calls == []
    assert window.gog_api.mock_calls == []


def test_settings_ignores_predictable_temporary_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("preserved")
    path = tmp_path / "user.conf"
    path.with_suffix(".conf.tmp").symlink_to(outside)
    macos.write_settings(path, {"KEY": "value"})
    assert outside.read_text() == "preserved"
    assert macos.read_settings(path) == {"KEY": "value"}


def test_settings_replace_failure_preserves_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "user.conf"
    path.write_text("original")
    monkeypatch.setattr(macos.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        macos.write_settings(path, {"KEY": "value"})
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("extension,dispatch", [
    (".msi", ["msiexec", "/i"]), (".bat", ["cmd", "/c"]),
    (".cmd", ["cmd", "/c"]), (".reg", ["regedit"]),
])
def test_adapter_dispatch_and_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               extension: str, dispatch: list[str]) -> None:
    target = tmp_path / ("game" + extension)
    target.touch()
    monkeypatch.setenv("PORT_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(macos.shutil, "which", lambda _: "/wine")
    execute, change_directory = Mock(), Mock()
    monkeypatch.setattr(macos.os, "execvpe", execute)
    monkeypatch.setattr(macos.os, "chdir", change_directory)
    assert macos.main([str(target), "extra argument"]) == 0
    assert execute.call_args.args[1] == ["/wine", *dispatch, str(target), "extra argument"]
    change_directory.assert_called_once_with(tmp_path)


def test_darwin_extraction_failure_and_cancel_preserve_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import tarfile
    from portprotonqt.dialogs import wine_extractor
    monkeypatch.setattr(wine_extractor.sys, "platform", "darwin")
    destination = macos.version_directory(tmp_path, "Engine")
    destination.mkdir(parents=True)
    (destination / "original").write_text("working")
    archive = tmp_path / "wine.tar"
    with tarfile.open(archive, "w") as stream:
        for name in ("bin/wine", "../escape"):
            entry = tarfile.TarInfo(name)
            entry.mode, entry.size = 0o755, 4
            stream.addfile(entry, io.BytesIO(b"wine"))
    worker = wine_extractor.ExtractionThread(str(archive), str(destination))
    failed = Mock()
    worker.error.connect(failed)
    worker.run()
    failed.assert_called_once()
    assert list(destination.iterdir()) == [destination / "original"]
    worker.stop()
    worker.run()
    assert list(destination.parent.iterdir()) == [destination]


def test_darwin_extraction_promotes_complete_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import tarfile
    from portprotonqt.dialogs import wine_extractor
    monkeypatch.setattr(wine_extractor.sys, "platform", "darwin")
    archive = tmp_path / "wine.tar"
    with tarfile.open(archive, "w") as stream:
        entry = tarfile.TarInfo("bin/wine")
        entry.mode, entry.size = 0o755, 4
        stream.addfile(entry, io.BytesIO(b"wine"))
    destination = macos.version_directory(tmp_path, "Engine")
    worker = wine_extractor.ExtractionThread(str(archive), str(destination))
    complete = Mock()
    worker.finished.connect(complete)
    worker.run()
    complete.assert_called_once_with(str(archive), True)
    assert macos.find_wine(destination) == destination / "bin/wine"
    assert list(destination.parent.iterdir()) == [destination]
