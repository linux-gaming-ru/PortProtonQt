#!/usr/bin/env python3
"""Synchronize GPU names with Wine without rewriting the surrounding header."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "build-aux/src/wine_gpu_names.h"
WINE_REPOSITORY = "https://github.com/wine-mirror/wine.git"
WINE_SOURCE = "dlls/win32u/sysparams.c"
NETWORK_TIMEOUT = 30
MAX_SOURCE_BYTES = 2 * 1024 * 1024
C_STRING = r'"(?:[^"\\\r\n]|\\[^\r\n])*"'
WINE_ROW = re.compile(
    r'case\s+MAKELONG\(\s*(0x[0-9a-fA-F]+)\s*,\s*(0x[0-9a-fA-F]+)\s*\)'
    r'\s*:\s*return\s+(' + C_STRING + r')\s*;'
)
HEADER_ROW = re.compile(
    r'^    \{(0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+), (' + C_STRING + r')\},$', re.M,
)
TABLE = re.compile(r'(\} wine_gpu_names\[\] = \{\n)(.*?)(\n\};)', re.S)


def parse_wine_names(source):
    function = re.search(
        r'\bconst char\s*\*gpu_device_name\([^)]*\)\s*\{(.*?)\n\};', source, re.S,
    )
    if function is None:
        raise ValueError("Wine gpu_device_name() was not found")
    body = function.group(1)
    rows = WINE_ROW.findall(body)
    if not rows or len(rows) != len(re.findall(r'\bcase\b', body)):
        raise ValueError("Wine GPU table is empty or contains unsupported cases")
    result = []
    seen = set()
    for vendor, device, name in rows:
        identity = (int(vendor, 16), int(device, 16))
        if identity in seen or any(value > 0xffff for value in identity) or name == '""':
            raise ValueError(f"Invalid or duplicate Wine GPU entry: {vendor}:{device}")
        seen.add(identity)
        result.append((f"0x{identity[0]:04x}", f"0x{identity[1]:04x}", name))
    return result


def update_header(header, source, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError("Invalid Wine source revision")
    rows = parse_wine_names(source)
    tables = list(TABLE.finditer(header))
    if len(tables) != 1:
        raise ValueError("Expected exactly one wine_gpu_names array in the header")
    table = tables[0]
    existing = HEADER_ROW.findall(table.group(2))
    if not existing or len(existing) != len(table.group(2).strip().splitlines()):
        raise ValueError("Unsupported existing header table format")
    if rows == existing:
        return header
    replacement = "\n".join(f"    {{{vendor}, {device}, {name}}}," for vendor, device, name in rows)
    updated = header[:table.start(2)] + replacement + header[table.end(2):]
    updated, count = re.subn(r'^// Revision: [0-9a-f]{40}$', f"// Revision: {revision}", updated, flags=re.M)
    if count != 1:
        raise ValueError("Expected exactly one Wine revision comment")
    return updated


def main():
    print("Resolving Wine master revision...", flush=True)
    refs = subprocess.run(
        ["git", "ls-remote", WINE_REPOSITORY, "refs/heads/master"],
        capture_output=True, text=True, check=True, timeout=NETWORK_TIMEOUT,
    ).stdout.split()
    if len(refs) != 2 or not re.fullmatch(r'[0-9a-f]{40}', refs[0]):
        raise ValueError("Could not resolve Wine master revision")
    revision = refs[0]
    url = f"https://raw.githubusercontent.com/wine-mirror/wine/{revision}/{WINE_SOURCE}"
    print(f"Fetching Wine GPU names at {revision}...", flush=True)
    with urlopen(url, timeout=NETWORK_TIMEOUT) as response:
        source = response.read(MAX_SOURCE_BYTES + 1)
    if len(source) > MAX_SOURCE_BYTES:
        raise ValueError("Wine source exceeds the download size limit")
    header = HEADER.read_text(encoding="utf-8")
    updated = update_header(header, source.decode("utf-8"), revision)
    if updated == header:
        print("Wine GPU names are unchanged.")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=HEADER.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(updated)
        temporary.chmod(HEADER.stat().st_mode & 0o777)
        os.replace(temporary, HEADER)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Updated {len(parse_wine_names(source.decode('utf-8')))} Wine GPU names.")


if __name__ == "__main__":
    main()
