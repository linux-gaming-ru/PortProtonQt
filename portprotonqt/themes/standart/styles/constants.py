from portprotonqt.theme_manager import ThemeManager
from portprotonqt.config import ui_config

theme_manager = ThemeManager()
current_theme_name = ui_config.get_theme()

# === Layout Constants ===
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
downloadsSummaryHeight = 96
downloadsTableHeaderHeight = 38
downloadsTableRowHeight = 68
downloadsCoverSize = (72, 48)
downloadsCoverRadius = 6
downloadsSectionSpacing = 14
downloadsCellMargins = (8, 6, 8, 6)
downloadsCellSpacing = 10
downloadsActiveCardHeight = 190
downloadsActiveCoverSize = (180, 120)
downloadsActiveCardMargins = (16, 14, 16, 14)
downloadsActiveCardSpacing = 14
storeDlcDialogWidth = 480
storeDlcVisibleRows = 3
storeDlcCoverSize = (56, 36)
storeDlcRowHeight = 52
mangoHudSwitchesColumns = 4
mangoHudSwitchesVerticalSpacing = 10
mangoHudFpsColumns = 4
mangoHudFpsVerticalSpacing = 10
mangoHudPresetsColumns = 2
exeSettingsGroupBoxBlockSpacing = 14
exeSettingsGroupBoxElementVerticalSpacing = 10
exeSettingsGroupBoxElementHorizontalSpacing = 10

# === Typography ===
font_family = "Play"
font_size_small = "11px"
font_size_normal = "16px"
font_size_value = "13px"
font_size_keyboard = "14px"
font_size_header = "24px"
font_size_play = "18px"
font_size_title = "32px"

# === Borders ===
border_none = "0px solid"
border_thin = "1px solid"
border_medium = "2px solid"
border_radius_small = "10px"
border_radius_large = "15px"
border_radius_card = "20px"
border_radius_header = "30px"
border_radius_badge = "5px"
border_radius_slider = "3px"
border_radius_slider_handle = "9px"

# === Core Palette ===
color_accent = "#409EFF"
color_bg = "#282a33"
color_bg_darker = "#22242b"
color_surface = "#3f424d"
color_surface_elevated = "#32343d"
color_surface_hover = "#404554"
color_text = "#ffffff"
color_text_accent_hover = "#ffffff"
color_transparent = "transparent"
color_overlay = "rgba(40, 42, 51, 0.9)"

# === Secondary Palette ===
color_shadow_card = "#00000096"
color_shadow_detail = "#000000c8"
color_placeholder_bg = "#333333"
color_default_fallback = "#1a1a1a"
color_disabled_bg = "#f0f0f0"
color_disabled_text = "#777a84"
color_text_muted = "#bbbbbb"
color_accent_blue = "#007AFF"
color_preloader = "#007AFF"
color_gamepad_supported = "#00ff00"
color_white = "#ffffff"
missing_exe_cover_opacity = 0.45

# === Button Icons Color ===
ICON_COLORS = {
    "*_hover": color_text,
    "*_pressed": color_text,
    "*_focused": color_text,
    "*_disabled": color_text,
}

# === Widget State Colors ===
color_combo_disabled_bg = "#2a2c35"
color_combo_disabled_border = "#2a2c35"
color_combo_disabled_text = "#777a84"

# === Navigation ===
color_nav_inactive = "#7f7f7f"
color_separator = "#7f7f7f"

# === Scrollbar ===
color_scrollbar_bg = "rgba(20, 20, 20, 0.30)"
color_scrollbar_handle = "#bebebe"
border_radius_scroll = "5px"

# === Slider ===
color_slider_handle = "#bebebe"
color_slider_groove_bg = "rgba(20, 20, 20, 0.30)"

# === Border Variants ===
color_border_subtle = "rgba(255, 255, 255, 0.01)"
color_border_input = "rgba(255, 255, 255, 0.5)"
color_border_light = "rgba(255, 255, 255, 0.2)"
color_border_faint = "rgba(255, 255, 255, 0.05)"
color_border_focus = "rgba(255, 255, 255, 0.3)"

# === Checkbox ===
color_checkbox_unchecked_bg = "rgba(255, 255, 255, 0.1)"
color_checkbox_hover_bg = "rgba(255, 255, 255, 0.2)"

# === Favorite ===
color_favorite_star = "gold"

# === Badge: Steam ===
color_badge_steam_bg = "rgba(0, 0, 0, 0.5)"
color_badge_steam_text = "white"
color_badge_default_bg = "rgba(0, 0, 0, 0.5)"
color_badge_default_text = "white"

# === Badge: ProtonDB ===
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

# === Badge: PPDB ===
color_ppdb_platinum = "#b2b2ff"
color_ppdb_gold = "#ffc107"
color_ppdb_silver = "#e0e0e0"
color_ppdb_bronze = "#cd7f32"
color_ppdb_broken = "#f44336"

# === Badge: Anticheat ===
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

# === Detail Page ===
color_detail_overlay = "rgba(20, 20, 20, 0.40)"
color_cover_frame_bg = "rgba(30, 30, 30, 0.80)"
color_no_cover_bg = "rgba(20,20,20,0.95)"
color_detail_line = "rgba(255,255,255,0.12)"

# === Library Gradient ===
color_library_gradient_start = "rgba(112,20,132,1)"
color_library_gradient_end = "rgba(50,134,182,1)"

# === Source Corner (Ribbon) ===
SOURCE_CORNER = {
    "ribbon_color": "#3f424d",
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

# === Compact Card ===
COMPACT_CARD = {
    "width_threshold": 150,
    "height_ratio": 2.25,
    "title_lines": 3,
    "title_scale": 0.75,
}

# === Detail Compact ===
DETAIL_COMPACT = {
    "cover_size": 128,
    "width": 1280,
    "cover_image_size": 108,
    "content_spacing": 15,
    "header_spacing": 16,
    "title_margins": (0, 0, 0, 0),
    "description_margins": (3, 3, 3, 3),
}

# === Badge Layout ===
BADGE = {
    "width": 200,
    "icon_size": 16,
    "compact_width": 30,
    "right_margin": 8,
    "spacing": 5,
    "top_y": 10,
}

# === Cover ===
COVER = {
    "width": 300,
    "height": 450,
}

# === Preview Buttons ===
color_preview_btn_bg = "rgba(0, 0, 0, 0.5)"
color_preview_btn_text = "white"

# === Shadow ===
shadow_blur_radius = 20
shadow_offset = (0, 0)
settings_tooltip_offset_x = 28
settings_tooltip_offset_y = 4

# === Animation ===
virtual_keyboard_slide_animation_duration = 160
virtual_keyboard_fade_animation_duration = 140
virtual_keyboard_slide_fade_animation_duration = 180
virtual_keyboard_slide_bounce_animation_duration = 220
virtual_keyboard_animation_type = "slide"
DETAIL_PAGE_LAYOUT_MODE = "full"

COMPATIBILITY_REPORT_DIALOG = {
    "minimum_width": 760,
    "minimum_height": 560,
    "icon_size": 48,
    "margin": 24,
    "spacing": 16,
}

GAME_CARD_ANIMATION = {
    "detail_page_animation_type": "fade",
    "default_border_width": 2,
    "hover_border_width": 8,
    "focus_border_width": 12,
    "pulse_min_border_width": 8,
    "pulse_max_border_width": 10,
    "thickness_anim_duration": 300,
    "pulse_anim_duration": 800,
    "gradient_anim_duration": 3000,
    "gradient_start_angle": 360,
    "gradient_end_angle": 0,
    "card_animation_type": "gradient",
    "fill_color": color_accent,
    "fill_alpha": 90,
    "stripe_color": color_accent,
    "stripe_alpha": 255,
    "glow_base_alpha": 120,
    "glow_pulse_alpha": 80,
    "default_scale": 1.0,
    "hover_scale": 1.1,
    "focus_scale": 1.05,
    "scale_anim_duration": 200,
    "thickness_easing_curve": "OutBack",
    "thickness_easing_curve_out": "InBack",
    "scale_easing_curve": "OutBack",
    "scale_easing_curve_out": "InBack",
    "gradient_colors": [
        {"position": 0, "color": "#00fff5"},
        {"position": 0.33, "color": "#FF5733"},
        {"position": 0.66, "color": "#9B59B6"},
        {"position": 1, "color": "#00fff5"},
    ],
    "detail_page_fade_duration": 350,
    "detail_page_slide_duration": 500,
    "detail_page_bounce_duration": 400,
    "detail_page_fade_duration_exit": 350,
    "detail_page_slide_duration_exit": 500,
    "detail_page_bounce_duration_exit": 400,
    "detail_page_easing_curve": "OutCubic",
    "detail_page_easing_curve_exit": "InCubic",
}
