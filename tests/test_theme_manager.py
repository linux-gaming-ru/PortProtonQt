"""Tests for theme_manager: AST injection, parent resolution, and ThemeWrapper."""
import ast
import types
from pathlib import Path
from typing import Any
import orjson
import pytest
from PySide6.QtSvg import QSvgRenderer

from portprotonqt.theme_manager import (
    DMS_COLOR_ROLES,
    ThemeManager,
    ThemeWrapper,
    _get_parent_theme_name,
    _inject_ast_constants,
    _inject_parent_theme_constants,
    _is_valid_theme_name,
    _read_theme_parent_name,
    load_dms_palette,
)


def test_theme_wrapper_loads_screenshots_lazily(monkeypatch) -> None:
    loaded_themes = []
    monkeypatch.setattr(
        "portprotonqt.theme_manager.load_theme_screenshots",
        lambda theme_name: loaded_themes.append(theme_name) or [],
    )
    wrapper = ThemeWrapper(types.ModuleType("preview_theme"))

    assert loaded_themes == []
    assert wrapper.screenshots == []
    assert wrapper.screenshots == []
    assert loaded_themes == ["preview_theme"]


def test_theme_manager_reuses_loaded_theme(monkeypatch) -> None:
    manager = ThemeManager()
    manager.current_theme_name = "previous"
    manager.current_theme_module = types.SimpleNamespace()
    manager._theme_module_cache = {}
    loaded_themes = []
    monkeypatch.setattr(
        "portprotonqt.theme_manager.load_theme",
        lambda name: loaded_themes.append(name) or types.SimpleNamespace(),
    )
    monkeypatch.setattr("portprotonqt.theme_manager.load_theme_fonts", lambda name: None)
    monkeypatch.setattr("portprotonqt.config.ui.UIConfig.set_theme", lambda self, name: None)
    monkeypatch.setattr("portprotonqt.sound_manager.SoundManager.set_sounds_dirs", lambda self, dirs: None)

    first = manager.apply_theme("first")
    manager.apply_theme("second")
    repeated = manager.apply_theme("first")

    assert repeated is first
    assert loaded_themes == ["first", "second"]


def test_invalidate_theme_discards_module_and_icon_caches(monkeypatch) -> None:
    icon_cache = {
        "play_custom_False_1.0_None": object(),
        "play_other_False_1.0_None": object(),
    }
    icon_dirs_cache = {"custom": {}, "other": {}}
    monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", icon_cache)
    monkeypatch.setattr("portprotonqt.theme_manager._icon_dirs_cache", icon_dirs_cache)
    manager = ThemeManager()
    manager._theme_module_cache = {"custom": object(), "other": object()}
    manager.current_theme_name = "custom"
    manager.current_theme_module = object()

    manager.invalidate_theme("custom")

    assert manager._theme_module_cache.keys() == {"other"}
    assert icon_dirs_cache.keys() == {"other"}
    assert icon_cache.keys() == {"play_other_False_1.0_None"}
    assert manager.current_theme_name is None
    assert manager.current_theme_module is None


# === load_dms_palette ===


class TestLoadDmsPalette:
    def _palette(self) -> dict:
        dark = dict.fromkeys(DMS_COLOR_ROLES, "#131318")
        light = dict.fromkeys(DMS_COLOR_ROLES, "#fcf8ff")
        dark["primary"] = "#c6bfff"
        return {"colors": {"dark": dark, "light": light}}

    def _write_palette(self, tmp_path: Path, palette: object) -> Path:
        colors_dir = tmp_path / "DankMaterialShell"
        colors_dir.mkdir()
        colors_file = colors_dir / "dms-colors.json"
        colors_file.write_bytes(orjson.dumps(palette))
        return colors_file

    def test_loads_variant_and_ignores_unknown_roles(
        self, tmp_path: Path, monkeypatch,
    ):
        palette = self._palette()
        palette["colors"]["dark"]["unknown"] = "#ffffff"
        self._write_palette(tmp_path, palette)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        colors = load_dms_palette("dark")

        assert colors["background"] == "#131318"
        assert colors["primary"] == "#c6bfff"
        assert "unknown" not in colors

    def test_invalid_document_falls_back(self, tmp_path: Path, monkeypatch):
        self._write_palette(tmp_path, [])
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        assert load_dms_palette("light") == {}

    def test_rejects_invalid_color_value(self, tmp_path: Path, monkeypatch):
        palette = self._palette()
        palette["colors"]["dark"]["primary"] = "url(evil)"
        self._write_palette(tmp_path, palette)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        assert load_dms_palette("dark") == {}

    def test_rejects_group_writable_file(self, tmp_path: Path, monkeypatch):
        colors_file = self._write_palette(tmp_path, self._palette())
        colors_file.chmod(0o664)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        assert load_dms_palette("dark") == {}

    def test_rejects_symlink(self, tmp_path: Path, monkeypatch):
        colors_dir = tmp_path / "DankMaterialShell"
        colors_dir.mkdir()
        target = tmp_path / "palette.json"
        target.write_bytes(orjson.dumps(self._palette()))
        (colors_dir / "dms-colors.json").symlink_to(target)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        assert load_dms_palette("dark") == {}


# === _is_valid_theme_name ===


class TestIsValidThemeName:
    def test_valid_names(self):
        assert _is_valid_theme_name("standart")
        assert _is_valid_theme_name("classic")
        assert _is_valid_theme_name("my-theme")
        assert _is_valid_theme_name("a")

    def test_empty_string(self):
        assert not _is_valid_theme_name("")

    def test_too_long(self):
        assert not _is_valid_theme_name("x" * 51)

    def test_abs_path(self):
        assert not _is_valid_theme_name("/etc/passwd")

    def test_path_separator(self):
        assert not _is_valid_theme_name("a/b")

    def test_dotdot(self):
        assert not _is_valid_theme_name("..")

    def test_single_dot(self):
        assert not _is_valid_theme_name(".")

    def test_non_string(self):
        assert not _is_valid_theme_name(123)  # type: ignore[arg-type]
        assert not _is_valid_theme_name(None)  # type: ignore[arg-type]


def test_remove_custom_theme_only_removes_user_theme(tmp_path: Path, monkeypatch: Any) -> None:
    custom_dir = tmp_path / "custom"
    builtin_dir = tmp_path / "builtin"
    custom_theme = custom_dir / "removable"
    builtin_theme = builtin_dir / "protected"
    custom_theme.mkdir(parents=True)
    builtin_theme.mkdir(parents=True)
    monkeypatch.setattr(
        "portprotonqt.theme_manager.THEMES_DIRS",
        [str(custom_dir), str(builtin_dir)],
    )
    manager = ThemeManager()

    assert manager.remove_custom_theme("removable")
    assert not custom_theme.exists()
    assert not manager.remove_custom_theme("protected")
    assert builtin_theme.exists()


# === _get_parent_theme_name ===


class TestGetParentThemeName:
    def test_standart_returns_none(self):
        assert _get_parent_theme_name("standart") is None

    def test_default_parent_is_standart(self):
        assert _get_parent_theme_name("classic") == "standart"

    def test_explicit_parent(self):
        assert _get_parent_theme_name("classic-light", "standart-light") == "standart-light"

    def test_self_parent_falls_back(self):
        result = _get_parent_theme_name("classic", "classic")
        assert result == "standart"

    def test_invalid_parent_falls_back(self):
        result = _get_parent_theme_name("classic", "/etc/passwd")
        assert result == "standart"


# === _inject_ast_constants ===


class TestInjectAstConstants:
    def _make_module(self) -> types.ModuleType:
        mod = types.ModuleType("test_module")
        return mod

    def test_injects_string_constants(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('font_family = "Play"\nfont_size = "16px"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.font_family == "Play"
        assert mod.font_size == "16px"

    def test_injects_numeric_constants(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('width = 150\nheight_ratio = 2.25\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.width == 150
        assert mod.height_ratio == 2.25

    def test_injects_tuple_constants(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('margins = (10, 7, 15, 10)\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.margins == (10, 7, 15, 10)

    def test_injects_list_constants(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('items = [1, 2, 3]\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.items == [1, 2, 3]

    def test_injects_dict_constants(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('config = {"key": "value", "count": 42}\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.config == {"key": "value", "count": 42}

    def test_injects_nested_dict(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('data = [{"position": 0, "color": "#fff"}]\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.data == [{"position": 0, "color": "#fff"}]

    def test_skips_private_names(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('_private = "hidden"\npublic = "visible"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert not hasattr(mod, "_private")
        assert mod.public == "visible"

    def test_skips_callables(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('def foo(): pass\nresult = "ok"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert not hasattr(mod, "foo")
        assert mod.result == "ok"

    def test_skips_fstring_assignments(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('border_none = "0px solid"\nSTYLE = f"border: {border_none};"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.border_none == "0px solid"
        assert not hasattr(mod, "STYLE")

    def test_does_not_overwrite_existing(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('color = "new"\n')
        mod = self._make_module()
        mod.__dict__["color"] = "original"
        _inject_ast_constants(str(src), mod)
        assert mod.color == "original"

    def test_dict_with_variable_refs_skipped(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('accent = "#409EFF"\nanim = {"fill_color": accent}\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.accent == "#409EFF"
        assert not hasattr(mod, "anim")

    def test_syntax_error_does_not_crash(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('this is not valid python {{{\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)

    def test_missing_file_does_not_crash(self):
        mod = self._make_module()
        _inject_ast_constants("/nonexistent/file.py", mod)

    def test_skips_import_statements(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('import os\nfrom pathlib import Path\nvalue = "ok"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert mod.value == "ok"

    def test_skips_class_definitions(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('class MyClass: pass\nvalue = "ok"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert not hasattr(mod, "MyClass")
        assert mod.value == "ok"

    def test_skips_function_definitions(self, tmp_path: Path):
        src = tmp_path / "test.py"
        src.write_text('def helper(): return 1\nvalue = "ok"\n')
        mod = self._make_module()
        _inject_ast_constants(str(src), mod)
        assert not hasattr(mod, "helper")
        assert mod.value == "ok"


# === _inject_parent_theme_constants ===


class TestInjectParentThemeConstants:
    def _make_child_theme(self, tmp_path: Path, name: str, parent: str, styles_content: str):
        """Create a child theme folder with styles.py."""
        theme_dir = tmp_path / "themes" / name
        theme_dir.mkdir(parents=True)
        (theme_dir / "styles.py").write_text(
            f'THEME_INHERITS = "{parent}"\n{styles_content}'
        )
        return theme_dir

    def _make_parent_theme(self, tmp_path: Path, name: str, styles_content: str):
        """Create a parent theme folder with styles.py (no styles/ subdir)."""
        theme_dir = tmp_path / "themes" / name
        theme_dir.mkdir(parents=True)
        (theme_dir / "styles.py").write_text(styles_content)
        return theme_dir

    def _patch_dirs(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "portprotonqt.theme_manager.THEMES_DIRS",
            [str(tmp_path / "themes_custom"), str(tmp_path / "themes")],
        )

    def test_inherits_simple_constants_from_styles(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "parent1",
            'border_none = "0px solid"\ncolor_transparent = "transparent"\n'
        )
        self._make_child_theme(tmp_path, "child1", "parent1", 'my_color = "red"\n')

        mod = types.ModuleType("child1")
        mod.__dict__["my_color"] = "red"
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["border_none"] == "0px solid"
        assert mod.__dict__["color_transparent"] == "transparent"
        assert mod.__dict__["my_color"] == "red"

    def test_inherits_dict_constants(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "parent2",
            'CARD = {"width": 200, "height": 300}\n'
        )
        self._make_child_theme(tmp_path, "child2", "parent2", '')

        mod = types.ModuleType("child2")
        _inject_parent_theme_constants(mod, "")

        assert mod.CARD == {"width": 200, "height": 300}

    def test_constants_py_used_when_exists(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        theme_dir = tmp_path / "themes" / "parent3"
        styles_dir = theme_dir / "styles"
        styles_dir.mkdir(parents=True)
        (styles_dir / "constants.py").write_text('from_const = "constants"\n')
        (theme_dir / "styles.py").write_text('from_styles = "styles"\n')
        self._make_child_theme(tmp_path, "child3", "parent3", '')

        mod = types.ModuleType("child3")
        _inject_parent_theme_constants(mod, "")

        assert mod.from_const == "constants"
        assert mod.from_styles == "styles"

    def test_does_not_inject_submodule_styles(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        theme_dir = tmp_path / "themes" / "parent4"
        styles_dir = theme_dir / "styles"
        styles_dir.mkdir(parents=True)
        (styles_dir / "constants.py").write_text('const_val = "from_constants"\n')
        (styles_dir / "base.py").write_text('base_val = "from_base"\n')
        (theme_dir / "styles.py").write_text('')
        self._make_child_theme(tmp_path, "child4", "parent4", '')

        mod = types.ModuleType("child4")
        _inject_parent_theme_constants(mod, "")

        assert mod.const_val == "from_constants"
        assert not hasattr(mod, "base_val")

    def test_no_parent_does_nothing(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_child_theme(tmp_path, "orphan", "standart", '')

        mod = types.ModuleType("orphan")
        _inject_parent_theme_constants(mod, "")
        assert not hasattr(mod, "any_key")

    def test_inherits_through_two_levels(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "grandparent",
            'grand_color = "#aaa"\ngrand_size = 42\n'
        )
        self._make_parent_theme(
            tmp_path, "parent_mid",
            'THEME_INHERITS = "grandparent"\nparent_color = "#bbb"\n'
        )
        self._make_child_theme(tmp_path, "child_deep", "parent_mid", '')

        mod = types.ModuleType("child_deep")
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["grand_color"] == "#aaa"
        assert mod.__dict__["grand_size"] == 42
        assert mod.__dict__["parent_color"] == "#bbb"

    def test_inherits_through_three_levels(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "root_theme",
            'root_val = "from_root"\n'
        )
        self._make_parent_theme(
            tmp_path, "mid_theme",
            'THEME_INHERITS = "root_theme"\nmid_val = "from_mid"\n'
        )
        self._make_parent_theme(
            tmp_path, "inner_theme",
            'THEME_INHERITS = "mid_theme"\ninner_val = "from_inner"\n'
        )
        self._make_child_theme(tmp_path, "leaf_theme", "inner_theme", '')

        mod = types.ModuleType("leaf_theme")
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["root_val"] == "from_root"
        assert mod.__dict__["mid_val"] == "from_mid"
        assert mod.__dict__["inner_val"] == "from_inner"

    def test_constants_py_used_across_chain(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        gp_dir = tmp_path / "themes" / "gp_chain"
        gp_styles = gp_dir / "styles"
        gp_styles.mkdir(parents=True)
        (gp_styles / "constants.py").write_text('gp_const = "from_gp_constants"\n')
        (gp_dir / "styles.py").write_text('gp_style = "from_gp_styles"\n')

        self._make_parent_theme(
            tmp_path, "mid_chain",
            'THEME_INHERITS = "gp_chain"\nmid_val = "ok"\n'
        )
        self._make_child_theme(tmp_path, "leaf_chain", "mid_chain", '')

        mod = types.ModuleType("leaf_chain")
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["gp_const"] == "from_gp_constants"
        assert mod.__dict__["gp_style"] == "from_gp_styles"
        assert mod.__dict__["mid_val"] == "ok"

    def test_cycle_does_not_loop_forever(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "theme_a",
            'THEME_INHERITS = "theme_b"\na_val = 1\n'
        )
        self._make_parent_theme(
            tmp_path, "theme_b",
            'THEME_INHERITS = "theme_a"\nb_val = 2\n'
        )
        self._make_child_theme(tmp_path, "theme_c", "theme_a", '')

        mod = types.ModuleType("theme_c")
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["a_val"] == 1
        assert mod.__dict__["b_val"] == 2

    def test_child_overrides_not_lost(self, tmp_path: Path, monkeypatch):
        self._patch_dirs(monkeypatch, tmp_path)
        self._make_parent_theme(
            tmp_path, "parent_override",
            'shared_key = "parent_value"\nparent_only = "yes"\n'
        )
        self._make_child_theme(
            tmp_path, "child_override", "parent_override",
            'shared_key = "child_value"\n'
        )

        mod = types.ModuleType("child_override")
        mod.__dict__["shared_key"] = "child_value"
        _inject_parent_theme_constants(mod, "")

        assert mod.__dict__["shared_key"] == "child_value"
        assert mod.__dict__["parent_only"] == "yes"


# === _read_theme_parent_name ===


class TestReadThemeParentName:
    def test_reads_theme_inherits(self, tmp_path: Path, monkeypatch):
        theme_dir = tmp_path / "themes" / "mytheme"
        theme_dir.mkdir(parents=True)
        (theme_dir / "styles.py").write_text('THEME_INHERITS = "standart"\n')

        monkeypatch.setattr(
            "portprotonqt.theme_manager._find_theme_folder",
            lambda name: str(theme_dir) if name == "mytheme" else None,
        )
        assert _read_theme_parent_name("mytheme") == "standart"

    def test_no_theme_inherits_returns_standart(self, tmp_path: Path, monkeypatch):
        theme_dir = tmp_path / "themes" / "bare"
        theme_dir.mkdir(parents=True)
        (theme_dir / "styles.py").write_text('color = "red"\n')

        monkeypatch.setattr(
            "portprotonqt.theme_manager._find_theme_folder",
            lambda name: str(theme_dir) if name == "bare" else None,
        )
        assert _read_theme_parent_name("bare") == "standart"

    def test_missing_folder_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.theme_manager._find_theme_folder",
            lambda name: None,
        )
        assert _read_theme_parent_name("nonexistent") == "standart"


# === Colored SVG icons ===


class TestColoredSvgIcons:
    def test_get_icon_uses_icon_color_constant(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", {})
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text('<svg><path fill="#fff"/></svg>', encoding="utf-8")
        monkeypatch.setattr(
            "portprotonqt.theme_manager.build_icon_cache",
            lambda _theme_name: {"icon": str(icon_path)},
        )
        manager = ThemeManager()
        manager.current_theme_name = "test-theme"
        theme_module = types.ModuleType("test-theme")
        theme_module.__dict__["ICON_COLORS"] = {"icon": "#123456"}
        manager.current_theme_module = theme_module

        colored_path = manager.get_icon("icon", "test-theme", as_path=True)

        assert isinstance(colored_path, str)
        assert colored_path != str(icon_path)
        assert 'fill="#123456"' in Path(colored_path).read_text(encoding="utf-8")

    def test_get_icon_without_icon_color_keeps_original_path(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", {})
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text('<svg><path fill="#fff"/></svg>', encoding="utf-8")
        monkeypatch.setattr(
            "portprotonqt.theme_manager.build_icon_cache",
            lambda _theme_name: {"icon": str(icon_path)},
        )
        manager = ThemeManager()
        manager.current_theme_name = "test-theme"
        theme_module = types.ModuleType("test-theme")
        theme_module.__dict__["ICON_COLORS"] = {}
        manager.current_theme_module = theme_module

        icon_result = manager.get_icon("icon", "test-theme", as_path=True)

        assert icon_result == str(icon_path)

    def test_creates_colored_svg_cache_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path)
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text('<svg><path fill="currentColor"/></svg>', encoding="utf-8")

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), "#123456")

        assert colored_path is not None
        assert colored_path != str(icon_path)
        assert 'fill="#123456"' in Path(colored_path).read_text(encoding="utf-8")

    def test_colored_namespaced_svg_is_valid_for_qt(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path)
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><path fill="#fff"/></svg>',
            encoding="utf-8",
        )

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), "#123456")

        assert colored_path is not None
        assert QSvgRenderer(colored_path).isValid()

    def test_recolors_svg_paint_attributes(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path)
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text(
            '<svg><path fill="#fff" stroke="rgb(1, 2, 3)" color="red"/></svg>',
            encoding="utf-8",
        )

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), "#123456")
        assert colored_path is not None
        content = Path(colored_path).read_text(encoding="utf-8")

        assert 'fill="#123456"' in content
        assert 'stroke="#123456"' in content
        assert 'color="#123456"' in content

    def test_recolors_svg_style_paints(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path)
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text(
            '<svg><style>path{fill:#fff;stroke:blue}</style>'
            '<path style="fill: #fff; stroke: rgb(1,2,3);"/></svg>',
            encoding="utf-8",
        )

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), "#123456")
        assert colored_path is not None
        content = Path(colored_path).read_text(encoding="utf-8")

        assert "fill:#123456" in content or "fill: #123456" in content
        assert "stroke:#123456" in content or "stroke: #123456" in content

    def test_keeps_non_color_svg_paints(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path)
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text(
            '<svg><path fill="none" stroke="url(#g)" style="color: transparent"/></svg>',
            encoding="utf-8",
        )

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), "#123456")
        assert colored_path is not None
        content = Path(colored_path).read_text(encoding="utf-8")

        assert 'fill="none"' in content
        assert 'stroke="url(#g)"' in content
        assert "transparent" in content

    def test_unsafe_color_falls_back_to_original_svg(self, tmp_path: Path):
        icon_path = tmp_path / "icon.svg"
        icon_path.write_text('<svg><path fill="currentColor"/></svg>', encoding="utf-8")

        colored_path = ThemeManager().get_colored_icon_path(str(icon_path), 'red";<script>')

        assert colored_path == str(icon_path)


# === Integration: classic/classic-light themes have required styles ===


class TestThemeStylesIntegrity:
    """Verify theme files define required styles and use f-strings."""

    _themes_dir = Path(__file__).parent.parent / "portprotonqt" / "themes"

    def _read_theme(self, name: str) -> str:
        path = self._themes_dir / name / "styles.py"
        if not path.exists():
            pytest.skip(f"Theme '{name}' not found")
        return path.read_text(encoding="utf-8")

    def test_classic_has_required_styles(self):
        content = self._read_theme("classic")
        required_styles = [
            "NAV_BUTTON_STYLE",
            "COMBOBOX_STYLE",
            "SETTINGS_TABLE_COMBOBOX_STYLE",
            "LINE_EDIT_STYLE",
            "ADDGAME_INPUT_STYLE",
            "TAB_STYLE",
            "HINT_BAR_STYLE",
            "QGROUP_BOX_STYLE",
            "WINETRICKS_TABBLE_STYLE",
            "SETTINGS_TITLE_STYLE",
            "ACTION_BUTTON_STYLE",
            "ACTION_BUTTON_ACTIVE_STYLE",
            "LIBRARY_WIDGET_STYLE",
            "GAME_CARD_WINDOW_STYLE",
            "PLAY_BUTTON_STYLE",
            "ADDGAME_BACK_BUTTON_STYLE",
            "LIBRARY_CONTROLS_BUTTON_STYLE",
            "SEARCH_EDIT_STYLE",
            "THEME_STORE_SCROLL_STYLE",
            "THEME_STORE_CARD_STYLE",
            "THEME_STORE_CARD_TITLE_STYLE",
            "THEME_STORE_CARD_META_STYLE",
            "THEME_STORE_DETAIL_TITLE_STYLE",
            "THEME_STORE_DESCRIPTION_STYLE",
            "THEME_STORE_PREVIEW_STYLE",
        ]
        for style_name in required_styles:
            assert f"{style_name}" in content, f"classic/styles.py missing {style_name}"

    def test_classic_light_has_required_styles(self):
        content = self._read_theme("classic-light")
        required_styles = [
            "NAV_BUTTON_STYLE",
            "COMBOBOX_STYLE",
            "LINE_EDIT_STYLE",
            "ADDGAME_INPUT_STYLE",
            "TAB_STYLE",
            "QGROUP_BOX_STYLE",
            "WINETRICKS_TABBLE_STYLE",
            "SETTINGS_TITLE_STYLE",
            "ACTION_BUTTON_STYLE",
            "ACTION_BUTTON_ACTIVE_STYLE",
        ]
        for style_name in required_styles:
            assert f"{style_name}" in content, f"classic-light/styles.py missing {style_name}"

    def test_classic_light_wine_table_keeps_classic_compact_rows(self):
        content = self._read_theme("classic-light")

        assert "QTableWidget::item {{" in content
        assert "padding: 3px;" in content
        assert "height: 32px;" in content

    def test_classic_game_card_animation_has_glow_keys(self):
        content = self._read_theme("classic")
        assert '"glow_base_alpha"' in content
        assert '"glow_pulse_alpha"' in content

    def test_classic_light_game_card_animation_has_glow_keys(self):
        content = self._read_theme("classic-light")
        assert '"glow_base_alpha"' in content
        assert '"glow_pulse_alpha"' in content

    def test_classic_styles_use_fstrings_not_hardcoded(self):
        """Classic QSS style constants should be f-strings, not plain strings
        (except HINT_BAR_STYLE and %-formatted styles for icon paths)."""
        content = self._read_theme("classic")
        tree = ast.parse(content)

        plain_style_count = 0
        fstring_style_count = 0
        percent_style_count = 0
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not target.id.endswith("_STYLE"):
                    continue
                if isinstance(node.value, ast.JoinedStr):
                    fstring_style_count += 1
                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Mod):
                    percent_style_count += 1
                elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    plain_style_count += 1

        assert fstring_style_count > 10, "Classic should use f-strings for most styles"
        assert plain_style_count <= 1, f"Classic has {plain_style_count} plain string styles"
        assert percent_style_count <= 3, f"Classic has {percent_style_count} %-formatted styles"

    def test_classic_light_styles_use_fstrings_not_hardcoded(self):
        """Classic-light QSS style constants should be f-strings, not plain strings
        (except %-formatted styles for icon paths)."""
        content = self._read_theme("classic-light")
        tree = ast.parse(content)

        plain_style_count = 0
        fstring_style_count = 0
        percent_style_count = 0
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not target.id.endswith("_STYLE"):
                    continue
                if isinstance(node.value, ast.JoinedStr):
                    fstring_style_count += 1
                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Mod):
                    percent_style_count += 1
                elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    plain_style_count += 1

        assert fstring_style_count > 10, "Classic-light should use f-strings for most styles"
        assert plain_style_count == 0, f"Classic-light has {plain_style_count} plain string styles"
        assert percent_style_count <= 3, f"Classic-light has {percent_style_count} %-formatted styles"

    def test_classic_theme_inherits_standart(self):
        content = self._read_theme("classic")
        assert 'THEME_INHERITS = "standart"' in content

    def test_classic_light_theme_inherits_standart_light(self):
        content = self._read_theme("classic-light")
        assert 'THEME_INHERITS = "standart-light"' in content

    def test_standart_defines_shared_visual_constants(self):
        styles_dir = self._themes_dir / "standart" / "styles"
        constants = (styles_dir / "constants.py").read_text(encoding="utf-8")
        base = (styles_dir / "base.py").read_text(encoding="utf-8")

        assert "color_preloader" in constants
        assert "TRANSPARENT_BACKGROUND_STYLE" in base

    def test_standart_light_defines_shared_visual_constants(self):
        content = self._read_theme("standart-light")

        assert "color_preloader" in content
        assert "TRANSPARENT_BACKGROUND_STYLE" in content


# === Integration: all theme .py files are valid Python ===


class TestMixThemeConstants:
    """Verify color-only themes get constants from the full inheritance chain."""

    @pytest.fixture()
    def stub_themes(self, tmp_path, monkeypatch):
        from portprotonqt.theme_manager import THEMES_DIRS
        base_dir = tmp_path / "themes"
        base_dir.mkdir()
        monkeypatch.setattr(
            "portprotonqt.theme_manager.THEMES_DIRS",
            [str(base_dir), str(THEMES_DIRS[1])],
        )
        return base_dir

    @staticmethod
    def _make_root(base_dir, name="root"):
        d = base_dir / name
        d.mkdir()
        (d / "styles.py").write_text(
            'color_accent = "#409EFF"\ncolor_bg = "#282a33"\n',
            encoding="utf-8",
        )
        styles = d / "styles"
        styles.mkdir()
        (styles / "__init__.py").write_text("", encoding="utf-8")
        (styles / "constants.py").write_text(
            'color_accent = "#409EFF"\ncolor_bg = "#282a33"\n',
            encoding="utf-8",
        )

    @staticmethod
    def _make_child(base_dir, name, inherits):
        d = base_dir / name
        d.mkdir()
        (d / "styles.py").write_text(
            f'THEME_INHERITS = "{inherits}"\n',
            encoding="utf-8",
        )

    def test_child_gets_color_accent_from_root_chain(self, stub_themes):
        self._make_root(stub_themes, "root")
        self._make_child(stub_themes, "mid", "root")
        self._make_child(stub_themes, "leaf", "mid")
        mod = types.ModuleType("leaf")
        mod.__dict__["__name__"] = "leaf"
        _inject_parent_theme_constants(
            mod, str(stub_themes / "leaf" / "styles.py"),
        )
        assert "color_accent" in mod.__dict__, (
            "leaf theme must inherit color_accent through mid -> root chain"
        )

    def test_mid_gets_color_accent_from_root(self, stub_themes):
        self._make_root(stub_themes, "root")
        self._make_child(stub_themes, "mid", "root")
        mod = types.ModuleType("mid")
        mod.__dict__["__name__"] = "mid"
        _inject_parent_theme_constants(
            mod, str(stub_themes / "mid" / "styles.py"),
        )
        assert "color_accent" in mod.__dict__

    def test_child_direct_gets_color_accent_from_parent(self, stub_themes):
        self._make_root(stub_themes, "root")
        self._make_child(stub_themes, "child", "root")
        mod = types.ModuleType("child")
        mod.__dict__["__name__"] = "child"
        _inject_parent_theme_constants(
            mod, str(stub_themes / "child" / "styles.py"),
        )
        assert "color_accent" in mod.__dict__


class TestGeneratedStylesUseChildColors:
    """Verify that color-only themes get QSS styles re-computed with their palette."""

    _CONSTANTS_PY = """\
font_family = "Test"
font_size_normal = "16px"
font_size_small = "11px"
border_none = "0px solid"
border_thin = "1px solid"
border_medium = "2px solid"
border_radius_small = "10px"
border_radius_large = "15px"
color_accent = "#409EFF"
color_bg = "#282a33"
color_surface = "#3f424d"
color_text = "#ffffff"
color_border_subtle = "rgba(255, 255, 255, 0.01)"
"""

    _BASE_PY = """\
from .constants import *

MAIN_WINDOW_STYLE = f"QWidget {{ background: {color_bg}; color: {color_text}; }}"
ACTION_BUTTON_STYLE = f"QPushButton {{ background: {color_accent}; border-radius: {border_radius_small}; }}"
TAB_STYLE = f"QTabBar {{ background: {color_surface}; }}"
NAV_BUTTON_STYLE = f"QPushButton {{ color: {color_text}; }}"
GAME_CARD_WINDOW_STYLE = f"QFrame {{ background: {color_surface}; border: {border_medium} {color_border_subtle}; }}"
CHECKBOX_STYLE = f"QCheckBox {{ color: {color_text}; }}"
CONTAINER_STYLE = f"QWidget {{ background: {color_bg}; }}"
"""

    @pytest.fixture()
    def stub_themes(self, tmp_path, monkeypatch):
        from portprotonqt.theme_manager import THEMES_DIRS
        base_dir = tmp_path / "themes"
        base_dir.mkdir()
        monkeypatch.setattr(
            "portprotonqt.theme_manager.THEMES_DIRS",
            [str(base_dir), str(THEMES_DIRS[1])],
        )

        parent_dir = base_dir / "parent_theme"
        parent_dir.mkdir()
        (parent_dir / "styles.py").write_text(
            'color_accent = "#409EFF"\ncolor_bg = "#282a33"\n',
            encoding="utf-8",
        )
        styles_dir = parent_dir / "styles"
        styles_dir.mkdir()
        (styles_dir / "__init__.py").write_text("", encoding="utf-8")
        (styles_dir / "constants.py").write_text(
            self._CONSTANTS_PY, encoding="utf-8",
        )
        (styles_dir / "base.py").write_text(
            self._BASE_PY, encoding="utf-8",
        )
        return base_dir

    def test_child_qss_uses_child_colors(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        child_dir = stub_themes / "child_theme"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "parent_theme"\n'
            'color_accent = "#FF0000"\n'
            'color_bg = "#00FF00"\n',
            encoding="utf-8",
        )
        child = load_theme("child_theme")
        parent = load_theme("parent_theme")
        assert child.MAIN_WINDOW_STYLE != parent.MAIN_WINDOW_STYLE
        assert "#00FF00" in child.MAIN_WINDOW_STYLE
        assert "#409EFF" not in child.MAIN_WINDOW_STYLE

    def test_child_theme_styles_differ_from_parent(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        child_dir = stub_themes / "child_theme"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "parent_theme"\n'
            'color_accent = "#FF0000"\n'
            'color_bg = "#00FF00"\n',
            encoding="utf-8",
        )
        child = load_theme("child_theme")
        parent = load_theme("parent_theme")
        for style_name in ("ACTION_BUTTON_STYLE", "TAB_STYLE",
                           "NAV_BUTTON_STYLE", "GAME_CARD_WINDOW_STYLE"):
            child_style = getattr(child, style_name)
            parent_style = getattr(parent, style_name)
            assert child_style != parent_style, (
                f"{style_name} not re-computed with child colors"
            )

    def test_child_qss_uses_child_colors_from_parent_styles_file(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        parent_dir = stub_themes / "parent_file_theme"
        parent_dir.mkdir()
        (parent_dir / "styles.py").write_text(
            'color_bg = "#111111"\n'
            'color_text = "#ffffff"\n'
            'MAIN_WINDOW_STYLE = f"QWidget {{ background: {color_bg}; color: {color_text}; }}"\n',
            encoding="utf-8",
        )
        child_dir = stub_themes / "child_file_theme"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "parent_file_theme"\n'
            'color_bg = "#fbf1c7"\n'
            'color_text = "#3c3836"\n',
            encoding="utf-8",
        )
        child = load_theme("child_file_theme")
        assert "#fbf1c7" in child.MAIN_WINDOW_STYLE
        assert "#3c3836" in child.MAIN_WINDOW_STYLE
        assert "#111111" not in child.MAIN_WINDOW_STYLE


class TestThemeInheritanceChain:
    """Verify inheritance works correctly through all chain depths.

    Uses stub themes in tmp_path to avoid dependency on real themes.
    """

    _CONSTANTS_PY = """\
font_family = "Test"
font_size_normal = "16px"
font_size_small = "11px"
border_none = "0px solid"
border_thin = "1px solid"
border_medium = "2px solid"
border_radius_small = "10px"
border_radius_large = "15px"
color_accent = "#409EFF"
color_bg = "#282a33"
color_surface = "#3f424d"
color_text = "#ffffff"
color_border_subtle = "rgba(255, 255, 255, 0.01)"
"""

    _BASE_PY = """\
from .constants import *

MAIN_WINDOW_STYLE = f"QWidget {{ background: {color_bg}; color: {color_text}; }}"
ACTION_BUTTON_STYLE = f"QPushButton {{ background: {color_accent}; border-radius: {border_radius_small}; }}"
TAB_STYLE = f"QTabBar {{ background: {color_surface}; }}"
NAV_BUTTON_STYLE = f"QPushButton {{ color: {color_text}; }}"
LIBRARY_WIDGET_STYLE = f"QWidget {{ background: {color_bg}; }}"
GAME_CARD_WINDOW_STYLE = f"QFrame {{ background: {color_surface}; border: {border_medium} {color_border_subtle}; }}"
CHECKBOX_STYLE = f"QCheckBox {{ color: {color_text}; }}"
CONTAINER_STYLE = f"QWidget {{ background: {color_bg}; }}"
DETAILS_WIDGET_STYLE = f"QFrame {{ background: {color_surface}; }}"
"""

    @pytest.fixture()
    def stub_themes(self, tmp_path, monkeypatch):
        from portprotonqt.theme_manager import THEMES_DIRS
        base_dir = tmp_path / "themes"
        base_dir.mkdir()
        monkeypatch.setattr(
            "portprotonqt.theme_manager.THEMES_DIRS",
            [str(base_dir), str(THEMES_DIRS[1])],
        )
        return base_dir

    @staticmethod
    def _make_parent(base_dir, name="grandparent"):
        d = base_dir / name
        d.mkdir()
        (d / "styles.py").write_text(
            'color_accent = "#409EFF"\ncolor_bg = "#282a33"\n',
            encoding="utf-8",
        )
        styles = d / "styles"
        styles.mkdir()
        (styles / "__init__.py").write_text("", encoding="utf-8")
        (styles / "constants.py").write_text(
            TestGeneratedStylesUseChildColors._CONSTANTS_PY,
            encoding="utf-8",
        )
        (styles / "base.py").write_text(
            TestThemeInheritanceChain._BASE_PY,
            encoding="utf-8",
        )

    @staticmethod
    def _make_child(base_dir, name, inherits, overrides=""):
        d = base_dir / name
        d.mkdir()
        content = f'THEME_INHERITS = "{inherits}"\n{overrides}'
        (d / "styles.py").write_text(content, encoding="utf-8")

    def test_child_inherits_from_parent_not_grandparent(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "grandparent")
        self._make_child(stub_themes, "parent", "grandparent")
        self._make_child(stub_themes, "child", "parent")
        child = load_theme("child")
        parent = load_theme("parent")
        assert child.color_accent == parent.color_accent
        for style_name in ("ACTION_BUTTON_STYLE", "NAV_BUTTON_STYLE",
                           "TAB_STYLE", "LIBRARY_WIDGET_STYLE"):
            assert getattr(child, style_name) == getattr(parent, style_name)

    def test_child_inherits_from_parent_chain(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "grandparent")
        self._make_child(stub_themes, "parent", "grandparent")
        self._make_child(stub_themes, "child", "parent")
        child = load_theme("child")
        parent = load_theme("parent")
        grandparent = load_theme("grandparent")
        assert hasattr(child, "MAIN_WINDOW_STYLE")
        assert child.MAIN_WINDOW_STYLE == parent.MAIN_WINDOW_STYLE
        assert grandparent.MAIN_WINDOW_STYLE != ""

    def test_child_with_overrides_applies_own_colors(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "base")
        self._make_child(
            stub_themes, "custom", "base",
            'color_accent = "#FF0000"\ncolor_bg = "#00FF00"\n',
        )
        custom = load_theme("custom")
        assert hasattr(custom, "GAME_CARD_WINDOW_STYLE")
        assert hasattr(custom, "DETAILS_WIDGET_STYLE")

    def test_child_with_overrides_differs_from_grandparent(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "base")
        self._make_child(
            stub_themes, "custom", "base",
            'color_accent = "#FF0000"\ncolor_bg = "#00FF00"\n',
        )
        custom = load_theme("custom")
        base = load_theme("base")
        assert custom.GAME_CARD_WINDOW_STYLE != base.GAME_CARD_WINDOW_STYLE

    def test_middle_theme_inherits_from_parent(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "base")
        self._make_child(stub_themes, "mid", "base")
        self._make_child(stub_themes, "leaf", "mid")
        mid = load_theme("mid")
        assert hasattr(mid, "MAIN_WINDOW_STYLE")
        assert hasattr(mid, "CHECKBOX_STYLE")

    def test_deepest_child_gets_grandparent_styles(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "base")
        self._make_child(stub_themes, "mid", "base")
        self._make_child(stub_themes, "leaf", "mid")
        leaf = load_theme("leaf")
        assert hasattr(leaf, "MAIN_WINDOW_STYLE")
        assert hasattr(leaf, "CHECKBOX_STYLE")
        assert hasattr(leaf, "CONTAINER_STYLE")

    def test_leaf_generates_styles_from_root(self, stub_themes):
        from portprotonqt.theme_manager import load_theme
        self._make_parent(stub_themes, "base")
        self._make_child(stub_themes, "mid", "base")
        self._make_child(stub_themes, "leaf", "mid")
        leaf = load_theme("leaf")
        assert hasattr(leaf, "MAIN_WINDOW_STYLE")
        assert hasattr(leaf, "ACTION_BUTTON_STYLE")
        base = load_theme("base")
        assert leaf.MAIN_WINDOW_STYLE != base.MAIN_WINDOW_STYLE


class TestThemeFilesParse:
    """All themes must be valid, parseable Python files."""

    _themes_dir = Path(__file__).parent.parent / "portprotonqt" / "themes"

    @pytest.mark.parametrize(
        "theme_file",
        sorted(p for p in _themes_dir.glob("*/styles.py")),
    )
    def test_styles_py_parses(self, theme_file: Path):
        source = theme_file.read_text(encoding="utf-8")
        ast.parse(source, filename=str(theme_file))

    @pytest.mark.parametrize(
        "constants_file",
        sorted(_themes_dir.glob("*/styles/constants.py")),
    )
    def test_constants_py_parses(self, constants_file: Path):
        source = constants_file.read_text(encoding="utf-8")
        ast.parse(source, filename=str(constants_file))


# === Recursive theme loading (d5fedd8 regression) ===


class TestRecursiveThemeLoading:
    """load_theme must not recurse when styles.py calls get_icon during exec_module."""

    @pytest.fixture()
    def stub_themes(self, tmp_path, monkeypatch):
        from portprotonqt.theme_manager import THEMES_DIRS
        base_dir = tmp_path / "themes"
        base_dir.mkdir()
        monkeypatch.setattr(
            "portprotonqt.theme_manager.THEMES_DIRS",
            [str(base_dir), str(THEMES_DIRS[1])],
        )
        return base_dir

    def test_theme_wrapper_parent_load_during_loading(self, stub_themes, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", {})

        parent_dir = stub_themes / "load_parent"
        parent_dir.mkdir()
        (parent_dir / "styles.py").write_text(
            'PARENT_VAL = "from_parent"\n',
            encoding="utf-8",
        )

        child_dir = stub_themes / "load_child"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "load_parent"\nCHILD_VAL = "from_child"\n',
            encoding="utf-8",
        )

        from portprotonqt.theme_manager import load_theme
        result = load_theme("load_child")
        assert getattr(result, "CHILD_VAL", None) == "from_child"
        assert getattr(result, "PARENT_VAL", None) == "from_parent"

    def test_icon_color_applies_after_recursive_load(self, stub_themes, tmp_path, monkeypatch):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", {})
        monkeypatch.setattr("portprotonqt.theme_manager._icon_dirs_cache", {})

        theme_dir = stub_themes / "color_theme"
        theme_dir.mkdir()
        images_dir = theme_dir / "images"
        images_dir.mkdir()
        icon_path = images_dir / "down.svg"
        icon_path.write_text('<svg><path fill="#fff"/></svg>', encoding="utf-8")
        (theme_dir / "styles.py").write_text(
            "from portprotonqt.theme_manager import ThemeManager\n"
            'ICON_COLORS = {"down": "#123456"}\n'
            "theme_manager = ThemeManager()\n"
            'ICON_PATH = theme_manager.get_icon("down", "color_theme", as_path=True)\n',
            encoding="utf-8",
        )

        from portprotonqt.theme_manager import load_theme
        theme = load_theme("color_theme")
        colored_path = getattr(theme, "ICON_PATH", None)

        assert isinstance(colored_path, str)
        assert colored_path != str(icon_path)
        assert 'fill="#123456"' in Path(colored_path).read_text(encoding="utf-8")

    def test_missing_child_icon_colors_do_not_load_parent_recursively(
        self, stub_themes, tmp_path, monkeypatch,
    ):
        monkeypatch.setattr("portprotonqt.theme_manager.CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr("portprotonqt.theme_manager._icon_cache", {})
        monkeypatch.setattr("portprotonqt.theme_manager._icon_dirs_cache", {})

        parent_dir = stub_themes / "parent_icons"
        parent_dir.mkdir()
        images_dir = parent_dir / "images"
        images_dir.mkdir()
        icon_path = images_dir / "down.svg"
        icon_path.write_text('<svg><path fill="#fff"/></svg>', encoding="utf-8")
        (parent_dir / "styles.py").write_text(
            "from portprotonqt.theme_manager import ThemeManager\n"
            "theme_manager = ThemeManager()\n"
            'PARENT_ICON = theme_manager.get_icon("down", "child_icons", as_path=True)\n',
            encoding="utf-8",
        )

        child_dir = stub_themes / "child_icons"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "parent_icons"\nCHILD_VAL = "from_child"\n',
            encoding="utf-8",
        )

        from portprotonqt.theme_manager import ThemeManager, load_theme
        child = load_theme("child_icons")
        manager = ThemeManager()
        manager.current_theme_name = "child_icons"
        manager.current_theme_module = child

        assert getattr(child, "PARENT_ICON", None) == str(icon_path)

    def test_icon_colors_are_not_inherited(self, stub_themes):
        parent_dir = stub_themes / "parent_colors"
        parent_dir.mkdir()
        (parent_dir / "styles.py").write_text(
            'ICON_COLORS = {"down": "#123456"}\nPARENT_VAL = "from_parent"\n',
            encoding="utf-8",
        )

        child_dir = stub_themes / "child_colors"
        child_dir.mkdir()
        (child_dir / "styles.py").write_text(
            'THEME_INHERITS = "parent_colors"\nCHILD_VAL = "from_child"\n',
            encoding="utf-8",
        )

        from portprotonqt.theme_manager import load_theme
        child = load_theme("child_colors")

        assert getattr(child, "ICON_COLORS", {}) == {}
        assert getattr(child, "PARENT_VAL", None) == "from_parent"
