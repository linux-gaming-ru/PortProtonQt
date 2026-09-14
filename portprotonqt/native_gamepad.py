import ctypes
from dataclasses import dataclass
from pathlib import Path

GAMEPAD_LIBRARY_NAME = "libportprotonqt_gamepad.so"
SYSTEM_GAMEPAD_LIBRARY = Path(__file__).parent / GAMEPAD_LIBRARY_NAME
DEV_GAMEPAD_LIBRARY = (
    Path(__file__).parent.parent / "build-aux" / "lib" / GAMEPAD_LIBRARY_NAME
)
GAMEPAD_LIBRARY_PATH = (
    SYSTEM_GAMEPAD_LIBRARY
    if SYSTEM_GAMEPAD_LIBRARY.is_file()
    else DEV_GAMEPAD_LIBRARY
)


def _load_library() -> ctypes.CDLL:
    return ctypes.CDLL(str(GAMEPAD_LIBRARY_PATH))


_library = _load_library()
_handle = ctypes.c_void_p
_library.portproton_gamepad_find.argtypes = []
_library.portproton_gamepad_find.restype = _handle
_library.portproton_gamepad_get_error.argtypes = []
_library.portproton_gamepad_get_error.restype = ctypes.c_char_p
_library.portproton_gamepad_close.argtypes = [_handle]
_library.portproton_gamepad_close.restype = None
_library.portproton_gamepad_connected.argtypes = [_handle]
_library.portproton_gamepad_connected.restype = ctypes.c_bool
_library.portproton_gamepad_update.argtypes = [_handle]
_library.portproton_gamepad_update.restype = None
_library.portproton_gamepad_get_button.argtypes = [_handle, ctypes.c_int]
_library.portproton_gamepad_get_button.restype = ctypes.c_int
_library.portproton_gamepad_get_axis.argtypes = [_handle, ctypes.c_int]
_library.portproton_gamepad_get_axis.restype = ctypes.c_int16
_library.portproton_gamepad_get_active_instance_id.argtypes = [_handle]
_library.portproton_gamepad_get_active_instance_id.restype = ctypes.c_uint32
_library.portproton_gamepad_get_name.argtypes = [_handle]
_library.portproton_gamepad_get_name.restype = ctypes.c_char_p
_library.portproton_gamepad_get_instance_id.argtypes = [_handle]
_library.portproton_gamepad_get_instance_id.restype = ctypes.c_uint32
_library.portproton_gamepad_get_type.argtypes = [_handle]
_library.portproton_gamepad_get_type.restype = ctypes.c_int
_library.portproton_gamepad_shutdown.argtypes = []
_library.portproton_gamepad_shutdown.restype = None


class GamepadBackendError(RuntimeError):
    """SDL failed while discovering connected gamepads."""


@dataclass
class SDLGamepad:
    controller: int
    name: str
    path: str
    instance_id: int
    sdl_type: int
    active_instance_id: int = 0

    def close(self) -> None:
        if self.controller:
            _library.portproton_gamepad_close(self.controller)
            self.controller = 0

    def __del__(self) -> None:
        self.close()

    def connected(self) -> bool:
        return bool(_library.portproton_gamepad_connected(self.controller))

    def update(self) -> bool:
        _library.portproton_gamepad_update(self.controller)
        active_instance_id = int(
            _library.portproton_gamepad_get_active_instance_id(self.controller)
        )
        if active_instance_id == self.active_instance_id:
            return False
        self.active_instance_id = active_instance_id
        return True

    def get_button(self, button: int) -> int:
        return int(_library.portproton_gamepad_get_button(self.controller, button))

    def get_axis(self, axis: int) -> int:
        return int(_library.portproton_gamepad_get_axis(self.controller, axis))


def find_gamepad() -> SDLGamepad | None:
    controller = _library.portproton_gamepad_find()
    if not controller:
        error = _library.portproton_gamepad_get_error().decode(errors="replace")
        if error:
            raise GamepadBackendError(error)
        return None
    instance_id = int(_library.portproton_gamepad_get_instance_id(controller))
    name = _library.portproton_gamepad_get_name(controller).decode(errors="replace")
    return SDLGamepad(
        controller=controller,
        name=name,
        path=f"sdl3-gamepad:{instance_id}",
        instance_id=instance_id,
        sdl_type=int(_library.portproton_gamepad_get_type(controller)),
    )


def shutdown() -> None:
    _library.portproton_gamepad_shutdown()
