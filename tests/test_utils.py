"""Tests for steam_api/utils.py — normalize_name, search, VDF loading."""
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from portprotonqt.search_utils import SearchOptimizer, build_search_items, search_index
from portprotonqt.steam_api.utils import (
    APPINFO_ENTRY_METADATA_SIZE,
    APPINFO_MAGIC_V41,
    STEAM_ID64_INDIVIDUAL_BASE,
    normalize_name,
    is_valid_candidate,
    filter_candidates,
    remove_duplicates,
    safe_vdf_load,
    convert_steam_id,
    decode_text,
    get_steam_launch_commands,
    get_steam_compatibilitytools_dir,
    get_steam_compat_tool,
    get_last_steam_user,
    get_local_steam_cover,
    get_steam_installed_games,
    _iter_existing_steam_data_dirs,
    _is_steam_proton_dir,
    _is_portrait_image,
)
from portprotonqt.steam_api.cache import (
    build_index,
    search_app,
    build_weanticheatyet_index,
    search_anticheat_entry,
    search_anticheat_status,
    build_ppdb_index,
    search_ppdb_entry,
)


@pytest.fixture(autouse=True)
def use_automatic_steam_account(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "portprotonqt.steam_api.utils.game_config.get_steam_account_id",
        lambda: "auto",
    )


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("Ter", "Terraria"),
        ("TERR", "Terraria"),
        ("террария", "Террария"),
        ("Wi", "The Witcher 3: Wild Hunt"),
        ("witch", "The Witcher 3: Wild Hunt"),
        ("ведьмак", "Ведьмак 3: Дикая Охота"),
        ("Deep", "Deep Rock Galactic"),
        ("rock", "Deep Rock Galactic"),
        ("галактические", "Галактические шахтёры"),
        ("Cyber", "Cyberpunk 2077"),
        ("киберпанк", "Киберпанк 2077"),
        ("Red", "Red Dead Redemption 2"),
        ("dead", "Red Dead Redemption 2"),
        ("Dota", "Dota 2"),
        ("Portal", "Portal 2"),
        ("портал", "Портал 2"),
        ("Half", "Half-Life 2"),
        ("life", "Half-Life 2"),
    ],
)
def test_search_index_finds_game_names(
    query: str,
    expected_name: str,
) -> None:
    games = [
        ("Кириллица", "Тестовая игра"),
        ("Terraria", ""),
        ("Террария", ""),
        ("The Witcher 3: Wild Hunt", ""),
        ("Ведьмак 3: Дикая Охота", ""),
        ("Deep Rock Galactic", ""),
        ("Галактические шахтёры", ""),
        ("Cyberpunk 2077", ""),
        ("Киберпанк 2077", ""),
        ("Red Dead Redemption 2", "История банды Датча ван дер Линде"),
        ("Dota 2", ""),
        ("Portal 2", ""),
        ("Портал 2", ""),
        ("Half-Life 2", "Приключения Гордона Фримена"),
    ]
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items(games, lambda item: item[0]))

    result_names = [game[0] for game in search_index(optimizer, query)]

    assert result_names == [expected_name]


def test_search_index_searches_single_character_in_names() -> None:
    games = [("Кириллица", ""), ("Terraria", "Копайте и сражайтесь")]
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items(games, lambda item: item[0]))

    assert search_index(optimizer, "к") == [games[0]]


@pytest.mark.parametrize("query", ["к", "я", "x", "z"])
def test_search_index_does_not_fuzzy_match_single_character(query: str) -> None:
    game = ("Terraria", "Копайте и сражайтесь в мире Террарии")
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items([game], lambda item: item[0]))

    assert search_index(optimizer, query) == []


def test_search_index_ignores_descriptions() -> None:
    game = ("Terraria", "Копайте и сражайтесь в мире Террарии")
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items([game], lambda item: item[0]))

    assert search_index(optimizer, "копайте") == []


def test_search_index_finds_all_names_containing_query() -> None:
    games = [("DOOM 64", ""), ("Akalabeth: World of Doom", "")]
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items(games, lambda item: item[0]))

    assert search_index(optimizer, "doom") == games


def test_search_index_keeps_same_name_from_different_sources() -> None:
    games = [("Control", "egs"), ("Control", "portproton")]
    optimizer = SearchOptimizer()
    optimizer.build_indices(build_search_items(games, lambda item: item[0]))

    assert search_index(optimizer, "control") == games


def test_is_portrait_image_rejects_oversized_png_metadata(
    tmp_path: Path,
) -> None:
    cover = tmp_path / "logo.png"
    cover.touch()
    with patch(
        "portprotonqt.steam_api.utils.Image.open",
        side_effect=ValueError("Decompressed data too large"),
    ):
        assert not _is_portrait_image(cover)


def _write_appinfo(path: Path, apps: list[tuple[int, str, str]]) -> None:
    strings = ["appinfo", "common", "type", "oslist"]
    entries = bytearray()
    for appid, app_type, oslist in apps:
        blob = (
            b"\x00" + struct.pack("<I", 0)
            + b"\x00" + struct.pack("<I", 1)
            + b"\x01" + struct.pack("<I", 2) + app_type.encode() + b"\x00"
            + b"\x01" + struct.pack("<I", 3) + oslist.encode() + b"\x00"
            + b"\x08\x08\x08"
        )
        entry_data = bytes(APPINFO_ENTRY_METADATA_SIZE) + blob
        entries.extend(struct.pack("<II", appid, len(entry_data)) + entry_data)
    table_offset = 16 + len(entries) + 4
    string_table = b"\x00".join(value.encode() for value in strings) + b"\x00"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        struct.pack("<IIq", APPINFO_MAGIC_V41, 1, table_offset)
        + entries + struct.pack("<I", 0)
        + struct.pack("<I", len(strings)) + string_table
    )


class TestNormalizeName:
    def test_lowercase(self):
        assert normalize_name("Counter-Strike 2") == "counter strike 2"

    def test_trademark_symbol(self):
        assert normalize_name("Cyberpunk 2077™") == "cyberpunk 2077"

    def test_registered_symbol(self):
        assert normalize_name("Game®") == "game"

    def test_colon_replaced_with_space(self):
        assert normalize_name("Call of Duty: Modern Warfare") == "call of duty modern warfare"

    def test_comma_replaced_with_space(self):
        assert normalize_name("Halo, mcc") == "halo mcc"

    def test_hyphen_replaced_with_space(self):
        assert normalize_name("Grand Theft Auto V") == "grand theft auto v"

    def test_multiple_spaces_collapsed(self):
        assert normalize_name("Game    Title") == "game title"

    def test_suffix_bin_removed(self):
        assert normalize_name("gamebin") == "game"

    def test_suffix_app_removed(self):
        assert normalize_name("gameapp") == "game"

    def test_suffix_bin_with_space(self):
        assert normalize_name("game bin") == "game"

    def test_keyword_ultimate_removed(self):
        assert normalize_name("Red Dead Redemption 2 Ultimate Edition") == "red dead redemption 2"

    def test_keyword_edition_removed(self):
        assert normalize_name("Cyberpunk 2077 Edition") == "cyberpunk 2077"

    def test_keyword_definitive_removed(self):
        assert normalize_name("Zelda Definitive") == "zelda"

    def test_keyword_complete_removed(self):
        assert normalize_name("Halo Complete") == "halo"

    def test_keyword_remastered_removed(self):
        assert normalize_name("Dark Souls Remastered") == "dark souls"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_only_symbols(self):
        assert normalize_name("™®") == ""

    def test_preserves_normal_words(self):
        assert normalize_name("The Witcher 3") == "the witcher 3"


class TestIsValidCandidate:
    def test_valid_candidate(self):
        assert is_valid_candidate("Cyberpunk 2077") is True

    def test_rejects_game(self):
        assert is_valid_candidate("game") is False

    def test_rejects_win32(self):
        assert is_valid_candidate("GameWin32") is False

    def test_rejects_win64(self):
        assert is_valid_candidate("GameWin64") is False

    def test_rejects_gamelauncher(self):
        assert is_valid_candidate("GameLauncher") is False

    def test_empty_string(self):
        assert is_valid_candidate("") is True

    def test_whitespace_only(self):
        assert is_valid_candidate("   ") is True


class TestFilterCandidates:
    def test_filters_invalid(self):
        candidates = ["Cyberpunk 2077", "game", "GameWin32", "Dota 2"]
        result = filter_candidates(candidates)
        assert "Cyberpunk 2077" in result
        assert "Dota 2" in result
        assert "game" not in result
        assert "GameWin32" not in result

    def test_filters_empty_strings(self):
        candidates = ["Valid Game", "", "  ", "Another"]
        result = filter_candidates(candidates)
        assert "" not in result
        assert "  " not in result

    def test_empty_list(self):
        assert filter_candidates([]) == []


class TestRemoveDuplicates:
    def test_preserves_order(self):
        assert remove_duplicates(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_empty_list(self):
        assert remove_duplicates([]) == []


class TestSafeVdfLoad:
    def test_load_text_vdf(self, tmp_path: Path):
        vdf_file = tmp_path / "test.vdf"
        vdf_file.write_text('"root"\n{\n    "key" "value"\n}\n')
        result = safe_vdf_load(str(vdf_file))
        assert result["root"]["key"] == "value"

    def test_load_empty_file(self, tmp_path: Path):
        vdf_file = tmp_path / "empty.vdf"
        vdf_file.write_bytes(b"")
        result = safe_vdf_load(str(vdf_file))
        assert result == {}

    def test_load_nonexistent_file(self):
        result = safe_vdf_load("/nonexistent/path/file.vdf")
        assert result == {}

    def test_load_binary_vdf(self, tmp_path: Path):
        vdf_file = tmp_path / "binary.vdf"
        vdf_file.write_bytes(b"\x00binary data")
        result = safe_vdf_load(str(vdf_file))
        assert isinstance(result, dict)


class TestBuildIndex:
    def test_builds_index_by_normalized_name(self, sample_steam_apps):
        index = build_index(sample_steam_apps)
        assert "counter strike 2" in index
        assert index["counter strike 2"]["appid"] == 730

    def test_empty_list(self):
        assert build_index([]) == {}

    def test_skips_empty_normalized_name(self):
        apps = [{"appid": 1, "name": "Game", "normalized_name": ""}]
        assert build_index(apps) == {}


class TestSearchApp:
    def test_exact_match(self, sample_steam_apps):
        index = build_index(sample_steam_apps)
        result = search_app("counter strike 2", index)
        assert result is not None
        assert result["appid"] == 730

    def test_partial_match_high_ratio(self, sample_steam_apps):
        index = build_index(sample_steam_apps)
        result = search_app("team fortress", index)
        assert result is not None
        assert result["appid"] == 440

    def test_no_match(self, sample_steam_apps):
        index = build_index(sample_steam_apps)
        result = search_app("totally unknown game xyz", index)
        assert result is None

    def test_empty_index(self):
        assert search_app("anything", {}) is None


class TestBuildWeanticheatyetIndex:
    def test_builds_index(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        assert "fortnite" in index
        assert index["fortnite"]["status"] == "Broken"

    def test_empty_list(self):
        assert build_weanticheatyet_index([]) == {}

    def test_skips_empty_normalized_name(self):
        apps = [{"normalized_name": "", "status": "ok", "slug": "x"}]
        assert build_weanticheatyet_index(apps) == {}


class TestSearchAnticheatEntry:
    def test_exact_match(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        result = search_anticheat_entry("fortnite", index)
        assert result is not None
        assert result["status"] == "Broken"

    def test_no_match(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        result = search_anticheat_entry("unknown game", index)
        assert result is None

    def test_empty_candidate(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        assert search_anticheat_entry("", index) is None


class TestSearchAnticheatStatus:
    def test_returns_status(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        assert search_anticheat_status("fortnite", index) == "Broken"

    def test_returns_empty_string_on_miss(self, sample_anticheat_apps):
        index = build_weanticheatyet_index(sample_anticheat_apps)
        assert search_anticheat_status("unknown", index) == ""


class TestBuildPpdbIndex:
    def test_builds_index(self, sample_ppdb_apps):
        index = build_ppdb_index(sample_ppdb_apps)
        assert "мир кораблей" in index
        assert index["мир кораблей"]["id"] == 70547

    def test_empty_list(self):
        assert build_ppdb_index([]) == {}

    def test_skips_empty_normalized_name(self):
        apps = [{"id": 1, "normalized_name": "", "overall_rating": "platinum"}]
        assert build_ppdb_index(apps) == {}


class TestSearchPpdbEntry:
    def test_exact_match(self, sample_ppdb_apps):
        index = build_ppdb_index(sample_ppdb_apps)
        result = search_ppdb_entry("Мир кораблей", index)
        assert result is not None
        assert result["overall_rating"] == "silver"

    def test_no_match(self, sample_ppdb_apps):
        index = build_ppdb_index(sample_ppdb_apps)
        result = search_ppdb_entry("unknown game", index)
        assert result is None

    def test_empty_candidate(self, sample_ppdb_apps):
        index = build_ppdb_index(sample_ppdb_apps)
        assert search_ppdb_entry("", index) is None


class TestConvertSteamId:
    def test_positive(self):
        assert convert_steam_id(12345) == 12345

    def test_negative_to_unsigned(self):
        assert convert_steam_id(-1) == 0xFFFFFFFF

    def test_zero(self):
        assert convert_steam_id(0) == 0


def test_get_last_steam_user_falls_back_to_autologin(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "AccountName" "x"\n'
        '        "AutoLogin" "1"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    assert get_last_steam_user(tmp_path) == {"SteamID": 76561198012003723}


def test_get_last_steam_user_prefers_autologin_to_most_recent(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "MostRecent" "1"\n'
        '    }\n'
        '    "76561198012003724"\n'
        '    {\n'
        '        "AutoLogin" "1"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    assert get_last_steam_user(tmp_path) == {"SteamID": 76561198012003724}


def test_get_last_steam_user_supports_legacy_most_recent(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "MostRecent" "1"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    assert get_last_steam_user(tmp_path) == {"SteamID": 76561198012003723}


def test_get_last_steam_user_uses_latest_timestamp(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "AutoLogin" "1"\n'
        '        "Timestamp" "1755173073"\n'
        '    }\n'
        '    "76561198012003724"\n'
        '    {\n'
        '        "AutoLogin" "0"\n'
        '        "Timestamp" "1784901561"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    assert get_last_steam_user(tmp_path) == {"SteamID": 76561198012003724}


def test_get_last_steam_user_uses_configured_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "Timestamp" "1755173073"\n'
        '    }\n'
        '    "76561198012003724"\n'
        '    {\n'
        '        "Timestamp" "1784901561"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "portprotonqt.steam_api.utils.game_config.get_steam_account_id",
        lambda: "76561198012003723",
    )

    assert get_last_steam_user(tmp_path) == {"SteamID": 76561198012003723}


def test_get_last_steam_user_ignores_allow_autologin(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "loginusers.vdf").write_text(
        '"users"\n{\n'
        '    "76561198012003723"\n'
        '    {\n'
        '        "AllowAutoLogin" "1"\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    assert get_last_steam_user(tmp_path) is None


def test_get_last_steam_user_falls_back_to_only_userdata(tmp_path: Path):
    account_id = 51737995
    localconfig = (
        tmp_path / "userdata" / str(account_id) / "config/localconfig.vdf"
    )
    localconfig.parent.mkdir(parents=True)
    localconfig.write_text('"UserLocalConfigStore"\n{\n}\n', encoding="utf-8")

    assert get_last_steam_user(tmp_path) == {
        "SteamID": STEAM_ID64_INDIVIDUAL_BASE + account_id
    }


def test_get_last_steam_user_rejects_multiple_userdata(tmp_path: Path):
    for account_id in (51737995, 51737996):
        localconfig = (
            tmp_path / "userdata" / str(account_id) / "config/localconfig.vdf"
        )
        localconfig.parent.mkdir(parents=True)
        localconfig.touch()

    assert get_last_steam_user(tmp_path) is None


class TestDecodeText:
    def test_html_entities(self):
        assert decode_text("&amp;") == "&"
        assert decode_text("&lt;b&gt;") == "<b>"

    def test_plain_text(self):
        assert decode_text("hello world") == "hello world"


class TestIterExistingSteamDataDirs:
    def test_returns_existing_dirs(self, tmp_path: Path):
        steam_dir = tmp_path / "steam"
        steam_dir.mkdir()
        with patch("portprotonqt.steam_api.utils.STEAM_DATA_DIRS", (str(steam_dir),)):
            result = _iter_existing_steam_data_dirs()
            assert len(result) == 1

    def test_skips_nonexistent(self):
        with patch("portprotonqt.steam_api.utils.STEAM_DATA_DIRS", ("/nonexistent/path",)):
            result = _iter_existing_steam_data_dirs()
            assert len(result) == 0

    def test_deduplicates_resolved_symlinks(self, tmp_path: Path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "link"
        link_dir.symlink_to(real_dir)
        with patch("portprotonqt.steam_api.utils.STEAM_DATA_DIRS", (str(real_dir), str(link_dir))):
            result = _iter_existing_steam_data_dirs()
            assert len(result) == 1


class TestIsSteamProtonDir:
    def test_with_files_bin_wine(self, tmp_path: Path):
        proton_dir = tmp_path / "Proton"
        proton_dir.mkdir()
        wine_file = proton_dir / "files" / "bin" / "wine"
        wine_file.parent.mkdir(parents=True)
        wine_file.touch()
        assert _is_steam_proton_dir(proton_dir) is True

    def test_with_dist_bin_wine(self, tmp_path: Path):
        proton_dir = tmp_path / "Proton"
        proton_dir.mkdir()
        wine_file = proton_dir / "dist" / "bin" / "wine"
        wine_file.parent.mkdir(parents=True)
        wine_file.touch()
        assert _is_steam_proton_dir(proton_dir) is True

    def test_not_proton_dir(self, tmp_path: Path):
        proton_dir = tmp_path / "NotProton"
        proton_dir.mkdir()
        assert _is_steam_proton_dir(proton_dir) is False

    def test_not_a_dir(self, tmp_path: Path):
        assert _is_steam_proton_dir(tmp_path / "nope") is False


class TestGetSteamLaunchCommands:
    def test_no_steam_home(self):
        with patch("portprotonqt.steam_api.utils._iter_existing_steam_data_dirs", return_value=[]):
            result = get_steam_launch_commands("730")
            assert result == []

    def test_flatpak_steam(self, tmp_path: Path):
        steam_dir = tmp_path / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam"
        steam_dir.mkdir(parents=True)
        with (
            patch("portprotonqt.steam_api.utils._iter_existing_steam_data_dirs", return_value=[steam_dir]),
            patch("shutil.which", return_value="/usr/bin/flatpak"),
        ):
            result = get_steam_launch_commands("730")
            assert len(result) == 1
            assert "flatpak" in result[0][0]
            assert "730" in result[0]


class TestGetSteamCompatTool:
    def test_no_steam_home(self):
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=None):
            assert get_steam_compat_tool(730) is None

    def test_no_config_vdf(self, tmp_path: Path):
        steam_dir = tmp_path / "steam"
        steam_dir.mkdir()
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=steam_dir):
            assert get_steam_compat_tool(730) is None


class TestGetLocalSteamCover:
    def test_no_steam_home(self):
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=None):
            assert get_local_steam_cover(730) == ""

    def test_empty_appid(self):
        assert get_local_steam_cover("") == ""

    def test_no_librarycache(self, tmp_path: Path):
        steam_dir = tmp_path / "steam"
        steam_dir.mkdir()
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=steam_dir):
            assert get_local_steam_cover(730) == ""


class TestGetSteamInstalledGames:
    def test_no_steam_home(self):
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=None):
            assert get_steam_installed_games() == []

    def test_keeps_games_and_related_apps_without_soundtracks_or_tools(self, tmp_path: Path):
        steam_dir = tmp_path / "Steam"
        steamapps = steam_dir / "steamapps"
        steamapps.mkdir(parents=True)
        apps = (
            (10, "Windows Game", "game", "windows"),
            (20, "Game Soundtrack", "music", "windows"),
            (30, "Linux Game", "game", "windows,linux"),
            (40, "Game Demo", "demo", "windows"),
            (50, "Game Mod", "mod", "windows"),
            (60, "Application", "application", "windows"),
            (70, "Dedicated Server", "tool", "windows"),
            (80, "Game Beta", "beta", "windows"),
        )
        excluded_types = (
            "invalid", "deprected", "dlc", "guide", "driver", "config",
            "hardware", "franchise", "video", "plugin", "series", "comic",
            "shortcut", "depotonly",
        )
        apps += tuple(
            (appid, app_type, app_type, "windows")
            for appid, app_type in enumerate(excluded_types, start=100)
        )
        for appid, name, _, _ in apps:
            (steamapps / f"appmanifest_{appid}.acf").write_text(
                f'"AppState"\n{{\n"appid" "{appid}"\n"name" "{name}"\n}}\n',
                encoding="utf-8",
            )
        _write_appinfo(
            steam_dir / "appcache" / "appinfo.vdf",
            [(appid, app_type, oslist) for appid, _, app_type, oslist in apps],
        )

        with (
            patch("portprotonqt.steam_api.utils.get_steam_home", return_value=steam_dir),
            patch("portprotonqt.steam_api.utils.get_steam_libs", return_value={steam_dir}),
            patch("portprotonqt.steam_api.utils.get_playtime_data", return_value={}),
        ):
            games = get_steam_installed_games()

        assert {game[1] for game in games} == {10, 30, 40, 50, 60, 80}

    def test_keeps_games_when_appinfo_is_unreadable(self, tmp_path: Path):
        steam_dir = tmp_path / "Steam"
        steamapps = steam_dir / "steamapps"
        steamapps.mkdir(parents=True)
        (steamapps / "appmanifest_10.acf").write_text(
            '"AppState"\n{\n"appid" "10"\n"name" "Test Game"\n}\n',
            encoding="utf-8",
        )
        appinfo = steam_dir / "appcache" / "appinfo.vdf"
        appinfo.parent.mkdir()
        appinfo.write_bytes(b"invalid")

        with (
            patch("portprotonqt.steam_api.utils.get_steam_home", return_value=steam_dir),
            patch("portprotonqt.steam_api.utils.get_steam_libs", return_value={steam_dir}),
            patch("portprotonqt.steam_api.utils.get_playtime_data", return_value={}),
        ):
            games = get_steam_installed_games()

        assert [game[1] for game in games] == [10]


class TestGetSteamCompatibilitytoolsDir:
    def test_no_steam_home(self):
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=None):
            assert get_steam_compatibilitytools_dir() is None

    def test_creates_dir(self, tmp_path: Path):
        steam_dir = tmp_path / "steam"
        steam_dir.mkdir()
        with patch("portprotonqt.steam_api.utils.get_steam_home", return_value=steam_dir):
            result = get_steam_compatibilitytools_dir()
            assert result is not None
            assert result.exists()


class TestIsPortraitImage:
    def test_nonexistent_file(self):
        assert _is_portrait_image(Path("/nonexistent/file.png")) is False

    def test_invalid_image(self, tmp_path: Path):
        bad_file = tmp_path / "bad.png"
        bad_file.write_bytes(b"not an image")
        assert _is_portrait_image(bad_file) is False
