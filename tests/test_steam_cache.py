"""Tests for steam_api/cache.py — exiftool skip and search functions."""
import time
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from portprotonqt.steam_api.cache import (
    get_exiftool_data,
    delete_cached_app_files,
    _EXIFTOOL_CACHE,
    _CACHE_MAX_ENTRIES,
    _CACHE_TTL,
)


@pytest.fixture(autouse=True)
def clear_exiftool_cache():
    _EXIFTOOL_CACHE.clear()
    yield
    _EXIFTOOL_CACHE.clear()


@pytest.mark.parametrize("kind", ["app", "protondb", "steam", "anticheat", "ppdb"])
def test_slow_metadata_cache_keeps_qt_responsive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str,
) -> None:
    import orjson
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from portprotonqt.steam_api import api, cache

    app = QApplication.instance() or QApplication([])
    manager = cache.CacheManager(tmp_path)
    monkeypatch.setattr(cache, "CacheManager", lambda: manager)
    monkeypatch.setattr(api, "CacheManager", lambda: manager)
    entry = {"normalized_name": "game", "appid": 1, "id": 1, "status": "works", "slug": "game"}
    catalogs = {
        "steam": ("_STEAM_APPS_CACHE", "steam_apps", api.get_steam_apps_and_index_async),
        "anticheat": ("_ANTICHEAT_CACHE", "anticheat_games", api.get_anticheat_data_and_index_async),
        "ppdb": ("_PPDB_CACHE", "ppdb_games", api.get_ppdb_data_and_index_async),
    }
    if kind in catalogs:
        name, filename, request = catalogs[kind]
        monkeypatch.setattr(api, name, manager)
        payload: Any = [entry]
        expected: Any = ([entry], {"game": entry})
    elif kind == "app":
        filename, payload = "steam_app_1", {"name": "Game"}
        request = partial(api.fetch_app_info_async, 1)
        expected = payload
    else:
        filename, payload = "protondb_1", {"tier": "gold"}
        request = partial(api.get_protondb_tier_async, 1)
        expected = "gold"
    target = tmp_path / f"{filename}.json"
    target.write_bytes(orjson.dumps(payload))
    original_stat = Path.stat
    entered, release = Event(), Event()

    def slow_stat(path: Path, **kwargs: Any) -> Any:
        if path == target:
            assert QThread.currentThread() != app.thread()
            entered.set()
            assert release.wait(5)
        return original_stat(path, **kwargs)

    monkeypatch.setattr(Path, "stat", slow_stat)
    results: list[tuple[Any, QThread]] = []
    tick = MagicMock()
    try:
        request(lambda result: results.append((result, QThread.currentThread())))
        assert entered.wait(5)
        QTimer.singleShot(0, tick)
        app.processEvents()
        tick.assert_called_once_with()
        assert not results
    finally:
        release.set()
        assert api._METADATA_LOOKUPS.waitForDone(5000)
    app.processEvents()
    assert results == [(expected, app.thread())]


class TestGetExiftoolData:
    def test_skips_missing_executable(self, tmp_path: Path):
        fake_exe = tmp_path / "game.exe"
        fake_exe.touch()
        with patch("shutil.which", return_value=None):
            assert get_exiftool_data(str(fake_exe)) == {}

    def test_skips_nonexistent_file(self):
        assert get_exiftool_data("/nonexistent/game.exe") == {}

    def test_returns_empty_on_nonzero_returncode(self, tmp_path: Path):
        fake_exe = tmp_path / "game.exe"
        fake_exe.touch()
        mock_proc = MagicMock(returncode=1, stderr="error")
        with (
            patch("shutil.which", return_value="/usr/bin/exiftool"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            assert get_exiftool_data(str(fake_exe)) == {}

    def test_returns_metadata(self, tmp_path: Path):
        import orjson
        fake_exe = tmp_path / "game.exe"
        fake_exe.touch()
        meta = [{"FileName": "game.exe", "FileSize": 1024}]
        mock_proc = MagicMock(returncode=0, stdout=orjson.dumps(meta).decode())
        with (
            patch("shutil.which", return_value="/usr/bin/exiftool"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = get_exiftool_data(str(fake_exe))
            assert result == {"FileName": "game.exe", "FileSize": 1024}

    def test_caches_result(self, tmp_path: Path):
        import orjson
        fake_exe = tmp_path / "game.exe"
        fake_exe.touch()
        meta = [{"FileName": "game.exe"}]
        mock_proc = MagicMock(returncode=0, stdout=orjson.dumps(meta).decode())
        with (
            patch("shutil.which", return_value="/usr/bin/exiftool"),
            patch("subprocess.run", return_value=mock_proc) as mock_run,
        ):
            get_exiftool_data(str(fake_exe))
            get_exiftool_data(str(fake_exe))
            assert mock_run.call_count == 1

    def test_expired_cache_fetched_again(self, tmp_path: Path):
        import orjson
        fake_exe = tmp_path / "game.exe"
        fake_exe.touch()
        meta = [{"FileName": "game.exe"}]
        mock_proc = MagicMock(returncode=0, stdout=orjson.dumps(meta).decode())

        _EXIFTOOL_CACHE[str(fake_exe)] = (meta[0], time.time() - _CACHE_TTL - 1)

        with (
            patch("shutil.which", return_value="/usr/bin/exiftool"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = get_exiftool_data(str(fake_exe))
            assert result == {"FileName": "game.exe"}

    def test_cache_eviction(self, tmp_path: Path):
        for i in range(_CACHE_MAX_ENTRIES // 2 + 1):
            exe = tmp_path / f"game{i}.exe"
            exe.touch()
            _EXIFTOOL_CACHE[str(exe)] = ({"file": i}, time.time() - _CACHE_TTL - 1)

        import orjson
        new_exe = tmp_path / "new.exe"
        new_exe.touch()
        meta = [{"FileName": "new.exe"}]
        mock_proc = MagicMock(returncode=0, stdout=orjson.dumps(meta).decode())
        with (
            patch("shutil.which", return_value="/usr/bin/exiftool"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            get_exiftool_data(str(new_exe))
        assert str(new_exe) in _EXIFTOOL_CACHE


class TestDeleteCachedAppFiles:
    def test_deletes_matching_files(self, tmp_path: Path):
        for name in ("steam_app_1.json", "steam_app_2.json", "other.json"):
            (tmp_path / name).write_text("{}")
        delete_cached_app_files(str(tmp_path), "steam_app_*.json")
        assert not (tmp_path / "steam_app_1.json").exists()
        assert not (tmp_path / "steam_app_2.json").exists()
        assert (tmp_path / "other.json").exists()

    def test_no_matching_files(self, tmp_path: Path):
        (tmp_path / "other.txt").write_text("hello")
        delete_cached_app_files(str(tmp_path), "steam_app_*.json")
        assert (tmp_path / "other.txt").exists()


@pytest.mark.parametrize("source", ["exe", "gog", "egs"])
def test_matched_steam_game_keeps_cover_when_app_details_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    import portprotonqt.steam_api.api as api

    monkeypatch.setattr("portprotonqt.config.cache.CACHE_DIR", tmp_path / "cache")
    executable = tmp_path / "Praest.exe"
    executable.touch()
    exec_line = str(executable) if source == "exe" else f"{source}://launch/graven"
    app = {"appid": 1371690, "normalized_name": "graven"}
    monkeypatch.setattr(api.ui_config, "get_economy_mode", lambda: False)
    monkeypatch.setattr("portprotonqt.steam_api.cache.get_exiftool_data", lambda _exe: {})
    monkeypatch.setattr(api, "_has_custom_data_for_exe", lambda _name: False)
    monkeypatch.setattr(api, "get_steam_apps_and_index_async", lambda cb: cb(([app], {"graven": app})))
    monkeypatch.setattr(api, "fetch_app_info_async", lambda _appid, cb: cb(None))
    monkeypatch.setattr(api, "get_local_steam_cover", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(api, "get_weanticheatyet_info_async", lambda _name, cb: cb({}))
    monkeypatch.setattr(api, "_add_ppdb_info", lambda result, _name, cb: cb(result))
    results = []
    api.get_steam_game_info_async("GRAVEN", exec_line, results.append)
    assert len(results) == 1
    assert results[0]["appid"] == 1371690
    assert results[0]["steam_game"] == "true"
    expected_cover = (
        "https://steamcdn-a.akamaihd.net/steam/apps/1371690/library_600x900_2x.jpg"
        if source == "exe" else ""
    )
    assert results[0]["cover"] == expected_cover
    with (
        patch("portprotonqt.steam_api.cache.get_exiftool_data", side_effect=AssertionError("EXE reread")),
        patch.object(api, "get_steam_apps_and_index_async", side_effect=AssertionError("Catalog reloaded")),
        patch.object(api, "search_app", side_effect=AssertionError("AppID searched again")),
    ):
        api.get_steam_game_info_async("GRAVEN", exec_line, results.append)
    assert len(results) == 2
    assert results[1] == results[0]
