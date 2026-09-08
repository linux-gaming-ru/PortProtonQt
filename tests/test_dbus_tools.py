"""Tests for scripts_utils/dbus_tools.py — D-Bus helpers, notifications, power profiles."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dbus_fast import DBusError, Message, Variant

from portprotonqt.scripts_utils.dbus_tools import (
    ACTIVE_PROFILE,
    DBUS_TIMEOUT,
    NOTIFICATIONS_BUS_NAME,
    NOTIFICATIONS_BUS_PATH,
    PORTAL_BUS_NAME,
    PORTAL_BUS_PATH,
    PORTAL_IDLE_FLAG,
    PORTAL_INTERFACE,
    PORTAL_NOTIFICATION_INTERFACE,
    PORTAL_REQUEST_INTERFACE,
    POWER_PROFILE_ENDPOINTS,
    PROFILES,
    PROPERTIES_INTERFACE,
    SCREENSAVER_BUS_NAME,
    SCREENSAVER_BUS_PATH,
    NotificationRequest,
    _active_power_profile,
    _bus_call,
    _get_property,
    _profile_names,
    _serialize_icon,
    _variant_value,
    dbus_call,
    get_power_profile,
    main,
    parse_args,
    release_idle_inhibit,
    request_deepin_wm_switch,
    request_idle_inhibit,
    send_notification,
    set_power_profile,
)

DUMMY_MSG = Message(
    destination="a.b",
    path="/a",
    interface="a.b",
    member="m",
)


class TestNotificationRequest:
    def test_construction(self):
        req = NotificationRequest("app", "icon", "title", "body", 5000)
        assert req.app == "app"
        assert req.icon == "icon"
        assert req.title == "title"
        assert req.body == "body"
        assert req.timeout == 5000

    def test_frozen(self):
        req = NotificationRequest("a", "i", "t", "b", 1)
        with pytest.raises(AttributeError):
            req.app = "x"  # type: ignore[misc]


class TestSerializeIcon:
    def test_file_path_with_slash(self):
        result = _serialize_icon("/usr/share/icon.png")
        assert result.value == ["file", Variant("s", "/usr/share/icon.png")]

    def test_file_path_with_dot(self):
        result = _serialize_icon("icon.png")
        assert result.value == ["file", Variant("s", "icon.png")]

    def test_themed_icon(self):
        result = _serialize_icon("dialog-information")
        assert result.value == ["themed", Variant("as", ["dialog-information"])]

    def test_themed_icon_hyphen(self):
        result = _serialize_icon("audio-x-generic")
        assert result.value == ["themed", Variant("as", ["audio-x-generic"])]


class TestVariantValue:
    def test_string(self):
        assert _variant_value("hello") == "hello"

    def test_int(self):
        assert _variant_value(42) == 42

    def test_variant(self):
        assert _variant_value(Variant("s", "test")) == "test"

    def test_list(self):
        val = [Variant("s", "a"), "b"]
        assert _variant_value(val) == ["a", "b"]

    def test_empty_list(self):
        assert _variant_value([]) == []

    def test_dict_with_plain_keys(self):
        val = {"key": Variant("s", "value")}
        assert _variant_value(val) == {"key": "value"}

    def test_list_of_dicts(self):
        val = [{"Profile": Variant("s", "balanced")}]
        assert _variant_value(val) == [{"Profile": "balanced"}]

    def test_none_passthrough(self):
        assert _variant_value(None) is None

    def test_bool_passthrough(self):
        assert _variant_value(True) is True


class TestProfileNames:
    def test_valid_profiles(self):
        profiles = [
            {"Profile": "balanced"},
            {"Profile": "performance"},
        ]
        assert _profile_names(profiles) == {"balanced", "performance"}

    def test_empty_list(self):
        assert _profile_names([]) == set()

    def test_not_a_list(self):
        assert _profile_names("invalid") == set()

    def test_none(self):
        assert _profile_names(None) == set()

    def test_missing_profile_key(self):
        assert _profile_names([{"Name": "x"}]) == set()

    def test_non_string_profile(self):
        assert _profile_names([{"Profile": 123}]) == set()

    def test_mixed_valid_invalid(self):
        profiles = [
            {"Profile": "balanced"},
            {"Name": "missing"},
            {"Profile": "powersave"},
        ]
        assert _profile_names(profiles) == {"balanced", "powersave"}


class TestParseArgs:
    def test_notify_minimal(self):
        with patch("sys.argv", ["dbus_tools", "notify", "Title"]):
            args = parse_args()
        assert args.command == "notify"
        assert args.title == "Title"
        assert args.body == ""
        assert args.app == "ru.linux_gaming.PortProtonQt"
        assert args.icon == ""
        assert args.timeout == 5000

    def test_notify_all_flags(self):
        with patch("sys.argv", ["dbus_tools", "notify", "-a", "myapp", "-i", "icon", "-t", "3000", "T", "B"]):
            args = parse_args()
        assert args.app == "myapp"
        assert args.icon == "icon"
        assert args.timeout == 3000
        assert args.title == "T"
        assert args.body == "B"

    def test_deepin_switch_wm(self):
        with patch("sys.argv", ["dbus_tools", "deepin-switch-wm"]):
            args = parse_args()
        assert args.command == "deepin-switch-wm"


def _run_async(coro):
    return asyncio.run(coro)


def _make_reply(name="METHOD_RETURN", body=None):
    reply = MagicMock()
    reply.message_type.name = name
    reply.body = body
    return reply


def _make_ok(body=None):
    return _make_reply("METHOD_RETURN", body)


def _make_error(body=None):
    return _make_reply("ERROR", body)


def _mock_bus(reply=None):
    bus = AsyncMock()
    bus.call = AsyncMock(return_value=reply or _make_ok())
    bus.disconnect = MagicMock()
    bus.get_proxy_object = MagicMock()
    return bus


def _patch_bus(reply=None):
    bus = _mock_bus(reply)
    patcher = patch("portprotonqt.scripts_utils.dbus_tools.MessageBus")
    MockBus = patcher.start()
    MockBus.return_value.connect = AsyncMock(return_value=bus)
    return bus, patcher


class TestDbusCall:
    def test_success(self):
        async def coro():
            return "ok"
        result = _run_async(dbus_call(coro()))
        assert result == "ok"

    def test_timeout(self):
        async def slow():
            await asyncio.sleep(100)
        with pytest.raises(asyncio.TimeoutError):
            _run_async(asyncio.wait_for(slow(), timeout=0.01))


class TestBusCall:
    def test_success_reply(self):
        async def run():
            bus = _mock_bus(_make_ok(["result"]))
            return await _bus_call(bus, DUMMY_MSG)
        assert _run_async(run()) == ["result"]

    def test_error_reply(self):
        async def run():
            bus = _mock_bus(_make_error(["err"]))
            return await _bus_call(bus, DUMMY_MSG)
        assert _run_async(run()) is None


class TestSessionCall:
    def test_success(self):
        async def run():
            bus, patcher = _patch_bus(_make_ok(["data"]))
            try:
                from portprotonqt.scripts_utils.dbus_tools import _session_call
                return await _session_call(DUMMY_MSG)
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_error_returns_false(self):
        async def run():
            bus, patcher = _patch_bus(_make_error())
            try:
                from portprotonqt.scripts_utils.dbus_tools import _session_call
                return await _session_call(DUMMY_MSG)
            finally:
                patcher.stop()
        assert _run_async(run()) is False


class TestSendNotification:
    def test_standard_notification_success(self):
        async def run():
            req = NotificationRequest("app", "icon", "Title", "Body", 5000)
            bus, patcher = _patch_bus(_make_ok([1]))
            try:
                return await send_notification(req)
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_standard_fails_portal_succeeds(self):
        async def run():
            req = NotificationRequest("app", "", "Title", "Body", 5000)
            call_count = 0

            async def side_effect(msg):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return _make_error()
                return _make_ok([None])

            bus, patcher = _patch_bus()
            bus.call = AsyncMock(side_effect=side_effect)
            try:
                return await send_notification(req)
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_both_fail(self):
        async def run():
            req = NotificationRequest("app", "", "Title", "Body", 5000)
            bus, patcher = _patch_bus(_make_error())
            try:
                return await send_notification(req)
            finally:
                patcher.stop()
        assert _run_async(run()) is False

    def test_portproton_app_has_hints(self):
        async def run():
            req = NotificationRequest("ru.linux_gaming.PortProtonQt", "", "T", "B", 5000)
            bus, patcher = _patch_bus(_make_ok([1]))
            try:
                return await send_notification(req)
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_notification_with_icon(self):
        async def run():
            req = NotificationRequest("app", "/path/to/icon.png", "T", "B", 5000)
            bus, patcher = _patch_bus(_make_ok([1]))
            try:
                return await send_notification(req)
            finally:
                patcher.stop()
        assert _run_async(run()) is True


class TestRequestDeepinWmSwitch:
    def test_success(self):
        async def run():
            bus, patcher = _patch_bus(_make_ok([]))
            try:
                return await request_deepin_wm_switch()
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_failure(self):
        async def run():
            bus, patcher = _patch_bus(_make_error())
            try:
                return await request_deepin_wm_switch()
            finally:
                patcher.stop()
        assert _run_async(run()) is False


class TestRequestIdleInhibit:
    def test_screensaver_fallback_to_portal(self):
        async def run():
            bus, patcher = _patch_bus()
            bus.get_proxy_object = MagicMock(side_effect=Exception("no screensaver"))

            call_count = 0

            async def side_effect(msg):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return _make_ok(["/portal/path"])
                return _make_ok(["/portal/path"])

            bus.call = AsyncMock(side_effect=side_effect)
            try:
                return await request_idle_inhibit("app", "reason")
            finally:
                patcher.stop()

        bus, kind, payload = _run_async(run())
        assert kind == "portal"
        assert payload == "/portal/path"
        assert bus is not None


class TestReleaseIdleInhibit:
    def test_release_screensaver(self):
        async def run():
            mock_bus = MagicMock()
            mock_iface = AsyncMock()
            mock_bus.disconnect = MagicMock()
            await release_idle_inhibit(mock_bus, "screensaver", (mock_iface, "cookie123"))
            return mock_iface, mock_bus

        iface, bus = _run_async(run())
        iface.call_un_inhibit.assert_called_once_with("cookie123")
        bus.disconnect.assert_called_once()

    def test_release_portal(self):
        async def run():
            bus, patcher = _patch_bus(_make_ok([]))
            try:
                await release_idle_inhibit(bus, "portal", "/handle/path")
                return bus
            finally:
                patcher.stop()

        bus = _run_async(run())
        bus.disconnect.assert_called_once()

    def test_release_suppresses_dbus_error(self):
        async def run():
            mock_bus = MagicMock()
            mock_iface = AsyncMock()
            mock_iface.call_un_inhibit.side_effect = DBusError("org.freedesktop.DBus.Error.Failed", "err")
            mock_bus.disconnect = MagicMock()
            await release_idle_inhibit(mock_bus, "screensaver", (mock_iface, "cookie"))
            return mock_bus

        bus = _run_async(run())
        bus.disconnect.assert_called_once()

    def test_release_suppresses_timeout(self):
        async def run():
            mock_bus = MagicMock()
            mock_iface = AsyncMock()
            mock_iface.call_un_inhibit.side_effect = TimeoutError()
            mock_bus.disconnect = MagicMock()
            await release_idle_inhibit(mock_bus, "screensaver", (mock_iface, "cookie"))
            return mock_bus

        bus = _run_async(run())
        bus.disconnect.assert_called_once()

    def test_release_portal_suppresses_error(self):
        async def run():
            bus = AsyncMock()
            bus.call = AsyncMock(side_effect=DBusError("org.freedesktop.DBus.Error.Failed", "err"))
            bus.disconnect = MagicMock()
            await release_idle_inhibit(bus, "portal", "/handle/path")
            return bus

        bus = _run_async(run())
        bus.disconnect.assert_called_once()


class TestGetPowerProfile:
    def test_success(self):
        async def run():
            bus, patcher = _patch_bus(_make_ok([Variant("s", "balanced")]))
            try:
                return await get_power_profile()
            finally:
                patcher.stop()
        assert _run_async(run()) == "balanced"

    def test_no_profile(self):
        async def run():
            bus, patcher = _patch_bus(_make_error())
            try:
                return await get_power_profile()
            finally:
                patcher.stop()
        assert _run_async(run()) is None


class TestSetActivePowerProfile:
    def test_first_endpoint_succeeds(self):
        async def run():
            bus = _mock_bus(_make_ok([Variant("s", "balanced")]))
            return await _active_power_profile(bus)
        result = _run_async(run())
        assert result is not None
        assert result[1] == "balanced"

    def test_all_endpoints_fail(self):
        async def run():
            bus = _mock_bus(_make_error())
            return await _active_power_profile(bus)
        assert _run_async(run()) is None


class TestGetProperty:
    def test_success(self):
        async def run():
            bus = _mock_bus(_make_ok([Variant("s", "balanced")]))
            return await _get_property(bus, ("bus.name", "/path"), "ActiveProfile")
        assert _run_async(run()) == "balanced"

    def test_empty_body(self):
        async def run():
            bus = _mock_bus(_make_ok(None))
            return await _get_property(bus, ("bus.name", "/path"), "ActiveProfile")
        assert _run_async(run()) is None


class TestSetPowerProfile:
    def test_set_success(self):
        async def run():
            profiles_data = [
                {"Profile": "balanced"},
                {"Profile": "powersave"},
            ]

            async def side_effect(msg):
                if msg.member == "Get" and len(msg.body) >= 2 and msg.body[1] == "ActiveProfile":
                    return _make_ok([Variant("s", "balanced")])
                if msg.member == "Get" and len(msg.body) >= 2 and msg.body[1] == "Profiles":
                    return _make_ok([profiles_data])
                if msg.member == "Set":
                    return _make_ok([None])
                return _make_ok([None])

            bus, patcher = _patch_bus()
            bus.call = AsyncMock(side_effect=side_effect)
            try:
                return await set_power_profile("balanced")
            finally:
                patcher.stop()
        assert _run_async(run()) is True

    def test_no_active_profile(self):
        async def run():
            bus, patcher = _patch_bus(_make_error())
            try:
                return await set_power_profile("balanced")
            finally:
                patcher.stop()
        assert _run_async(run()) is False

    def test_invalid_profile_name(self):
        async def run():
            profiles_data = [
                {"Profile": "balanced"},
                {"Profile": "powersave"},
            ]

            async def side_effect(msg):
                if msg.member == "Get" and len(msg.body) >= 2 and msg.body[1] == "ActiveProfile":
                    return _make_ok([Variant("s", "balanced")])
                if msg.member == "Get" and len(msg.body) >= 2 and msg.body[1] == "Profiles":
                    return _make_ok([profiles_data])
                return _make_ok([None])

            bus, patcher = _patch_bus()
            bus.call = AsyncMock(side_effect=side_effect)
            try:
                return await set_power_profile("nonexistent")
            finally:
                patcher.stop()
        assert _run_async(run()) is False


class TestMain:
    def test_main_notify_success(self):
        with patch("sys.argv", ["dbus_tools", "notify", "Title"]):
            with patch(
                "portprotonqt.scripts_utils.dbus_tools.send_notification",
                new_callable=AsyncMock,
                return_value=True,
            ):
                assert main() == 0

    def test_main_deepin_success(self):
        with patch("sys.argv", ["dbus_tools", "deepin-switch-wm"]):
            with patch(
                "portprotonqt.scripts_utils.dbus_tools.request_deepin_wm_switch",
                new_callable=AsyncMock,
                return_value=True,
            ):
                assert main() == 0

    def test_main_notify_failure(self):
        with patch("sys.argv", ["dbus_tools", "notify", "Title"]):
            with patch(
                "portprotonqt.scripts_utils.dbus_tools.send_notification",
                new_callable=AsyncMock,
                return_value=False,
            ):
                assert main() == 1

    def test_main_deepin_failure(self):
        with patch("sys.argv", ["dbus_tools", "deepin-switch-wm"]):
            with patch(
                "portprotonqt.scripts_utils.dbus_tools.request_deepin_wm_switch",
                new_callable=AsyncMock,
                return_value=False,
            ):
                assert main() == 1

    def test_main_exception_returns_1(self):
        with patch("sys.argv", ["dbus_tools", "notify", "Title"]):
            with patch(
                "portprotonqt.scripts_utils.dbus_tools.send_notification",
                new_callable=AsyncMock,
                side_effect=Exception("dbus error"),
            ):
                assert main() == 1

    def test_main_no_subcommand(self):
        with patch("sys.argv", ["dbus_tools"]):
            with pytest.raises(SystemExit):
                main()


class TestConstants:
    def test_power_profile_endpoints_count(self):
        assert len(POWER_PROFILE_ENDPOINTS) == 2

    def test_power_profile_endpoints_format(self):
        for name, path in POWER_PROFILE_ENDPOINTS:
            assert isinstance(name, str)
            assert isinstance(path, str)
            assert path.startswith("/")

    def test_bus_timeout(self):
        assert DBUS_TIMEOUT == 10

    def test_portal_idle_flag(self):
        assert PORTAL_IDLE_FLAG == 8

    def test_screensaver_bus(self):
        assert SCREENSAVER_BUS_NAME == "org.freedesktop.ScreenSaver"
        assert SCREENSAVER_BUS_PATH == "/org/freedesktop/ScreenSaver"

    def test_portal_bus(self):
        assert PORTAL_BUS_NAME == "org.freedesktop.portal.Desktop"
        assert PORTAL_BUS_PATH == "/org/freedesktop/portal/desktop"

    def test_notification_bus(self):
        assert NOTIFICATIONS_BUS_NAME == "org.freedesktop.Notifications"
        assert NOTIFICATIONS_BUS_PATH == "/org/freedesktop/Notifications"

    def test_interfaces(self):
        assert PORTAL_INTERFACE == "org.freedesktop.portal.Inhibit"
        assert PORTAL_NOTIFICATION_INTERFACE == "org.freedesktop.portal.Notification"
        assert PORTAL_REQUEST_INTERFACE == "org.freedesktop.portal.Request"
        assert PROPERTIES_INTERFACE == "org.freedesktop.DBus.Properties"

    def test_profile_constants(self):
        assert ACTIVE_PROFILE == "ActiveProfile"
        assert PROFILES == "Profiles"
