  Эта документация также доступна на [русском](README.ru.md)

---

## Contents
- [Overview](#overview)
- [Creating the Theme Folder](#creating-the-theme-folder)
- [Theme Variants](#theme-variants)
- [Style File](#style-file-stylespy)
- [Style Inheritance](#style-inheritance)
  - [How Inheritance Works](#how-inheritance-works)
  - [Overriding QSS Styles](#overriding-qss-styles)
- [Library Layout Mode](#library-layout-mode)
- [Detail Page Layout Mode](#detail-page-layout-mode)
- [Detail Page Background Mode](#detail-page-background-mode)
  - [Background Configuration](#background-configuration)
- [Library Background](#library-background)
- [Preloader](#preloader)
- [Source Corner (Ribbon)](#source-corner-ribbon)
- [Terminal Color Schemes](#terminal-color-schemes)
- [Animation configuration](#animation-configuration)
- [Metadata](#metadata-metainfoini)
  - [Translation Support](#translation-support)
- [Screenshots](#screenshots)
- [Fonts and Icons](#fonts-and-icons-optional)
  - [Recoloring SVG Icons](#recoloring-svg-icons)
  - [AutoSizeButton State Recoloring](#autosizebutton-state-recoloring)
  - [Non-Inherited Icon Colors](#non-inherited-icon-colors)
- [Sound Effects](#sound-effects-optional)

---

## Overview

Themes in `PortProtonQT` allow customizing the UI appearance. Themes are stored under:

- `~/.local/share/PortProtonQT/themes`.

---

## Creating the Theme Folder

```bash
mkdir -p ~/.local/share/PortProtonQT/themes/my_custom_theme
```

---

## Theme Variants

The theme tab groups light and dark variants under one base theme name.

Define the related theme folders in each variant's `metainfo.ini`:

```ini
[Metainfo]
dark_variant = my_custom_theme
light_variant = my_custom_theme_light
```

The folder names can be any valid theme folder names.

If both configured folders exist, the application shows a separate variant selector with `Dark`, `Light`, and `Auto`. If only one folder exists, the variant selector is hidden and the existing theme is used directly.

`Auto` is the default variant. It follows the system color scheme using the desktop portal first, then `gsettings`, and Qt color scheme detection as a fallback.

Both variants are regular themes and must contain their own `styles.py`. Use `THEME_INHERITS` if one variant should reuse missing style values from another theme.

---

## Style File (`styles.py`)

Create a `styles.py` in the theme root. It should define variables or functions that return QSS (Qt Style Sheets). For better organization, you can split your theme into multiple submodules by creating a `styles/` subdirectory with separate Python files for different components, and import them in `styles.py`.

**Example of modular structure:**
```
my_custom_theme/
├── styles.py
├── metainfo.ini
├── fonts/
├── images/
├── sounds/
└── styles/
    ├── __init__.py  # This empty file makes the directory a Python package
    ├── constants.py
    ├── base.py
    ├── game_card.py
    ├── detail_page.py
    ├── settings.py
    ├── winetricks.py
    ├── get_wine.py
    ├── file_explorer.py
    └── theme_utils.py
```

**Main styles.py file:**

You can use either absolute imports (recommended for built-in themes):
```python
# Import from the theme's submodules using absolute paths relative to the package
# Replace 'my_custom_theme' with your actual theme folder name and 'styles' with your subdirectory name
from portprotonqt.themes.my_custom_theme.styles.constants import *
from portprotonqt.themes.my_custom_theme.styles.base import *
from portprotonqt.themes.my_custom_theme.styles.game_card import *
from portprotonqt.themes.my_custom_theme.styles.detail_page import *
from portprotonqt.themes.my_custom_theme.styles.settings import *
from portprotonqt.themes.my_custom_theme.styles.winetricks import *
from portprotonqt.themes.my_custom_theme.styles.theme_utils import *
```

Or you can use relative imports (recommended for custom user themes):
```python
# Import from the theme's submodules using relative paths
from .styles.constants import *
from .styles.base import *
from .styles.game_card import *
from .styles.detail_page import *
from .styles.settings import *
from .styles.winetricks import *
from .styles.theme_utils import *
```

**Example submodule (styles/constants.py):**
```python
# Theme constants
font_family = "Play"
font_size_normal = "16px"
font_size_header = "24px"
border_radius_small = "10px"
color_accent = "#409EFF"
color_bg = "#282a33"
# ... other constants
```

---

## Style Inheritance

Themes can inherit missing style variables and functions from another theme by defining `THEME_INHERITS` in `styles.py`:

```python
THEME_INHERITS = "classic"
```

If `THEME_INHERITS` is not defined, the theme inherits styles from `standart`.

Fonts, icons, images, and sounds also follow the inheritance chain — the first match found walking from child to `standart` wins. If your theme has a `fonts/` directory, it takes priority over the parent's. Missing sound events fall back individually to the parent theme. Screenshots are the exception — they are loaded only from the current theme, not inherited.

### How Inheritance Works

The inheritance system uses **AST-based constant injection**. When a child theme loads, the engine walks the full inheritance chain (child → parent → grandparent → … → `standart`) and collects all constant assignments from each theme's `styles/constants.py` (or `styles.py` if no `styles/` directory exists).

Constants are collected in order from root to child. **Child theme constants override parent constants.** This means you can change any color, size, or layout value by simply redefining it in your theme — you do not need to copy entire QSS strings.

For parent themes with a `styles/` directory (like `standart`), the QSS styles are **regenerated** with your child constants. Each style file (e.g., `base.py`, `game_card.py`) is re-evaluated with `{**parent_constants, **child_constants}`, so all f-string QSS values reflect your overrides.

For parent themes with only a monolithic `styles.py`, assignments overridden by the child are stripped before re-execution, and the remaining code runs with your constants.

**Example — overriding colors and borders in a child theme:**
```python
# my_child_theme/styles.py
THEME_INHERITS = "standart"

# Override accent color — all QSS using color_accent will use this value
color_accent = "#3daee9"
color_bg = "#2c3746"
color_surface = "#323e4f"
color_text = "#fdfdfd"
```

**Example — overriding font and borders:**
```python
# my_child_theme/styles.py
THEME_INHERITS = "standart"

font_family = "Adwaita Sans"
border_radius_small = "12px"
border_radius_large = "18px"
border_radius_card = "12px"
border_radius_header = "24px"
border_radius_badge = "6px"
```

**Example — light theme variant:**
```python
# my_child_theme_light/styles.py
THEME_INHERITS = "standart-light"

color_accent = "#6c782e"
color_bg = "#fbf1c7"
color_surface = "#f4e8be"
color_text = "#3c3836"
```

**Inheritance chain examples:**
```
standart  (root, no parent)
  ├── standart-light  (defaults to "standart")
  │     └── classic-light  (THEME_INHERITS = "standart-light")
  └── classic  (THEME_INHERITS = "standart")
```

Only the **immediate parent's** `styles/` directory generates QSS for your child theme. Grandparent styles are inherited via attribute lookup fallback, not regenerated.

### Overriding QSS Styles

You can also override entire QSS style strings in your theme. This is useful when you need complete control over a widget's appearance:

```python
# my_child_theme/styles.py
THEME_INHERITS = "standart"

LIBRARY_WIDGET_STYLE = f"""
    QWidget {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {color_library_gradient_start},
            stop:1 {color_library_gradient_end});
        border-radius: 0px;
    }}
"""

NAV_BUTTON_STYLE = f"""
    NavLabel {{
        background: {color_transparent};
        border-radius: 0px;
        border-bottom: {border_thin} {color_accent};
    }}
"""
```

---

## Library Layout Mode

You can control the game library card layout directly from the theme via `styles.py`:

```python
# "grid", "list", "vertical", "horizontal", or "horizontal_top"
LIBRARY_LAYOUT_MODE = "grid"
```

- `grid`: multi-column card grid (classic behavior).
- `list`: horizontal row-style cards (launcher-style list).
- `vertical`: a full-width table with game title, last launch, time spent, and
  library columns.
- `horizontal`: one horizontally scrolling row containing every game.
- `horizontal_top`: the first `horizontalTopGameLimit` games from the current
  filter and sort order, followed by a tile composed from the next games that
  opens the complete grid.

The `horizontal_top` preview tile is configured with theme-level constants:

```python
horizontalTopGameLimit = 10       # Games shown before the tile.
fullLibraryTileGameCount = 4      # Cover images shown in the tile.
fullLibraryTileSize = (180, 180)   # Tile width and height.
fullLibraryTileColumns = 2        # Cover columns inside the tile.
fullLibraryTileRows = 2           # Cover rows inside the tile.
fullLibraryTileRadius = 10        # Tile corner radius in pixels.
```

`fullLibraryTileColumns * fullLibraryTileRows` should be at least
`fullLibraryTileGameCount`. The tile opens the complete library grid when
activated.

Card geometry is controlled by `GAME_CARD_LIST`, `GAME_CARD_GRID`, and
`GAME_CARD_HORIZONTAL`:

```python
GAME_CARD_LIST = {
    "extra_margin": 8,
    "spacing": 12,
    "cover_load_size": 64,
    "cover_size": 56,
    "min_cover_size": 48,
    "cover_left_margin": 10,
    "row_height": 72,
    "min_row_height": 68,
    "cover_radius": 8,
    "border_radius": 18,
}

GAME_CARD_GRID = {
    "card_animation_type": "gradient",
    "extra_margin": 20,
    "spacing": 5,
    "cover_aspect_ratio": 1.5,
    "card_height_ratio": 1.8,
    "cover_radius": 15,
    "border_radius": 18,
}

GAME_CARD_HORIZONTAL = {
    "card_orientation": "vertical",
    "card_animation_type": "scale",
    "extra_margin": 20,
    "spacing": 5,
    "cover_aspect_ratio": 0.56,
    "card_height_ratio": 0.78,
    "cover_radius": 15,
    "layout_margins": (20, 20, 20, 20),
    "layout_spacing": 20,
}
```

Set `card_orientation` to `"vertical"` to reuse the grid card proportions in
the horizontal strip. Omit it to keep the horizontal block proportions.

Values are logical pixels. `cover_radius` applies to static and animated covers;
`border_radius` applies to the painted focus and hover border. Grid cover width
continues to follow the library card-size setting.

Card animation keys can be overridden independently in `GAME_CARD_LIST`,
`GAME_CARD_GRID`, or `GAME_CARD_HORIZONTAL`: `card_animation_type`, border
widths, pulse settings, gradient angles and colors, fill/stripe/glow colors and
opacity, scale values, animation durations, and easing curves. For example,
`horizontal_top` can define its own `scale` type, scale values, duration, and
easing while the complete grid uses separately configured `gradient` values.
Keys omitted from a layout continue to use `GAME_CARD_ANIMATION` as fallback.

```python
GAME_CARD_HORIZONTAL = {
    "card_animation_type": "scale",
    "default_scale": 1.0,
    "hover_scale": 1.055,
    "focus_scale": 1.075,
    "scale_anim_duration": 135,
    "scale_easing_curve": "OutCubic",
    "scale_easing_curve_out": "InOutCubic",
}
```

Card shadows use the shared `shadow_blur_radius` and `shadow_offset` theme
constants in both grid and list layouts.

This is a theme-level option and does not depend on app settings.

---

## Detail Page Layout Mode

You can control the detail page layout from the theme via `styles.py`:

```python
# "full" (default) or "compact"
DETAIL_PAGE_LAYOUT_MODE = "full"
```

- `full`: full cover size, description, badges, controller support, and HowLongToBeat data.
- `compact`: smaller cover and simplified detail content.

Economy mode also forces the compact detail page layout.

---

## Detail Page Background Mode

You can control the detail page background style from the theme via `styles.py`:

```python
# One of the background modes listed below
DETAIL_PAGE_BG_MODE = "gradient"
```

- `gradient`: diagonal linear gradient extracted from the cover image palette (default).
- `waves`: gradient background with animated wave shapes that drift over time.
- `aurora`: animated vertical aurora ribbons.
- `metaballs`: animated glowing metaballs.
- `leaf`: animated falling leaves with a configurable foliage type.
- `veins`: animated connected vein pattern.
- `diagnostics`: animated grid, signal trace, scanner, and compatibility status.

Prefix an animated background mode with `static_` to render one frame without
starting its animation timer. For example:

```python
DETAIL_PAGE_BG_MODE = "static_diagnostics"
```

The supported static modes are `static_waves`, `static_aurora`,
`static_metaballs`, `static_leaf`, `static_veins`, and
`static_diagnostics`.

Set the number of colors extracted from the cover:

```python
# Must be at least 2
DETAIL_PAGE_PALETTE_COLORS = 5
```

### Background Configuration

Background modes use `DETAIL_PAGE_BACKGROUNDS`:

```python
DETAIL_PAGE_BACKGROUNDS = {
    # Common settings for aurora, diagnostics, leaf, metaballs, and veins.
    "animation_interval_ms": 30,  # Milliseconds between frames.
    "animation_speed": 0.03,      # Phase increment per frame.
    "gradient": {
        # None uses cover colors.
        # [0, 0.3, 0.7, 1] distributes cover colors at custom positions.
        # [{"position": 0, "color": "#101010"}, ...] sets custom colors.
        # "stop:0 #101010, stop:1 #303030" accepts raw QSS stops.
        "stops": None,
        "type": "linear", # "linear" or "radial".
        "x1": 0,          # Linear gradient start X (0.0-1.0).
        "y1": 0,          # Linear gradient start Y (0.0-1.0).
        "x2": 1,          # Linear gradient end X (0.0-1.0).
        "y2": 1,          # Linear gradient end Y (0.0-1.0).
        "cx": 0.5,        # Radial gradient center X (0.0-1.0).
        "cy": 0.5,        # Radial gradient center Y (0.0-1.0).
        "radius": 0.5,    # Radial gradient radius relative to the page.
        "fx": 0.5,        # Radial gradient focal point X (0.0-1.0).
        "fy": 0.5,        # Radial gradient focal point Y (0.0-1.0).
    },
    "waves": {
        "layer_count": 4,              # Number of overlapping wave layers.
        "wave_amplitude_ratio": 0.06,  # Wave height / page height.
        "wave_frequency": 2.0,         # Oscillations across the page.
        "layer_spacing_ratio": 0.04,   # Layer gap / page height.
        "base_opacity": 0.45,          # First layer opacity (0.0-1.0).
        "opacity_decay": 0.85,         # Opacity multiplier for later layers.
        "animation_speed": 0.03,       # Wave phase increment per frame.
        "animation_interval_ms": 30,   # Milliseconds between wave frames.
    },
    "aurora": {
        "line_count": 8,           # Number of vertical ribbons.
        "line_width_ratio": 0.006, # Ribbon width / page width.
        "opacity": 0.35,           # Ribbon opacity (0.0-1.0).
        "steps": 40,               # Curve segments per ribbon.
        "frequency": 5.0,          # Bends along each ribbon.
        "speed": 1.2,              # Ribbon motion speed multiplier.
        "phase_step": 0.8,         # Phase difference between ribbons.
        "edge_offset": 0.5,        # Offset used to distribute ribbons.
        "drift_ratio": 0.06,       # Horizontal drift / page width.
    },
    "diagnostics": {
        "color": color_accent,     # Color of every diagnostics element.
        "font_family": font_family,# Status text font.
        "font_size": 13,           # Status text size in pixels.
        "grid_spacing": 64,        # Grid cell size in pixels.
        "grid_line_width": 1,      # Grid line width in pixels.
        "grid_opacity": 0.08,      # Grid opacity (0.0-1.0).
        "trace_baseline": 0.78,    # Trace Y position / page height.
        "trace_amplitude": 0.025,  # Trace height / page height.
        "trace_frequency": 28,     # Oscillations across the page.
        "trace_speed": 1.4,        # Trace motion speed multiplier.
        "trace_step_width": 4,     # Pixels between trace samples.
        "trace_line_width": 2,     # Trace line width in pixels.
        "trace_opacity": 0.45,     # Trace opacity (0.0-1.0).
        "text_opacity": 0.7,       # Status text opacity (0.0-1.0).
        "text_x_ratio": 0.025,     # Text left margin / page width.
        "first_line_y_ratio": 0.88,# First status Y / page height.
        "second_line_y_ratio": 0.91,# Second status Y / page height.
        "status_text": "COMPATIBILITY LAYER: OPERATIONAL", # First status.
        "containment_text": "WINDOWS CONTAINMENT: ACTIVE",  # Second status.
        "sweep_offset": 0.25,      # Initial scanner X position (0.0-1.0).
        "sweep_speed": 0.08,       # Scanner motion speed multiplier.
        "sweep_width": 2,          # Scanner width in pixels.
        "sweep_opacity": 0.2,      # Scanner opacity (0.0-1.0).
    },
    "metaballs": {
        "count": 18,               # Number of glowing balls.
        "seed_offset": 1,          # Seed offset for another layout.
        "min_radius_ratio": 0.08,  # Minimum radius / page height.
        "radius_range": 0.08,      # Random extra radius range.
        "min_speed": 0.004,        # Minimum vertical travel speed.
        "opacity": 0.55,           # Ball center opacity (0.0-1.0).
        "x_seed": 1.31,            # Horizontal placement seed multiplier.
        "y_seed": 7.13,            # Vertical placement seed multiplier.
        "speed_seed": 2.71,        # Individual speed seed multiplier.
    },
    "leaf": {
        # "generic", "sakura", "oak", "maple", or "birch".
        "type": "generic",         # Shape of the falling foliage.
        "count": 32,               # Number of leaves.
        "seed_offset": 1,          # Seed offset for another layout.
        "min_size_ratio": 0.009,   # Minimum size / page height.
        "size_range": 0.009,       # Random extra size range.
        "min_speed": 0.002,        # Minimum falling speed.
        "opacity": 0.65,           # Leaf opacity (0.0-1.0).
        "sway_ratio": 0.04,        # Horizontal sway / page width.
        "rotation_speed": 40,      # Degrees per animation phase.
        "x_seed": 1.31,            # Horizontal placement seed multiplier.
        "y_seed": 7.13,            # Vertical placement seed multiplier.
        "speed_seed": 2.71,        # Individual speed seed multiplier.
    },
    "veins": {
        "columns": 9,          # Number of point columns.
        "rows": 6,             # Number of point rows.
        "seed_offset": 1,      # Seed offset for another pattern.
        "cell_offset": 0.5,    # Point position inside a grid cell.
        "motion_ratio": 0.12,  # Horizontal movement / cell width.
        "line_width": 2,       # Connection width in pixels.
        "opacity": 0.3,        # Connection opacity (0.0-1.0).
    },
}
```

Each named dictionary contains the visual constants for that effect. Copy the
corresponding dictionary from the standard theme before overriding individual
values so that all required keys remain present.

The `diagnostics` effect also exposes `status_text` and `containment_text`. The
standard theme uses `COMPATIBILITY LAYER: OPERATIONAL` and
`WINDOWS CONTAINMENT: ACTIVE`.

Existing themes may continue using `DETAIL_PAGE_GRADIENT`,
`DETAIL_PAGE_GRADIENT_TYPE`, `DETAIL_PAGE_GRADIENT_X1` through
`DETAIL_PAGE_GRADIENT_FY`, and `DETAIL_PAGE_WAVES`. Legacy values override the
corresponding nested settings.

## Library Background

The library can use the cover of the currently hovered or focused card as its
background. This feature is opt-in: if `LIBRARY_BACKGROUND` is not defined, the
library keeps the theme's regular background unchanged.

`LIBRARY_BACKGROUND` selects the effect and can override detail-page
background settings locally. Its `backgrounds` dictionary is merged with
`DETAIL_PAGE_BACKGROUNDS`, so only the values that should differ need to be
specified:

```python
LIBRARY_BACKGROUND = {
    "margins": (0, 0, 0, 0),
    "mode": "waves",  # gradient, blur, waves, aurora, metaballs, leaf, veins, diagnostics
    "backgrounds": {
        "animation_interval_ms": 30,
        "animation_speed": 0.03,
        "blur": {
            "render_resolution": (1280, 720),
            "radius": 64,
        },
        "gradient": {
            "stops": None,
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 1, "y2": 1,
        },
        "waves": {
            "layer_count": 4,
            "wave_amplitude_ratio": 0.06,
            "wave_frequency": 2.0,
            "layer_spacing_ratio": 0.04,
            "base_opacity": 0.45,
            "opacity_decay": 0.85,
            "animation_speed": 0.03,
            "animation_interval_ms": 30,
        },
    },
}
```

The `blur` settings control the intermediate image size and blur radius.
`margins` are applied to the background layer layout. Animated modes use the
same effect-specific dictionaries documented in `DETAIL_PAGE_BACKGROUNDS`;
copy the corresponding dictionary there when overriding `aurora`, `leaf`,
`metaballs`, `veins`, or `diagnostics`.

---

The `PRELOADER` dictionary controls the loading indicator style and animation. If not defined, the default spinner is used.

```python
PRELOADER = {
    # Style: "default" (spinning arc), "bat" (flying bat), "pulse" (expanding rings),
    #        "dots" (orbiting dots), "wave" (sine wave)
    "style": "bat",

    # --- Bat style options ---
    "bat_size": 80,           # Size of the bat in pixels
    "bat_flap_speed": 3.0,    # Wing flap speed
    "bat_alpha": 220,         # Opacity (0-255)
    "bat_color": color_accent,

    # --- Pulse style options ---
    "pulse_count": 3,         # Number of expanding rings
    "pulse_max_radius": 40,   # Maximum ring radius
    "pulse_speed": 2.0,       # Expansion speed
    "pulse_color": color_accent,

    # --- Dots style options ---
    "dots_count": 8,          # Number of orbiting dots
    "dots_radius": 38,        # Orbit radius
    "dots_dot_size": 5,       # Dot size
    "dots_speed": 3.0,        # Orbit speed
    "dots_color": color_accent,

    # --- Wave style options ---
    "wave_width": 80,         # Wave width in pixels
    "wave_amplitude": 15,     # Wave height
    "wave_speed": 3.0,        # Wave animation speed
    "wave_line_width": 3,     # Line thickness
    "wave_color": color_accent,
}
```

---

## Source Corner (Ribbon)

The `SOURCE_CORNER` dictionary controls the ribbon/corner badge that indicates the game source (Steam, EGS, etc.) on game cards.

```python
SOURCE_CORNER = {
    "ribbon_color": color_surface,         # Main ribbon background
    "ribbon_fold_color": "#00000096",      # Shadow of the folded corner
    "size_ratio": 0.28,                    # Ribbon size as ratio of card width
    "min_size": 54,                        # Minimum ribbon size in pixels
    "min_widget_size": 4,                  # Minimum widget size for ribbon to show
    "peel_start_ratio": 0.32,             # Peel effect start position
    "peel_mid_ratio": 0.58,               # Peel midpoint
    "peel_end_ratio": 0.82,               # Peel end position
    "peel_shadow_width": 3,               # Peel shadow thickness
    "fold_start_ratio": 0.60,             # Fold crease start
    "fold_end_ratio": 0.92,               # Fold crease end
    "icon_center_ratio": 0.84,            # Icon center position
    "icon_size_ratio": 0.25,              # Icon size relative to ribbon
    "min_icon_size": 8,                   # Minimum icon size
    "gradient_start": 0.0,                # Gradient start position
    "gradient_end": 1.0,                  # Gradient end position
    "gradient_lighter": 145,              # Lighter gradient stop (brightness)
    "gradient_darker": 112,               # Darker gradient stop (brightness)
    "fold_darker": 132,                   # Fold area brightness
}
```

---

## Terminal Color Schemes

Terminal color schemes are separate Kitty-style `.conf` files. Built-in schemes are stored in `portprotonqt/terminal_schemes/`. User schemes can be placed in:

```text
~/.local/share/PortProtonQt/terminal_schemes/
```

The filename without `.conf` is used as the scheme name. The terminal menu lists all available `.conf` files from the user directory and the built-in directory.

Example:

```conf
foreground #d4d4d4
background #1e1e1e
cursor #bbbbbb
selection_foreground #ffffff
selection_background #264f78
background_opacity 1.0
cursor_shape block
enable_audio_bell no

color0 #000000
color1 #cd3131
color2 #0dbc79
color3 #e5e510
color4 #2472c8
color5 #bc3fbc
color6 #11a8cd
color7 #e5e5e5

font_size 14
font_family Monospace
```

Supported terminal-specific options:

- `foreground`, `background`: default text and background colors.
- `selection_foreground`, `selection_background`: selected text colors.
- `cursor` or `cursor_color`: cursor color.
- `cursor_shape`: `block`, `beam`, or `underline`.
- `enable_audio_bell`: `yes`/`no`, `true`/`false`, `on`/`off`, or `1`/`0`.
- `background_opacity`: background opacity from `0.0` to `1.0`.
- `font_size`, `font_family`: terminal font settings.
- `color0` through `color255`: ANSI palette entries.

If `cursor_shape` is omitted, the terminal uses `beam`. If `enable_audio_bell` is omitted, audio bell is disabled.

---

## Animation configuration

The `GAME_CARD_ANIMATION` dictionary controls all animation parameters for game cards:

```python
GAME_CARD_ANIMATION = {
    # Type of animation when entering or exiting the detail page
    # Possible values: "fade", "slide_left", "slide_right", "slide_up", "slide_down", "bounce"
    # Determines how the detail page appears and disappears
    "detail_page_animation_type": "fade",

    # Border width of the card in idle state (no hover or focus)
    # Affects the thickness of the border around the card when it's not selected
    # Value in pixels
    "default_border_width": 2,

    # Border width on hover
    # Increases the border thickness when the cursor is over the card
    # Value in pixels
    "hover_border_width": 8,

    # Border width on focus (e.g., when selected via keyboard)
    # Increases the border thickness when the card is focused
    # Value in pixels
    "focus_border_width": 12,

    # Minimum border width during pulsing animation
    # Determines the minimum border thickness during the "breathing" animation
    # Value in pixels
    "pulse_min_border_width": 8,

    # Maximum border width during pulsing animation
    # Determines the maximum border thickness during pulsing
    # Value in pixels
    "pulse_max_border_width": 10,

    # Duration of the border thickness animation (e.g., on hover or focus)
    # Affects the speed of transition from one border width to another
    # Value in milliseconds
    "thickness_anim_duration": 300,

    # Duration of one pulsing animation cycle
    # Determines how fast the border "pulses" between min and max values
    # Value in milliseconds
    "pulse_anim_duration": 800,

    # Duration of the gradient rotation animation
    # Affects how fast the gradient border rotates around the card
    # Value in milliseconds
    "gradient_anim_duration": 3000,

    # Starting angle of the gradient (in degrees)
    # Determines the initial rotation point of the gradient at animation start
    "gradient_start_angle": 360,

    # Ending angle of the gradient (in degrees)
    # Determines the final rotation point of the gradient
    # Value 0 means a full 360° rotation
    "gradient_end_angle": 0,

    # Type of card animation on hover or focus
    # Possible values: "gradient", "scale", "fill", "stripe", "glow", "scale_fill"
    # "gradient" enables a rotating gradient border, "scale" enlarges the card,
    # "fill" applies a static overlay, "stripe" applies a static border color,
    # "glow" adds pulsing border glow, "scale_fill" combines scaling + fill
    "card_animation_type": "gradient",

    # Overlay color for "fill" animation type
    # Any valid Qt color string (hex/rgb/rgba)
    "fill_color": color_accent,

    # Overlay opacity for "fill" animation type (0-255)
    "fill_alpha": 90,

    # Border color for "stripe" animation type
    # Any valid Qt color string (hex/rgb/rgba)
    "stripe_color": color_accent,

    # Border opacity for "stripe" animation type (0-255)
    "stripe_alpha": 255,

    # Base opacity for "glow" animation type (0-255)
    "glow_base_alpha": 120,

    # Extra pulse opacity for "glow" animation type (0-255)
    "glow_pulse_alpha": 80,

    # Card scale in idle state
    # Determines the base size of the card (1.0 = 100% of original size)
    # Value as a fraction (e.g., 1.0 for normal size)
    "default_scale": 1.0,

    # Card scale on hover
    # Increases the card size on hover
    # Value as a fraction (e.g., 1.1 = 110% of original size)
    "hover_scale": 1.1,

    # Card scale on focus (e.g., when selected via keyboard)
    # Increases the card size on focus
    # Value as a fraction (e.g., 1.05 = 105% of original size)
    "focus_scale": 1.05,

    # Duration of scale animation
    # Affects how fast the card changes size on hover or focus
    # Value in milliseconds
    "scale_anim_duration": 200,

    # Easing curve type for border thickness increase animation (on hover/focus)
    # Affects the "feel" of the animation (e.g., smooth acceleration or deceleration)
    # Possible values: strings corresponding to QEasingCurve.Type (e.g., "OutBack", "InOutQuad")
    "thickness_easing_curve": "OutBack",

    # Easing curve type for border thickness decrease animation (on hover/focus exit)
    # Affects the "feel" of returning to the default border width
    "thickness_easing_curve_out": "InBack",

    # Easing curve type for scale increase animation (on hover/focus)
    # Affects the "feel" of the scaling animation (e.g., with a "bounce" effect)
    # Possible values: strings corresponding to QEasingCurve.Type
    "scale_easing_curve": "OutBack",

    # Easing curve type for scale decrease animation (on hover/focus exit)
    # Affects the "feel" of returning to the original scale
    "scale_easing_curve_out": "InBack",

    # Gradient colors for animated border
    # List of dictionaries, each specifying position (0.0–1.0) and color in hex format
    # Affects the appearance of the border on hover or focus if card_animation_type="gradient"
    "gradient_colors": [
        {"position": 0, "color": "#00fff5"},    # Starting color (cyan)
        {"position": 0.33, "color": "#FF5733"}, # Color at 33% (orange)
        {"position": 0.66, "color": "#9B59B6"}, # Color at 66% (purple)
        {"position": 1, "color": "#00fff5"}     # Ending color (back to cyan)
    ],

    # Duration of fade animation when entering the detail page
    # Affects the speed of page appearance with fade animation
    # Value in milliseconds
    "detail_page_fade_duration": 350,

    # Duration of slide animation when entering the detail page
    # Affects the speed of page sliding animation
    # Value in milliseconds
    "detail_page_slide_duration": 500,

    # Duration of bounce animation when entering the detail page
    # Affects the speed of page "bounce" animation
    # Value in milliseconds
    "detail_page_bounce_duration": 400,

    # Duration of fade animation when exiting the detail page
    # Affects the speed of page disappearance with fade animation
    # Value in milliseconds
    "detail_page_fade_duration_exit": 350,

    # Duration of slide animation when exiting the detail page
    # Affects the speed of page sliding animation
    # Value in milliseconds
    "detail_page_slide_duration_exit": 500,

    # Duration of bounce animation when exiting the detail page
    # Affects the speed of page "compression" animation
    # Value in milliseconds
    "detail_page_bounce_duration_exit": 400,

    # Easing curve type for animations when entering the detail page
    # Applied to slide and bounce animations; affects the "feel" of movement
    # Possible values: strings corresponding to QEasingCurve.Type
    "detail_page_easing_curve": "OutCubic",

    # Easing curve type for animations when exiting the detail page
    # Applied to slide and bounce animations; affects the "feel" of movement
    # Possible values: strings corresponding to QEasingCurve.Type
    "detail_page_easing_curve_exit": "InCubic"
}
```

Virtual keyboard animation options are configured with theme-level constants:

```python
virtual_keyboard_animation_type = "slide"  # "slide", "fade", "slide_fade", "slide_bounce"
virtual_keyboard_slide_animation_duration = 160
virtual_keyboard_fade_animation_duration = 140
virtual_keyboard_slide_fade_animation_duration = 180
virtual_keyboard_slide_bounce_animation_duration = 220
```

---

## Metadata (`metainfo.ini`)

```ini
[Metainfo]
dark_variant = my_custom_theme
light_variant = my_custom_theme_light
name_en = My Custom Theme
name_ru = Моя пользовательская тема
author = Your Name
author_link = https://example.com
description_en = Description of your theme.
description_ru = Описание вашей темы.
```

### Translation Support

You must provide translations for your theme's name and description by adding language-specific fields:
- `name_en`, `name_ru`, etc. for theme names
- `description_en`, `description_ru`, etc. for theme descriptions

The application will automatically select the appropriate translation based on the user's system language, falling back to English if translations are not available for the user's language.

`dark_variant` and `light_variant` are required when the theme has both variants. Add them to both variant folders so either selected folder can resolve back to the same variant pair.

---

## Screenshots

Folder: `images/screenshots/` — place UI screenshots there.
Screenshot files can have any convenient names.

---

## Fonts and Icons (optional)

- Fonts: `fonts/*.ttf` or `.otf`
- Icons and Images: `images/` directory for all visual assets. Supported formats: `.svg`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.jxl`.
  - `images/icons/` - Main application icons (organized in subdirectories like actions/, navigation/, platforms/, etc.)
  - `images/icons/buttons/` - Button icons for UI elements
  - `images/icons/keyboards/` - Keyboard key icons (key_+, key_enter, etc.)
  - `images/icons/controllers/` - Controller button icons
  - `images/icons/controllers/xbox/` - Xbox controller button icons (xbox_a, xbox_b, etc.)
  - `images/icons/controllers/playstation/` - PlayStation controller button icons (ps_circle, ps_cross, etc.)
  - `images/ui_elements/` - UI elements (placeholder images, etc.)
  - `images/screenshots/` - Theme preview screenshots

Icons and images can be referenced by name without specifying the subdirectory, as the system will search through all subdirectories automatically. Theme creators can organize images in any logical subdirectory structure.

### Recoloring SVG Icons

SVG icons can be recolored from theme constants without editing the SVG files. Define `ICON_COLORS` as a dictionary where the key is the icon file name without extension and the value is the target color:

```python
ICON_COLORS = {
    "tray_portproton": color_accent,
}
```

Only icons listed in `ICON_COLORS` are recolored. Icons without an entry keep their original file unchanged. The source SVG is never modified; PortProtonQt writes a recolored copy to the icon cache and uses that path.

The recoloring helper handles common SVG paint declarations: `fill`, `stroke`, `color`, `stop-color`, `flood-color`, `lighting-color`, inline `style` attributes, and CSS inside `<style>` blocks. It preserves non-color paint values such as `none`, `transparent`, `url(#...)`, `context-fill`, and `context-stroke`.

### AutoSizeButton State Recoloring

`AutoSizeButton` icons and text can be recolored automatically for button states. State-specific keys have priority over base icon keys. The lookup order is:

1. `{icon_name}_{state}`
2. `*_{state}`
3. `{icon_name}`

Supported states are `hover`, `pressed`, `focused`, and `disabled`. Use state wildcard keys to apply one color to all button icons in that state:

```python
ICON_COLORS = {
    "settings_hover": color_accent,
    "*_hover": color_text,
    "*_pressed": color_text,
    "*_focused": color_text,
    "*_disabled": color_text,
}
```

When no `ICON_COLORS` entry matches an `AutoSizeButton` state, the button falls back to theme colors: `color_disabled` for disabled, `color_accent_dark` or `color_accent` for pressed, and `color_accent` for hover/focus.

### Non-Inherited Icon Colors

`ICON_COLORS` is not inherited from parent themes. If a child theme needs SVG recoloring, define its own `ICON_COLORS` dictionary in that theme.

---

## Sound Effects (optional)

Place UI sound effects in the theme's `sounds/` directory. File names must match an event name; do not add numeric suffixes such as `_001`:

| Event | Used for |
|---|---|
| `navigate` | Moving focus between UI items |
| `click` | Pressing buttons, clickable labels, and confirming actions |
| `back` | Returning or closing with the Back action |
| `toggle` | Changing a checkbox or opening a combo box |
| `open` | Opening pages, dialogs, and menus |
| `tab_switch` | Switching application tabs |
| `game_launch` | Successful game process launch |
| `gamepad_connect` | Connecting a gamepad |
| `gamepad_off` | Disconnecting a gamepad |

Use uncompressed PCM WAV files, for example `sounds/navigate.wav`. Other audio formats are not supported.

Sounds are inherited per event. A child theme can override only `navigate`; missing events are resolved through its parent chain up to `standart`.

Theme validation checks the extension, file size, and format signature before a sound is loaded. Sound files larger than 20 MiB, symlinks, files outside the theme directory, and files whose content does not match their extension are rejected. Include the license and attribution required by every sound asset distributed with a theme.

---
