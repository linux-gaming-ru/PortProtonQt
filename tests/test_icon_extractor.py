"""Tests for icon_extractor.py — NE/PE parsing, DIB decoding, thumbnail generation."""
import io
import struct
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from PIL import Image
from pytest import MonkeyPatch, raises

import portprotonqt.game_card as game_card_module
import portprotonqt.image_utils as image_utils
from portprotonqt.game_card import GameCard
from portprotonqt.icon_extractor import (
    IconExtractor,
    IconExtractorError,
    generate_thumbnail,
    get_exe_icon_cache_path,
    RT_ICON,
    RT_GROUP_ICON,
    THUMBNAIL_SIZE,
)


class FakePixmap:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self._width = 0
        self._height = 0

    def load(self, path: str) -> None:
        self.path = path

    def isNull(self) -> bool:
        return not self.path or not Path(self.path).exists()

    def scaled(self, width: int, height: int, *_args: object) -> "FakePixmap":
        self._width = width
        self._height = height
        return self

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def copy(self, *_args: object) -> "FakePixmap":
        return self


def test_exe_icon_cache_path_uses_shared_directory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("portprotonqt.icon_extractor.CACHE_DIR", tmp_path / "cache" / "PortProtonQt")
    monkeypatch.setattr(image_utils, "CACHE_DIR", tmp_path / "cache" / "PortProtonQt")

    icon_path = get_exe_icon_cache_path("/games/Game Name.exe")

    assert icon_path == str(
        tmp_path / "cache" / "PortProtonQt" / "images" / "exe_icons" / "Game_Name.exe.png"
    )


def _make_png_bytes(width: int = 16, height: int = 16) -> bytes:
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_group_icon_data(entries: list[tuple[int, int, int, int, int]] | None = None) -> bytes:
    if entries is None:
        entries = [(16, 16, 32, 500, 1)]
    header = struct.pack("<HHH", 0, RT_GROUP_ICON, len(entries))
    body = b""
    for width, height, bitcount, bytes_in_res, res_id in entries:
        body += struct.pack(
            "<BBBBHHIH",
            width % 256,
            height % 256,
            0,
            0,
            0,
            bitcount,
            bytes_in_res,
            res_id,
        )
    return header + body


def _make_dib_icon(
    width: int = 16,
    height: int = 16,
    bitcount: int = 32,
    color: tuple[int, int, int] = (255, 0, 0),
) -> bytes:
    image_height = height
    palette_size = 0
    if bitcount <= 8:
        palette_size = 1 << bitcount
        image_height = height
    xor_stride = ((width * bitcount + 31) // 32) * 4
    and_stride = ((width + 31) // 32) * 4

    header = struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        bitcount,
        0,
        0,
        0,
        0,
        palette_size,
        0,
    )

    palette = b""
    for i in range(palette_size):
        if i == 0:
            palette += struct.pack("BBBB", color[2], color[1], color[0], 0)
        else:
            palette += struct.pack("BBBB", 0, 0, 0, 0)

    if bitcount == 32:
        pixel_data = b""
        for _ in range(image_height):
            row = b""
            for _ in range(width):
                row += struct.pack("BBBB", color[2], color[1], color[0], 255)
            row += b"\x00" * (xor_stride - len(row))
            pixel_data += row
    elif bitcount == 8:
        pixel_data = b""
        for _ in range(image_height):
            row = bytes([0] * width)
            row += b"\x00" * (xor_stride - len(row))
            pixel_data += row
    elif bitcount == 4:
        pixel_data = b""
        for _ in range(image_height):
            row = bytes([0x00] * ((width + 1) // 2))
            row += b"\x00" * (xor_stride - len(row))
            pixel_data += row
    elif bitcount == 1:
        pixel_data = b""
        for _ in range(image_height):
            row = bytes([0x00] * ((width + 7) // 8))
            row += b"\x00" * (xor_stride - len(row))
            pixel_data += row
    else:
        pixel_data = b"\x00" * (xor_stride * image_height)

    mask_data = b"\x00" * (and_stride * image_height)

    return header + palette + pixel_data + mask_data


def _make_ne_exe(icon_data: bytes | None = None, group_data: bytes | None = None) -> bytes:
    if icon_data is None:
        icon_data = _make_dib_icon(16, 16, 32)
    if group_data is None:
        group_data = _make_group_icon_data()

    mz_header = b"MZ" + b"\x00" * 58
    e_lfanew = 64
    mz_header += struct.pack("<I", e_lfanew)

    ne_header = b"NE" + b"\x00" * 0x22

    resource_offset = 0x100
    ne_header += struct.pack("<H", resource_offset)

    shift = 4
    data_start = resource_offset + 0x40
    group_off = data_start >> shift
    icon_off = (data_start + len(group_data)) >> shift

    rt_data = struct.pack("<H", shift)
    rt_data += struct.pack("<HHI", RT_GROUP_ICON, 1, 0)
    rt_data += struct.pack("<HHI", group_off, len(group_data), 0)
    rt_data += struct.pack("<HHI", RT_ICON, 1, 0)
    rt_data += struct.pack("<HHI", icon_off, len(icon_data), 0)
    rt_data += b"\x00" * 8

    remaining = resource_offset - e_lfanew - len(ne_header)
    ne_header += b"\x00" * remaining

    result = mz_header + ne_header + rt_data + group_data + icon_data
    return result


class TestIconExtractorInit:
    def test_creates_extractor(self, tmp_path):
        f = tmp_path / "test.exe"
        f.write_bytes(b"MZ" + b"\x00" * 62 + struct.pack("<I", 64) + b"PE" + b"\x00" * 200)
        ext = IconExtractor(str(f))
        assert ext.file_path == str(f)
        assert ext._icons == {}
        assert ext._groups == []


class TestParseFile:
    def test_not_mz_returns_false(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        ext = IconExtractor(str(f))
        with open(str(f), "rb") as fh:
            assert ext._parse_file(fh) is False

    def test_pe_no_resources(self, tmp_path):
        pe_data = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64)
        pe_data += b"PE" + b"\x00" * 2
        pe_data += b"\x00" * 200
        f = tmp_path / "no_resources.exe"
        f.write_bytes(pe_data)
        ext = IconExtractor(str(f))
        with open(str(f), "rb") as fh:
            result = ext._parse_file(fh)
        assert result is False

    def test_ne_no_resource_table(self, tmp_path):
        mz_header = b"MZ" + b"\x00" * 58
        e_lfanew = 64
        mz_header += struct.pack("<I", e_lfanew)
        ne_header = b"NE" + b"\x00" * 0x22
        ne_header += struct.pack("<H", 0)
        ne_header += b"\x00" * 100
        f = tmp_path / "test.exe"
        f.write_bytes(mz_header + ne_header)
        ext = IconExtractor(str(f))
        with open(str(f), "rb") as fh:
            assert ext._parse_file(fh) is False


class TestGetIcon:
    def test_raises_extractor_error_for_unreadable_file(self, tmp_path):
        missing_file = tmp_path / "missing.exe"
        ext = IconExtractor(str(missing_file))

        with raises(IconExtractorError, match="Failed to extract icon"):
            ext.get_icon()

    def test_returns_none_for_non_mz(self, tmp_path):
        f = tmp_path / "not_exe.bin"
        f.write_bytes(b"\x00" * 100)
        ext = IconExtractor(str(f))
        assert ext.get_icon() is None

    def test_returns_none_for_empty_file(self, tmp_path):
        f = tmp_path / "empty.exe"
        f.write_bytes(b"")
        ext = IconExtractor(str(f))
        assert ext.get_icon() is None

    def test_returns_none_for_pe_without_resources(self, tmp_path):
        pe_data = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64)
        pe_data += b"PE" + b"\x00" * 2
        pe_data += b"\x00" * 200
        f = tmp_path / "no_resources.exe"
        f.write_bytes(pe_data)
        ext = IconExtractor(str(f))
        assert ext.get_icon() is None


class TestSelectBestIconData:
    def test_returns_none_for_short_data(self):
        ext = IconExtractor("/dev/null")
        assert ext._select_best_icon_data(b"\x00\x01") is None

    def test_returns_none_for_no_icons(self):
        ext = IconExtractor("/dev/null")
        ext._icons = {}
        group = _make_group_icon_data()
        assert ext._select_best_icon_data(group) is None

    def test_selects_best_by_size(self):
        ext = IconExtractor("/dev/null")
        ext._icons = {
            1: b"small",
            2: b"LARGE",
        }
        group = _make_group_icon_data([
            (16, 16, 32, 100, 1),
            (32, 32, 32, 500, 2),
        ])
        result = ext._select_best_icon_data(group)
        assert result == b"LARGE"

    def test_selects_best_by_bitcount(self):
        ext = IconExtractor("/dev/null")
        ext._icons = {
            1: b"low_depth",
            2: b"high_depth",
        }
        group = _make_group_icon_data([
            (32, 32, 16, 500, 1),
            (32, 32, 32, 500, 2),
        ])
        result = ext._select_best_icon_data(group)
        assert result == b"high_depth"

    def test_skips_missing_icon_id(self):
        ext = IconExtractor("/dev/null")
        ext._icons = {1: b"exists"}
        group = _make_group_icon_data([
            (16, 16, 32, 100, 1),
            (32, 32, 32, 500, 99),
        ])
        result = ext._select_best_icon_data(group)
        assert result == b"exists"


class TestIconDataToImage:
    def test_png_passthrough(self):
        ext = IconExtractor("/dev/null")
        png_data = _make_png_bytes(16, 16)
        result = ext._icon_data_to_image(png_data)
        assert result is not None
        img = Image.open(result)
        assert img.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)

    def test_dib_icon_32bit(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 32)
        result = ext._icon_data_to_image(dib)
        assert result is not None
        img = Image.open(result)
        assert img.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        assert img.mode == "RGBA"

    def test_dib_icon_8bit(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 8)
        result = ext._icon_data_to_image(dib)
        assert result is not None

    def test_dib_icon_4bit(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 4)
        result = ext._icon_data_to_image(dib)
        assert result is not None

    def test_dib_icon_1bit(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 1)
        result = ext._icon_data_to_image(dib)
        assert result is not None

    def test_corrupt_png_returns_none(self):
        ext = IconExtractor("/dev/null")
        assert ext._icon_data_to_image(b"\x89PNG\r\n\x1a\n\x00\x00corrupt") is None

    def test_invalid_dib_returns_none(self):
        ext = IconExtractor("/dev/null")
        assert ext._icon_data_to_image(b"\x00" * 10) is None


class TestDecodeDibIcon:
    def test_returns_none_too_short(self):
        ext = IconExtractor("/dev/null")
        assert ext._decode_dib_icon(b"\x00" * 10) is None

    def test_returns_none_compression_not_zero(self):
        ext = IconExtractor("/dev/null")
        header = struct.pack("<IIIHHIIIIII", 40, 16, 32, 1, 32, 1, 0, 0, 0, 0, 0)
        assert ext._decode_dib_icon(header + b"\x00" * 100) is None

    def test_returns_none_zero_width(self):
        ext = IconExtractor("/dev/null")
        header = struct.pack("<IIIHHIIIIII", 40, 0, 32, 1, 32, 0, 0, 0, 0, 0, 0)
        assert ext._decode_dib_icon(header + b"\x00" * 100) is None

    def test_returns_none_zero_height(self):
        ext = IconExtractor("/dev/null")
        header = struct.pack("<IIIHHIIIIII", 40, 16, 0, 1, 32, 0, 0, 0, 0, 0, 0)
        assert ext._decode_dib_icon(header + b"\x00" * 100) is None

    def test_valid_32bit_icon(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 32)
        img = ext._decode_dib_icon(dib)
        assert img is not None
        assert img.size == (16, 8)

    def test_valid_8bit_icon(self):
        ext = IconExtractor("/dev/null")
        dib = _make_dib_icon(16, 16, 8)
        img = ext._decode_dib_icon(dib)
        assert img is not None

    def test_returns_none_data_too_short_for_pixels(self):
        ext = IconExtractor("/dev/null")
        header = struct.pack("<IIIHHIIIIII", 40, 16, 32, 1, 32, 0, 0, 0, 0, 0, 0)
        assert ext._decode_dib_icon(header) is None


class TestReadPixel:
    def test_32bit_transparent(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x80])
        row = struct.pack("BBBB", 0, 128, 255, 128)
        pixel = ext._read_pixel(row, mask, 0, 32, [])
        assert pixel == (255, 128, 0, 0)

    def test_32bit_opaque(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        row = struct.pack("BBBB", 0, 128, 255, 200)
        pixel = ext._read_pixel(row, mask, 0, 32, [])
        assert pixel == (255, 128, 0, 200)

    def test_24bit(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        row = struct.pack("BBB", 100, 150, 200)
        pixel = ext._read_pixel(row, mask, 0, 24, [])
        assert pixel == (200, 150, 100, 255)

    def test_16bit(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        value = (10 << 10) | (20 << 5) | 30
        row = struct.pack("<H", value)
        pixel = ext._read_pixel(row, mask, 0, 16, [])
        assert pixel is not None
        assert pixel[3] == 255

    def test_8bit_palette(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        palette = [(255, 0, 0), (0, 255, 0)]
        pixel = ext._read_pixel(bytes([1]), mask, 0, 8, palette)
        assert pixel == (0, 255, 0, 255)

    def test_4bit_palette(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        pixel = ext._read_pixel(bytes([0x10]), mask, 0, 4, palette)
        assert pixel == (0, 255, 0, 255)

    def test_1bit_palette(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        palette = [(255, 0, 0), (0, 255, 0)]
        pixel = ext._read_pixel(bytes([0x80]), mask, 0, 1, palette)
        assert pixel == (0, 255, 0, 255)

    def test_1bit_palette_low_bit(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        palette = [(255, 0, 0), (0, 255, 0)]
        pixel = ext._read_pixel(bytes([0x00]), mask, 0, 1, palette)
        assert pixel == (255, 0, 0, 255)

    def test_8bit_index_out_of_range(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        pixel = ext._read_pixel(bytes([99]), mask, 0, 8, [(255, 0, 0)])
        assert pixel is None

    def test_unknown_bitcount(self):
        ext = IconExtractor("/dev/null")
        mask = bytes([0x00])
        pixel = ext._read_pixel(b"\x00" * 10, mask, 0, 64, [])
        assert pixel is None


class TestGenerateThumbnail:
    def test_returns_false_for_nonexistent(self, tmp_path):
        out = tmp_path / "out.png"
        assert generate_thumbnail("/nonexistent/file.exe", str(out)) is False

    def test_returns_false_for_non_mz(self, tmp_path):
        f = tmp_path / "not_exe.bin"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        out = tmp_path / "out.png"
        assert generate_thumbnail(str(f), str(out)) is False
        assert not out.exists()

    def test_handles_exception_gracefully(self, tmp_path):
        f = tmp_path / "game.exe"
        f.write_bytes(b"MZ" + b"\x00" * 100)
        out = tmp_path / "thumb.png"
        with patch.object(IconExtractor, "get_icon", side_effect=Exception("boom")):
            assert generate_thumbnail(str(f), str(out)) is False

    def test_with_mocked_icon(self, tmp_path):
        f = tmp_path / "game.exe"
        f.write_bytes(b"MZ" + b"\x00" * 100)
        out = tmp_path / "thumb.png"
        png_data = _make_png_bytes(32, 32)
        with patch.object(IconExtractor, "get_icon", return_value=io.BytesIO(png_data)):
            result = generate_thumbnail(str(f), str(out))
            assert result is True
            assert out.exists()
            img = Image.open(str(out))
            assert img.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)

    def test_uses_executable_from_neighboring_batch(self, tmp_path):
        launcher = tmp_path / "GameLauncher.exe"
        launcher.touch()
        target = tmp_path / "MKKE.exe"
        target.touch()
        (tmp_path / "custom-launcher.cmd").write_text(
            "start MKKE.exe\nexit\n",
            encoding="utf-8",
        )
        out = tmp_path / "thumb.png"
        png_data = _make_png_bytes(32, 32)

        with patch.object(
            IconExtractor,
            "get_icon",
            autospec=True,
            side_effect=[None, io.BytesIO(png_data)],
        ) as get_icon:
            assert generate_thumbnail(str(launcher), str(out)) is True

        assert get_icon.call_count == 2
        assert get_icon.call_args_list[1].args[0].file_path == str(target)
        assert out.exists()

    def test_custom_size_with_mock(self, tmp_path):
        f = tmp_path / "game.exe"
        f.write_bytes(b"MZ" + b"\x00" * 100)
        out = tmp_path / "thumb.png"
        png_data = _make_png_bytes(64, 64)
        with patch.object(IconExtractor, "get_icon", return_value=io.BytesIO(png_data)):
            result = generate_thumbnail(str(f), str(out), size=64, force_resize=True)
            assert result is True
            img = Image.open(str(out))
            assert img.size == (64, 64)

    def test_no_resize_when_same_size(self, tmp_path):
        f = tmp_path / "game.exe"
        f.write_bytes(b"MZ" + b"\x00" * 100)
        out = tmp_path / "thumb.png"
        png_data = _make_png_bytes(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        with patch.object(IconExtractor, "get_icon", return_value=io.BytesIO(png_data)):
            result = generate_thumbnail(str(f), str(out), size=THUMBNAIL_SIZE, force_resize=False)
            assert result is True


def test_game_card_exe_fallback_uses_image_cache(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exe_path = tmp_path / "game.exe"
    exe_path.write_bytes(b"MZ")
    monkeypatch.setattr("portprotonqt.icon_extractor.CACHE_DIR", tmp_path / "cache" / "PortProtonQt")
    monkeypatch.setattr(image_utils, "CACHE_DIR", tmp_path / "cache" / "PortProtonQt")
    card: Any = SimpleNamespace(
        exec_line=str(exe_path),
        name="Game",
        _extract_executable_path=GameCard._extract_executable_path,
    )

    fallback_exe, fallback_path = GameCard._get_exe_icon_fallback(card)

    assert fallback_exe == str(exe_path)
    assert fallback_path == str(
        tmp_path / "cache" / "PortProtonQt" / "images" / "exe_icons" / "game.exe.png"
    )


def test_game_card_uses_exe_fallback_without_valid_cover(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    broken_cover = tmp_path / "broken.jpg"
    broken_cover.write_bytes(b"broken")
    calls: list[dict[str, str]] = []
    card: Any = SimpleNamespace(
        appid="game",
        list_layout=False,
        base_card_width=100,
        on_cover_loaded=lambda _pixmap: None,
        _set_animated_cover=lambda *_args: False,
        _get_exe_icon_fallback=lambda: ("/games/game.exe", "/cache/images/Game.png"),
    )

    def fake_load(_cover: str, _width: int, _height: int, _callback: Any, **kwargs: str) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(game_card_module, "load_pixmap_async", fake_load)
    GameCard._load_cover_image(card, "")
    GameCard._load_cover_image(card, str(broken_cover))

    assert calls == [
        {
            "app_name": "game",
            "fallback_exe": "/games/game.exe",
            "fallback_icon_path": "/cache/images/Game.png",
        },
        {
            "app_name": "game",
            "fallback_exe": "/games/game.exe",
            "fallback_icon_path": "/cache/images/Game.png",
        },
    ]


def test_remote_cover_replaces_immediate_exe_fallback_only_on_success(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exe_path = tmp_path / "game.exe"
    exe_path.write_bytes(b"MZ")
    fallback_path = tmp_path / "cache" / "PortProtonQt" / "images" / "Game.png"
    fallback_path.parent.mkdir(parents=True)
    fallback_path.write_bytes(b"exe icon")
    callbacks: list[Callable[[str | None], None]] = []
    loaded_paths: list[str] = []

    def defer_download(
        _url: str,
        _path: str,
        timeout: int,
        callback: Callable[[str | None], None],
    ) -> None:
        callbacks.append(callback)

    monkeypatch.setattr("portprotonqt.icon_extractor.CACHE_DIR", tmp_path / "cache" / "PortProtonQt")
    monkeypatch.setattr(image_utils, "CACHE_DIR", tmp_path / "cache" / "PortProtonQt")
    monkeypatch.setattr(image_utils, "QPixmap", FakePixmap)
    monkeypatch.setattr(image_utils.image_executor, "submit", lambda callback: callback())
    monkeypatch.setattr(image_utils, "downloader", SimpleNamespace(download_async=defer_download))
    monkeypatch.setattr(image_utils.ui_config, "get_theme", lambda: "standart")
    theme = SimpleNamespace(color_placeholder_bg="#333333", color_white="#ffffff")
    monkeypatch.setattr(
        image_utils,
        "ThemeManager",
        lambda: SimpleNamespace(current_theme_module=theme),
    )

    image_utils.load_pixmap_async(
        "https://example.org/game.jpg", 100, 150,
        lambda pixmap: loaded_paths.append(cast(FakePixmap, pixmap).path),
        app_name="game", fallback_exe=str(exe_path),
        fallback_icon_path=str(fallback_path),
    )
    callbacks[0](None)
    downloaded_path = tmp_path / "cache" / "PortProtonQt" / "images" / "game.jpg"
    downloaded_path.write_bytes(b"cover")
    callbacks[0](str(downloaded_path))

    assert loaded_paths == [str(fallback_path), str(downloaded_path)]
