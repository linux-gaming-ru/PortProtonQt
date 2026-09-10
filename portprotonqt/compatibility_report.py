# Copyright 2026 mirkobrombin <brombin94@gmail.com>
# Adapted from the Bottles compatibility analyser under GPL-3.0.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import pefile

from portprotonqt.debug_utils import (
    get_portproton_env,
    get_prefix_name,
    get_selectable_gpu_entries,
    get_vulkan_use_info,
    get_wine_version,
    get_winetricks_log,
)
from portprotonqt.logger import get_logger
from portprotonqt.scripts_utils.graphics_detector import analyze_executable

logger = get_logger(__name__)

CRASH_THRESHOLD_SECONDS = 7
COMPATIBILITY_ALWAYS_REPORT_ENV = "PORTPROTONQT_COMPATIBILITY_ALWAYS_REPORT"
PE_MACHINE_AMD64 = 0x8664
COMPATIBILITY_SCAN_BYTES = 4_194_304
COMPATIBILITY_NEIGHBOR_SCAN_LIMIT = 20
COMPATIBILITY_RULES_PATH = Path(__file__).with_name("compatibility_rules.json")
I586_ELF_LOADER = "/lib/ld-linux.so.2"
DXVK_VULKAN_REQUIREMENTS = {
    "6": ("Newest", "DXVK_NEW_VER", (1, 4)),
    "2": ("Stable", "DXVK_OLD_VER", (1, 3)),
    "1": ("Sarek", "DXVK_SAREK_VER", (1, 1)),
}
DXVK_DRIVER_REQUIREMENTS = {
    "0x1002": ("AMD RADV", (25, 0), "driver_version"),
    "0x10de": ("NVIDIA", (550, 54, 14), "driver_info"),
    "0x8086": ("Intel ANV", (25, 1), "driver_version"),
}
DXVK_NVK_REQUIREMENT = ("NVIDIA NVK", (25, 1), "driver_version")
DXVK_NEWEST_NVIDIA_REQUIREMENT = ("NVIDIA", (575, 51, 2), "driver_info")
VCRUN_COMPONENTS = {
    "Visual C++ 2010": ("vcrun2010",),
    "Visual C++ 2012": ("vcrun2012",),
    "Visual C++ 2013": ("vcrun2013",),
    "Visual C++ 2015-2022": ("vcrun2015", "vcrun2017", "vcrun2019", "vcrun2022"),
}

DLL_MAPPINGS = {
    "mscoree.dll": (".NET Framework", "Runtimes"),
    "hostfxr.dll": (".NET Core/5+", "Runtimes"),
    "coreclr.dll": (".NET Core/5+", "Runtimes"),
    "mono-2.0-bdwgc.dll": ("Mono", "Runtimes"),
    "jvm.dll": ("Java", "Runtimes"),
    "python3.dll": ("Python", "Runtimes"),
    "msvcp100.dll": ("Visual C++ 2010", "Runtimes"),
    "msvcp110.dll": ("Visual C++ 2012", "Runtimes"),
    "msvcp120.dll": ("Visual C++ 2013", "Runtimes"),
    "msvcp140.dll": ("Visual C++ 2015-2022", "Runtimes"),
    "vcruntime140.dll": ("Visual C++ 2015-2022", "Runtimes"),
    "unityplayer.dll": ("Unity", "Engines"),
    "gameassembly.dll": ("Unity IL2CPP", "Engines"),
    "cryrenderd3d11.dll": ("CryEngine", "Engines"),
    "tier0.dll": ("Source", "Engines"),
    "libcef.dll": ("Chromium Embedded Framework", "Frameworks"),
    "electron.dll": ("Electron", "Frameworks"),
    "qt5core.dll": ("Qt 5", "Frameworks"),
    "qt6core.dll": ("Qt 6", "Frameworks"),
    "xinput1_3.dll": ("XInput 1.3", "Input"),
    "dinput8.dll": ("DirectInput", "Input"),
    "sdl2.dll": ("SDL2", "Input"),
    "xaudio2_7.dll": ("XAudio 2.7", "Audio"),
    "fmod.dll": ("FMOD", "Audio"),
    "fmod64.dll": ("FMOD", "Audio"),
    "binkw64.dll": ("Bink", "Audio"),
    "openal32.dll": ("OpenAL", "Audio"),
    "steam_api64.dll": ("Steamworks", "Social/DRM"),
    "galaxy64.dll": ("GOG Galaxy", "Social/DRM"),
    "eossdk-win64-shipping.dll": ("Epic Online Services", "Social/DRM"),
    "easyanticheat_x64.dll": ("Easy Anti-Cheat", "Protection"),
    "beclient_x64.dll": ("BattlEye", "Protection"),
    "vmprotectsdk64.dll": ("VMProtect", "Protection"),
}


@dataclass(frozen=True)
class CompatibilityLaunch:
    executable: str
    exit_code: int | None
    duration: float


def is_suspected_crash(duration: float, stopped_by_user: bool, executable: str) -> bool:
    """Return whether an executable closed too soon after launch."""
    always_report = os.getenv(COMPATIBILITY_ALWAYS_REPORT_ENV) == "1"
    return (
        (always_report or (not stopped_by_user and duration < CRASH_THRESHOLD_SECONDS))
        and executable.lower().endswith((".exe", ".msi"))
        and os.path.isfile(executable)
    )


def _read_imports(pe: pefile.PE) -> set[str]:
    imports = set()
    for directory_name in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, directory_name, []):
            try:
                imports.add(entry.dll.decode("utf-8", errors="ignore").lower())
            except AttributeError:
                continue
    return imports


def _load_rules() -> list[dict[str, Any]]:
    try:
        data = orjson.loads(COMPATIBILITY_RULES_PATH.read_bytes())
    except (OSError, orjson.JSONDecodeError) as error:
        logger.error("Compatibility report failed to load signature rules: %s", error)
        return []
    rules = data.get("rules", [])
    return rules if isinstance(rules, list) else []


def _matched_pattern_ids(
    data: bytes,
    lowered: bytes,
    flattened_wide: bytes,
    patterns: list[dict[str, str]],
) -> set[str]:
    matched = set()
    for pattern in patterns:
        identifier = pattern.get("id", "")
        text = pattern.get("text")
        if text is not None:
            needle = text.encode("utf-8", errors="ignore").lower()
            if needle in lowered or needle in flattened_wide:
                matched.add(identifier)
            continue
        expression = pattern.get("regex")
        if expression and re.search(expression.encode(), data, re.IGNORECASE):
            matched.add(identifier)
    return matched


def _scan_file(
    file_path: str, rules: list[dict[str, Any]], source: str
) -> list[dict[str, str]]:
    try:
        with open(file_path, "rb") as source_file:
            data = source_file.read(COMPATIBILITY_SCAN_BYTES)
    except OSError as error:
        logger.warning("Compatibility report failed to scan %s: %s", file_path, error)
        return []
    data = os.path.basename(file_path).encode(errors="ignore") + b"\n" + data
    lowered = data.lower()
    flattened_wide = lowered.replace(b"\x00", b"")
    findings = []
    for rule in rules:
        matched = _matched_pattern_ids(
            data,
            lowered,
            flattened_wide,
            rule.get("patterns", []),
        )
        required_sets = rule.get("required_sets", [])
        if not any(set(required).issubset(matched) for required in required_sets):
            continue
        findings.append({
            "category": str(rule.get("category", "Unknown")),
            "name": str(rule.get("name", rule.get("id", "Unknown"))),
            "description": str(rule.get("description", "")),
            "severity": str(rule.get("severity", "info")),
            "source": source,
        })
    return findings


def _scan_installer(
    installer_path: str, rules: list[dict[str, Any]]
) -> list[dict[str, str]]:
    seven_zip = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
    if seven_zip is None:
        return []
    findings = []
    try:
        with tempfile.TemporaryDirectory(prefix="portprotonqt-compatibility-") as extract_dir:
            result = subprocess.run(
                [seven_zip, "x", "-y", f"-o{extract_dir}", installer_path],
                capture_output=True,
                check=False,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning("Compatibility report could not extract installer %s", installer_path)
                return []
            extracted = []
            for root, _directories, files in os.walk(extract_dir):
                extracted.extend(
                    os.path.join(root, name)
                    for name in files
                    if name.lower().endswith((".exe", ".dll", ".msi", ".js", ".json", ".node"))
                )
            for file_path in extracted[:COMPATIBILITY_NEIGHBOR_SCAN_LIMIT]:
                findings.extend(
                    _scan_file(file_path, rules, f"Installer: {os.path.basename(file_path)}")
                )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Compatibility report installer scan failed for %s: %s", installer_path, error)
    return findings


def _neighbor_files(executable: str) -> list[str]:
    executable_dir = os.path.realpath(os.path.dirname(executable))
    unsafe_dirs = {
        os.path.realpath(str(Path.home())),
        *(os.path.realpath(str(Path.home() / name))
          for name in ("Downloads", "Desktop", "Documents", "Templates")),
    }
    if executable_dir in unsafe_dirs:
        return []
    try:
        neighbors = [
            os.path.join(executable_dir, name)
            for name in os.listdir(executable_dir)
            if name.lower().endswith(".dll")
        ]
    except OSError:
        return []
    executable_base = os.path.splitext(os.path.basename(executable))[0]
    plugins_dir = os.path.join(executable_dir, f"{executable_base}_Data", "Plugins")
    if os.path.isdir(plugins_dir):
        for root, _directories, files in os.walk(plugins_dir):
            neighbors.extend(
                os.path.join(root, name) for name in files if name.lower().endswith(".dll")
            )
    return neighbors[:COMPATIBILITY_NEIGHBOR_SCAN_LIMIT]


def _add_directory_findings(executable: str, findings: dict[str, list[str]]) -> None:
    executable_dir = os.path.dirname(executable)
    executable_base = os.path.splitext(os.path.basename(executable))[0]
    markers = (
        ("Engine", "Unreal", "Engines"),
        (f"{executable_base}_Data", "Unity", "Engines"),
        ("renpy", "Ren'Py", "Engines"),
        ("www", "RPG Maker", "Engines"),
        ("resources/app.asar", "Electron", "Frameworks"),
        (f"{executable_base}.pck", "Godot", "Engines"),
        (f"{executable_base}.runtimeconfig.json", ".NET Core/5+", "Runtimes"),
        (f"{executable_base}.deps.json", ".NET Core/5+", "Runtimes"),
    )
    for relative_path, name, category in markers:
        if os.path.exists(os.path.join(executable_dir, relative_path)):
            values = findings.setdefault(category, [])
            if name not in values:
                values.append(name)


def _analyze_pe(executable: str) -> tuple[str, dict[str, list[str]]]:
    findings: dict[str, list[str]] = {}
    try:
        pe = pefile.PE(executable, fast_load=True)
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"],
            ]
        )
    except (OSError, pefile.PEFormatError) as error:
        logger.warning("Compatibility report could not parse %s: %s", executable, error)
        return "Unknown", findings

    machine = getattr(pe.FILE_HEADER, "Machine", None)
    architecture = "64-bit" if machine == PE_MACHINE_AMD64 else "32-bit"
    imports = _read_imports(pe)
    for dll_name, (name, category) in DLL_MAPPINGS.items():
        if dll_name in imports and name not in findings.setdefault(category, []):
            findings[category].append(name)
    try:
        optional_header = getattr(pe, "OPTIONAL_HEADER", None)
        data_directories = getattr(optional_header, "DATA_DIRECTORY", [])
        descriptor_index = pefile.DIRECTORY_ENTRY[
            "IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"
        ]
        if not isinstance(descriptor_index, int):
            raise IndexError
        clr = data_directories[descriptor_index]
        if clr.VirtualAddress and ".NET Framework" not in findings.setdefault("Runtimes", []):
            findings["Runtimes"].append(".NET Framework")
    except (AttributeError, IndexError):
        pass
    _add_directory_findings(executable, findings)
    return architecture, findings


def _apply_signature_findings(
    findings: dict[str, list[str]], signature_findings: list[dict[str, str]]
) -> None:
    for item in signature_findings:
        values = findings.setdefault(item["category"], [])
        if item["name"] not in values:
            values.append(item["name"])


def _uses_integrated_gpu(environment: dict[str, str]) -> bool:
    selected_gpu = environment.get("PW_GPU_USE", "")
    if not selected_gpu or selected_gpu == "disabled":
        return False
    return any(
        entry["device_name"] == selected_gpu
        and entry.get("device_type") == "INTEGRATED_GPU"
        for entry in get_selectable_gpu_entries()
    )


def _version_at_least(version: str, required: tuple[int, ...]) -> bool:
    parts = tuple(int(part) for part in re.findall(r"\d+", version)[:len(required)])
    normalized = parts + (0,) * (len(required) - len(parts))
    return bool(parts) and normalized >= required


def _selected_gpu(environment: dict[str, str]) -> dict[str, str] | None:
    entries = get_selectable_gpu_entries()
    selected_name = environment.get("PW_GPU_USE", "")
    if selected_name and selected_name != "disabled":
        return next(
            (entry for entry in entries if entry["device_name"] == selected_name),
            None,
        )
    return entries[0] if entries else None


def _dxvk_driver_requirement(
    gpu: dict[str, str], backend: str,
) -> tuple[str, tuple[int, ...], str] | None:
    vendor_id = gpu.get("vendor_id", "").lower()
    driver_name = gpu.get("driver_name", "").lower()
    if vendor_id == "0x10de" and "nvk" in driver_name:
        return DXVK_NVK_REQUIREMENT
    if vendor_id == "0x10de" and backend == "6":
        return DXVK_NEWEST_NVIDIA_REQUIREMENT
    return DXVK_DRIVER_REQUIREMENTS.get(vendor_id)


def _dxvk_vulkan_compatibility(
    environment: dict[str, str],
) -> tuple[str | None, list[str]]:
    backend = environment.get("PW_VULKAN_USE", "")
    requirement = DXVK_VULKAN_REQUIREMENTS.get(backend)
    if requirement is None:
        return None, []
    backend_name, version_key, required_vulkan = requirement
    dxvk_version = environment.get(version_key, "unknown")
    gpu = _selected_gpu(environment)
    if gpu is None:
        return f"{backend_name} DXVK {dxvk_version}: Vulkan version unknown", []

    api_version = gpu.get("api_version", "unknown")
    required_api = ".".join(map(str, required_vulkan))
    details = f"{backend_name} DXVK {dxvk_version}: Vulkan {api_version} (requires {required_api}+)"
    suggestions = []
    if not _version_at_least(api_version, required_vulkan):
        suggestions.append(
            f"Update the graphics driver: {backend_name} DXVK requires Vulkan {required_api}+."
        )
        if backend != "1" and _version_at_least(api_version, (1, 1)):
            suggestions.append("Switch to Sarek for Vulkan 1.1 drivers.")

    driver_requirement = _dxvk_driver_requirement(gpu, backend)
    if backend not in {"6", "2"} or driver_requirement is None:
        return details, suggestions
    driver_name, required_driver, version_field = driver_requirement
    driver_version = gpu.get(version_field, "unknown")
    required_version = ".".join(map(str, required_driver))
    details += f"; {driver_name} {driver_version} (requires {required_version}+)"
    if not _version_at_least(driver_version, required_driver):
        fallback = "Stable DXVK" if backend == "6" else "Sarek"
        suggestions.append(
            f"Update {driver_name} to {required_version}+ or switch to {fallback}."
        )
    return details, suggestions


def has_dxvk_vulkan_incompatibility(executable: str) -> bool:
    """Return whether configured DXVK cannot run on the selected GPU."""
    environment = get_portproton_env(executable)
    _details, suggestions = _dxvk_vulkan_compatibility(environment)
    return bool(suggestions)


def _glibc_32_compatibility() -> tuple[str, list[str]]:
    if os.path.isfile(I586_ELF_LOADER):
        return "available", []
    return (
        f"unavailable (missing {I586_ELF_LOADER})",
        [
            "Install or enable 32-bit glibc with its ELF loader."
        ],
    )


def _compatibility_suggestions(
    findings: dict[str, list[str]],
    graphics: str,
    shipping_executable: str,
    environment: dict[str, str],
) -> list[str]:
    suggestions = []
    if shipping_executable:
        suggestions.append(f"Try launching the game binary instead: {shipping_executable}")
    uses_directx_8_11 = any(
        version in graphics
        for version in ("DirectX 8", "DirectX 9", "DirectX 10", "DirectX 11")
    )
    if uses_directx_8_11 and environment.get("PW_VULKAN_USE") == "0":
        suggestions.append("Switch from WineD3D to DXVK for DirectX 8-11.")
    if _uses_integrated_gpu(environment):
        suggestions.append("Use the discrete GPU.")
    runtimes = findings.get("Runtimes", [])
    prefix_name = environment.get("PW_PREFIX_NAME", "DEFAULT")
    needs_dotnet = any(".NET" in runtime for runtime in runtimes)
    needs_dotnet = needs_dotnet or "WPF" in findings.get("Frameworks", [])
    if needs_dotnet and prefix_name != "DOTNET":
        suggestions.append("Use the DOTNET prefix.")
    installers = findings.get("Installer", [])
    wine_version = environment.get("PW_WINE_USE", "")
    if installers and not wine_version.startswith("WINE_LG"):
        suggestions.append("Use WINE_LG for installers.")
    winetricks_log = environment.get("PW_WINETRICKS_LOG", "").lower()
    missing_vcrun = [
        components[-1]
        for runtime, components in VCRUN_COMPONENTS.items()
        if runtime in runtimes
        and not any(component in winetricks_log for component in components)
    ]
    if missing_vcrun:
        suggestions.append(
            f"Install {', '.join(missing_vcrun)} through Winetricks."
        )
    if "PhysX" in findings.get("Physics", []) and "physx" not in winetricks_log:
        suggestions.append("Install physx through Winetricks.")
    return list(dict.fromkeys(suggestions))


def _format_signature_details(items: list[dict[str, str]]) -> list[str]:
    lines = []
    seen = set()
    for item in items:
        key = (item["category"], item["name"])
        if key in seen:
            continue
        seen.add(key)
        severity = item["severity"].upper()
        lines.append(
            f"- [{severity}] {item['category']}: {item['name']} "
            f"({item['source']}) — {item['description']}"
        )
    return lines


def analyze_launch(launch: CompatibilityLaunch, portproton_path: str) -> str:
    """Build a local compatibility report for a failed launch."""
    architecture, findings = _analyze_pe(launch.executable)
    rules = _load_rules()
    signature_findings = _scan_file(launch.executable, rules, "Main executable")
    for neighbor in _neighbor_files(launch.executable):
        signature_findings.extend(_scan_file(neighbor, rules, f"Neighbor: {os.path.basename(neighbor)}"))
    has_installer = launch.executable.lower().endswith(".msi") or any(
        item["category"] == "Installer" for item in signature_findings
    )
    if has_installer:
        signature_findings.extend(_scan_installer(launch.executable, rules))
    _apply_signature_findings(findings, signature_findings)
    graphics = analyze_executable(launch.executable)
    graphics_executable = str(graphics.get("source", launch.executable))
    graphics_name = os.path.basename(graphics_executable).lower()
    shipping_executable = (
        graphics_executable if graphics_name.endswith(("-win64-shipping.exe", "-win32-shipping.exe"))
        else ""
    )
    detected_graphics = str(graphics["highest_directx"])
    if graphics["uses_opengl"]:
        detected_graphics = f"{detected_graphics}, OpenGL"
    environment = get_portproton_env(launch.executable)
    prefix_name = get_prefix_name(launch.executable)
    environment.setdefault("PW_PREFIX_NAME", prefix_name)
    environment["PW_WINETRICKS_LOG"] = get_winetricks_log(
        portproton_path, environment["PW_PREFIX_NAME"]
    )
    suggestions = _compatibility_suggestions(
        findings,
        detected_graphics,
        shipping_executable,
        environment,
    )
    dxvk_compatibility, version_suggestions = _dxvk_vulkan_compatibility(environment)
    suggestions.extend(version_suggestions)
    glibc_32_compatibility, glibc_32_suggestions = _glibc_32_compatibility()
    suggestions.extend(glibc_32_suggestions)
    lines = [
        f"Executable: {launch.executable}",
        f"Exit code: {launch.exit_code if launch.exit_code is not None else 'unknown'}",
        f"Runtime before exit: {launch.duration:.1f} s",
        f"Architecture: {architecture}",
        f"Prefix: {prefix_name}",
        f"Wine/Proton: {get_wine_version(portproton_path, launch.executable)}",
        f"Configured 3D API: {get_vulkan_use_info(portproton_path, launch.executable)}",
        f"Detected 3D API: {detected_graphics}",
        f"32-bit glibc: {glibc_32_compatibility}",
    ]
    if dxvk_compatibility:
        lines.append(f"DXVK/Vulkan compatibility: {dxvk_compatibility}")
    if graphics_executable != launch.executable:
        lines.append(f"3D API source: {graphics_executable}")
    if environment.get("PW_WINDOWS_VER"):
        lines.append(f"Windows version: {environment['PW_WINDOWS_VER']}")
    for category, values in findings.items():
        if values:
            lines.append(f"Detected {category}: {', '.join(values)}")
    detail_lines = _format_signature_details(signature_findings)
    if detail_lines:
        lines.extend(("", "Detection details:", *detail_lines))
    if suggestions:
        lines.extend(("", "Possible fixes:", *(f"- {item}" for item in suggestions)))
    return "\n".join(lines)
