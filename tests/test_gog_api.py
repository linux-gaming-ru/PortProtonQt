import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import orjson
import pytest

from portprotonqt.gog_api import GOGAPI, GOGDL_UPDATE_INTERVAL, GOG_PRODUCT_LOCALES
from portprotonqt.localization import LOCALE_MAP


def test_default_games_directory_is_user_games_folder() -> None:
    api = GOGAPI()

    assert api.games_dir == Path.home() / "Games"


def test_extract_auth_code() -> None:
    url = "https://embed.gog.com/on_login_success?origin=client&code=test%20code"

    assert GOGAPI.extract_auth_code(url) == "test code"
    assert GOGAPI.extract_auth_code("https://example.com/?code=test") == ""


def test_load_installed_uses_isolated_data_dir(tmp_path: Path) -> None:
    api = GOGAPI()
    api.installed_path = tmp_path / "installed.json"
    api.installed_path.write_bytes(orjson.dumps({"123": {"title": "Game"}}))

    assert api.load_installed() == {"123": {"title": "Game"}}


def test_remove_installed_game_keeps_other_records(tmp_path: Path) -> None:
    api = GOGAPI()
    api.installed_path = tmp_path / "installed.json"
    api.installed_path.write_bytes(orjson.dumps({"123": {}, "456": {}}))

    api.remove_installed_game("123")

    assert api.load_installed() == {"456": {}}


def test_clear_library_cache_removes_gog_metadata(tmp_path: Path) -> None:
    api = GOGAPI()
    api.library_path = tmp_path / "library.json"
    api.library_path.write_bytes(orjson.dumps([
        {"app_id": "123", "cover": "cover.webp", "description": "Description"}
    ]))

    api.clear_library_cache()

    assert not api.library_path.exists()


def test_get_launch_target_reads_primary_task(tmp_path: Path) -> None:
    api = GOGAPI()
    api.installed_path = tmp_path / "installed.json"
    game_dir = tmp_path / "game"
    executable = game_dir / "BIN/Game.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    api.installed_path.write_bytes(orjson.dumps({"123": {"install_path": str(game_dir)}}))
    info = {
        "playTasks": [{
            "type": "FileTask", "path": "bin\\game.exe",
            "arguments": '-conf "..\\game.conf"', "isPrimary": True,
        }]
    }
    (game_dir / "goggame-123.info").write_bytes(orjson.dumps(info))

    assert api.get_launch_target("123") == str(executable)

    api.ensure_launch_parameters("123")
    assert 'export LAUNCH_PARAMETERS="-conf ../game.conf"' in Path(
        f"{executable}.ppdb"
    ).read_text()


def test_launch_parameters_keep_gog_relative_paths(tmp_path: Path) -> None:
    api = GOGAPI()
    api.config_dir = tmp_path / "gogdl"
    api.installed_path = tmp_path / "installed.json"
    game_dir = tmp_path / "game"
    executable = game_dir / "DOSBOX/DOSBox.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    api.installed_path.write_bytes(orjson.dumps({"123": {"install_path": str(game_dir)}}))
    info = {"playTasks": [{
        "type": "FileTask", "path": "DOSBOX\\DOSBox.exe",
        "arguments": '-conf "..\\game.conf"', "isPrimary": True,
    }]}
    (game_dir / "goggame-123.info").write_bytes(orjson.dumps(info))

    api.ensure_launch_parameters("123")

    assert 'export LAUNCH_PARAMETERS="-conf ../game.conf"' in Path(
        f"{executable}.ppdb"
    ).read_text()


def test_install_support_reuses_and_runs_isi(
    tmp_path: Path, monkeypatch
) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path / "gog"
    api.config_dir = api.data_dir / "gogdl"
    api.installed_path = api.data_dir / "installed.json"
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    executable = game_dir / "DOSBOX/DOSBox.exe"
    executable.parent.mkdir()
    executable.touch()
    Path(f"{executable}.ppdb").write_text(
        'export PW_USE_FSYNC="1"\n'
        'export LAUNCH_PARAMETERS="-old"\n'
        'export FILE_SHA256SUM="old"\n',
        encoding="utf-8",
    )
    (game_dir / "goggame-123.info").write_bytes(orjson.dumps({
        "playTasks": [{
            "type": "FileTask",
            "path": "DOSBOX\\DOSBox.exe",
            "arguments": '-conf "..\\game.conf"',
            "isPrimary": True,
        }],
    }))
    api.save_installed_game("123", {"install_path": str(game_dir)})
    manifest_path = api.config_dir / "heroic_gogdl/manifests/123"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(orjson.dumps({
        "scriptInterpreter": True,
        "products": [{"productId": "123"}],
        "buildId": "build",
        "versionName": "version",
    }))
    interpreter = api.data_dir / "redist/gog/__redist/ISI/scriptinterpreter.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    calls = []
    process = SimpleNamespace(wait=lambda **_kwargs: 0)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(api, "build_command", lambda arguments: ["gogdl", *arguments])
    monkeypatch.setattr("portprotonqt.gog_api.subprocess.run", run)
    monkeypatch.setattr(
        "portprotonqt.gog_api.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or process,
    )
    launched = []
    api.install_support("123", ["start.sh"], launched.append)

    assert calls[0][0] == ["start.sh", str(interpreter)]
    ppdb = Path(f"{interpreter}.ppdb").read_text()
    setup_path = api.data_dir / "setup/123"
    assert f"/DIR=Z:{str(setup_path).replace('/', chr(92))}" in ppdb
    assert setup_path.resolve() == game_dir
    assert "PW_PREFIX_NAME" not in ppdb
    assert 'export PW_USE_FSYNC="1"' in ppdb
    assert 'export LAUNCH_PARAMETERS="-old"' not in ppdb
    assert "FILE_SHA256SUM" not in ppdb
    assert "PW_RUN_AFTER_EXE" not in ppdb
    assert calls[0][1]["start_new_session"] is True
    assert launched == [process]


def test_is_game_installed_requires_gogdl_metadata(tmp_path: Path) -> None:
    api = GOGAPI()
    api.installed_path = tmp_path / "installed.json"
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    api.installed_path.write_bytes(orjson.dumps({"123": {"install_path": str(game_dir)}}))

    assert api.is_game_installed("123") is False

    (game_dir / "goggame-123.info").write_text("{}")
    assert api.is_game_installed("123") is True


def test_find_install_path_returns_gogdl_directory(tmp_path: Path) -> None:
    api = GOGAPI()
    game_dir = tmp_path / "Game created by gogdl"
    game_dir.mkdir()
    (game_dir / "goggame-123.info").write_text("{}")

    assert api.find_install_path("123", tmp_path) == game_dir


def test_is_game_installed_discovers_default_gogdl_directory(tmp_path: Path) -> None:
    api = GOGAPI()
    api.installed_path = tmp_path / "installed.json"
    api.games_dir = tmp_path / "games"
    game_dir = api.games_dir / "Game created by gogdl"
    game_dir.mkdir(parents=True)
    (game_dir / "goggame-123.info").write_text("{}")

    assert api.is_game_installed("123") is True


def test_localized_value_prefers_current_language(monkeypatch) -> None:
    monkeypatch.setattr("portprotonqt.gog_api.get_metadata_language", lambda: "ru")

    assert GOGAPI._localized_value({"*": "English", "ru-RU": "Русский"}) == "Русский"


def test_product_locales_cover_supported_languages() -> None:
    assert set(GOG_PRODUCT_LOCALES) == {language.lower() for language in LOCALE_MAP}


def test_parse_download_sizes_includes_language_data() -> None:
    output = (
        b'{"size":{"*":{"download_size":100,"disk_size":200},'
        b'"en-US":{"download_size":30,"disk_size":40}},'
        b'"languages":["en-US"]}'
    )

    assert GOGAPI.parse_download_sizes(output) == (130, 240)


def test_download_sizes_cache(tmp_path: Path) -> None:
    api = GOGAPI()
    api.sizes_path = tmp_path / "sizes.json"

    assert api.get_cached_download_sizes("123") is None
    api.save_download_sizes("123", (100, 200))

    assert api.get_cached_download_sizes("123") == (100, 200)


@pytest.mark.parametrize(
    ("lead", "expected"),
    [
        (
            "Description française.<br><br>Deuxième paragraphe.",
            "Description française.",
        ),
        (
            "<b>Avertissement.</b><br><br>Description.<br><br>Troisième paragraphe.",
            "<b>Avertissement.</b><br><br>Description.",
        ),
    ],
)
def test_get_game_loads_localized_product_description(
    monkeypatch: pytest.MonkeyPatch, lead: str, expected: str
) -> None:
    gamesdb_response = Mock()
    gamesdb_response.json.return_value = {
        "game": {
            "title": {"*": "Game"},
            "visible_in_library": True,
            "releases": [{"platform_id": "steam", "external_id": "358180"}],
        },
        "summary": {"*": "English description"},
    }
    product_response = Mock()
    product_response.json.return_value = {
        "description": {"lead": lead},
    }
    request = Mock(side_effect=[gamesdb_response, product_response])
    monkeypatch.setattr("portprotonqt.gog_api.get_metadata_language", lambda: "fr")
    monkeypatch.setattr("portprotonqt.gog_api.requests.get", request)

    game = GOGAPI()._get_game(
        {"platform_id": "gog", "external_id": "1207666073"}, "token"
    )

    assert game["description"] == expected
    assert game["steam_appid"] == "358180"
    assert request.call_args_list[1].kwargs["params"]["locale"] == "fr-FR"


def test_is_authenticated_requires_token_and_user_id(monkeypatch) -> None:
    api = GOGAPI()

    monkeypatch.setattr(api, "get_credentials", lambda: {"access_token": "token"})
    assert api.is_authenticated() is False

    monkeypatch.setattr(
        api, "get_credentials", lambda: {"access_token": "token", "user_id": "123"}
    )
    assert api.is_authenticated() is True


def test_ensure_gogdl_downloads_matching_architecture(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    asset = {"name": "gogdl_linux_x86_64"}
    response = Mock()
    response.json.return_value = {"assets": [asset], "tag_name": "v1.2.1"}
    monkeypatch.setattr("portprotonqt.gog_api.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("portprotonqt.gog_api.requests.get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        api, "_install_gogdl_release",
        lambda selected, tag: f'{selected["name"]}:{tag}',
    )

    assert api.ensure_gogdl() == "gogdl_linux_x86_64:v1.2.1"


def test_update_gogdl_skips_current_release(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    api.gogdl_version_path = tmp_path / "bin/gogdl.version"
    gogdl_path = tmp_path / "bin/gogdl"
    gogdl_path.parent.mkdir()
    gogdl_path.touch()
    gogdl_path.chmod(0o755)
    api.gogdl_version_path.write_text("v1.2.1", encoding="utf-8")
    latest_release = Mock(return_value=({}, "v1.2.1"))
    monkeypatch.setattr(api, "_get_latest_gogdl_release", latest_release)
    install = Mock()
    monkeypatch.setattr(api, "_install_gogdl_release", install)

    assert api.update_gogdl() == str(gogdl_path)
    latest_release.assert_not_called()
    install.assert_not_called()


def test_update_gogdl_checks_release_after_month(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    api.gogdl_version_path = tmp_path / "bin/gogdl.version"
    gogdl_path = tmp_path / "bin/gogdl"
    gogdl_path.parent.mkdir()
    gogdl_path.touch()
    gogdl_path.chmod(0o755)
    api.gogdl_version_path.write_text("v1.2.1", encoding="utf-8")
    os.utime(api.gogdl_version_path, (1, 1))
    last_check = api.gogdl_version_path.stat().st_mtime
    monkeypatch.setattr(
        "portprotonqt.gog_api.time.time",
        lambda: last_check + GOGDL_UPDATE_INTERVAL,
    )
    latest_release = Mock(return_value=({}, "v1.2.1"))
    monkeypatch.setattr(api, "_get_latest_gogdl_release", latest_release)

    assert api.update_gogdl() == str(gogdl_path)
    latest_release.assert_called_once_with()


def test_update_gogdl_records_failed_monthly_check(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    api.gogdl_version_path = tmp_path / "bin/gogdl.version"
    gogdl_path = tmp_path / "bin/gogdl"
    gogdl_path.parent.mkdir()
    gogdl_path.touch()
    gogdl_path.chmod(0o755)
    api.gogdl_version_path.write_text("v1.2.1", encoding="utf-8")
    os.utime(api.gogdl_version_path, (1, 1))
    last_check = api.gogdl_version_path.stat().st_mtime
    monkeypatch.setattr(
        "portprotonqt.gog_api.time.time",
        lambda: last_check + GOGDL_UPDATE_INTERVAL,
    )
    monkeypatch.setattr(
        api, "_get_latest_gogdl_release", Mock(side_effect=OSError("offline"))
    )

    with pytest.raises(OSError, match="offline"):
        api.update_gogdl()

    assert api.gogdl_version_path.stat().st_mtime > last_check


def test_update_gogdl_installs_new_release(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    api.gogdl_version_path = tmp_path / "bin/gogdl.version"
    asset = {"name": "gogdl_linux_x86_64"}
    monkeypatch.setattr(api, "_get_latest_gogdl_release", lambda: (asset, "v1.2.1"))
    monkeypatch.setattr(
        api, "_install_gogdl_release",
        lambda selected, tag: f'{selected["name"]}:{tag}',
    )

    assert api.update_gogdl() == "gogdl_linux_x86_64:v1.2.1"


def test_install_gogdl_release_records_version(tmp_path: Path, monkeypatch) -> None:
    api = GOGAPI()
    api.gogdl_version_path = tmp_path / "bin/gogdl.version"
    api.gogdl_version_path.parent.mkdir()
    monkeypatch.setattr(api, "_download_gogdl_asset", lambda _asset: "/bin/gogdl")

    assert api._install_gogdl_release({}, "v1.2.1") == "/bin/gogdl"
    assert api.gogdl_version_path.read_text(encoding="utf-8") == "v1.2.1"


def test_authenticate_returns_gogdl_error(monkeypatch) -> None:
    api = GOGAPI()
    result = Mock(returncode=1, stdout=b"", stderr=b"authorization failed")
    monkeypatch.setattr(api, "ensure_gogdl", lambda: "/bin/gogdl")
    monkeypatch.setattr(api, "build_command", lambda arguments: ["gogdl", *arguments])
    monkeypatch.setattr("portprotonqt.gog_api.subprocess.run", lambda *args, **kwargs: result)

    assert api.authenticate("code") == (False, "authorization failed")
