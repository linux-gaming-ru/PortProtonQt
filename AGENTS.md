# PortProtonQt — AI Agent Guidelines

**Project:** PortProtonQt — Game library manager and launcher for Linux
**Language:** Python 3.11+
**Platform:** Linux (POSIX)
**License:** GPL-3.0
**Build:** Meson + uv

---

**Summary:** AI agents MUST behave as conservative patching assistants, prioritizing minimal changes and existing patterns over architectural refactoring or code cleanup. AI MUST NOT perform architectural improvements unless explicitly requested.

**Scope:** These guidelines apply exclusively to AI-generated code. Documentation updates and human maintainers are exempt from line limits and these constraints.

## License and Attribution

- All code MUST be compatible with GPL-3.0.
- AI agents MUST NOT add `Signed-off-by` tags.

When AI contributes to the project, add an `Assisted-by` tag:

`Assisted-by: AGENT_NAME:MODEL_VERSION`

Where:
- `AGENT_NAME` is the AI agent or framework name.
- `MODEL_VERSION` is the specific model version.

Example:

`Assisted-by: Claude:claude-3-opus`

---

## Core Principles

| Principle | Required | Forbidden |
|-----------|----------|-----------|
| KISS | New/rewritten functions ≤50 lines | Deep nesting |
| YAGNI | Concrete code | Future abstractions |
| DRY | Extract methods (if directly related to task) | Copy-paste |
| SRP | 1 task per method | God functions |
| Linux | POSIX paths, shebangs | Windows-specific code |
| Minimal changes | Modify relevant section only | Rewrite entire files |

**Priority order (highest to lowest):**

1. Minimal changes (overrides DRY, SRP)
2. Security (no shell=True, no hardcoded credentials)
3. Linux compatibility
4. KISS / YAGNI
5. DRY / SRP

**When principles conflict:**

- Prefer minimal diff over extracting methods
- Prefer existing patterns over "correct" refactoring
- Prefer small targeted fix over comprehensive cleanup
- Never break security for code quality
- Remove duplicates only if directly related to current task
- Do not split untouched legacy functions only to satisfy line limits
- Do not rewrite untouched legacy files or blocks only to satisfy metrics

---

## Code Metrics

| Check | Limit |
|-------|-------|
| Functions | ≤50 lines, ≤4 params (required for new/fully rewritten functions) |
| Files | ≤800 lines (required for new/fully rewritten files) |
| Nesting | ≤4 levels (required in new/modified code) |
| Comments | English, 1-2 lines max |
| Indentation | 4 spaces (no tabs) |
| Whitespace | No trailing spaces |
| Blank lines | No excessive blank lines |
| EOF | Exactly one newline |
| Commits | English, ≤72 chars |

---

## Commit Classification

Use Conventional Commit prefixes according to the primary purpose of the change:

| Prefix | Use for |
|--------|---------|
| `feat` | A new user-facing capability or supported workflow |
| `fix` | A correction for a confirmed defect or regression in existing behavior |
| `chore` | Maintenance, integration adjustments, filtering, metadata, or routine upkeep that is neither a feature nor a confirmed bug fix |
| `refactor` | Internal restructuring with no intended behavior change |
| `perf` | A measurable performance improvement |
| `test` | Test-only changes |
| `docs` | Documentation-only changes |
| `build` | Build system or dependency changes |
| `ci` | CI or automation configuration changes |
| `style` | Formatting-only changes with no behavior change |
| `revert` | Reverting an earlier commit |

- Classify by intent, not merely by whether code behavior changed.
- Do not default to `fix` for every behavioral correction or edge-case filter.
- Use `fix` only when the task identifies a bug/regression or the defect is clearly demonstrated.
- If `feat`, `fix`, and `chore` are ambiguous, prefer `chore` unless the task clearly establishes a new capability or confirmed defect.

---

## Forbidden Patterns

```python
# NEVER: 6+ parameters
def process_game(user, ctx, log, val, map, cache): ...

# NEVER: Deep nesting
if c1:
    if c2:
        if c3:
            if c4: ...

# NEVER: print statements
print(f"Game {name} started")

# NEVER: shell=True
subprocess.run(cmd, shell=True)

# NEVER: Hardcoded credentials
API_KEY = "sk-abc123"

# NEVER: Path traversal
file_path = f"/data/{user_filename}"

# NEVER: Hardcoded styles or constants (colors, sizes, etc.)
shadow.setBlurRadius(20)
shadow.setColor(QColor(0, 0, 0, 150))
label.setStyleSheet("color: #bbbbbb;")
QColor(128, 128, 128)

# NEVER: Unexplained magic numbers in business logic
# Status codes, flags, timeouts, limits, protocol values — use named constants or enums
if status == 3: ...                    # BAD
if key_value >= 0x01000000: ...        # BAD

# NEVER: Visual constants in application code (game_card.py, detail_pages/, etc.)
# ALL visual/layout constants MUST live in themes/standart/styles/constants.py
# Application code reads them via self.theme.CONSTANT_NAME
COMPACT_CARD_WIDTH_THRESHOLD = 150  # BAD: in game_card.py
RIBBON_SIZE_RATIO = 0.28           # BAD: in game_card.py
BADGE_ICON_SIZE = 16               # BAD: in detail_pages/widgets.py
SOURCE_CORNER_RATIO = 0.28         # BAD: in detail_pages/widgets.py
```

```python
# ALWAYS: ≤4 parameters
def process_game(game_id: str, config: dict) -> Game:
    """Process game data."""
    ...

# ALWAYS: Early returns
if not condition1:
    return
if not condition2:
    return

# ALWAYS: Logging
from portprotonqt.logger import get_logger
logger = get_logger(__name__)
logger.info("Game %s started", name)

# ALWAYS: Explicit subprocess arguments
subprocess.run(["cmd", "arg1", "arg2"])

# ALWAYS: Environment variables
API_KEY = os.getenv("API_KEY")

# ALWAYS: Sanitize paths
file_path = os.path.join(BASE_DIR, os.path.basename(user_filename))

# ALWAYS: Use theme constants for styles
shadow.setBlurRadius(self.theme.shadow_blur_radius)
shadow.setColor(QColor(self.theme.color_shadow_card))
label.setStyleSheet(self.theme.CONTENT_STYLE)
QColor(self.theme.color_disabled_text)

# ALWAYS: Add new constants to theme files
# New colors → portprotonqt/themes/standart/styles/constants.py
# New QSS styles → portprotonqt/themes/standart/styles/base.py or submodule

# ALWAYS: Use descriptive named constants, enums, or built-in Qt values instead of magic numbers
STATUS_COMPLETED = 3

if status == STATUS_COMPLETED:
    ...

# ALWAYS: Use named Qt.Key constants with comments for keyboard system key checks
# Skip system/modifier keys (Shift, Enter, Arrow keys, etc.)
if key_value >= Qt.Key.Key_Escape.value: ...
```

---

## Code Modification Rules

- NEVER rewrite entire file unless explicitly requested
- Modify only the relevant section
- Preserve existing architecture and naming
- Do not auto-format unrelated code
- Do not change formatting-only lines without explicit user request
- Do not reorder imports unless necessary
- Do not introduce abstractions without request
- Do not change logging system
- Do not change public APIs without reason
- Do not add dependencies unless required
- Do not refactor unrelated code
- Do not modify localization files (`portprotonqt/locales/`) unless explicitly requested
- Do not extract single-use logic into a helper function without a clear need
- **Before adding any helper, wrapper, class, or infrastructure, search for an existing method that already performs the operation and call it directly**
- **NEVER add a task-local helper that only wraps an existing method or a single call; keep the call in the modified block unless extraction is required by the function limits**
- If the user identifies overengineering, remove the unnecessary abstraction before continuing; do not layer another fix on top of it
- Do not add comments for obvious code
- **NEVER leave outdated comments after refactoring** (e.g., "without numpy" after numpy removal, "legacy" after rewrite)
- **ALWAYS update or remove comments that reference removed dependencies, patterns, or context**
- **NEVER leave stub/no-op functions** (e.g., `def func(): pass` with comment "removed")
- **When removing a feature, delete the function entirely, not stub it**
- When removing async/download code, preserve callback completion paths in callers
- Add or update regression tests for callback-driven UI loading paths touched by the change
- Never invent modules
- Do not move files unless requested
- Do not create new files for organization (unless task requires a new module)
- No circular imports
- Prefer dedicated functions for subprocess calls when practical within task scope
- No shared mutable global state (except logger and explicit cache/session infrastructure)

**ALWAYS:**

- Minimal diff
- Targeted changes only
- Preserve existing patterns
- Keep surrounding code unchanged
- Keep formatting changes limited to touched logic or required hook fixes
- **NEVER delete existing style constants from theme files (QSS strings like `*_STYLE`). All styles must be preserved during rewrites. Deleted styles break child theme inheritance.**

---

## LLM Prohibitions

**Specific prohibitions for AI-generated code:**

- Add type hints to existing code unless requested (new code MUST include type hints)
- Replace existing patterns with "better" alternatives
- Consolidate similar code blocks
- Extract methods or functions without request
- Add validation or error handling outside the modified block unless it fixes a security issue or directly supports the current change
- Generate boilerplate or scaffolding
- Add configuration options
- Create new files for "organization" (unless explicitly requested for a new module)
- Split or merge existing modules
- Change function signatures
- Modify docstrings unnecessarily
- Add or remove blank lines for "style"
- Normalize or standardize code patterns
- Invent CLI arguments, config files, API endpoints, environment variables, theme structures, or localization keys

---

## AI Permissions

AI agents MAY:
- Fix obvious bugs within the modified block
- Improve variable naming inside the modified block
- Add missing logging if required by policy
- Add missing validation or error handling in new/modified code when required by this policy
- Add missing type hints in new functions

---

## Performance Rules

- No blocking I/O in UI thread
- No synchronous HTTP in UI thread
- Cache API responses in `~/.cache/PortProtonQt`
- Avoid repeated disk reads in loops
- Avoid O(n²) in game lists
- Lazy load images
- Limit threads to CPU cores

### Clarification: "No Shared Mutable Global State" Does NOT Mean Removing Caches

Rule intent: avoid shared mutable globals that hold application state or cause hidden side effects.

This does not prohibit:
- Module-level cache constants (e.g., cache TTL values)
- Dedicated cache managers or classes with explicit lifecycle
- Disk caches under `~/.cache/PortProtonQt`
- `requests.Session()` objects if they are encapsulated and not mutated unpredictably

Do not delete or disable caching or downloaders to satisfy this rule. Caching is required by the Performance Rules ("Cache API responses in `~/.cache/PortProtonQt`" and "Avoid repeated disk reads in loops").

---

## PySide6 Rules

- No business logic in widgets
- Use signals/slots (no direct coupling)
- No heavy operations in paintEvent
- Use methods instead of lambda for complex logic
- Use QThread for long tasks

---

## Refactoring Constraints

- Max 1 business module per task (unless explicitly requested)
- Related technical files are allowed in the same task (`meson.build`, tests, theme constants)
- Preserve git blame
- Avoid renaming unless necessary

---

## When Uncertain

Ask before proceeding if unsure about:
- Architecture
- Naming
- Design decisions

Do not assume conventions. Never invent behavior.

---

## Development Workflow

```bash
# Setup
uv python install 3.11
uv sync
source .venv/bin/activate
pre-commit install --install-hooks

# Run
portprotonqt

# Manual checks
pre-commit run --all-files

# Build
meson setup builddir && meson compile -C builddir

# Localization
python dev-scripts/l10n.py --update-all
python dev-scripts/l10n.py

# Commit
git commit -m "feat: description in English ≤72 chars"
```

### Pre-commit Hooks

| Hook | Checks |
|------|--------|
| uv-lock | uv.lock up to date |
| ruff-check | Linting (E, W, F, B, C4, UP) |
| pyright | Type checking |
| pytest | Unit tests |
| bash-n | Bash syntax check and shebang `CRLF` check for `build-aux/share/portproton/scripts/` |
| check-meson | meson.build syntax + files |
| check-qss-properties | Theme QSS validation |
| trailing-whitespace | Whitespace cleanup |
| end-of-file-fixer | EOF newline |

### Linting and Type-Checking

AI agents MUST NOT run linting or type-checking tools directly.

#### Forbidden

- Running `ruff`
- Running `pyright`
- Running `uv run ruff`
- Running `uv run pyright`
- Running any linter/type checker binary directly
- Installing dev tools automatically

These tools are executed ONLY via pre-commit hooks.

#### Allowed

- `pre-commit run --all-files`
- `pre-commit run ruff-check`
- `pre-commit run pyright`
- `pre-commit run pytest`

#### Rationale

`ruff` and `pyright` are managed by pre-commit.
Direct execution bypasses project configuration and is forbidden.

Do not attempt to execute binaries manually.

---

## Testing

### Structure

```
tests/
├── conftest.py              # Shared fixtures (tmp_config_dir, sample_steam_apps)
├── test_utils.py            # Steam API utils (normalize_name, search, VDF, Steam utils)
├── test_validators.py       # Config validators (string, int, bool, path, url)
├── test_cache_manager.py    # CacheManager (save/load/TTL/atomic writes)
├── test_appimage_updater.py # AppImage auto-update worker, mirrors, changelog parsing
├── test_dark_theme.py       # Dark theme detection (XFCE/MATE/Cinnamon/GNOME)
├── test_steam_cache.py      # exiftool skip, cache eviction, delete_cached_app_files
├── test_base_config.py      # BaseConfig read/write, caching, versioning
├── test_cli.py              # normalize_launch_path, URL/resolution parsing
├── test_debug_env_utils.py  # Debug environment helpers, runtime variables
├── test_input_manager.py    # Gamepad input navigation and focus regressions
├── test_sound_manager.py    # UI sound playback, widget events, gamepad connection, theme sound files
├── test_main_window.py      # Main window data processing and callback regressions
├── test_portproton_config.py # exec_line parsing, launcher tail, extensions
├── test_portproton_api.py   # PPDB API helpers, autoinstall localization fallback
├── test_autoinstall_status.py # Autoinstall installed-status matching regressions
├── test_migration.py        # Desktop shortcut migration, prefix backup, squashfs
├── test_file_explorer.py    # File explorer themed icon state regressions
├── test_icon_extractor.py   # NE/PE icon extraction, DIB decoding, thumbnails
├── test_dbus_tools.py       # D-Bus tools (notifications, idle inhibit, power profiles)
├── test_time_utils.py       # Playtime parsing, last launch cache, formatting
├── test_shortcuts.py        # Desktop shortcut creation, paths with spaces, .desktop entry
├── test_theme_store.py      # Theme store UI worker lifecycle and race regressions
├── test_theme_manager.py    # Theme AST injection, parent resolution, ThemeWrapper, style integrity
├── test_theme_security.py   # Theme security checker (allowlist AST, forbidden modules/methods, SVG/font/image safety)
├── test_settings_search.py  # MangoHud, vkBasalt, Gamescope settings search and layout regressions
├── test_detail_pages.py     # Detail page gradient stops, wave background modes, palette handling
└── test_proton_manager.py   # Local Wine/Proton drag-and-drop and safe archive extraction
```

### Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_utils.py -v

# Run specific test class
uv run pytest tests/test_utils.py::TestNormalizeName -v

# Run with pre-commit
pre-commit run pytest
```

### Writing Tests

- Tests MUST use `pytest` with `tmp_path` fixture for file isolation
- Tests MUST mock external resources (network, system paths, env vars)
- Tests MUST NOT depend on system state (installed apps, real Steam dirs)
- Use `monkeypatch` for environment variables and function patching
- Keep tests locale-independent: assert stable identifiers or numbers instead of translated strings; resolve values created through `_()` from the same application mapping using stable identifiers; use `monkeypatch` to provide deterministic text when testing translated search or matching
- Test regression scenarios from git fix commits

### Key Regression Areas

| Module | Regression | Commit |
|--------|-----------|--------|
| `time_utils` | Spaced exe names in cache | 764bb3c |
| `time_utils` | SHA256 hash + L5- index | 7a02b6b |
| `time_utils` | Malformed playtime data | dd65021 |
| `theme_manager` | AST injection lost dict constants, leaked CONTAINER_STYLE | 519edd1 |
| `theme_manager` | Recursive load_theme when styles.py calls get_icon during exec_module | d5fedd8 |
| `classic/styles.py` | Missing styles after theme rewrite (NAV, COMBOBOX, TAB, etc.) | 519edd1 |
| `classic-light/styles.py` | NameError: border_none not defined (no styles/constants.py) | 519edd1 |
| `detail_pages` | DETAIL_PAGE_GRADIENT stops override, wave background modes | — |
| `detail_pages` | Edit/Add shortcut buttons shown together for non-Steam games | 7e38d9a |
| `wine_extractor` | Archive traversal and process-wide cwd changes during extraction | — |

---

## AI Agent Checklist

### Writing Code

- [ ] New/rewritten functions ≤50 lines, ≤4 params
- [ ] New/modified code nesting ≤4 levels
- [ ] LF line endings, 4-space indent
- [ ] No excessive blank lines, no trailing whitespace
- [ ] Type hints (required for new code)
- [ ] Logging via `portprotonqt.logger`
- [ ] New/modified code handles expected/recoverable failures
- [ ] New installable Python files added to `portprotonqt/meson.build`
- [ ] If CLI arguments are changed: update `dev-scripts/generate-completions.sh` (do not regenerate `completions/` unless explicitly requested for build/release)
- [ ] Comments in English, concise
- [ ] No circular imports introduced by the change
- [ ] Prefer dedicated functions for subprocess calls when practical within task scope
- [ ] No shared mutable global state (except logger and explicit cache/session infrastructure)
- [ ] No blocking calls introduced in the UI thread
- [ ] **No hardcoded styles or constants (use theme constants)**
- [ ] **New constants added to theme files only**

### Refactoring

- [ ] No code duplicates (only if directly related to current task)
- [ ] No unused imports
- [ ] No commented-out code
- [ ] No TODO without tickets
- [ ] Clear variable names

### Dependencies

- [ ] Prefer standard library
- [ ] No heavy frameworks
- [ ] No async frameworks (use QThread instead)
- [ ] No additional logging libraries
- [ ] License GPL-3.0 compatible
- [ ] If dependencies are added: added to `pyproject.toml`
- [ ] If dependencies change: `uv lock` run

---

## Error Handling Policy

### When to Rethrow

| Condition | Action | Example |
|-----------|--------|---------|
| Cannot handle locally | Rethrow | API errors in business logic |
| Need to add context | Wrap & rethrow | `raise ValueError(f"Invalid game ID: {game_id}") from e` |
| Public API boundary | Rethrow | Let caller decide |
| Expected & recoverable | Handle with fallback (log when useful) | Cache miss → fetch from source |

```python
# Bad: Silent swallow
try:
    data = load_config()
except Exception:
    pass

# Good: Rethrow with context
try:
    data = load_config()
except FileNotFoundError as e:
    raise ConfigError(f"Config not found: {path}") from e
```

### When to Log and Continue

| Condition | Action | Example |
|-----------|--------|---------|
| Non-critical failure | Log, continue | Thumbnail download failed |
| Fallback available | Log, use fallback | Cache miss → network request |
| Best-effort operation | Log, skip | Optional metadata |
| User notification only | Log, notify UI | Network timeout |

```python
# Log and continue for non-critical
try:
    cover = download_cover(url)
except requests.RequestException as e:
    logger.warning("Cover download failed: %s", e)
    cover = QPixmap()  # Use placeholder
```

### When to Fail Fast

| Condition | Action | Example |
|-----------|--------|---------|
| Critical dependency | Raise immediately | Database connection lost |
| Data corruption | Raise immediately | Invalid config format |
| Security violation | Raise immediately | Path traversal attempt |
| Unrecoverable state | Raise immediately | Missing required file |

```python
# Fail fast for critical
if not config_path.exists():
    raise ConfigError(f"Required config missing: {config_path}")
```

### Exception Hierarchy

```python
# Base exception for application errors
class PortProtonError(Exception):
    """Base exception for PortProtonQt."""

# Domain-specific exceptions
class ConfigError(PortProtonError):
    """Configuration-related errors."""

class APIError(PortProtonError):
    """External API errors."""

class ValidationError(PortProtonError):
    """Input validation errors."""

class ParseError(PortProtonError):
    """Parsing-related errors."""
```

### Error Handling Patterns

```python
# Pattern 1: Guard clauses for validation
def process_game(game_id: str) -> Game:
    if not game_id:
        raise ValidationError("Game ID required")
    ...

# Pattern 2: Context manager for resources
with open(path) as f:
    data = json.load(f)

# Pattern 3: Specific exception handling
try:
    response = requests.get(url, timeout=5)
except requests.Timeout:
    logger.warning("Request timeout for %s", url)
    return None
except requests.ConnectionError:
    logger.error("Connection failed for %s", url)
    raise APIError("Network unavailable") from None

# Pattern 4: Exception chaining
try:
    value = int(text)
except ValueError as e:
    raise ParseError(f"Invalid integer: {text}") from e
```

### UI Thread Rules

| Context | Strategy |
|---------|----------|
| UI thread | Never block, use signals for errors |
| Worker thread | Catch, emit error signal |
| Async operations | Return error in result tuple |

```python
# Worker thread pattern
def run_in_thread():
    try:
        result = long_operation()
        success_signal.emit(result)
    except Exception as e:
        logger.error("Operation failed: %s", e)
        error_signal.emit(str(e))
```

### Logging Guidelines

| Level | When to Use |
|-------|-------------|
| DEBUG | Detailed diagnostic info |
| INFO | Normal operation events |
| WARNING | Recoverable issues |
| ERROR | Failures requiring attention |
| CRITICAL | System-wide failures |

```python
# Log with context
logger.error("Failed to load game %s: %s", game_id, e)

# Include stack trace for unexpected errors
try:
    ...
except Exception as e:
    logger.exception("Unexpected error processing %s", game_id)
```

### Forbidden Patterns

```python
# NEVER: Bare except
try:
    ...
except:
    pass

# NEVER: Catch Exception without logging
try:
    ...
except Exception:
    pass

# NEVER: Silent failures in critical paths
if not critical_file.exists():
    return None  # Should raise

# NEVER: Multiple exceptions in one handler (unless re-throwing as a unified domain exception)
try:
    ...
except (FileNotFoundError, ValueError, TypeError, KeyError):
    pass  # Each needs separate handling
```

---

## Code Style

### Imports
```python
# Standard library
import os
from pathlib import Path

# Third-party
from PySide6.QtWidgets import QApplication
import requests

# Local
from portprotonqt.steam_api import SteamAPI
from portprotonqt.logger import get_logger
```

### Type Hints
```python
def get_game(game_id: str, cache: dict | None = None) -> Game | None:
    ...

class Game:
    name: str
    playtime: int
    cover_url: str | None
```

### Theme Constants
All style-related constants MUST be defined in theme files, not in application code.

**File structure for theme constants:**
- `portprotonqt/themes/standart/styles/constants.py` — Color constants, sizes, shadow values
- `portprotonqt/themes/standart/styles/base.py` — Global widget styles (MAIN_WINDOW_STYLE, etc.)
- `portprotonqt/themes/standart/styles/game_card.py` — Game card specific styles
- `portprotonqt/themes/standart/styles/detail_page.py` — Detail page styles
- `portprotonqt/themes/standart/styles/settings.py` — Settings dialog styles
- `portprotonqt/themes/standart/styles/get_wine.py` — Wine manager styles
- `portprotonqt/themes/standart/styles/winetricks.py` — Winetricks styles
- `portprotonqt/themes/standart/styles/theme_utils.py` — Utility styles (context menus, etc.)

**Adding new constants:**
```python
# In constants.py — add color constant
color_new_feature = "#FF5733"

# In constants.py — add size constant
new_widget_size = 42

# In base.py or submodule — add QSS style
NEW_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_new_feature};
        border-radius: {border_radius_a};
    }}
"""
```

**Usage in application code:**
```python
# Bad: Hardcoded in application code
shadow.setBlurRadius(20)
label.setStyleSheet("color: #bbbbbb;")

# Good: Use theme constants
shadow.setBlurRadius(self.theme.shadow_blur_radius)
label.setStyleSheet(self.theme.CONTENT_STYLE)
```

**Tooltip rule:**
- Prefer the themed `gamepad_tooltip`/`TOOLTIP_STYLE` mechanism for in-app `QWidget` tooltips
- Avoid `setToolTip()` for regular widgets when the themed tooltip can be used
- `setToolTip()` is acceptable only for APIs that are not regular widgets, such as `QSystemTrayIcon`

### Comments
```python
# NEVER: Russian or verbose
# Проверить существование файла

# ALWAYS: Concise English
# Check if file exists
if os.path.exists(path):
    ...

# ALWAYS: Docstrings for public APIs
def check_file_exists(path: str) -> bool:
    """Check if file exists at given path."""
    ...
```

---

## Code Review Guidelines

Review scope: prioritize new/modified code. Existing unrelated legacy issues should not block unless they are CRITICAL security issues. Development scripts under `dev-scripts/` follow their exemption rules unless explicitly requested.

### Security (CRITICAL)

- Hardcoded credentials
- SQL injection risks
- Missing input validation on external boundaries (user input, files, network, subprocess args)
- Insecure dependencies
- Path traversal risks
- `shell=True` in subprocess

### Code Quality (HIGH)

- New/rewritten functions >50 lines
- New/rewritten functions >4 params
- New/rewritten files >800 lines
- New/modified code nesting >4 levels
- Missing error handling for expected/recoverable failures in new/modified code
- Circular imports introduced by the change
- Shared mutable global state introduced in new/modified code (except logger and explicit cache/session infrastructure)
- Blocking calls introduced in the UI thread

### Performance (MEDIUM)

- O(n²) when O(n log n) possible
- Missing caching
- N+1 queries

### Best Practices (MEDIUM)

- Emoji usage
- TODO without tickets
- Poor variable naming (x, tmp, data)
- Unexplained magic numbers in business logic (status codes, flags, timeouts, limits, protocol values)
- Non-English comments
- **Hardcoded styles or constants (colors, sizes, shadow values, etc.)**

### Review Output

```
[CRITICAL] Hardcoded API key
File: portprotonqt/steam_api.py:42
Issue: API key exposed in source code
Fix: Use environment variable

API_KEY = "sk-abc123"  # Bad
API_KEY = os.getenv("API_KEY")  # Good

[MEDIUM] Hardcoded style value
File: portprotonqt/game_card.py:81
Issue: Shadow color hardcoded instead of using theme
Fix: Use theme constant

shadow.setColor(QColor(0, 0, 0, 150))  # Bad
shadow.setColor(QColor(self.theme.color_shadow_card))  # Good

[MEDIUM] Hardcoded style constant in application code
File: portprotonqt/game_card.py:52
Issue: Visual constant defined in application code instead of theme
Fix: Add to themes/standart/styles/constants.py and read via self.theme

COMPACT_CARD_WIDTH_THRESHOLD = 150  # Bad: in game_card.py
# In constants.py: COMPACT_CARD = {"width_threshold": 150, ...}
# In game_card.py: self.theme.COMPACT_CARD["width_threshold"]  # Good
```

### Approval

- **Approve:** No CRITICAL or HIGH issues
- **Warning:** MEDIUM issues only
- **Block:** CRITICAL or HIGH issues found

---

## Meson Build Guidelines

The `check-meson` hook validates `meson.build` on commit.

**Checks:**
- Syntax: brackets, quotes, commas, control structures
- All `.py` files in `install_data()`
- No duplicates or missing files

### Adding Files

```meson
# portprotonqt/meson.build
install_data(
  ['existing.py',
   'new_module.py',
  ],
  install_dir: pythondir / meson.project_name(),
)
```

### Common Errors

```meson
# Bad: Missing comma      # Bad: Unclosed
install_data(             install_data(
  'file1.py'                'file1.py',
  'file2.py'                'file2.py'
)                         # Missing )

# Good
install_data(
  'file1.py',
  'file2.py',
)
```

---

## Project Structure

```
PortProtonQt/
├── portprotonqt/                    # Python package
│   ├── animations/                  # UI animation modules
│   │   ├── detail_background.py
│   │   ├── detail_page.py
│   │   ├── game_card.py
│   │   ├── library_controls.py
│   │   └── virtual_keyboard.py
│   ├── config/                      # Application configuration
│   │   ├── base.py
│   │   ├── cache.py
│   │   ├── display.py
│   │   ├── favorites.py
│   │   ├── game.py
│   │   ├── gamepad.py
│   │   ├── portproton.py
│   │   ├── proxy.py
│   │   ├── ui.py
│   │   ├── validators.py
│   │   └── window.py
│   ├── debug_utils/                 # Debug data collection and processing
│   │   ├── debug_log_manager.py
│   │   ├── env_utils.py
│   │   ├── game_debug.py
│   │   ├── gpu_info.py
│   │   ├── log_processor.py
│   │   ├── system_info.py
│   │   └── xorg_utils.py
│   ├── detail_pages/                # Game detail page components
│   │   ├── utils.py
│   │   └── widgets.py
│   ├── dialogs/                     # Application dialogs
│   │   ├── appimage_update.py
│   │   ├── base.py
│   │   ├── compatibility_report.py
│   │   ├── dialog_utils.py
│   │   ├── file_explorer.py
│   │   ├── prefix_backup.py
│   │   ├── proton_manager.py
│   │   ├── settings_dialog.py
│   │   ├── settings_gamescope.py
│   │   ├── settings_mangohud.py
│   │   ├── settings_vkbasalt.py
│   │   ├── wine_downloader.py
│   │   ├── wine_extractor.py
│   │   ├── wine_loader.py
│   │   └── winetricks_dialog.py
│   ├── input_manager/               # Keyboard and gamepad input routing
│   │   ├── buttons.py
│   │   ├── constants.py
│   │   ├── dialog_modes.py
│   │   ├── dpad.py
│   │   ├── file_explorer.py
│   │   ├── keyboard.py
│   │   ├── mixin.py
│   │   ├── runtime.py
│   │   ├── settings.py
│   │   └── settings_visual.py
│   ├── scripts_utils/               # Helpers used by PortProton scripts
│   │   ├── dbus_tools.py
│   │   ├── easyterm.py
│   │   ├── graphics_detector.py
│   │   ├── idle_inhibit.py
│   │   ├── json_tools.py
│   │   ├── mount_points.py
│   │   ├── power_profiles.py
│   │   ├── prefix_backup.py
│   │   └── shortcut_tools.py
│   ├── steam_api/                   # Steam API, cache, and shortcuts
│   │   ├── api.py
│   │   ├── cache.py
│   │   ├── shortcuts.py
│   │   └── utils.py
│   ├── system_manager/              # System settings backends
│   │   ├── audio.py
│   │   ├── bluetooth.py
│   │   ├── common.py
│   │   ├── network.py
│   │   └── storage.py
│   ├── tabs/                        # Main window tabs and workers
│   │   ├── autoinstall_tab.py
│   │   ├── control_hints.py
│   │   ├── gog_tab.py
│   │   ├── library_tab.py
│   │   ├── settings_tab.py
│   │   ├── system_tab.py
│   │   ├── theme_store.py
│   │   ├── theme_store_workers.py
│   │   ├── theme_tab.py
│   │   ├── wine_tab.py
│   │   └── workers.py
│   ├── locales/                    # Translation catalogs
│   ├── terminal_schemes/           # Terminal color schemes
│   ├── themes/                     # Built-in themes and assets
│   ├── app.py                      # Entry point
│   ├── game_card.py                # Game card widget
│   ├── gog_api.py                  # GOG integration
│   ├── main_window.py              # Main window
│   ├── native_gamepad.py           # Native SDL3 gamepad backend
│   ├── portproton_api.py           # PortProton integration
│   ├── theme_manager.py            # Theme management
│   └── logger.py                   # Logging
├── tests/                          # Unit tests
├── build-aux/                      # Build resources
├── dev-scripts/                    # Development scripts
├── documentation/                  # Documentation
├── meson.build                     # Meson config
├── pyproject.toml                  # Python config
└── .pre-commit-config.yaml
```

---

## Development Scripts

**`dev-scripts/`** contains development utilities that are not part of the application codebase.

**Policy:**
- Scripts in `dev-scripts/` are exempt from code quality guidelines
- No type hints, linting, or code style requirements apply
- These scripts are for developer convenience only
- Do not refactor or improve dev-scripts unless explicitly requested

## PortProton Scripts

- In `build-aux/share/portproton/scripts/`, run `portprotonqt.scripts_utils` modules through the existing `python_module` function
- Do not add direct `python3 -m portprotonqt.scripts_utils.*` calls where `python_module` is available
- When adding new PortProton component variables (for example `D7VK_*`), update matching env filters in scripts, runtime `var.log`, and Qt debug/UI helpers

---

## Dependencies

### Core

| Package | Purpose | License |
|---------|---------|---------|
| PySide6 | GUI | LGPL |
| Legendary | EGS integration | GPL-3.0 |
| Icoextract | Icon extraction | MIT |
| Requests | HTTP | Apache-2.0 |
| Pillow | Image handling | MIT |

### Compatibility

- Keep `dbus-fast` 2.x compatibility for Fedora
- Do not use `dbus_fast.annotations` or `DBusSignature`

**License compatibility:**
- MIT, Apache-2.0, BSD: Compatible
- LGPL: Requires dynamic linking
- Proprietary: Incompatible

---

## Resources

- [Theme documentation](documentation/theme_guide)
- [Localization guide](documentation/localization_guide)
- [Metadata override guide](documentation/metadata_override)
- [TODO list](TODO.md)
- [Changelog](CHANGELOG.md)

---

**Last updated:** 2026-08-11
**Version:** 1.3
**Status:** Release
