"""Tests for config/base.py — BaseConfig read/write cycle."""
from pathlib import Path
import runpy

import pytest

from portprotonqt.config.base import BaseConfig
from portprotonqt.config.game import GameConfig
from portprotonqt.config.ui import UIConfig
import portprotonqt.localization as localization


@pytest.fixture(autouse=True)
def isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_file = tmp_path / "PortProtonQt.conf"
    monkeypatch.setattr("portprotonqt.config.base.CONFIG_FILE", config_file)
    monkeypatch.setattr("portprotonqt.config.base._config_cache", {})
    monkeypatch.setattr("portprotonqt.config.base._config_mtime", {})
    return config_file


class TestBaseConfigRead:
    def test_read_creates_file_if_missing(self, tmp_path: Path):
        config_file = tmp_path / "new.conf"
        cfg = BaseConfig(config_file=config_file)
        cp = cfg._read_config()
        assert config_file.exists()
        assert cp is not None

    def test_read_returns_none_on_os_error(self):
        cfg = BaseConfig(config_file=Path("/proc/invalid"))
        assert cfg._read_config() is None

    def test_read_caches_result(self, tmp_path: Path):
        config_file = tmp_path / "cached.conf"
        config_file.write_text("[Section]\nkey = value\n", encoding="utf-8")
        cfg = BaseConfig(config_file=config_file)
        cp1 = cfg._read_config()
        cp2 = cfg._read_config()
        assert cp1 is cp2

    def test_cache_invalidated_on_save(self, tmp_path: Path):
        config_file = tmp_path / "cache_test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Test"
        cfg._save_value("key", "val1", "str")
        cp1 = cfg._read_config()
        cfg._save_value("key", "val2", "str")
        cp2 = cfg._read_config()
        assert cp1 is not cp2


class TestBaseConfigReadWrite:
    def test_save_and_get_str(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        cfg._save_value("theme", "standart", "str")
        assert cfg._get_str("theme", "default") == "standart"

    def test_save_and_get_int(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        cfg._save_value("width", 250, "int")
        assert cfg._get_int("width", 100) == 250

    def test_save_and_get_bool(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        cfg._save_value("flag", True, "bool")
        assert cfg._get_bool("flag", False) is True

    def test_get_returns_default_when_missing(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        assert cfg._get_str("missing", "fallback") == "fallback"
        assert cfg._get_int("missing", 42) == 42
        assert cfg._get_bool("missing", False) is False

    def test_get_returns_default_on_corrupt_value(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        config_file.write_text("[Section]\nnum = notanumber\n", encoding="utf-8")
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        assert cfg._get_int("num", 99) == 99

    def test_save_value_validates_int(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        from portprotonqt.config.validators import ValidationError
        with pytest.raises(ValidationError):
            cfg._save_value("num", "not_int", "int")

    def test_save_value_validates_bool(self, tmp_path: Path):
        config_file = tmp_path / "test.conf"
        cfg = BaseConfig(config_file=config_file)
        cfg._section = "Section"
        from portprotonqt.config.validators import ValidationError
        with pytest.raises(ValidationError):
            cfg._save_value("flag", "yes", "bool")


def test_game_config_saves_steam_account(tmp_path: Path):
    config = GameConfig(config_file=tmp_path / "test.conf")

    assert config.get_steam_account_id() == "auto"
    config.set_steam_account_id("76561198012003723")
    assert config.get_steam_account_id() == "76561198012003723"


def test_crash_reports_config_defaults_to_enabled(tmp_path: Path):
    config = UIConfig(config_file=tmp_path / "test.conf")

    assert config.get_crash_reports_enabled() is True
    config.set_crash_reports_enabled(False)
    assert config.get_crash_reports_enabled() is False


def test_control_hints_are_visible_by_default(tmp_path: Path):
    config = UIConfig(config_file=tmp_path / "test.conf")

    assert config.get_hide_control_hints() is False
    config.set_hide_control_hints(True)
    assert config.get_hide_control_hints() is True


def test_force_english_is_disabled_by_default(tmp_path: Path):
    config = UIConfig(config_file=tmp_path / "test.conf")

    assert config.get_force_english() is False
    config.set_force_english(True)
    assert config.get_force_english() is True


def test_translation_can_switch_to_english_without_restart(
    monkeypatch: pytest.MonkeyPatch,
):
    force_english = False
    monkeypatch.setattr(localization.translate, "gettext", lambda message: f"ru:{message}")
    monkeypatch.setattr(
        "portprotonqt.config.ui_config.get_force_english",
        lambda: force_english,
    )
    monkeypatch.setattr(localization, "_translation_sources", {})

    translated = localization._("Settings")
    force_english = True

    assert localization.retranslate(translated) == "Settings"


class TestUpdateAppVersion:
    def test_first_save_returns_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("portprotonqt.config.base.CONFIG_FILE", tmp_path / "test.conf")
        monkeypatch.setattr("portprotonqt.config.base._config_cache", {})
        monkeypatch.setattr("portprotonqt.config.base._config_mtime", {})
        from portprotonqt.config.base import update_app_version
        assert update_app_version("1.0.0") is True

    def test_same_version_returns_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config_file = tmp_path / "test.conf"
        monkeypatch.setattr("portprotonqt.config.base.CONFIG_FILE", config_file)
        monkeypatch.setattr("portprotonqt.config.base._config_cache", {})
        monkeypatch.setattr("portprotonqt.config.base._config_mtime", {})
        from portprotonqt.config.base import update_app_version
        update_app_version("1.0.0")
        assert update_app_version("1.0.0") is False

    def test_different_version_returns_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config_file = tmp_path / "test.conf"
        monkeypatch.setattr("portprotonqt.config.base.CONFIG_FILE", config_file)
        monkeypatch.setattr("portprotonqt.config.base._config_cache", {})
        monkeypatch.setattr("portprotonqt.config.base._config_mtime", {})
        from portprotonqt.config.base import update_app_version
        update_app_version("1.0.0")
        assert update_app_version("1.1.0") is True


def test_cache_path_does_not_follow_temporary_xdg_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    source = Path(__file__).parents[1] / "portprotonqt" / "config" / "base.py"
    for launch in ("first", "second"):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / launch))
        paths = runpy.run_path(str(source))
        assert paths["CACHE_DIR"] == tmp_path / "data" / "PortProtonQt" / "cache"
