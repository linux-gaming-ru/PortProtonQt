from portprotonqt.theme_manager import ThemeManager
from portprotonqt.config import ui_config

theme_manager = ThemeManager()
current_theme_name = ui_config.get_theme()

# CONSTANTS
autoSizeButtonPadding = (10, 20)
favoriteLabelSize = 48, 48
favoriteLabelIconSize = 32
detailCompactCoverFrameSize = 128
detailCompactCoverImageSize = 108
detailCompactContentSpacing = 15
detailCompactHeaderSpacing = 16
detailCompactTitleMargins = (0, 0, 0, 0)
detailCompactDescriptionMargins = (3, 3, 3, 3)
portProtonPageMargins = (15, 15, 15, 15)
portProtonPageHorizontalSpacing = 15
portProtonPageVerticalSpacing = 10
portProtonPageSectionHeaderSpacing = 10
wineSettingsSetSpacing = 10
themeStorePageSpacing = 10
themeStoreCardDefaultWidth = 280
themeStoreDetailCarouselMinHeight = 300
mangoHudSwitchesColumns = 4
mangoHudSwitchesVerticalSpacing = 10
mangoHudFpsColumns = 4
mangoHudFpsVerticalSpacing = 10
mangoHudPresetsColumns = 2
exeSettingsGroupBoxBlockSpacing = 14
exeSettingsGroupBoxElementVerticalSpacing = 10
exeSettingsGroupBoxElementHorizontalSpacing = 10

# VARS
font_family = "Play"
font_size_normal = "16px"
font_size_header = "24px"
border_none = "0px solid"
border_thin = "1px solid"
border_medium = "2px solid"
border_radius_small = "10px"
border_radius_large = "15px"
border_radius_card = "20px"
border_radius_badge = "5px"
color_accent = "#409EFF"
color_bg = "#F8F9FC"
color_bg_darker = "#bfc0c7"
color_surface = "#F0F2F5"
color_surface_elevated = "#E9ECEF"
color_surface_hover = "#DEE2E6"
color_text = "#ffffff"
color_text_accent_hover = "#F8F9FC"
color_text_dark = "#212529"
color_transparent = "transparent"
color_overlay = "rgba(40, 42, 51, 0.9)"
color_surface_light = "#d2d3db"
color_surface_mid = "#9394a5"

# === Button Icons Color ===
ICON_COLORS = {
    "*_hover": color_text,
    "*_pressed": color_text,
    "*_focused": color_text,
    "*_disabled": color_text,
}

# Widget State
color_combo_disabled_bg = "#dee2e6"
color_combo_disabled_border = "#dee2e6"
color_combo_disabled_text = "#777a84"

# Navigation
color_nav_inactive = "#7f7f7f"
color_separator = "#7f7f7f"

# Scrollbar
color_scrollbar_bg = "rgba(20, 20, 20, 0.20)"
color_scrollbar_handle = "#bfbfbf"
border_radius_scroll = "5px"

# Slider
color_slider_handle = "#bfbfbf"
color_slider_groove_bg = "rgba(20, 20, 20, 0.20)"

# Border variants
color_border_subtle = "rgba(255, 255, 255, 0.01)"
color_border_input = "rgba(255, 255, 255, 0.5)"
color_border_light = "rgba(255, 255, 255, 0.2)"
color_border_faint = "rgba(255, 255, 255, 0.05)"

# Checkbox
color_checkbox_unchecked_bg = "rgba(255, 255, 255, 0.1)"
color_checkbox_hover_bg = "rgba(255, 255, 255, 0.2)"

# Favorite
color_favorite_star = "gold"

# Badge
color_badge_steam_bg = "rgba(0, 0, 0, 0.5)"
color_badge_steam_text = "white"
color_badge_default_bg = "rgba(0, 0, 0, 0.5)"
color_badge_default_text = "white"

# ProtonDB badges
color_protondb_platinum_bg = "rgba(255,255,255,0.9)"
color_protondb_platinum_text = "black"
color_protondb_gold_bg = "rgba(253,185,49,0.7)"
color_protondb_gold_text = "black"
color_protondb_silver_bg = "rgba(169,169,169,0.8)"
color_protondb_silver_text = "black"
color_protondb_bronze_bg = "rgba(205,133,63,0.7)"
color_protondb_bronze_text = "black"
color_protondb_borked_bg = "rgba(255,0,0,0.7)"
color_protondb_borked_text = "black"
color_protondb_pending_bg = "rgba(160,82,45,0.7)"
color_protondb_pending_text = "black"

# Anticheat badges
color_anticheat_supported_bg = "rgba(102, 168, 15, 0.7)"
color_anticheat_supported_text = "black"
color_anticheat_running_bg = "rgba(25, 113, 194, 0.7)"
color_anticheat_running_text = "black"
color_anticheat_planned_bg = "rgba(156, 54, 181, 0.7)"
color_anticheat_planned_text = "black"
color_anticheat_broken_bg = "rgba(232, 89, 12, 0.7)"
color_anticheat_broken_text = "black"
color_anticheat_denied_bg = "rgba(224, 49, 49, 0.7)"
color_anticheat_denied_text = "black"

# Detail page
color_detail_overlay = "rgba(220, 222, 226, 0.40)"
color_cover_frame_bg = "rgba(233, 236, 239, 0.80)"
color_no_cover_bg = "rgba(220,222,226,0.95)"
color_detail_line = "rgba(0,0,0,0.12)"
color_card_gradient_start = "rgba(255, 255, 255, 1)"
color_card_gradient_end = "rgba(210, 211, 219, 0.5)"
color_library_gradient_start = "#cea2fa"
color_library_gradient_end = "#70b8ff"

# Preview buttons
color_preview_btn_bg = "rgba(0, 0, 0, 0.5)"
color_preview_btn_text = "white"

# Source corner
SOURCE_CORNER = {
    "ribbon_color": color_surface,
    "ribbon_fold_color": "#00000096",
    "size_ratio": 0.28,
    "min_size": 54,
    "min_widget_size": 4,
    "peel_start_ratio": 0.32,
    "peel_mid_ratio": 0.58,
    "peel_end_ratio": 0.82,
    "peel_shadow_width": 3,
    "fold_start_ratio": 0.60,
    "fold_end_ratio": 0.92,
    "icon_center_ratio": 0.84,
    "icon_size_ratio": 0.25,
    "min_icon_size": 8,
    "gradient_start": 0.0,
    "gradient_end": 1.0,
    "gradient_lighter": 145,
    "gradient_darker": 112,
    "fold_darker": 132,
}

# PPDB Badge colors
color_ppdb_platinum = "#b2b2ff"
color_ppdb_gold = "#ffc107"
color_ppdb_silver = "#e0e0e0"
color_ppdb_bronze = "#cd7f32"
color_ppdb_broken = "#f44336"

# QColor constants for programmatic use
color_shadow_card = "#00000096"
color_shadow_detail = "#000000c8"
color_placeholder_bg = "#333333"
color_default_fallback = "#1a1a1a"
color_disabled_bg = "#f0f0f0"
color_disabled_text = "#777a84"
color_text_muted = "#bbbbbb"
color_accent_blue = "#007AFF"
color_preloader = "#70b8ff"
color_gamepad_supported = "#00ff00"
color_white = "#ffffff"
missing_exe_cover_opacity = 0.45

# Shadow constants
shadow_blur_radius = 20
shadow_offset = (0, 0)
settings_tooltip_offset_x = 28
settings_tooltip_offset_y = 4
virtual_keyboard_slide_animation_duration = 160
virtual_keyboard_fade_animation_duration = 140
virtual_keyboard_slide_fade_animation_duration = 180
virtual_keyboard_slide_bounce_animation_duration = 220
virtual_keyboard_animation_type = "slide"

GAME_CARD_ANIMATION = {
    # Animation type for entering/exiting detail page
    # Possible values: "fade", "slide_left", "slide_right", "slide_up", "slide_down", "bounce"
    # Defines how the detail page appears and disappears
    "detail_page_animation_type": "fade",

    # Border width of card in idle state (no hover or focus)
    # Affects border thickness around card when not highlighted
    # Value in pixels
    "default_border_width": 2,

    # Border width on hover
    # Increases border thickness when cursor is over card
    # Value in pixels
    "hover_border_width": 8,

    # Border width on focus (e.g., keyboard selection)
    # Increases border thickness when card is focused
    # Value in pixels
    "focus_border_width": 12,

    # Minimum border width during pulse animation
    # Defines minimum border thickness during pulse (breathing) animation
    # Value in pixels
    "pulse_min_border_width": 8,

    # Maximum border width during pulse animation
    # Defines maximum border thickness during pulse
    # Value in pixels
    "pulse_max_border_width": 10,

    # Duration of border thickness change animation (e.g., on hover or focus)
    # Affects speed of transition between border widths
    # Value in milliseconds
    "thickness_anim_duration": 300,

    # Duration of one pulse animation cycle
    # Defines how fast border "pulses" between min and max values
    # Value in milliseconds
    "pulse_anim_duration": 800,

    # Duration of gradient rotation animation
    # Affects speed of gradient border rotation around card
    # Value in milliseconds
    "gradient_anim_duration": 3000,

    # Starting gradient angle (in degrees)
    # Defines starting point of gradient rotation
    "gradient_start_angle": 360,

    # Ending gradient angle (in degrees)
    # Defines ending point of gradient rotation
    # Value 0 means full 360 degree rotation
    "gradient_end_angle": 0,

    # Animation type for card on hover or focus
    # Possible values: "gradient", "scale", "fill", "stripe", "glow", "scale_fill"
    # "gradient" enables rotating gradient border, "scale" increases card size, "fill" applies accent overlay,
    # "stripe" applies static accent border, "glow" applies pulsing accent border,
    # "scale_fill" combines scale animation with fill overlay
    "card_animation_type": "gradient",

    # Overlay color for "fill" card animation type
    # Any valid Qt color string (hex/rgb/rgba)
    "fill_color": color_accent,

    # Overlay opacity for "fill" card animation type (0-255)
    "fill_alpha": 90,

    # Border color for "stripe" card animation type
    # Any valid Qt color string (hex/rgb/rgba)
    "stripe_color": color_accent,

    # Border opacity for "stripe" card animation type (0-255)
    "stripe_alpha": 255,

    # Base opacity for "glow" card animation type (0-255)
    "glow_base_alpha": 120,

    # Additional pulse opacity for "glow" card animation type (0-255)
    "glow_pulse_alpha": 80,

    # Card scale in idle state
    # Defines base card size (1.0 = 100% of original size)
    # Value as fraction (e.g., 1.0 for normal size)
    "default_scale": 1.0,

    # Card scale on hover
    # Increases card size on hover
    # Value as fraction (e.g., 1.1 = 110% of original size)
    "hover_scale": 1.1,

    # Card scale on focus (e.g., keyboard selection)
    # Increases card size on focus
    # Value as fraction (e.g., 1.05 = 105% of original size)
    "focus_scale": 1.05,

    # Duration of scale animation
    # Affects speed of card size change on hover or focus
    # Value in milliseconds
    "scale_anim_duration": 200,

    # Easing curve type for border thickness increase animation (on hover/focus)
    # Affects animation "feel" (e.g., smooth acceleration or deceleration)
    # Possible values: strings matching QEasingCurve.Type (e.g., "OutBack", "InOutQuad")
    "thickness_easing_curve": "OutBack",

    # Easing curve type for border thickness decrease animation (on hover/focus loss)
    # Affects "feel" of return to original border width
    "thickness_easing_curve_out": "InBack",

    # Easing curve type for scale increase animation (on hover/focus)
    # Affects scale animation "feel" (e.g., with "bounce" effect)
    # Possible values: strings matching QEasingCurve.Type
    "scale_easing_curve": "OutBack",

    # Easing curve type for scale decrease animation (on hover/focus loss)
    # Affects "feel" of return to original scale
    "scale_easing_curve_out": "InBack",

    # Gradient colors for animated border
    # List of dicts, each specifying position (0.0–1.0) and hex color
    # Affects border appearance on hover or focus if card_animation_type="gradient"
    "gradient_colors": [
        {"position": 0, "color": "#00fff5"},    # Start color (cyan)
        {"position": 0.33, "color": "#FF5733"}, # Color at 33% (orange)
        {"position": 0.66, "color": "#9B59B6"}, # Color at 66% (purple)
        {"position": 1, "color": "#00fff5"}     # End color (return to cyan)
    ],

    # Fade animation duration on detail page enter
    # Affects page appearance speed for fade animation
    # Value in milliseconds
    "detail_page_fade_duration": 350,

    # Slide animation duration on detail page enter
    # Affects page sliding speed for slide animation
    # Value in milliseconds
    "detail_page_slide_duration": 500,

    # Bounce animation duration on detail page enter
    # Affects page "bounce" speed for bounce animation
    # Value in milliseconds
    "detail_page_bounce_duration": 400,

    # Fade animation duration on detail page exit
    # Affects page disappearance speed for fade animation
    # Value in milliseconds
    "detail_page_fade_duration_exit": 350,

    # Slide animation duration on detail page exit
    # Affects page sliding speed for slide animation
    # Value in milliseconds
    "detail_page_slide_duration_exit": 500,

    # Bounce animation duration on detail page exit
    # Affects page "squeeze" speed for bounce animation
    # Value in milliseconds
    "detail_page_bounce_duration_exit": 400,

    # Easing curve type for detail page enter animation
    # Applied to slide and bounce animations, affects movement "feel"
    # Possible values: strings matching QEasingCurve.Type
    "detail_page_easing_curve": "OutCubic",

    # Easing curve type for detail page exit animation
    # Applied to slide and bounce animations, affects movement "feel"
    # Possible values: strings matching QEasingCurve.Type
    "detail_page_easing_curve_exit": "InCubic"
}

MAIN_WINDOW_STYLE = f"""
    QWidget {{
        background: {color_surface_light};
    }}
    QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QPushButton {{
        background: {color_surface};
        border: {border_medium} {color_border_subtle};
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        border: {border_medium} {color_accent};
    }}
    QPushButton:pressed {{
        background: {color_bg};
    }}
    QPushButton:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
    }}
"""

# Favorite Star
FAVORITE_LABEL_STYLE = f"color: {color_favorite_star}; font-size: 32px; background: {color_transparent};"

# Transparent background style
TRANSPARENT_BACKGROUND_STYLE = f"""
    QWidget {{
        background: {color_transparent};
    }}
"""

# QMessageBox STYLES (MESSAGE BOXES)
MESSAGE_BOX_STYLE = f"""
    QMessageBox {{
        background: {color_surface_light};
        border: {border_none};
    }}
    QMessageBox QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QMessageBox QPushButton {{
        background: {color_surface};
        border: {border_none} {color_transparent};
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-family: '{font_family}';
        padding: 8px 20px;
        min-width: 80px;
    }}
    QMessageBox QPushButton:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border-color: border: {border_thin} {color_accent};
    }}
    QMessageBox QPushButton:focus {{
        border: {border_medium} {color_accent};
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# PROGRESS BAR STYLE
PROGRESS_BAR_STYLE = f"""
    QProgressBar {{
        color: {color_text_dark};
        background-color: {color_surface};
        text-align: center;
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QProgressBar::chunk {{
        background-color: {color_accent};
    }}
"""

# STATUS BAR STYLE
STATUS_BAR_STYLE = f"""
    QStatusBar {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
"""

TAB_TITLE_STYLE = f"font-family: '{font_family}'; font-size: {font_size_header}; color: {color_text_dark}; background-color: none;"

# PARAMS_TITLE_STYLE
PARAMS_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        height: 34px;
        padding: 7px;
        background: {color_surface_elevated};
        border-radius: {border_radius_small};
        min-width: 150px;
    }}
"""

THEME_TAB_FOCUS_STYLE = f"""
    QComboBox#themeTabCombo:focus {{
        border: {border_thin} {color_text_dark};
        background-color: {color_accent};
    }}
    QPushButton#themeApplyButton:focus,
    QPushButton#themeDeleteButton:focus {{
        border: {border_thin} {color_text_dark};
    }}
    QGraphicsView#themeScreenshotsCarousel,
    QGraphicsView#themeStoreScreenshotsCarousel {{
        border: {border_medium} {color_transparent};
        border-radius: {border_radius_small};
    }}
    QGraphicsView#themeScreenshotsCarousel:focus,
    QGraphicsView#themeStoreScreenshotsCarousel:focus {{
        border: {border_thin} {color_accent};
    }}
"""

THEME_STORE_SCROLL_STYLE = f"""
    QScrollArea {{
        background: {color_surface_elevated};
        border: {border_none} {color_transparent};
    }}
"""

THEME_STORE_CARD_STYLE = f"""
    QFrame#themeStoreCard {{
        background: {color_surface};
        border: {border_thin} {color_border_light};
        border-radius: {border_radius_small};
    }}
    QFrame#themeStoreCard:hover {{
        background: {color_surface_hover};
        border: {border_thin} {color_accent};
    }}
    QFrame#themeStoreCard:focus {{
        background: {color_surface_hover};
        border: {border_medium} {color_accent};
    }}
"""

THEME_STORE_PREVIEW_STYLE = f"""
    QLabel {{
        background: {color_bg};
        border: {border_none} {color_transparent};
        border-top-left-radius: {border_radius_small};
        border-top-right-radius: {border_radius_small};
    }}
"""

THEME_STORE_CARD_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        background: {color_transparent};
        border: {border_none} {color_transparent};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        padding: 10px 12px 4px 12px;
    }}
"""

THEME_STORE_CARD_META_STYLE = f"""
    QLabel {{
        color: {color_text_muted};
        background: {color_transparent};
        border: {border_none} {color_transparent};
        font-family: '{font_family}';
        font-size: 13px;
        padding: 2px 12px;
    }}
"""

THEME_STORE_DETAIL_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        background: {color_transparent};
        border: {border_none} {color_transparent};
        font-family: '{font_family}';
        font-size: {font_size_header};
        font-weight: bold;
    }}
"""

THEME_STORE_DESCRIPTION_STYLE = f"""
    QTextBrowser {{
        color: {color_text_dark};
        background: {color_surface};
        border: {border_thin} {color_border_light};
        border-radius: {border_radius_small};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        padding: 12px;
    }}
"""

PREVIEW_WIDGET_STYLE = f"""
    QWidget {{
        margin-top: 3px;
        background-color: {color_surface_hover};
        border-radius: {border_radius_small};
    }}
"""

CONTENT_STYLE = f"""
    QLabel {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        color: {color_text_dark};
        background-color: none;
        border-bottom: {border_thin} {color_border_light};
        padding-bottom: 15px;
    }}
"""

LIBRARY_WIDGET_STYLE = f"""
    QWidget {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_library_gradient_start},
            stop:1 {color_library_gradient_end}
    );
        border-radius: 0px;
    }}
"""

LIBRARY_CONTROL_STYLE = f"""
    QWidget#libraryControlsWidget {{
        background: {color_bg_darker};
        border: {border_thin} {color_accent};
        border-radius: {border_radius_small};
    }}
    QWidget#libraryControlsWidget QCheckBox {{
        background: {color_transparent};
    }}
"""

# CONTAINER_STYLE
CONTAINER_STYLE= """
    QWidget {
        background-color: none;
    }
"""

# OTHER_PAGES_WIDGET_STYLE
OTHER_PAGES_WIDGET_STYLE= f"""
    QWidget {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_light},
            stop:1 {color_surface_mid}
    );
        border-radius: 0px;
    }}
"""

# CAROUSEL_WIDGET_STYLE
CAROUSEL_WIDGET_STYLE= f"""
    QWidget {{
        background: {color_surface_mid};
        border-radius: 0px;
    }}
"""

SETTINGS_FRAME_STYLE = f"""
    QFrame {{
        background: {color_transparent};
        border:  {border_thin} {color_surface};
        border-radius: {border_radius_large};
    }}
"""

SETTINGS_FRAME_TITLE_STYLE = f"""
    QLabel {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        color: {color_text_dark};
        background: {color_transparent};
        border:  {border_none} {color_surface};
    }}
"""

SETTINGS_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        height: 34px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        padding: 7px;
        background: {color_bg};
        border-radius: {border_radius_small};
        border:  {border_none} {color_surface};
        min-width: 320px;
    }}
"""

SETTINGS_TITLE_CHECKBOX_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        height: 34px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        padding: 7px;
        background: {color_transparent};
        border-radius: {border_radius_small};
        border:  {border_none} {color_surface};
        min-width: 180px;
    }}
"""

# Disabled line edit style
SETTINGS_DISABLED_INPUT_STYLE = f"background-color: {color_disabled_bg};"

# DRIVES BUTTONS STYLE (FILE MANAGER)
DRIVES_BUTTON_STYLE = f"""
    QPushButton {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        min-width: 90px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        border: {border_medium} {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_bg};
    }}
    QPushButton:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# OVERLAY STYLE
OVERLAY_WINDOW_STYLE = f"background: {color_bg};"
OVERLAY_BUTTON_STYLE = f"""
    QPushButton {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        border: {border_medium} {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_bg};
    }}
    QPushButton:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# QGroupBox STYLES
QGROUP_BOX_STYLE = f"""
    QGroupBox {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        color: {color_text_dark};
        border: {border_thin} {color_surface};
        border-radius: {border_radius_small};
        margin-top: 10px;
        margin-right: 10px;
        padding-top: 5px;
        background: {color_transparent};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
"""

# GAME CARD STYLE (GAMECARD)
GAME_CARD_WINDOW_STYLE = f"""
    QFrame {{
        border-radius: {border_radius_card};
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_card_gradient_start},
            stop:1 {color_card_gradient_end}
    );
        border: {border_none} {color_transparent};
    }}
"""

# GAME NAME LABEL IN CARD (QLabel)
GAME_CARD_NAME_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        background-color: {color_transparent};
        border: {border_none} {color_transparent};
        padding: 14px, 7px, 3px, 7px;
        qproperty-wordWrap: true;
    }}
"""

GAME_CARD_VERTICAL_NAME_STYLE = GAME_CARD_NAME_LABEL_STYLE

GAME_CARD_COLUMN_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_value};
        background: {color_transparent};
    }}
"""

LIBRARY_HEADER_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_small};
        font-weight: bold;
        background: {color_transparent};
    }}
"""

# PROTONDB BADGE STYLES ON CARD
def get_protondb_badge_style(tier):
    tier = tier.lower()
    tier_colors = {
        "platinum": {"background": color_protondb_platinum_bg, "color": color_protondb_platinum_text},
        "gold": {"background": color_protondb_gold_bg, "color": color_protondb_gold_text},
        "silver": {"background": color_protondb_silver_bg, "color": color_protondb_silver_text},
        "bronze": {"background": color_protondb_bronze_bg, "color": color_protondb_bronze_text},
        "borked": {"background": color_protondb_borked_bg, "color": color_protondb_borked_text},
        "pending": {"background": color_protondb_pending_bg, "color": color_protondb_pending_text}
    }
    colors = tier_colors.get(tier, {"background": color_badge_default_bg, "color": color_badge_default_text})
    return f"""
        qproperty-alignment: AlignCenter;
        background-color: {colors["background"]};
        color: {colors["color"]};
        border-radius: {border_radius_badge};
        font-family: '{font_family}';
        font-weight: bold;
    """

# WEANTICHEATYET BADGE STYLES
def get_anticheat_badge_style(status):
    status = status.lower()
    status_colors = {
        "supported": {"background": color_anticheat_supported_bg, "color": color_anticheat_supported_text},
        "running": {"background": color_anticheat_running_bg, "color": color_anticheat_running_text},
        "planned": {"background": color_anticheat_planned_bg, "color": color_anticheat_planned_text},
        "broken": {"background": color_anticheat_broken_bg, "color": color_anticheat_broken_text},
        "denied": {"background": color_anticheat_denied_bg, "color": color_anticheat_denied_text}
    }
    colors = status_colors.get(status, {"background": color_badge_default_bg, "color": color_badge_default_text})
    return f"""
        qproperty-alignment: AlignCenter;
        background-color: {colors["background"]};
        color: {colors["color"]};
        font-size: {font_size_normal};
        border-radius: {border_radius_badge};
        font-weight: bold;
    """

# STEAM BADGE STYLES
STEAM_BADGE_STYLE= f"""
    qproperty-alignment: AlignCenter;
    background: {color_badge_steam_bg};
    color: {color_badge_steam_text};
    border-radius: {border_radius_badge};
    font-family: '{font_family}';
    font-weight: bold;
"""


def get_source_corner_config() -> dict:
    return SOURCE_CORNER


# MAIN FRAME FOR GAME DETAILS
DETAIL_CONTENT_FRAME_STYLE = f"""
    QFrame {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_light},
            stop:1 {color_surface_mid}
        );
        border:  {border_none} transparent;
        border-radius: {border_radius_large};
    }}
"""

# FRAME UNDER COVER
COVER_FRAME_STYLE = f"""
    QFrame {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_elevated},
            stop:1 {color_surface_light}
        );
        border-radius: {border_radius_large};
        border:  {border_none} transparent;
    }}
"""

# COVER WIDGET
COVER_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        border:  {border_none} {color_transparent};
    }}
"""

# COVER LABEL BORDER RADIUS
COVER_LABEL_STYLE = f"border-radius: {border_radius_large};"

# DETAILS WIDGET (TEXT, DESCRIPTION)
DETAILS_WIDGET_STYLE = f"""
        QFrame {{
            background: qradialgradient(
            cx:0.5, cy:0.5, radius:0.8,
                stop:0 {color_surface_elevated},
                stop:1 {color_surface_light}
            );
            border-radius: {border_radius_large};
            padding: 10px;
        }}
        QWidget#child {{
            background: qradialgradient(
            cx:0.5, cy:0.5, radius:0.8,
                stop:0 {color_surface_elevated},
                stop:1 {color_surface_light}
            );
            border-radius: {border_radius_large};
            padding: 10px;
        }}
"""

COMPACT_DETAILS_WIDGET_STYLE = f"""
        QFrame, QWidget {{
            background: qradialgradient(
            cx:0.5, cy:0.5, radius:0.8,
                stop:0 {color_surface_elevated},
                stop:1 {color_surface_light}
            );
            border-radius: {border_radius_large};
            padding: 10px;
        }}
"""

# TITLE (HEADER) ON DETAIL PAGE
DETAIL_PAGE_TITLE_STYLE = f"font-family: '{font_family}'; font-size: 32px; color: {color_text_dark}; background: {color_transparent};"
COMPACT_DETAIL_PAGE_TITLE_STYLE = f"font-family: '{font_family}'; font-size: 32px; color: {color_text_dark}; background: {color_transparent};"

# DIVIDER LINE
DETAIL_PAGE_LINE_STYLE = f"background: {color_surface_light}; margin: 0 0;"

# DESCRIPTION TEXT
DETAIL_PAGE_DESC_STYLE = f"font-family: '{font_family}'; font-size: {font_size_normal}; color: {color_text_dark}; line-height: 1.5;"
COMPACT_DETAIL_PAGE_DESC_STYLE = f"font-family: '{font_family}'; font-size: {font_size_normal}; color: {color_text_dark}; line-height: 1.5; background: {color_transparent};"

# PLAYTIME WIDGET (PLAYTIME)
COMPACT_PLAYTIME_WIDGET_STYLE = f"background: {color_transparent}; border-radius: {border_radius_large}; padding: 10px;"

# ADDITIONAL INFO STYLES ON GAMES PAGE
LAST_LAUNCH_TITLE_STYLE = f"max-height: 16px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,stop:0 {color_surface_elevated},stop:1 {color_surface_light}); font-family: '{font_family}'; font-size: 11px; color: {color_text_dark}; text-transform: uppercase; letter-spacing: 0.75px;"
LAST_LAUNCH_VALUE_STYLE = f"height: 16px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,stop:0 {color_surface_elevated},stop:1 {color_surface_light}); font-family: '{font_family}'; font-size: 13px; color: {color_text_dark}; font-weight: 600; letter-spacing: 0.75px;"
PLAY_TIME_TITLE_STYLE = f"max-height: 16px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,stop:0 {color_surface_elevated},stop:1 {color_surface_light}); font-family: '{font_family}'; font-size: 11px; color: {color_text_dark}; text-transform: uppercase; letter-spacing: 0.75px;"
PLAY_TIME_VALUE_STYLE = f"height: 16px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,stop:0 {color_surface_elevated},stop:1 {color_surface_light}); font-family: '{font_family}'; font-size: 13px; color: {color_text_dark}; font-weight: 600; letter-spacing: 0.75px;"
GAMEPAD_SUPPORT_VALUE_STYLE = f"""
    font-family: '{font_family}'; font-size: {font_size_normal}; color: {color_gamepad_supported};
    font-weight: bold; background: transparent;
    border-radius: {border_radius_badge}; padding: 4px 8px;
"""

# PLAY BUTTON STYLE
PLAY_BUTTON_STYLE = f"""
    QPushButton {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_elevated},
            stop:1 {color_surface_light}
        );
        border: {border_thin} {color_text};
        border-radius: {border_radius_small};
        font-size: {font_size_normal};
        margin-top: 15px;
        color: {color_text_dark};
        font-weight: bold;
        font-family: '{font_family}';
        padding: 8px 16px;
        margin-top: 15px;
        min-width: 120px;
        min-height: 30px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:focus {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# BACKGROUND FOR DETAIL PAGE IF COVER NOT LOADED
DETAIL_PAGE_NO_COVER_STYLE = f"background: {color_no_cover_bg}; border-radius: {border_radius_large};"

# STYLE FOR "ADD GAME" AND "BACK" BUTTONS ON DETAIL PAGE AND LIBRARY
ADDGAME_BACK_BUTTON_STYLE = f"""
    QPushButton {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_elevated},
            stop:1 {color_surface_light}
        );
        border: {border_thin} {color_text};
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 5px 10px;
        min-width: 120px;
        min-height: 25px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:focus {{
        background: {color_accent};
        border: {border_thin} {color_accent};
        color: {color_text_accent_hover};
    }}
"""

LIBRARY_CONTROLS_BUTTON_STYLE = f"""
    QPushButton {{
        background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.8,
            stop:0 {color_surface_elevated},
            stop:1 {color_surface_light}
        );
        border: {border_thin} {color_text};
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 5px 10px;
        min-width: 24px;
        min-height: 25px;
    }}
    QPushButton:hover,
    QPushButton:pressed,
    QPushButton:focus,
    QPushButton:checked {{
        background: {color_accent};
        border: {border_thin} {color_accent};
    }}
"""

# SEARCH FIELD STYLE
SEARCH_EDIT_STYLE = f"""
    QLineEdit {{
        background: {color_bg};
        border: {border_none};
        border-radius: {border_radius_small};
        padding: 7px 14px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        color: {color_text_dark};
        min-height: 24px;
    }}
    QLineEdit:hover {{
        border: {border_thin} {color_accent};
    }}
    QLineEdit:focus {{
        border: {border_thin} {color_accent};
    }}
"""

# SLIDER_SIZE_STYLE
SLIDER_SIZE_STYLE= f"""
    QWidget {{
        background: {color_transparent};
        height: 25px;
    }}
    QSlider::groove:horizontal {{
        border:  {border_none};
        border-radius: 3px;
        height: 6px;
        background: {color_slider_groove_bg};
        margin: 6px 0;
    }}
    QSlider::handle:horizontal {{
        background: {color_slider_handle};
        border:  {border_none};
        width: 18px;
        height: 18px;
        margin: -6px 0;
        border-radius: 9px;
    }}
"""

# GAME CARD AREA STYLE (QWidget)
LIST_WIDGET_STYLE = f"""
    QWidget {{
        background: none;
        border:  {border_none} transparent;
        border-radius: {border_radius_card};
    }}
"""

# NAVIGATION TAB BUTTON STYLE
NAV_BUTTON_STYLE = f"""
    NavLabel {{
        background: {color_transparent};
        padding: 6px 3px;
        margin: 10px 0 10px 10px;
        color: {color_overlay};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        text-transform: uppercase;
        border: {color_accent};
        border-radius: 0px;
    }}
    NavLabel[checked = true] {{
        background: {color_transparent};
        color: {color_text_dark};
        font-weight: normal;
        text-decoration: none;
        border-bottom: {border_medium} {color_accent};
        border-radius: 0px;
    }}
    NavLabel:hover {{
        background: {color_transparent};
        color: {color_text_dark};
        border-bottom: {border_medium} {color_nav_inactive};
    }}
    NavLabel[checked = true]:hover {{
        background: {color_transparent};
        color: {color_text_dark};
        border-bottom: {border_medium} {color_accent};
    }}
"""

# NAVIGATION AREA STYLE (TAB BUTTONS)
NAV_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        border:  {border_none};
    }}
"""

WINETRICKS_TABBLE_STYLE = f"""
QTableWidget {{
    background: {color_transparent};
    color: {color_text_dark};
    gridline-color: {color_transparent};
    alternate-background-color: {color_surface_hover};
    border: {border_none};
    border-radius: {border_radius_small};
    font-family: '{font_family}';
    font-size: {font_size_normal};
}}
QHeaderView::section {{
    background: {color_surface_elevated};
    color: {color_text_dark};
    padding: 5px;
    border: {border_none};
    font-weight: bold;
    font-family: '{font_family}';
    font-size: {font_size_normal};
}}
QTableWidget::item {{
    padding: 8px;
    border-bottom: {border_none} {color_surface};
    height: 36px;
}}
QTableWidget::item:selected,
QTableWidget::item:focus,
QTableWidget::item:selected:focus {{
    background: {color_accent};
    color: {color_text_accent_hover};
    selection-background-color: {color_accent};
}}
QTableWidget::item:hover {{
    background: {color_transparent};
    color: {color_text_accent_hover};
}}
QTableWidget::item:selected:hover {{
    background: {color_accent};
    color: {color_text_accent_hover};
}}
"""

SCROLL_STYLE = f"""
    QScrollBar:vertical {{
        width: 10px;
        border:  {border_none};
        border-radius: {border_radius_scroll};
        background: {color_scrollbar_bg};
    }}
    QScrollBar::handle:vertical {{
        background: {color_scrollbar_handle};
        border:  {border_none};
        border-radius: {border_radius_scroll};
    }}
    QScrollBar::add-line:vertical {{
        border:  {border_none};
        background: none;
    }}
    QScrollBar::sub-line:vertical {{
        border:  {border_none};
        background: none;
    }}
    QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {{
        border:  {border_none};
        width: 3px;
        height: 3px;
        background: none;
    }}
    QScrollBar:horizontal {{
        height: 10px;
        border:  {border_none};
        border-radius: {border_radius_scroll};
        background: {color_scrollbar_bg};
    }}
    QScrollBar::handle:horizontal {{
        background: {color_scrollbar_handle};
        border:  {border_none};
        border-radius: {border_radius_scroll};
    }}
    QScrollBar::add-line:horizontal {{
        border:  {border_none};
        background: none;
    }}
    QScrollBar::sub-line:horizontal {{
        border:  {border_none};
        background: none;
    }}
    QScrollBar::up-arrow:horizontal, QScrollBar::down-arrow:horizontal {{
        border:  {border_none};
        width: 3px;
        height: 3px;
        background: none;
    }}
"""

# COMBOBOX
COMBOBOX_STYLE = f"""
    QComboBox {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        padding-left: 12px;
        height: 34px;
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        min-width: 120px;
        combobox-popup: 0;
    }}
    QComboBox:on {{
        background: {color_bg};
        border: {border_medium} {color_accent};
        border-bottom-style: none;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
    }}
    QComboBox:hover {{
        border: {border_medium} {color_accent};
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    /* Focus state */
    QComboBox:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
        color: {color_text_accent_hover};
    }}
    QComboBox:disabled {{
        background: {color_combo_disabled_bg};
        border: {border_medium} {color_combo_disabled_border};
        color: {color_combo_disabled_text};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        border-left: {border_thin} {color_border_faint};
        padding: 12px;
        height: 12px;
        width: 12px;
    }}
    QComboBox::down-arrow {{
        image: url({theme_manager.get_icon("down", current_theme_name, as_path=True)});
        padding: 12px;
        height: 12px;
        width: 12px;
    }}
    QComboBox::down-arrow:on {{
        image: url({theme_manager.get_icon("up", current_theme_name, as_path=True)});
        padding: 12px;
        height: 12px;
        width: 12px;
    }}
/* List when combobox is open */
    QComboBox QAbstractItemView {{
        outline: none;
        background: {color_surface};
        border: {border_medium} {color_accent};
        border-top-style: none;
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
        border-bottom-left-radius: 10px;
        border-bottom-right-radius: 10px;
    }}
    QComboBox:editable {{
        background: {color_surface};
        color: {color_text_dark};
    }}
    QComboBox::drop-down:editable:focus {{
        background: {color_accent};
        border-top-left-radius: 0px;
        border-top-right-radius: 10px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 10px;
    }}
    QListView {{
        background: {color_surface};
    }}
    QListView::item {{
        padding: 7px 7px 7px 12px;
        margin: 3px;
        min-height: 24px;
        border-radius: {border_radius_small};
        color: {color_text_dark};
    }}
    QListView::item:hover {{
        background: {color_bg};
    }}
    QListView::item:selected {{
        background: {color_bg};
    }}
    /* Selection in list when item is focused */
    QListView::item:focus {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

SETTINGS_TABLE_COMBOBOX_STYLE = f"""
    QComboBox#settingsTableCombo:hover,
    QComboBox#settingsTableCombo:focus {{
        background: {color_surface};
        border: {border_medium} {color_accent};
        color: {color_text_dark};
    }}
"""

CHECKBOX_STYLE = f"""
    QCheckBox {{
        height: 34px;
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QCheckBox::indicator {{
        width: 24px;
        height: 24px;
        border: {border_medium} {color_scrollbar_handle};
        border-radius: {border_radius_small};
        background: {color_surface};
    }}
    QCheckBox::indicator:hover {{
        background: {color_surface};
        border: {border_medium} {color_accent};
    }}
    QCheckBox::indicator:focus {{
        border: {border_medium} {color_accent};
    }}
    QCheckBox::indicator:checked {{
        image: url({theme_manager.get_icon("check", current_theme_name, as_path=True)});
        border: {border_medium} {color_accent};
    }}
    QCheckBox::indicator:disabled {{
        background: {color_surface_hover};
        border: {border_medium} {color_surface_hover};
    }}
    QCheckBox::indicator:checked:disabled {{
        image: url({theme_manager.get_icon("check", current_theme_name, as_path=True)});
        background: {color_surface_hover};
        border: {border_medium} {color_surface_hover};
    }}

    QTableWidget::indicator {{
        width: 24px;
        height: 24px;
        border: {border_medium} {color_scrollbar_handle};
        border-radius: {border_radius_small};
        background: {color_surface};
    }}
    QTableWidget::indicator:unchecked {{
        background: {color_surface};
        border: {border_medium} {color_scrollbar_handle};
        image: none;
    }}
    QTableWidget::indicator:checked {{
        background: {color_bg};
        image: url({theme_manager.get_icon("check", current_theme_name, as_path=True)});
        border: {border_medium} {color_accent};
    }}
    QTableWidget::indicator:hover {{
        background: {color_checkbox_hover_bg};
        border: {border_medium} {color_accent};
    }}
    QTableWidget::indicator:focus {{
        background: {color_checkbox_hover_bg};
        border: {border_medium} {color_accent};
    }}
    QTableWidget::indicator:disabled {{
        background: {color_bg};
        border: {border_medium} {color_surface_elevated};
    }}
    QTableWidget::indicator:checked:disabled {{
        image: url({theme_manager.get_icon("check", current_theme_name, as_path=True)});
        background: {color_bg};
        border: {border_medium} {color_surface_elevated};
    }}
"""

LINE_EDIT_STYLE = f"""
    QLineEdit {{
        background: {color_surface};
        border: {border_medium} {color_border_subtle};
        border-radius: {border_radius_small};
        height: 34px;
        padding-left: 12px;
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QLineEdit:hover {{
        background: {color_surface};
        border: {border_medium} {color_accent};
    }}
    QLineEdit:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_surface_hover};
    }}
"""

ADDGAME_INPUT_STYLE = f"""
    QLineEdit {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        height: 34px;
        padding-left: 12px;
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QLineEdit:hover {{
        background: {color_surface};
        border: {border_medium} {color_accent};
    }}
    QLineEdit:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_surface_hover};
    }}
"""

TAB_STYLE = f"""
    QTabWidget::pane {{
        border-top: 1px solid {color_surface};
        background: {color_transparent};
    }}
    QTabBar::tab {{
        background: {color_surface};
        color: {color_text_dark};
        padding: 8px 16px;
        border-top-left-radius: {border_radius_small};
        border-top-right-radius: {border_radius_small};
        margin-right: 2px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QTabBar::tab:selected {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QTabBar::tab:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# HINT BAR STYLE
HINT_BAR_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        max-height: 82px;
    }}
"""

# HINT LABEL STYLE
HINTS_LABEL_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        font-family: '{font_family}';
        font-size: 13px;
        color: {color_text_dark};
        font-weight: 600;
        letter-spacing: 0.75px;
    }}
"""

# MAIN WINDOW HEADER STYLE
MAIN_WINDOW_HEADER_STYLE = f"""
    QFrame {{
        background: {color_transparent};
        border: 10px solid transparent;
        border-bottom: 0px solid transparent;
        border-top-left-radius: 30px;
        border-top-right-radius: 30px;
        border: none;
    }}
"""

# ACTION BUTTONS STYLE (SAVE, APPLY, ETC.)
ACTION_BUTTON_STYLE = f"""
    QPushButton {{
        background: {color_bg};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        border: {border_medium} {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

# ACTION BUTTON ACTIVE STYLE (MANGOHUD, GAMESCOPE ETC.)
ACTION_BUTTON_ACTIVE_STYLE = f"""
    QPushButton {{
        background: {color_surface};
        border: {border_medium} {color_accent};
        border-radius: {border_radius_small};
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        border: {border_medium} {color_accent};
        color: {color_text_accent_hover};
    }}
    QPushButton:pressed {{
        background: {color_bg};
    }}
    QPushButton:focus {{
        border: {border_medium} {color_accent};
        background-color: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

GETWINE_WINDOW_STYLE = f"""
/* Table */
QHeaderView::section {{
    background: {color_surface_elevated};
    color: {color_text_dark};
    border: {border_none};
    font-weight: bold;
    font-family: '{font_family}';
    font-size: {font_size_normal};
}}
QTableWidget {{
    background: {color_transparent};
    gridline-color: {color_transparent};
    color: {color_text_dark};
    alternate-background-color: {color_surface_elevated};
    border: {border_none};
    border-radius: {border_radius_small};
    font-family: '{font_family}';
    font-size: {font_size_normal};
}}
QTableWidget::item:!enabled {{
    color: #7a7a7a;
}}
QTableWidget::item:selected,
QTableWidget::item:selected:!active,
QTableWidget::item:hover {{
    background: {color_accent};
    color: {color_text_accent_hover};
}}
/* LogArea */
QFrame {{
    background: {color_transparent};
}}
QTextEdit {{
    background: {color_surface_hover};
    border: {border_none};
    border-radius: {border_radius_small};
    color: {color_text_dark};
    font-family: '{font_family}';
    font-size: {font_size_normal};
    padding: 5px;
}}
QProgressBar {{
    color: {color_text_dark};
    background-color: {color_surface};
    height: 34px;
    text-align: center;
    font-family: '{font_family}';
    font-size: {font_size_normal};
}}
QProgressBar::chunk {{
    background-color: {color_accent};
}}
"""

# Empty state label style
GETWINE_EMPTY_LABEL_STYLE = f"font-size: {font_size_normal}; padding: 50px;"

FILE_EXPLORER_STYLE = f"""
    QListView {{
        font-size: {font_size_normal};
        font-family: {font_family};
        background: {color_surface_hover};
        alternate-background-color: {color_surface_hover};
        color: {color_text_dark};
        border-top-left-radius: 5px;
        border-bottom-left-radius: 5px;
    }}
    QListView::item {{
        padding: 8px;
        margin: 0px 5px;
    }}
    QListView::item:alternate {{
        margin: 0px 5px;
        background: {color_surface_elevated};
    }}
    QListView::item:selected {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border-radius: {border_radius_small};
    }}
    QListView::item:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border-radius: {border_radius_small};
    }}
    QListView::item:focus {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border-radius: {border_radius_small};
    }}
"""

FILE_EXPLORER_PATH_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_dark};
        font-size: {font_size_normal};
        font-family: {font_family};
    }}
"""

CONTEXT_MENU_STYLE = f"""
    QMenu {{
        background: {color_bg};
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        padding: 5px;
        min-width: 150px;
        border: {border_thin} {color_accent};
        border-radius: {border_radius_small};
    }}
    QMenu::icon {{
        margin-left: 15px;
    }}
    QMenu::item {{
        padding: 10px 20px 10px 10px;
        background: {color_transparent};
        border-radius: {border_radius_small};
        color: {color_text_dark};
    }}
    QMenu::item:selected {{
        background: {color_accent};
        color: {color_text};
    }}
    QMenu::item:disabled {{
            color: {color_nav_inactive};
        }}
    QMenu::item:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QMenu::item:focus {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border: {border_thin} {color_border_light};
        border-radius: {border_radius_small};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {color_separator};
        margin: 3px 6px;
    }}
"""

VIRTUAL_KEYBOARD_STYLE = f"""
QWidget {{
    background: {color_surface_mid};
}}
QPushButton {{
    font-size: 14px;
    border: {border_none} {color_transparent};
    border-radius: {border_radius_small};
    min-width: 30px;
    min-height: 30px;
    padding: 5px;
    background-color: {color_surface_hover};
    color: {color_text_dark};
}}
QPushButton:hover {{
    background-color: {color_accent};
    border: {border_thin} {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton:focus {{
    border: {border_thin} {color_accent};
    background-color: {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton[vk_selected="true"] {{
    border: {border_thin} {color_accent};
    background-color: {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton:pressed {{
    background-color: {color_surface_hover};
    border: {border_none} {color_transparent};
    color: {color_text};
}}
QPushButton[checked="true"] {{
    background-color: {color_accent};
    color: {color_text_accent_hover};
    border: {border_none} {color_transparent};
}}
QPushButton[checked="true"]:focus {{
    border: {border_thin} {color_text};
}}
"""

# FULLSCREEN THEME SCREENSHOT PREVIEW STYLES
PREV_BUTTON_STYLE=f"background-color: {color_preview_btn_bg}; color: {color_preview_btn_text}; border: none;"
NEXT_BUTTON_STYLE=f"background-color: {color_preview_btn_bg}; color: {color_preview_btn_text}; border: none;"

TOOLTIP_STYLE = f"""
    QLabel {{
        background-color: {color_bg};
        border: {border_thin} {color_surface};
        padding: 8px;
        color: {color_text_dark};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
"""
