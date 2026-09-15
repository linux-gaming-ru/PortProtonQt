"""Tests for theme_security: allowlist-based AST security checker."""
from pathlib import Path

import pytest

from portprotonqt.theme_security import (
    ThemeSecurityChecker,
    check_theme_directory_safety,
    check_theme_safety,
    is_safe_font_file,
    is_safe_image_file,
    is_safe_sound_file,
)

THEMES_DIR = Path(__file__).resolve().parent.parent / "portprotonqt" / "themes"


def _write_theme(tmp_path: Path, name: str, code: str) -> Path:
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


def _check(code: str, tmp_path: Path, allow_abs: bool = False) -> tuple[bool, list[str]]:
    f = _write_theme(tmp_path, "t.py", code)
    checker = ThemeSecurityChecker()
    return checker.check_theme_safety(str(f), allow_abs)


# === Built-in themes ===


class TestBuiltinThemes:
    @pytest.mark.parametrize(
        "theme_file",
        sorted(THEMES_DIR.glob("**/*.py")),
        ids=lambda p: str(p.relative_to(THEMES_DIR)),
    )
    def test_all_builtin_themes_pass(self, theme_file: Path) -> None:
        assert check_theme_safety(str(theme_file))


class TestCardShadowCompatibility:
    def test_disabled_card_shadow_is_blocked(self, tmp_path: Path) -> None:
        code = """
color_shadow_card = "#00000000"
shadow_blur_radius = 0
shadow_offset = (0, 0)
"""

        is_safe, errors = _check(code, tmp_path)

        assert not is_safe
        assert any("Disabled card shadow" in error for error in errors)

    @pytest.mark.parametrize(
        "code",
        [
            'color_shadow_card = "#00000000"\nshadow_blur_radius = 20\nshadow_offset = (0, 0)\n',
            'color_shadow_card = "#00000096"\nshadow_blur_radius = 0\nshadow_offset = (0, 0)\n',
            'shadow_blur_radius = 0\nshadow_offset = (0, 0)\n',
        ],
    )
    def test_individual_shadow_values_are_allowed(
        self, tmp_path: Path, code: str,
    ) -> None:
        is_safe, _ = _check(code, tmp_path)

        assert is_safe


# === Forbidden modules ===


class TestForbiddenModules:
    @pytest.mark.parametrize(
        "code",
        [
            "import os",
            "import sys",
            "import subprocess",
            "import socket",
            "import json",
            "import pickle",
            "import base64",
            "import hashlib",
            "import sqlite3",
            "import ctypes",
            "import threading",
            "import asyncio",
            "import requests",
            "import importlib",
            "import yaml",
            "import codecs",
            "import binascii",
            "import struct",
            "import marshal",
        ],
    )
    def test_forbidden_imports_blocked(self, tmp_path: Path, code: str) -> None:
        is_safe, _ = _check(code, tmp_path)
        assert not is_safe

    def test_import_from_forbidden_blocked(self, tmp_path: Path) -> None:
        is_safe, _ = _check("from os import system\n", tmp_path)
        assert not is_safe

    def test_import_submodule_blocked(self, tmp_path: Path) -> None:
        is_safe, _ = _check("import os.path\n", tmp_path)
        assert not is_safe


# === Safe imports ===


class TestSafeImports:
    def test_theme_manager_import(self, tmp_path: Path) -> None:
        is_safe, _ = _check(
            "from portprotonqt.theme_manager import ThemeManager\n", tmp_path,
        )
        assert is_safe

    def test_config_import(self, tmp_path: Path) -> None:
        is_safe, _ = _check(
            "from portprotonqt.config import ui_config\n", tmp_path,
        )
        assert is_safe

    def test_relative_import(self, tmp_path: Path) -> None:
        is_safe, _ = _check("from .constants import *\n", tmp_path)
        assert is_safe

    def test_import_module_not_alias(self, tmp_path: Path) -> None:
        is_safe, _ = _check(
            "import portprotonqt.theme_manager\n", tmp_path,
        )
        assert is_safe

    def test_random_import_blocked(self, tmp_path: Path) -> None:
        is_safe, _ = _check("import random\n", tmp_path)
        assert not is_safe


# === Forbidden functions ===


class TestForbiddenFunctions:
    @pytest.mark.parametrize(
        "code",
        [
            "x = exec(\"print(1)\")",
            "x = eval(\"1+1\")",
            "x = open(\"f.txt\")",
            "x = getattr(obj, \"attr\")",
            "x = setattr(obj, \"attr\", 1)",
            "x = globals()",
            "x = locals()",
            "x = vars()",
            "x = type(obj)",
        ],
    )
    def test_forbidden_calls(self, tmp_path: Path, code: str) -> None:
        is_safe, _ = _check(code, tmp_path)
        assert not is_safe


# === Forbidden methods ===


class TestForbiddenMethods:
    @pytest.mark.parametrize(
        "code",
        [
            "x = obj.system(\"ls\")",
            "x = obj.popen(\"ls\")",
            "x = obj.run(cmd)",
            "x = obj.Popen(cmd)",
            "x = obj.urlopen(url)",
            "x = obj.b64decode(data)",
            "x = obj.loads(data)",
            "x = obj.dumps(data)",
        ],
    )
    def test_forbidden_methods(self, tmp_path: Path, code: str) -> None:
        is_safe, _ = _check(code, tmp_path)
        assert not is_safe

    def test_dict_get_allowed(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = d.get(\"key\", \"default\")\n", tmp_path)
        assert is_safe

    def test_str_lower_allowed(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = tier.lower()\n", tmp_path)
        assert is_safe


# === Dunder attributes ===


class TestDunderAttributes:
    def test_dunder_class(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = obj.__class__\n", tmp_path)
        assert not is_safe

    def test_dunder_dict(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = obj.__dict__\n", tmp_path)
        assert not is_safe

    def test_dunder_builtins(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = __builtins__[\"eval\"]\n", tmp_path)
        assert not is_safe


# === Builtins subscript ===


class TestBuiltinsAccess:
    def test_builtins_subscript(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = __builtins__[\"eval\"]\n", tmp_path)
        assert not is_safe


# === Top-level statements ===


class TestTopLevelStatements:
    def test_while(self, tmp_path: Path) -> None:
        is_safe, _ = _check("while True:\n    pass\n", tmp_path)
        assert not is_safe

    def test_for(self, tmp_path: Path) -> None:
        is_safe, _ = _check("for i in range(10):\n    pass\n", tmp_path)
        assert not is_safe

    def test_with(self, tmp_path: Path) -> None:
        is_safe, _ = _check("with open(\"f\") as fh:\n    pass\n", tmp_path)
        assert not is_safe

    def test_try(self, tmp_path: Path) -> None:
        is_safe, _ = _check("try:\n    pass\nexcept:\n    pass\n", tmp_path)
        assert not is_safe

    def test_class(self, tmp_path: Path) -> None:
        is_safe, _ = _check("class A:\n    pass\n", tmp_path)
        assert not is_safe

    def test_lambda(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = lambda a: a\n", tmp_path)
        assert not is_safe

    def test_comprehension(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = [i for i in range(10)]\n", tmp_path)
        assert not is_safe

    def test_global(self, tmp_path: Path) -> None:
        is_safe, _ = _check("global x\n", tmp_path)
        assert not is_safe

    def test_yield(self, tmp_path: Path) -> None:
        is_safe, _ = _check("def g():\n    yield 1\n", tmp_path)
        assert not is_safe

    def test_raise_top_level(self, tmp_path: Path) -> None:
        is_safe, _ = _check("raise ValueError(\"test\")\n", tmp_path)
        assert not is_safe

    def test_raise_in_function(self, tmp_path: Path) -> None:
        is_safe, _ = _check("def f():\n    raise ValueError(\"test\")\n", tmp_path)
        assert not is_safe

    def test_assert(self, tmp_path: Path) -> None:
        is_safe, _ = _check("assert True\n", tmp_path)
        assert not is_safe

    def test_del(self, tmp_path: Path) -> None:
        is_safe, _ = _check("del x\n", tmp_path)
        assert not is_safe


# === Allowed constructs ===


class TestAllowedConstructs:
    def test_simple_assignment(self, tmp_path: Path) -> None:
        is_safe, _ = _check("color_accent = \"#409EFF\"\n", tmp_path)
        assert is_safe

    def test_dict_assignment(self, tmp_path: Path) -> None:
        is_safe, _ = _check("D = {\"key\": \"value\", \"num\": 42}\n", tmp_path)
        assert is_safe

    def test_fstring(self, tmp_path: Path) -> None:
        is_safe, _ = _check("x = f\"color: {color_accent}\"\n", tmp_path)
        assert is_safe

    def test_function_def(self, tmp_path: Path) -> None:
        code = (
            "def get_style(tier):\n"
            "    tier = tier.lower()\n"
            "    colors = {\"a\": \"red\", \"b\": \"blue\"}\n"
            "    return colors.get(tier, \"gray\")\n"
        )
        is_safe, _ = _check(code, tmp_path)
        assert is_safe

    def test_if_statement(self, tmp_path: Path) -> None:
        code = (
            "def f(x):\n"
            "    if x:\n"
            "        return \"a\"\n"
            "    else:\n"
            "        return \"b\"\n"
        )
        is_safe, _ = _check(code, tmp_path)
        assert is_safe

    def test_docstring(self, tmp_path: Path) -> None:
        is_safe, _ = _check("\"\"\"Theme module.\"\"\"\n", tmp_path)
        assert is_safe


# === AST size limit ===


class TestAstSizeLimit:
    def test_huge_file(self, tmp_path: Path) -> None:
        code = "x = 1\n" * 25000
        is_safe, errors = _check(code, tmp_path)
        assert not is_safe
        assert any("too many AST nodes" in e for e in errors)


# === File size limit ===


class TestFileSizeLimit:
    def test_oversized_file(self, tmp_path: Path) -> None:
        f = tmp_path / "t.py"
        f.write_bytes(b"x = 1\n" * 100000)
        checker = ThemeSecurityChecker()
        is_safe, errors = checker.check_theme_safety(str(f))
        assert not is_safe
        assert any("too large" in e for e in errors)


# === Syntax errors ===


class TestSyntaxErrors:
    def test_syntax_error(self, tmp_path: Path) -> None:
        is_safe, errors = _check("def f(\n", tmp_path)
        assert not is_safe
        assert any("Syntax error" in e for e in errors)


# === Decorators ===


class TestDecorators:
    def test_decorator_blocked(self, tmp_path: Path) -> None:
        is_safe, _ = _check("@decorator\ndef f():\n    pass\n", tmp_path)
        assert not is_safe


# === Default arguments ===


class TestDefaultArguments:
    def test_default_with_call(self, tmp_path: Path) -> None:
        is_safe, _ = _check("def f(x=get_value()):\n    pass\n", tmp_path)
        assert not is_safe

    def test_default_literal(self, tmp_path: Path) -> None:
        is_safe, _ = _check("def f(x=\"default\"):\n    pass\n", tmp_path)
        assert is_safe


# === Directory safety ===


class TestDirectorySafety:
    def test_symlink_dir(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (real / "styles.py").write_text("x = 1\n")
        link = tmp_path / "link"
        link.symlink_to(real)
        assert not check_theme_directory_safety(str(link))

    def test_symlink_file(self, tmp_path: Path) -> None:
        d = tmp_path / "theme"
        d.mkdir()
        real_file = tmp_path / "outside.py"
        real_file.write_text("x = 1\n")
        link = d / "styles.py"
        link.symlink_to(real_file)
        assert not check_theme_directory_safety(str(d))

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert not check_theme_directory_safety(str(tmp_path / "nope"))

    def test_valid_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "theme"
        d.mkdir()
        (d / "styles.py").write_text("color = \"red\"\n")
        assert check_theme_directory_safety(str(d))

    def test_valid_wav_in_theme_dir(self, tmp_path: Path) -> None:
        sounds = tmp_path / "theme" / "sounds"
        sounds.mkdir(parents=True)
        (sounds / "navigate.wav").write_bytes(
            b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 32
        )

        assert check_theme_directory_safety(str(tmp_path / "theme"))

    def test_invalid_wav_in_theme_dir_is_rejected(self, tmp_path: Path) -> None:
        sounds = tmp_path / "theme" / "sounds"
        sounds.mkdir(parents=True)
        (sounds / "navigate.wav").write_bytes(b"not audio")

        assert not check_theme_directory_safety(str(tmp_path / "theme"))


# === Font safety ===


class TestFontSafety:
    def test_bad_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "test.exe"
        f.write_bytes(b"\x00" * 10)
        assert not is_safe_font_file(str(f))

    def test_oversized(self, tmp_path: Path) -> None:
        f = tmp_path / "test.ttf"
        f.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * (11 * 1024 * 1024))
        assert not is_safe_font_file(str(f))

    def test_valid_ttf(self, tmp_path: Path) -> None:
        f = tmp_path / "test.ttf"
        f.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 100)
        assert is_safe_font_file(str(f))


class TestSoundSafety:
    def test_supported_wav_signature(self, tmp_path: Path) -> None:
        sound = tmp_path / "sound.wav"
        sound.write_bytes(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 32)
        assert is_safe_sound_file(str(sound))

    def test_rejects_disguised_sound(self, tmp_path: Path) -> None:
        sound = tmp_path / "sound.wav"
        sound.write_bytes(b"not audio")
        assert not is_safe_sound_file(str(sound))

    def test_rejects_non_wav_extension(self, tmp_path: Path) -> None:
        sound = tmp_path / "sound.ogg"
        sound.write_bytes(b"OggS" + b"\x00" * 32)
        assert not is_safe_sound_file(str(sound))


# === Image safety ===


class TestImageSafety:
    def test_bad_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "test.exe"
        f.write_bytes(b"\x00" * 10)
        assert not is_safe_image_file(str(f))

    def test_bad_png_signature(self, tmp_path: Path) -> None:
        f = tmp_path / "test.png"
        f.write_bytes(b"\x00" * 100)
        assert not is_safe_image_file(str(f))

    def test_valid_png(self, tmp_path: Path) -> None:
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert is_safe_image_file(str(f))

    def test_valid_jpeg(self, tmp_path: Path) -> None:
        f = tmp_path / "test.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        assert is_safe_image_file(str(f))

    def test_svg_script(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg><script>alert(1)</script></svg>')
        assert not is_safe_image_file(str(f))

    def test_svg_onload(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg onload="alert(1)"></svg>')
        assert not is_safe_image_file(str(f))

    def test_svg_image_tag(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg><image href="http://evil.com"/></svg>')
        assert not is_safe_image_file(str(f))

    def test_svg_style_tag(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg><style>@import url("http://evil.com")</style></svg>')
        assert not is_safe_image_file(str(f))

    def test_svg_inline_css_allowed(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg><style>.cls{fill:none;}</style><path d="M0 0"/></svg>')
        assert is_safe_image_file(str(f))

    def test_clean_svg(self, tmp_path: Path) -> None:
        f = tmp_path / "test.svg"
        f.write_bytes(b'<svg><circle cx="50" cy="50" r="40"/></svg>')
        assert is_safe_image_file(str(f))


# === Suspicious strings ===


class TestSuspiciousStrings:
    def test_discord_webhook(self, tmp_path: Path) -> None:
        is_safe, _ = _check(
            "url = \"https://discord.com/api/webhooks/123\"\n", tmp_path,
        )
        assert not is_safe

    def test_paste_service(self, tmp_path: Path) -> None:
        is_safe, _ = _check("url = \"https://pastebin.com/abc\"\n", tmp_path)
        assert not is_safe

    def test_miner(self, tmp_path: Path) -> None:
        is_safe, _ = _check("url = \"https://xmrig.com\"\n", tmp_path)
        assert not is_safe

    def test_ssh_key(self, tmp_path: Path) -> None:
        is_safe, _ = _check(
            "key = \"/home/user/.ssh/id_rsa\"\n", tmp_path,
        )
        assert not is_safe

    def test_normal_string(self, tmp_path: Path) -> None:
        is_safe, _ = _check("color = \"#409EFF\"\n", tmp_path)
        assert is_safe
