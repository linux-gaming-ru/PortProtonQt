"""GPU information gathering functions."""

import os
import re
import subprocess
from threading import Lock

from portprotonqt.logger import get_logger

logger = get_logger(__name__)

_vk_gpu_info_output: str | None = None
_vk_gpu_info_lock = Lock()
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m|\[[0-9;]{1,8}m')
_LOG_PREFIXES = ("Info:", "Warning:", "Error:")


def get_cached_vk_gpu_info() -> str:
    """Get cached vk_gpu_info output, running it only once."""
    global _vk_gpu_info_output

    with _vk_gpu_info_lock:
        if _vk_gpu_info_output is not None:
            return _vk_gpu_info_output
        try:
            vk_gpu_info_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "build-aux",
                "bin",
                "vk_gpu_info"
            )

            if os.path.exists(vk_gpu_info_path):
                result = subprocess.run(
                    [vk_gpu_info_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False
                )
            else:
                result = subprocess.run(
                    ["vk_gpu_info"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False
                )

            if result.returncode == 0:
                _vk_gpu_info_output = result.stdout
            else:
                logger.warning(_format_command_error("vk_gpu_info", result))
                _vk_gpu_info_output = ""
        except FileNotFoundError:
            _vk_gpu_info_output = ""
        except subprocess.TimeoutExpired as e:
            logger.warning(_format_command_timeout("vk_gpu_info", e))
            _vk_gpu_info_output = ""
        except Exception as e:
            logger.error("Error running vk_gpu_info: %s", e)
            _vk_gpu_info_output = ""

        return _vk_gpu_info_output


def _clean_vk_gpu_value(value: str) -> str:
    """Clean control sequences from vk_gpu_info values."""
    return _ANSI_RE.sub("", value).strip()


def _is_selectable_device_name(device_name: str) -> bool:
    """Check if vk_gpu_info device name can be shown in UI."""
    if not device_name:
        return False
    if device_name.startswith(_LOG_PREFIXES):
        return False
    return "llvmpipe" not in device_name.lower()


def get_gpu_list() -> list[str]:
    """Get list of available GPUs, sorted by type (discrete first)."""
    gpu_list: list[str] = []
    discrete_gpus: list[str] = []
    integrated_gpus: list[str] = []
    other_gpus: list[str] = []

    vk_gpu_info_output = get_cached_vk_gpu_info()
    if not vk_gpu_info_output:
        return gpu_list

    lines = vk_gpu_info_output.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("GPU #"):
            gpu_info: dict[str, str] = {}

            gpu_num_match = re.search(r'GPU #(\d+)', line)
            if gpu_num_match:
                gpu_info['id'] = gpu_num_match.group(1)

            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("GPU #"):
                prop_line = lines[i].strip()

                if ':' in prop_line:
                    key_value = prop_line.split(':', 1)
                    if len(key_value) == 2:
                        key = key_value[0].strip()
                        value = key_value[1].strip()

                        if key == 'device_name':
                            gpu_info['deviceName'] = _clean_vk_gpu_value(value)
                        elif key == 'device_type':
                            gpu_info['deviceType'] = _clean_vk_gpu_value(value)

                i += 1

            device_name = gpu_info.get('deviceName', 'Unknown')
            device_type = gpu_info.get('deviceType', 'Unknown')

            if device_type in ['CPU', 'VIRTUAL_GPU']:
                continue
            if not _is_selectable_device_name(device_name):
                continue

            if device_type == 'DISCRETE_GPU':
                discrete_gpus.append(device_name)
            elif device_type == 'INTEGRATED_GPU':
                integrated_gpus.append(device_name)
            else:
                other_gpus.append(device_name)

        else:
            i += 1

    gpu_list = discrete_gpus + integrated_gpus + other_gpus
    return gpu_list


def get_selectable_gpu_entries() -> list[dict[str, str]]:
    """Get selectable GPU entries from vk_gpu_info with ids."""
    entries: list[dict[str, str]] = []
    discrete_entries: list[dict[str, str]] = []
    integrated_entries: list[dict[str, str]] = []
    other_entries: list[dict[str, str]] = []

    vk_gpu_info_output = get_cached_vk_gpu_info()
    if not vk_gpu_info_output:
        return entries

    lines = vk_gpu_info_output.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("GPU #"):
            i += 1
            continue

        gpu_info: dict[str, str] = {}
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("GPU #"):
            prop_line = lines[i].strip()
            if ":" in prop_line:
                key, value = prop_line.split(":", 1)
                gpu_info[key.strip()] = _clean_vk_gpu_value(value)
            i += 1

        device_name = gpu_info.get("device_name", "").strip()
        device_type = gpu_info.get("device_type", "").strip()
        if not device_name or device_type in {"CPU", "VIRTUAL_GPU"}:
            continue
        if not _is_selectable_device_name(device_name):
            continue

        vendor_id = gpu_info.get("vendor_id", "").strip()
        device_id = gpu_info.get("device_id", "").strip()
        entry = {
            "device_name": device_name,
            "device_type": device_type,
            "vendor_id": vendor_id,
            "device_id": device_id,
            "driver_name": gpu_info.get("driver_name", "").strip(),
            "driver_info": gpu_info.get("driver_info", "").strip(),
            "driver_version": gpu_info.get("driver_version", "").strip(),
            "api_version": gpu_info.get("api_version", "").strip(),
        }

        if device_type == "DISCRETE_GPU":
            discrete_entries.append(entry)
        elif device_type == "INTEGRATED_GPU":
            integrated_entries.append(entry)
        else:
            other_entries.append(entry)

    entries.extend(discrete_entries)
    entries.extend(integrated_entries)
    entries.extend(other_entries)
    return entries


def get_selectable_gpu_list() -> list[str]:
    """Get GPU list for UI/selection, excluding software rasterizers."""
    return [entry["device_name"] for entry in get_selectable_gpu_entries()]


def _format_gpu_description(device_desc: str) -> str:
    """Format GPU description from lspci output."""
    if "NVIDIA" in device_desc:
        gpu_match = re.search(r'NVIDIA Corporation (.+)', device_desc)
        if gpu_match:
            return f"NVIDIA {gpu_match.group(1)}"
    elif "AMD" in device_desc or "ATI" in device_desc:
        gpu_match = re.search(
            r'Advanced Micro Devices, Inc. \[AMD/ATI\] (.+)',
            device_desc
        )
        if gpu_match:
            return f"AMD {gpu_match.group(1)}"
        gpu_match = re.search(r'(AMD|ATI) (.+)', device_desc)
        if gpu_match:
            return f"{gpu_match.group(1)} {gpu_match.group(2)}"
    elif "Intel" in device_desc:
        gpu_match = re.search(r'Intel Corporation (.+)', device_desc)
        if gpu_match:
            return f"Intel {gpu_match.group(1)}"
    return device_desc


def _extract_driver_info(all_lines: list[str], start_idx: int) -> str:
    """Extract driver info from lspci output lines."""
    for j in range(start_idx + 1, min(start_idx + 4, len(all_lines))):
        next_line = all_lines[j]
        if "Kernel driver in use:" in next_line:
            return next_line.split("Kernel driver in use:")[1].strip()
    return ""


def _get_nvidia_driver_version() -> str | None:
    """Get NVIDIA driver version from sysfs."""
    try:
        with open('/sys/module/nvidia/version') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _build_device_line(
    device_count: int,
    device_desc: str,
    driver_info: str
) -> str:
    """Build formatted device line with driver and version info."""
    formatted_device_desc = _format_gpu_description(device_desc)
    device_line = f"Device-{device_count}: {formatted_device_desc}"

    if driver_info:
        device_line += f" driver: {driver_info}"

    if "NVIDIA" in device_desc:
        version = _get_nvidia_driver_version()
        if version:
            device_line += f" v: {version}"

    return device_line


def _parse_lspci_output(stdout: str) -> list[str]:
    """Parse lspci -k output and return formatted graphics device lines."""
    device_count = 1
    all_lines = stdout.split("\n")
    devices_info = []

    i = 0
    while i < len(all_lines):
        line = all_lines[i]
        if any(x in line for x in ["VGA", "3D", "Display"]):
            parts = line.split(maxsplit=1)
            device_desc = parts[1] if len(parts) > 1 else ""

            driver_info = _extract_driver_info(all_lines, i)
            device_line = _build_device_line(
                device_count, device_desc, driver_info
            )

            devices_info.append(device_line)
            device_count += 1
        i += 1

    return devices_info


def _build_graphics_section(devices_info: list[str]) -> list[str]:
    """Build Graphics section with devices and display info."""
    graphics_lines = [f"Graphics:  {device}" for device in devices_info]

    if not graphics_lines:
        return graphics_lines

    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    display_info = f"Display: {session_type}"

    if session_type == "wayland":
        display_info += f" server: {os.environ.get('WAYLAND_DISPLAY', 'N/A')}"
    else:
        display_info += f" server: {os.environ.get('DISPLAY', 'N/A')}"

    try:
        from portprotonqt.debug_utils.xorg_utils import get_xorg_version
        xorg_version = get_xorg_version()
        display_info += f" X.Org version: {xorg_version}"
    except SystemExit:
        pass

    first_device = devices_info[0]
    if "driver: " in first_device:
        driver_part = first_device.split("driver: ")[1]
        driver_name = driver_part.split(" ")[0] if " " in driver_part else driver_part
        display_info += f" driver: loaded: {driver_name}"

    graphics_lines.append(f"           {display_info}")
    return graphics_lines


def _parse_glxinfo_output(stdout: str) -> list[str]:
    """Parse glxinfo output and return relevant lines."""
    keep_patterns = [
        "name of display",
        "display:",
        "direct rendering",
        "Memory info",
        "Dedicated video memory",
        "Total available memory",
        "Currently available",
        "OpenGL vendor",
        "OpenGL renderer",
        "OpenGL core profile version",
        "OpenGL core profile shading",
        "OpenGL core profile context",
        "OpenGL core profile profile",
        "OpenGL version string",
        "OpenGL shading language",
        "OpenGL context flags",
        "OpenGL profile mask",
        "OpenGL ES profile",
    ]
    lines = []

    for line in stdout.split("\n"):
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        if any(p in line for p in keep_patterns):
            lines.append(f"{key}: {value.strip()}")

    return lines


def _get_glxinfo_value(stdout: str, key_name: str) -> str:
    """Extract a single value from glxinfo output."""
    for line in stdout.split("\n"):
        key, separator, value = line.partition(":")
        if separator and key.strip() == key_name:
            return value.strip()
    return "Unknown"


def _format_glxinfo_gpu_line(stdout: str, vk_output: str | None = None) -> str | None:
    """Format primary GLX renderer using matched vk_gpu_info name."""
    device_name = _get_glxinfo_value(stdout, "OpenGL renderer string")
    if device_name == "Unknown":
        return None

    if vk_output is None:
        vk_output = get_cached_vk_gpu_info()

    renderer_name = device_name.lower()
    lines_vk = vk_output.split("\n")
    i = 0
    while i < len(lines_vk):
        line = lines_vk[i].strip()
        if not line.startswith("GPU #"):
            i += 1
            continue

        gpu_info, i = _parse_gpu_properties(lines_vk, i + 1)
        vulkan_name = gpu_info.get("device_name", "")

        if vulkan_name and vulkan_name.lower() in renderer_name:
            return f'export PW_GPU_INFO="{vulkan_name}"'

    return None


def _get_last_output_line(output: str | bytes | None) -> str | None:
    """Return the last non-empty process output line."""
    if not output:
        return None
    if isinstance(output, bytes):
        output = output.decode(errors="replace")

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[-1]


def _format_command_error(
    command: str,
    result: subprocess.CompletedProcess[str]
) -> str:
    """Format process error details for debug output."""
    last_line = _get_last_output_line(result.stderr or result.stdout)
    if last_line:
        return f"{command} error: {last_line}"
    return f"{command} exited with code {result.returncode}"


def _format_command_timeout(
    command: str,
    error: subprocess.TimeoutExpired
) -> str:
    """Format process timeout details for debug output."""
    details = [f"{command} timed out after {error.timeout} seconds"]
    last_line = _get_last_output_line(error.stderr or error.output)
    if last_line:
        details.append(f"last output: {last_line}")

    return "; ".join(details)


def _parse_gpu_properties(
    lines_vk: list[str],
    start_idx: int
) -> tuple[dict[str, str], int]:
    """Parse GPU properties from vk_gpu_info output."""
    gpu_info: dict[str, str] = {}
    i = start_idx

    while i < len(lines_vk) and lines_vk[i].strip() and not lines_vk[i].startswith("GPU #"):
        prop_line = lines_vk[i].strip()
        if ':' in prop_line:
            key_value = prop_line.split(':', 1)
            if len(key_value) == 2:
                key = key_value[0].strip()
                value = key_value[1].strip()
                gpu_info[key] = _clean_vk_gpu_value(value)
        i += 1

    return gpu_info, i


def _format_vulkan_gpu_line(gpu_info: dict[str, str]) -> str | None:
    """Format a single GPU line for vulkan output."""
    device_type = gpu_info.get('device_type', 'Unknown')
    if device_type in ['CPU', 'VIRTUAL_GPU']:
        return None

    gpu_id = gpu_info.get('id', 'Unknown')
    device_name = gpu_info.get('device_name', 'Unknown')
    driver_name = gpu_info.get('driver_name', 'Unknown')
    api_version = gpu_info.get('api_version', 'Unknown')

    if 'NVIDIA' in device_name.upper():
        driver_version = gpu_info.get('driver_info', 'Unknown')
    else:
        driver_version = gpu_info.get('driver_version', 'Unknown')

    return (
        f"GPU {gpu_id}: {device_name} deviceType: {device_type} "
        f"driverName: {driver_name} apiVersion: {api_version} "
        f"driverVersion: {driver_version}"
    )


def _parse_vulkan_output(vk_output: str) -> list[str]:
    """Parse vk_gpu_info output and return formatted GPU lines."""
    lines = []
    lines_vk = vk_output.split("\n")
    i = 0

    while i < len(lines_vk):
        line = lines_vk[i].strip()

        if line.startswith("GPU #"):
            gpu_num_match = re.search(r'GPU #(\d+)', line)
            gpu_id = gpu_num_match.group(1) if gpu_num_match else 'Unknown'

            gpu_info, i = _parse_gpu_properties(lines_vk, i + 1)
            gpu_info['id'] = gpu_id

            gpu_line = _format_vulkan_gpu_line(gpu_info)
            if gpu_line:
                lines.append(gpu_line)
                continue
        i += 1

    return lines


def get_graphics_info_detailed() -> str:
    """Get detailed graphics card info using lspci, glxinfo, and vk_gpu_info."""
    lines = []

    try:
        result = subprocess.run(
            ["lspci", "-k"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        if result.returncode == 0:
            devices_info = _parse_lspci_output(result.stdout)
            lines.extend(_build_graphics_section(devices_info))
        else:
            lines.append(_format_command_error("lspci", result))
    except subprocess.TimeoutExpired as e:
        lines.append(_format_command_timeout("lspci", e))
    except Exception as e:
        lines.append(f"lspci error: {e}")

    lines.append("----")

    gpu_line = None
    try:
        result = subprocess.run(
            ["glxinfo", "-B"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        if result.returncode == 0:
            gpu_line = _format_glxinfo_gpu_line(result.stdout)
            lines.extend(_parse_glxinfo_output(result.stdout))
        else:
            lines.append(_format_command_error("glxinfo", result))
    except FileNotFoundError:
        lines.append("glxinfo not found")
    except subprocess.TimeoutExpired as e:
        lines.append(_format_command_timeout("glxinfo", e))
    except Exception as e:
        lines.append(f"glxinfo error: {e}")

    lines.append("-----")
    if gpu_line:
        lines.append(gpu_line)

    try:
        vk_gpu_info_output = get_cached_vk_gpu_info()
        if vk_gpu_info_output:
            lines.append("Vulkan:")
            lines.extend(_parse_vulkan_output(vk_gpu_info_output))
        else:
            lines.append("vk_gpu_info not found")
    except FileNotFoundError:
        lines.append("vk_gpu_info not found")

    return "\n".join(lines) if lines else "Unable to retrieve graphics info"
