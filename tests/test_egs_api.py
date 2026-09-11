from pathlib import Path
from types import SimpleNamespace
from typing import Any

import orjson
from pytest import MonkeyPatch

from portprotonqt.egs_api import EGSAPI
from portprotonqt.localization import get_store_content_languages


def test_build_command_uses_isolated_legendary_config(
    tmp_path: Path, monkeypatch
) -> None:
    api = EGSAPI()
    api.config_dir = tmp_path / "legendary"
    monkeypatch.setattr(api, "get_legendary_path", lambda: "/bin/legendary")

    assert api.build_command(["list", "--json"]) == [
        "/bin/legendary", "list", "--json",
    ]
    assert api.get_environment()["LEGENDARY_CONFIG_PATH"] == str(api.config_dir)


def test_build_command_places_confirmation_before_subcommand(
    tmp_path: Path, monkeypatch
) -> None:
    api = EGSAPI()
    api.config_dir = tmp_path / "legendary"
    monkeypatch.setattr(api, "get_legendary_path", lambda: "/bin/legendary")

    assert api.build_command(["install", "Game", "-y"]) == [
        "/bin/legendary", "-y", "install", "Game",
    ]


def test_update_legendary_skips_matching_release(tmp_path: Path, monkeypatch) -> None:
    api = EGSAPI()
    api.data_dir = tmp_path
    api.bin_dir = tmp_path / "bin"
    api.version_path = tmp_path / "bin/legendary.version"
    bundled = tmp_path / "bin/legendary"
    bundled.parent.mkdir()
    bundled.touch(mode=0o755)
    api.version_path.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(api, "_get_latest_legendary_release", lambda: ({}, "v1"))

    assert api.update_legendary() == str(bundled)


def test_normalize_game_uses_epic_metadata() -> None:
    game = EGSAPI._normalize_game({
        "app_name": "TestGame",
        "app_title": "Test Game",
        "metadata": {
            "description": "Description",
            "namespace": "test-namespace",
            "keyImages": [{"type": "DieselGameBoxTall", "url": "cover.jpg"}],
        },
    })

    assert game == {
        "app_id": "TestGame",
        "title": "Test Game",
        "description": "Description",
        "cover": "cover.jpg",
        "namespace": "test-namespace",
        "description_locale": "",
        "description_preference": "",
        "description_cache_version": 0,
    }


def test_refresh_library_skips_mobile_only_games(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    api = EGSAPI()
    api.library_path = tmp_path / "library.json"
    games = [
        {
            "app_name": "MobileGame",
            "app_title": "Mobile Game",
            "metadata": {"releaseInfo": [{"platform": ["Android", "iOS"]}]},
        },
        {
            "app_name": "DesktopGame",
            "app_title": "Desktop Game",
            "metadata": {"releaseInfo": [{"platform": ["Windows"]}]},
        },
    ]
    result = SimpleNamespace(returncode=0, stdout=orjson.dumps(games), stderr=b"")
    monkeypatch.setattr(api, "update_legendary", lambda: "/bin/legendary")
    monkeypatch.setattr(api, "build_command", lambda args: ["legendary", *args])
    monkeypatch.setattr("portprotonqt.egs_api.subprocess.run", lambda *args, **kwargs: result)
    monkeypatch.setattr(api, "_enrich_descriptions", lambda *_args: None)

    library = api.refresh_library()

    assert [game["app_id"] for game in library] == ["DesktopGame"]


def test_store_description_uses_epic_product_page(monkeypatch: MonkeyPatch) -> None:
    api = EGSAPI()
    graphql_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "data": {"Catalog": {"catalogNs": {
                "mappings": [{"pageSlug": "control"}],
            }}},
        },
    )
    store_response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"pages": [{
            "type": "productHome",
            "data": {"about": {"description": "Real description"}},
        }]},
    )
    monkeypatch.setattr(
        "portprotonqt.egs_api.requests.post",
        lambda *args, **kwargs: graphql_response,
    )
    monkeypatch.setattr(
        "portprotonqt.egs_api.requests.get",
        lambda *args, **kwargs: store_response,
    )
    monkeypatch.setattr("portprotonqt.localization.get_metadata_language", lambda: "en")

    description = api._get_store_description({
        "app_id": "Calluna", "title": "Control", "namespace": "calluna",
    })

    assert description == ("Real description", "en")


def test_store_description_prefers_localized_short_text() -> None:
    data = {"pages": [{
        "type": "productHome",
        "data": {"about": {
            "shortDescription": "Краткое описание",
            "description": "Первый абзац\n\nВторой абзац",
        }},
    }]}

    assert EGSAPI._parse_store_description(data) == "Краткое описание"


def test_store_description_limits_fallback_to_first_paragraph() -> None:
    data = {"pages": [{
        "type": "productHome",
        "data": {"about": {"description": "Первый абзац\n\nВторой абзац"}},
    }]}

    assert EGSAPI._parse_store_description(data) == "Первый абзац"


def test_store_description_handles_missing_product_pages(
    monkeypatch: MonkeyPatch,
) -> None:
    api = EGSAPI()
    response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"pages": None},
    )
    monkeypatch.setattr(api, "_get_product_slug", lambda _namespace, _title: "game")
    monkeypatch.setattr("portprotonqt.egs_api.requests.get", lambda *args, **kwargs: response)

    description = api._get_store_description({
        "app_id": "Game", "title": "Game", "namespace": "game",
    })

    assert description == ("", "")


def test_content_languages_follow_epic_locale_conventions(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("portprotonqt.localization.get_metadata_language", lambda: "pt")
    monkeypatch.setattr("portprotonqt.localization.get_system_locale", lambda: "pt_BR")

    assert get_store_content_languages() == ("pt-BR", "pt", "en-US")

    monkeypatch.setattr("portprotonqt.localization.get_metadata_language", lambda: "zh")
    monkeypatch.setattr("portprotonqt.localization.get_system_locale", lambda: "zh_Hant_TW")

    assert get_store_content_languages() == ("zh-TW", "zh", "en-US")


def test_extract_auth_code_accepts_legendary_response() -> None:
    response = '{"authorizationCode":"epic-authorization-code"}'

    assert EGSAPI.extract_auth_code(response) == "epic-authorization-code"
    assert EGSAPI.extract_auth_code("direct-code") == "direct-code"
    assert EGSAPI.extract_auth_code("https://example.com") == ""


def test_description_enrichment_reports_library_progress(
    monkeypatch: MonkeyPatch,
) -> None:
    api = EGSAPI()
    games = [
        {"app_id": "one", "title": "One", "namespace": "one"},
        {"app_id": "two", "title": "Two", "namespace": "two"},
    ]
    progress = []
    monkeypatch.setattr(api, "load_library", lambda: [])
    monkeypatch.setattr(api, "_get_store_description", lambda _game: ("About", "en-US"))

    api._enrich_descriptions(games, lambda completed, total: progress.append(
        (completed, total)
    ))

    assert progress == [(1, 2), (2, 2)]


def test_get_launch_target_uses_legendary_install_record(tmp_path: Path) -> None:
    api = EGSAPI()
    api.config_dir = tmp_path / "legendary"
    game_dir = tmp_path / "game"
    executable = game_dir / "Binaries/Game.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    api.config_dir.mkdir()
    (api.config_dir / "installed.json").write_bytes(orjson.dumps({
        "TestGame": {
            "install_path": str(game_dir),
            "executable": "Binaries\\Game.exe",
        },
    }))

    assert api.get_launch_target("TestGame") == str(executable)


def test_parse_download_sizes_reads_legendary_info() -> None:
    output = orjson.dumps({
        "manifest": {"download_size": 1024},
        "install": {"install_size": 2048},
    })

    assert EGSAPI.parse_download_sizes(output) == (1024, 2048)


def test_parse_download_sizes_uses_manifest_disk_size() -> None:
    output = orjson.dumps({"manifest": {"download_size": 1024, "disk_size": 4096}})

    assert EGSAPI.parse_download_sizes(output) == (1024, 4096)


def test_zero_cached_install_size_is_refetched(tmp_path: Path) -> None:
    api = EGSAPI()
    api.sizes_path = tmp_path / "sizes.json"
    api.sizes_path.write_bytes(orjson.dumps({"Game": [1024, 0]}))

    assert api.get_cached_download_sizes("Game") is None


def test_authenticate_passes_epic_code(tmp_path: Path, monkeypatch) -> None:
    api = EGSAPI()
    api.config_dir = tmp_path / "legendary"
    api.user_path = api.config_dir / "user.json"
    monkeypatch.setattr(api, "ensure_legendary", lambda: "/bin/legendary")
    monkeypatch.setattr(api, "build_command", lambda args: ["legendary", *args])

    def run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        api.config_dir.mkdir(parents=True)
        api.user_path.write_text("{}", encoding="utf-8")
        assert command == ["legendary", "auth", "--code", "epic-code"]
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("portprotonqt.egs_api.subprocess.run", run)

    assert api.authenticate("epic-code") == (True, "")
