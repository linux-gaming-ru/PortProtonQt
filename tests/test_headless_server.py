"""Headless D-Bus data and command regressions."""

import asyncio
import io
import json

import pytest

from portproton import library
from portproton.library import get_autoinstall_games
from portproton.operations import run_command, validate_setting
from portproton.server import PortProtonService, _settings_values


def test_autoinstall_catalog_uses_shared_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    cache = tmp_path / "PortProtonQt/cache/autoinstall_games_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"games": [["Game", "Info", "cover.png", "", "", "autoinstall:test.ppai"]]}))

    games = get_autoinstall_games()

    assert games[0]["name"] == "Game"
    assert games[0]["script"] == "autoinstall:test.ppai"


def test_headless_exe_methods_have_client_signatures():
    methods = {method.name: method for method in PortProtonService().introspect().methods}

    assert [arg.signature for arg in methods["LaunchExe"].in_args] == ["s"]
    assert [arg.signature for arg in methods["GetExeSettings"].out_args] == ["s"]
    assert [arg.signature for arg in methods["SetExeSettings"].in_args] == ["s", "as"]


def test_settings_output_excludes_cli_messages_and_shell_quotes():
    output = '\x1b[36m Info: edit_db_from_gui PORTWINE_DB_FILE=/game.exe.ppdb\x1b[0m\n'
    output += 'PW_USE_ESYNC\nPW_USE_ESYNC="1"\nPW_WINE_USE="WINE_LG_11-10"\n'

    assert _settings_values(output) == 'PW_USE_ESYNC=1\nPW_WINE_USE=WINE_LG_11-10'


def test_autoinstall_catalog_fills_shared_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    payload = {"games": [{"id": 42, "name_en": "Game", "ppai_url": "https://example.org/game.ppai"}]}
    monkeypatch.setattr(library.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(library.locale, "getlocale", lambda: ("en_US", "UTF-8"))

    games = get_autoinstall_games()
    cache = tmp_path / "PortProtonQt/cache/autoinstall_games_cache.json"

    assert games[0]["name"] == "Game"
    assert games[0]["script"] == "autoinstall:https://example.org/game.ppai"
    assert json.loads(cache.read_text())["games"][0][0] == "Game"


def test_command_uses_configured_portproton_path(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    data = tmp_path / "portproton"
    data.mkdir()
    (config / "PortProton.conf").write_text(str(data))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "start.sh").write_text('printf "%s:%s" "$PORT_DATA_PATH" "$2"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))

    assert asyncio.run(run_command(scripts, ["--get-user-conf"])) == f"{data}:--get-user-conf"
    with pytest.raises(ValueError):
        validate_setting("PW_PREFIX_NAME=$(touch bad)")
