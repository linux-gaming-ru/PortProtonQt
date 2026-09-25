from .constants import *

# GAME CARD STYLE (GAMECARD)
GAME_CARD_WINDOW_STYLE = f"""
    QFrame {{
        border-radius: {border_radius_card};
        background: {color_detail_overlay};
        border:  {border_none} transparent;
    }}
"""

FULL_LIBRARY_TILE_STYLE = GAME_CARD_WINDOW_STYLE

GAME_CARD_VERTICAL_STYLE = GAME_CARD_WINDOW_STYLE

# GAME NAME LABEL IN CARD (QLabel)
GAME_CARD_NAME_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        background-color: {color_transparent};
        border-bottom-left-radius: {border_radius_card};
        border-bottom-right-radius: {border_radius_card};
        padding: 14px, 7px, 3px, 7px;
        qproperty-wordWrap: true;
    }}
"""

GAME_CARD_VERTICAL_NAME_STYLE = GAME_CARD_NAME_LABEL_STYLE

GAME_CARD_COLUMN_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_muted};
        font-family: '{font_family}';
        font-size: {font_size_value};
        background: {color_transparent};
    }}
"""

LIBRARY_HEADER_STYLE = f"""
    QWidget {{
        background: {color_surface_elevated};
        border-radius: {border_radius_small};
    }}
"""

LIBRARY_HEADER_LABEL_STYLE = f"""
    QLabel {{
        color: {color_text_muted};
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
        "pending": {"background": color_protondb_pending_bg, "color": color_protondb_pending_text},
    }
    colors = tier_colors.get(tier, {"background": color_badge_default_bg, "color": color_badge_default_text})
    return f"""
        qproperty-alignment: AlignCenter;
        background-color: {colors["background"]};
        color: {colors["color"]};
        border-radius: {border_radius_badge};
        font-family: '{font_family}';
        font-weight: bold;
        font-style: normal;
    """

# PPDB BADGE STYLES
def get_ppdb_badge_style(tier):
    tier = tier.lower()
    tier_colors = {
        "platinum": {"background": color_ppdb_platinum, "color": "black"},
        "gold": {"background": color_ppdb_gold, "color": "black"},
        "silver": {"background": color_ppdb_silver, "color": "black"},
        "bronze": {"background": color_ppdb_bronze, "color": "black"},
        "broken": {"background": color_ppdb_broken, "color": "black"},
    }
    colors = tier_colors.get(tier, {"background": color_badge_default_bg, "color": color_badge_default_text})
    return f"""
        qproperty-alignment: AlignCenter;
        background-color: {colors["background"]};
        color: {colors["color"]};
        border-radius: {border_radius_badge};
        font-family: '{font_family}';
        font-weight: bold;
        font-style: normal;
    """

# WEANTICHEATYET BADGE STYLES
def get_anticheat_badge_style(status):
    status = status.lower()
    status_colors = {
        "supported": {"background": color_anticheat_supported_bg, "color": color_anticheat_supported_text},
        "running": {"background": color_anticheat_running_bg, "color": color_anticheat_running_text},
        "planned": {"background": color_anticheat_planned_bg, "color": color_anticheat_planned_text},
        "broken": {"background": color_anticheat_broken_bg, "color": color_anticheat_broken_text},
        "denied": {"background": color_anticheat_denied_bg, "color": color_anticheat_denied_text},
    }
    colors = status_colors.get(status, {"background": color_badge_default_bg, "color": color_badge_default_text})
    return f"""
        qproperty-alignment: AlignCenter;
        background-color: {colors["background"]};
        color: {colors["color"]};
        font-size: {font_size_normal};
        border-radius: {border_radius_badge};
        font-weight: bold;
        font-style: normal;
    """

# STEAM BADGE STYLES
STEAM_BADGE_STYLE = f"""
    qproperty-alignment: AlignCenter;
    background: {color_badge_steam_bg};
    color: {color_badge_steam_text};
    border-radius: {border_radius_badge};
    font-family: '{font_family}';
    font-weight: bold;
    font-style: normal;
"""


# ADDITIONAL INFO STYLES ON GAMES PAGE
LAST_LAUNCH_TITLE_STYLE = f"max-height: 16px; background: {color_detail_overlay};font-family: '{font_family}'; font-size: {font_size_small}; color: {color_text}; text-transform: uppercase; letter-spacing: 0.75px;"
LAST_LAUNCH_VALUE_STYLE = f"height: 16px; background: {color_detail_overlay};font-family: '{font_family}'; font-size: {font_size_value}; color: {color_text}; font-weight: 600; letter-spacing: 0.75px;"
PLAY_TIME_TITLE_STYLE = f"max-height: 16px; background: {color_detail_overlay};font-family: '{font_family}'; font-size: {font_size_small}; color: {color_text}; text-transform: uppercase; letter-spacing: 0.75px;"
PLAY_TIME_VALUE_STYLE = f"height: 16px; background: {color_detail_overlay};font-family: '{font_family}'; font-size: {font_size_value}; color: {color_text}; font-weight: 600; letter-spacing: 0.75px;"
GAMEPAD_SUPPORT_VALUE_STYLE = f"""
    font-family: '{font_family}'; font-size: {font_size_normal}; color: {color_gamepad_supported};
    font-weight: bold; background: {color_transparent};
    border-radius: {border_radius_badge}; padding: 4px 8px;
"""


def get_source_corner_config() -> dict:
    return SOURCE_CORNER
