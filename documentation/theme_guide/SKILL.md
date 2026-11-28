---
name: PortProtonQt Theme Creator
description: Create, adapt, and validate built-in and user themes for PortProtonQt, including light and dark variants, QSS, icons, previews, and Linux-Gaming archives.
triggers:
  - theme
  - themes
  - portprotonqt theme
  - custom theme
  - color scheme
  - theme import
  - theme preview
pinned: false
---

# PortProtonQt Theme Creator Instructions

Use this skill when asked to create, import, or customize a **PortProtonQt theme**. Read the repository's `AGENTS.md` and the relevant sections of the [Theme Guide](README.md) before editing.

## 1. Where to Save the Theme

- **Built-in theme:** `portprotonqt/themes/<id>/`.
- **User theme:** `$XDG_DATA_HOME/PortProtonQt/themes/<id>/`, or `~/.local/share/PortProtonQt/themes/<id>/` if `XDG_DATA_HOME` is unset.
- Create `styles.py` and `metainfo.ini` for each variant. Use stable, lowercase kebab-case IDs, for example `meadow` and `meadow-light`. Do not overwrite another theme.
- For a light/dark pair, put the same `dark_variant` and `light_variant` IDs in both `metainfo.ini` files. Write short `description_en` and `description_ru` entries describing what the user sees. Leave `author` and `author_link` blank if the adaptation author is unknown.

## 2. File Format and Inheritance

```python
# styles.py — dark variant example
THEME_INHERITS = "standart"

color_bg = "#212121"
color_surface = "#2c2c2c"
color_text = "#ffffff"
color_accent = "#3281ea"
color_text_accent_hover = "#000000"
color_library_gradient_start = "#212121"
color_library_gradient_end = "#2c2c2c"
```

```ini
[Metainfo]
name_en = Meadow
name_ru = Meadow
author =
author_link =
dark_variant = meadow
light_variant = meadow-light
description_en = Graphite panels with a blue accent.
description_ru = Графитовые панели с синим акцентом.
```

For the light variant, inherit `standart-light` and use its color roles, including `color_text_dark` for text on light surfaces. Override only the necessary constants and `*_STYLE` values. Do not copy the parent theme, remove existing styles, or change application widgets to fix one theme. Check the effective QSS returned by the loader rather than assuming all styles or nested dictionaries merge as expected. `ICON_COLORS` is not inherited.

## 3. Palette and Design Rules

1. **Import from a verified source.** Record the palette file URL and its revision. Read upstream files as data; do not run upstream installation scripts. Check license compatibility and retain required notices. Compare with built-in and installed themes; if two families differ almost entirely by their accent, suggest keeping one rather than removing either without permission.
2. **Map colors by role.** Preserve the source's background, panels, and accent. Choose a readable foreground on each actual fill, accounting for transparency; aim for at least 4.5:1 contrast for ordinary text. Check SVG icons as well as labels. `AutoSizeButton` can use state-specific `ICON_COLORS` keys such as `addgame_focused` independently of ordinary `QPushButton` QSS.
3. **Check independently rendered surfaces.** The library uses `LIBRARY_WIDGET_STYLE` and its own gradient colors; inspect the detail-page background and card focus animation separately. For editable combo boxes, check both `QComboBox` and its `QLineEdit`, including the Wine prefix field. Keep keyboard focus visible without relying on hover.
4. **Use the guide for feature-specific settings.** It documents library layouts, detail-page backgrounds, card and keyboard animations, preloaders, boot video, sounds, and terminal schemes. Change only what the theme needs. UI palette changes do not automatically change the terminal scheme.

## 4. Validate and Preview

- For each variant, run `check_theme_directory_safety` (`allow_absolute_imports=False` for portable themes) and `load_theme`. Verify the effective colors and styles, both directions of variant switching, and that neither variant silently falls back to a base theme.
- Run `uv run pytest -q tests/test_theme_manager.py tests/test_theme_security.py`. Include `tests/test_detail_pages.py` or `tests/test_dark_theme.py` if relevant. For QSS changes, run `pre-commit run check-qss-properties --files <changed-style-files>`.
- Use an isolated profile and demo data to check the library, game details, Wine settings, PortProtonQt settings, and the Themes tab. Verify hover, keyboard focus, pressed, and disabled states separately. Apply each variant in the Themes tab and verify the rendered result. Do not launch games or connect real accounts for theme checks. Offscreen rendering is useful for static checks but does not verify real input, compositing, or animations.
- Capture matching previews for both variants when needed. Save client-area screenshots without personal data under `images/screenshots/`: `1_library.png`, `2_detail.png` (only the Play button focused), and `5_portproton_settings.png`. Wait for transitions and verify the active screen before capturing. Check that Qt can load the previews with `load_theme_screenshots()`.
- If asked for a Linux-Gaming archive, make one `.tar.gz` per family. Put the one or two theme directories at the archive root, with their files, previews, resources, and license inside. Do not include a wrapper folder, symlinks, caches, or temporary files. Do not publish without permission.

Report the variant IDs, what was actually checked, and any preview or archive paths. Separate automated tests, offscreen rendering, and checks performed in a live window.

## 5. What Themes Can Customize

### Inheritance, Resources, and Variant Selection

- In `theme_manager.py`, see `load_theme`, `ThemeWrapper`, `_inject_parent_theme_constants`, and `get_theme_override`. Scalar constants and supported composite values can come from the parent. Inspect the final `*_STYLE` string: a local override is not the same as an inherited template rendered with the effective theme. Do not assume dictionaries are deep-merged. Check the consumer's `getattr`, `.get`, merge logic, and required keys.
- In `config/ui.py`, `dark_variant` and `light_variant` link variants. Both user preference and system appearance affect selection. Verify the resolved theme ID and actual switching, not just the combo-box label.
- `theme_manager.py` and `theme_security.py` handle SVGs, fonts, sounds, previews, and file and code validation. `ICON_COLORS` **is not inherited**. In `custom_widgets.py`, `AutoSizeButton` looks up `<icon>_<state>`, `*_<state>`, then `<icon>` for `hover`, `focused`, `pressed`, and `disabled`. This can change both the SVG and the button label. Check actual icon filenames and verify ordinary `QPushButton` QSS separately.

### Library, Autoinstall, and Game Cards

Sources: `config/ui.py`, `game_library_manager.py`, `game_card.py`, `tabs/autoinstall_tab.py`, and `themes/standart/styles/game_card.py` and `constants.py`.

| `LIBRARY_LAYOUT_MODE` | What it displays | Geometry |
| --- | --- | --- |
| `grid` | Multi-column cover grid | `GAME_CARD_GRID` |
| `list` | Row cards | `GAME_CARD_LIST` |
| `vertical` | Full-width table with title, last launch, playtime, and source | `GAME_CARD_VERTICAL` |
| `horizontal` | Single horizontally scrolling strip | `GAME_CARD_HORIZONTAL` |
| `horizontal_top` | First games after filtering and sorting, followed by a tile opening the full grid | `GAME_CARD_HORIZONTAL`, `horizontalTopGameLimit`, `fullLibraryTileGameCount`, `fullLibraryTileSize`, `fullLibraryTileColumns`, `fullLibraryTileRows`, `fullLibraryTileRadius` |

- User settings `library_layout_mode` and `horizontal_card_orientation` override theme defaults. `GAME_CARD_HORIZONTAL['card_orientation']` accepts `horizontal` or `vertical`: portrait covers in a strip use `GAME_CARD_GRID` geometry without turning the strip into a table. Card width also depends on user settings.
- Grid and strip: `extra_margin`, `spacing`, `cover_aspect_ratio`, `card_height_ratio`, `cover_radius`, `border_radius`; the strip also has `layout_margins` and `layout_spacing`. Rows: `cover_load_size`, `cover_size`, `min_cover_size`, `cover_left_margin`, `row_height`, `min_row_height`. Table: `header_height`, `header_margins`, `header_spacing`, `header_cover_width`, `column_stretches`; Autoinstall also has `autoinstallColumnStretches`. Qt margins are `(left, top, right, bottom)`; dimensions are pixels and ratios are unitless.
- `COMPACT_CARD`: `width_threshold`, `height_ratio`, `title_lines`, `title_scale`. `COVER`: `width`, `height`. `BADGE`: `width`, `compact_width`, `icon_size`, `right_margin`, `spacing`, `top_y`. `SOURCE_CORNER` controls ribbon colors (`ribbon_color`, `ribbon_fold_color`), sizes and ratios (`size_ratio`, `min_size`, `min_widget_size`, `icon_size_ratio`, `icon_center_ratio`, `min_icon_size`), peel/fold geometry (`peel_*`, `fold_*`), shadows, and gradients. For game sources, compatibility, and status, see `color_badge_*`, `color_protondb_*`, `color_ppdb_*`, `color_anticheat_*`, `color_favorite_star`, and `missing_exe_cover_opacity`.
- `LIBRARY_WIDGET_STYLE` controls the normal background; the standard theme uses `color_library_gradient_start` and `color_library_gradient_end`. `LIBRARY_BACKGROUND = {"margins": (...), "mode": "...", "backgrounds": {...}}` enables a cover-derived background and overrides `DETAIL_PAGE_BACKGROUNDS` settings for the library. Test the full library opened from `horizontal_top` separately: `game_library_manager.py` handles it differently from the strip.
- **Check:** narrow and wide cards, long titles, missing covers, favorites and multiple badges, keyboard focus, scrolling, and opening the full grid. If layout geometry changes, check the Autoinstall tab too.

### Game Details: Layout, Background, and Transitions

Sources: `detail_pages/__init__.py`, `detail_pages/widgets.py`, `detail_pages/utils.py`, `animations/detail_page.py`, and `animations/detail_background.py`.

- `DETAIL_PAGE_LAYOUT_MODE` supports `full` (large cover and detailed information) and `compact` (compact header and smaller cover). Power-saving mode can force `compact`. `DETAIL_COMPACT` includes `cover_size`, `width`, `cover_image_size`, `content_spacing`, `buttons_bottom_spacing`, `header_spacing`, `title_margins`, and `description_margins`; check the theme's `detailCompact*` and `*_STYLE` values. `DETAIL_CONTENT_FRAME_STYLE`, `DETAILS_WIDGET_STYLE`, and `COMPACT_DETAILS_WIDGET_STYLE` style content layers, not the whole page background. Use `PLAY_BUTTON_STYLE` for actions and `ADDGAME_BACK_BUTTON_STYLE` for Back.
- `DETAIL_PAGE_BG_MODE` supports `gradient`, `blur`, `waves`, `aurora`, `metaballs`, `leaf`, `veins`, and `diagnostics`. Prefix an animated mode with `static_` for a still frame. These are separate from `detail_page_animation_type`.
- `DETAIL_PAGE_BACKGROUNDS['gradient']`: `type` is `linear` or `radial`; `stops` can be `None` (cover colors), a list of positions, a list of color stops, or a QSS string. Coordinates are `x1/y1/x2/y2` or `cx/cy/radius/fx/fy`. Legacy `DETAIL_PAGE_GRADIENT`, `DETAIL_PAGE_GRADIENT_TYPE`, `DETAIL_PAGE_GRADIENT_*` coordinates, and `DETAIL_PAGE_WAVES` are still accepted. Do not set conflicting legacy and current values.
- `DETAIL_PAGE_BACKGROUNDS` defines `animation_interval_ms` and `animation_speed`. `blur` uses `render_resolution` and `radius`; `waves` controls layer count, amplitude, frequency, spacing, `base_opacity`, and `opacity_decay`. `aurora`, `metaballs`, `leaf`, `veins`, and `diagnostics` have their own sections. See [Background Configuration](README.md#background-configuration) and verify keys against `.get(...)` in the current renderer. Do not move settings between renderer sections.
- `GAME_CARD_ANIMATION['detail_page_animation_type']` supports `fade`, `slide_left`, `slide_right`, `slide_up`, `slide_down`, and `bounce`. `detail_page_fade_duration`, `detail_page_slide_duration`, and `detail_page_bounce_duration` are in milliseconds; exit durations have separate `*_duration_exit` keys. Easing uses `detail_page_easing_curve` and `detail_page_easing_curve_exit`.
- **Check:** entering and leaving the page, changing or missing covers, long descriptions, and full and compact layouts. Verify that animated backgrounds visibly move, static ones do not start an animation, and going Back does not leave the old background behind.

### Card, Library Control, and Virtual Keyboard Animations

- `animations/game_card.py`: `GAME_CARD_ANIMATION['card_animation_type']` accepts `gradient` (gradient border), `glow`, `fill`, `stripe`, `scale`, and `scale_fill`. `default_border_width`, `hover_border_width`, `focus_border_width`, `pulse_min_border_width`, and `pulse_max_border_width` are in pixels. `default_scale`, `hover_scale`, and `focus_scale` are multipliers. `thickness_anim_duration`, `pulse_anim_duration`, `gradient_anim_duration`, and `scale_anim_duration` are in milliseconds.
- Rendering settings include `gradient_colors` (position/color pairs), `gradient_start_angle`/`gradient_end_angle`, `fill_color`/`fill_alpha`, `stripe_color`/`stripe_alpha`, and `glow_base_alpha`/`glow_pulse_alpha`. `thickness_easing_curve`, `scale_easing_curve`, and their `*_out` counterparts take Qt easing curve names. A palette change does not automatically recolor the animated border; check `gradient_colors`.
- `animations/library_controls.py` uses `library_controls_anim_duration` and `scale_easing_curve`/`scale_easing_curve_out` from the same dictionary when opening and closing the controls.
- `animations/virtual_keyboard.py`: `virtual_keyboard_animation_type` accepts `slide`, `fade`, `slide_fade`, and `slide_bounce`, with a corresponding `virtual_keyboard_*_animation_duration`. `SYSTEM_KEYBOARD` defines dimensions, layout, and spacing (`width`, `height`, `key_height`, `minimum_key_width`, `row_units`, `columns`, `spacing`, `margin`) and the `rows` and `emoji_rows` sets.
- **Check:** hover and focus separately, rapid movement between cards, loss of focus, whether a scaled card clips at the edge, returning from game details, and animations disabled. A screenshot alone does not verify a transition.

### Colors, QSS, and Geometry on Other Screens

Use `themes/standart/styles/constants.py` and `themes/standart-light/styles.py` as the canonical references. Find the exact key in the consumer rather than inventing one.

| Role | Example keys and selectors |
| --- | --- |
| Surfaces and text | `color_bg`, `color_bg_darker`, `color_surface`, `color_surface_elevated`, `color_surface_hover`, `color_text`, `color_text_dark` (Light), `color_text_muted`; for game details, `color_detail_overlay`, `color_cover_frame_bg`, `color_no_cover_bg` |
| States | `color_accent`, `color_text_accent_hover`, `color_border_focus`, `color_nav_inactive`, `color_disabled_bg`, `color_disabled_text`, `color_combo_disabled_*`, `color_checkbox_*`; QSS `:hover`, `:focus`, `:pressed`, `:checked`, `:disabled`, `:editable`, `:on`, and `QLineEdit` rules for combo boxes |
| Scrollbars, sliders, and borders | `color_scrollbar_bg`, `color_scrollbar_handle`, `scrollbar_handle_min_height`, `color_slider_handle`, `color_slider_groove_bg`, `color_border_input`, `color_border_subtle`, `color_border_light`, `color_border_faint`, `border_none`, `border_thin`, `border_medium`, `border_radius_*` |
| Typography and shadows | `font_family`, `font_size_small/normal/value/keyboard/header/play/title`, `shadow_blur_radius`, `shadow_offset`, `color_shadow_card`, `color_shadow_detail`, `settings_tooltip_offset_x/y` |
| Spacing and dimensions | `autoSizeButtonPadding`, `portProtonPageMargins`, `portProtonPage*Spacing`, `wineSettingsSetSpacing`, `themeStore*`, `downloads*`, `storeDlc*`, `mangoHud*`, `exeSettingsGroupBox*`, `WINETRICKS_*`, `COMPATIBILITY_REPORT_DIALOG`, `GAME_FOLDER_IMPORT_DIALOG_SIZE`, `RUN_AFTER_VALUE_WIDTH` |

Under `themes/standart/styles/`, look in `base.py` for the window, navigation, buttons, inputs, lists, scrolling, library, and carousel; `settings.py` for settings; `detail_page.py` and `game_card.py` for game UI; and `file_explorer.py`, `get_wine.py`, `winetricks.py`, and `theme_utils.py` for file browsing, Wine, Winetricks, menus, and utilities. Light defines some of these rules in `standart-light/styles.py`. Check narrow windows, scaling, long translations, actual borders and backgrounds of the editable Wine Prefix field, account fields, and focused icon contrast.

### Preloader, Boot Video, Sounds, and Terminal

- `preloader.py`: `PRELOADER['style']` accepts `default`, `bat`, `pulse`, `dots`, and `wave`. Shared settings include `speed` and `line_width`; effect-specific settings include `bat_color/size/alpha/flap_speed`, `pulse_color/count/max_radius/speed`, `dots_color/count/radius/dot_size/speed`, and `wave_color/width/amplitude/line_width/speed`. See `PRELOADER_DEFAULT` for all keys and defaults.
- `bootanimation.webm` lives in the theme directory and can be inherited. See `bootAnimationTimeoutMs` and `color_boot_animation`. Playback depends on fullscreen mode and the user's boot animation setting. Test skipping with a keyboard and a gamepad, not just playback.
- `sounds/`: override files by event name from `sound_manager.py:SOUND_EVENTS`: `navigate`, `click`, `back`, `toggle`, `open`, `tab_switch`, `game_launch`, `gamepad_connect`, and `gamepad_off`. Do not launch a game just to test a sound file.
- Terminal `.conf` schemes live separately in `terminal_schemes/` and are read by `scripts_utils/easyterm.py`. The [Theme Guide](README.md) documents text, background, selection, ANSI colors, font, and cursor settings. The UI palette does not automatically change the terminal scheme.

### Readability Without Changing the Palette

- Preserve the declared background, panel, and accent colors. If contrast is poor, use the palette's `onPrimary` color where provided, recolor the icon, or adjust where fills and spacing are applied. Check that the control stands out from its panel and that the icon and label are readable within it. Aim for 4.5:1 for ordinary text against the actual background after compositing transparency.
- If settings look flat, distinguish the page background from input surfaces using existing palette roles. Keyboard focus must be visible without the pointer. If the reference uses a contrasting fill, do not replace it with a thin border. Do not add an outline against the user's request.
- `AutoSizeButton` can draw its own text and SVG. If QSS `color:` does not help, inspect `_get_icon_color()` in `custom_widgets.py`. `ICON_COLORS` precedence is `<icon>_<state>`, `*_<state>`, then `<icon>`. The state is `focused`, not `focus`. Prefer specific keys such as `addgame_focused` and confirm the icon's actual name; a wildcard can change unrelated buttons. `ICON_COLORS` is not inherited.
- In an editable `QComboBox`, check both the combo box and its `QLineEdit`. `QComboBox:focus` can set text for an accent fill even though the editor stays dark. Inspect rendered text, not just `QPalette`.
- If the library still shows a purple-blue gradient, check `LIBRARY_WIDGET_STYLE` and its gradient separately. Changing `color_bg` alone is not enough.

## 6. Mistakes We Have Already Made

| What went wrong | How to avoid it |
| --- | --- |
| Nearly identical themes were imported, then given invented backgrounds and accents to make them look different. Eldritch Light lost its original pink and Solarized Dark lost its original hue. | Compare `background`, `surface`, `accent`, and text colors with the source for **both variants**. If the themes are too similar, suggest keeping fewer. Improve readability by changing the color role or icon, not by recoloring the palette without approval. |
| Only Settings was checked. The library kept the same purple-blue gradient because `color_bg` does not control it directly. | Check the populated library, game details, and settings separately. Inspect the library background and card border independently, including the gradient and renderer each uses. |
| All game detail buttons got the same fill, then the focus fill was replaced with a thin outline. The active button was hard to identify. Noctalia's yellow fill left the Add Shortcut label and icon white, even though Quick Launch was readable. | Follow the actual reference: a prominent focus fill, quieter neighboring buttons, and a contrasting label and SVG. Verify the real icon IDs, including `play`, `addgame`, and `back`. If the user wants no outline, do not just change the border color. Do not carry changes over to Light without discussion: it has its own colors and states. |
| Changing `QLineEdit` left `DEFAULT` dark even though `QPalette` checks passed. A later fix to the base style did not help the installed user theme. | Check `QComboBox:editable:focus`, the editor rule, actual rendered text pixels, and the installed theme's stylesheet together. Fix the affected theme, not the application base. In a portable theme, do not copy QSS that references `theme_manager` or `current_theme_name` when those names are not available in its module. Recheck the combo-box arrow. |
| `5_portproton_settings.png` was captured during an asynchronous transition and showed another game details page. Play was not focused in `2_detail.png`. The previews also included the window frame. | Capture settings before opening game details, or wait for the correct widget to become active. Verify that `2_detail` shows game details with only Play focused. Capture the client area or measure its bounds rather than using a fixed crop. Inspect the final PNG before replacing an existing preview. |
| Passing unit tests or a good-looking card were treated as proof that all screens worked. Canceled or interrupted captures were counted as complete. | State which variants and states were actually checked. Report any process signal after the pytest summary, cancellations, and old previews left in place. Inspect a full-size capture of the affected variant before running a batch. |
