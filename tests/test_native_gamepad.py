import ctypes
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


def test_missing_sdl_disables_gamepad(monkeypatch: pytest.MonkeyPatch) -> None:
    library_loader = Mock(side_effect=OSError("libSDL3.so.0: not found"))
    monkeypatch.setattr(ctypes.CDLL, "__init__", library_loader)
    path = Path(__file__).parents[1] / "portprotonqt" / "native_gamepad.py"
    spec = importlib.util.spec_from_file_location("gamepad_without_sdl", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)

    spec.loader.exec_module(module)

    assert module.find_gamepad() is None
    assert module.find_gamepad() is None
    module.shutdown()
    library_loader.assert_called_once()
