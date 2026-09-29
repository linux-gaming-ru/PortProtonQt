"""Tests for user-level AppImage integration."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from portprotonqt import appimage_integration


def test_integrate_appimage_installs_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Downloads" / "PortProtonQt.AppImage"
    appdir = tmp_path / "mount"
    source.parent.mkdir()
    appdir.mkdir()
    source.write_text("appimage", encoding="utf-8")
    (appdir / f"{appimage_integration.APP_ID}.svg").write_text(
        "icon",
        encoding="utf-8",
    )
    (appdir / f"{appimage_integration.APP_ID}.desktop").write_text(
        "[Desktop Entry]\n"
        "Name=PortProtonQt\n"
        "Exec=portprotonqt %u\n"
        "Type=Application\n"
        f"Icon={appimage_integration.APP_ID}\n",
        encoding="utf-8",
    )
    mime_source = appdir / "share/mime/packages"
    mime_source.mkdir(parents=True)
    (mime_source / appimage_integration.MIME_PACKAGE_NAME).write_text(
        "<mime-info/>",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPIMAGE", str(source))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        appimage_integration,
        "get_portproton_location",
        lambda: None,
    )
    desktop_dir = tmp_path / "Desktop"
    monkeypatch.setattr(
        appimage_integration.QStandardPaths,
        "writableLocation",
        lambda _location: str(desktop_dir),
    )
    stale_applications = tmp_path / "data" / "applications"
    icon_dir = tmp_path / "data/icons"
    stale_applications.mkdir(parents=True)
    icon_dir.mkdir(parents=True)
    legacy_entry = (
        "[Desktop Entry]\n"
        f"Exec={tmp_path}/Applications/PortProtonQt.AppImage %f\n"
        "Type=Application\n"
    )
    (stale_applications / f"{appimage_integration.APP_ID}.desktop").write_text(
        legacy_entry,
        encoding="utf-8",
    )
    desktop_dir.mkdir()
    (desktop_dir / f"{appimage_integration.APP_ID}.desktop").write_text(
        legacy_entry,
        encoding="utf-8",
    )
    legacy_game_entry = (
        "[Desktop Entry]\n"
        "Name=Legacy Game\n"
        f"Exec={tmp_path}/Applications/PortProtonQt.AppImage --silent /games/game.exe\n"
        "\n[Desktop Action RunLog]\n"
        f"Exec={tmp_path}/Applications/PortProtonQt.AppImage --log /games/game.exe\n"
    )
    legacy_applications = tmp_path / ".local/share/applications"
    legacy_applications.mkdir(parents=True)
    game_shortcuts = (
        legacy_applications / "Legacy Game.desktop",
        desktop_dir / "Legacy Game.desktop",
    )
    for game_shortcut in game_shortcuts:
        game_shortcut.write_text(legacy_game_entry, encoding="utf-8")
    (stale_applications / f"{appimage_integration.APP_ID}.log.desktop").write_text(
        "stale",
        encoding="utf-8",
    )
    stale_png = icon_dir / f"{appimage_integration.APP_ID}.png"
    stale_png.write_text("stale", encoding="utf-8")
    legacy_appimage = tmp_path / "Applications/PortProtonQt.AppImage"
    legacy_appimage.parent.mkdir()
    legacy_appimage.write_text("legacy", encoding="utf-8")
    commands = []
    monkeypatch.setattr(
        appimage_integration.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    destination = appimage_integration.integrate_appimage()

    assert destination == tmp_path / "AppImages" / "portprotonqt.appimage"
    assert "application/x-executable" not in appimage_integration.WINDOWS_MIME_TYPES
    assert destination.read_text(encoding="utf-8") == "appimage"
    assert not legacy_appimage.exists()
    assert not stale_png.exists()
    installed_icon = (
        tmp_path
        / "data/icons"
        / f"{appimage_integration.APP_ID}.svg"
    )
    assert installed_icon.read_text(encoding="utf-8") == "icon"
    applications = tmp_path / "data" / "applications"
    main_entry = (
        applications / f"{appimage_integration.APP_ID}.desktop"
    ).read_text()
    assert str(destination) in main_entry
    assert str(legacy_appimage) not in main_entry
    assert "TryExec=" in main_entry
    assert f"Icon={appimage_integration.APP_ID}\n" in main_entry
    desktop_entry = desktop_dir / f"{appimage_integration.APP_ID}.desktop"
    assert desktop_entry.read_text(encoding="utf-8") == main_entry
    assert desktop_entry.stat().st_mode & 0o111
    for game_shortcut in game_shortcuts:
        game_entry = game_shortcut.read_text(encoding="utf-8")
        assert str(legacy_appimage) not in game_entry
        assert game_entry.count(str(destination)) == 2
        assert "--silent /games/game.exe" in game_entry
        assert "--log /games/game.exe" in game_entry
    for mode in ("log", "silent"):
        entry = (
            applications / f"{appimage_integration.APP_ID}.{mode}.desktop"
        ).read_text()
        assert f"--{mode}" in entry
        assert "%u" in entry
        assert "NoDisplay=true" in entry
        assert "Name=PortProtonQt — " in entry
        assert "Comment=" in entry
        assert f"Icon={appimage_integration.APP_ID}\n" in entry
        assert "StartupWMClass=ru.linux_gaming.PortProtonQt" in entry
        assert "StartupNotify=true" in entry
    mime_commands = [
        [
            "xdg-mime",
            "default",
            f"{appimage_integration.APP_ID}.desktop",
            mime_type,
        ]
        for mime_type in appimage_integration.WINDOWS_MIME_TYPES.rstrip(";").split(";")
    ]
    installed_mime = (
        tmp_path / "data/mime/packages" / appimage_integration.MIME_PACKAGE_NAME
    )
    assert installed_mime.read_text(encoding="utf-8") == "<mime-info/>"
    assert commands == [
        ["update-mime-database", str(tmp_path / "data/mime")],
    ] + mime_commands + [
        ["update-desktop-database", str(applications)]
    ]


def test_app_restarts_installed_appimage_after_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portprotonqt import app

    destination = Path("/home/user/AppImages/portprotonqt.appimage")
    restarted: list[tuple[list[str], dict[str, str], bool]] = []
    reinstalled: list[bool] = []
    monkeypatch.setenv("PORTPROTONQT_INTEGRATE_APPIMAGE", "1")
    monkeypatch.setattr(app.sys, "argv", ["temporary.AppImage", "--reinstall-steam-compat-tool"])
    monkeypatch.setattr(
        app,
        "parse_args",
        lambda: SimpleNamespace(
            debug_level="NOTSET",
            json=False,
            list_games=False,
            reinstall_steam_compat_tool=True,
        ),
    )
    monkeypatch.setattr(
        appimage_integration,
        "integrate_appimage",
        lambda: destination,
    )
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda command, **kwargs: restarted.append(
            (command, kwargs["env"], kwargs["start_new_session"])
        ),
    )
    monkeypatch.setattr(
        app,
        "reinstall_steam_compat_tool",
        lambda: reinstalled.append(True) or True,
    )

    assert app.main() == 0
    assert restarted[0][0] == [
        str(destination),
        "--reinstall-steam-compat-tool",
    ]
    assert "PORTPROTONQT_INTEGRATE_APPIMAGE" not in restarted[0][1]
    assert restarted[0][2] is True
    assert reinstalled == []


def test_integrate_appimage_requires_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "PortProtonQt.AppImage"
    appdir = tmp_path / "mount"
    source.write_text("appimage", encoding="utf-8")
    appdir.mkdir()
    monkeypatch.setenv("APPIMAGE", str(source))
    monkeypatch.setenv("APPDIR", str(appdir))

    with pytest.raises(
        FileNotFoundError,
        match="AppImage desktop metadata is incomplete",
    ):
        appimage_integration.integrate_appimage()
