from .constants import *

# GLOBAL STYLE FOR WINDOW (BACKGROUND), LABELS, BUTTONS
MAIN_WINDOW_STYLE = f"""
    QWidget {{
        background: {color_bg};
    }}
    QLabel {{
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QPushButton {{
        background: {color_surface};
        border: {border_medium} {color_border_subtle};
        border-radius: {border_radius_small};
        color: {color_text};
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

# PROGRESS BAR STYLE
PROGRESS_BAR_STYLE = f"""
    QProgressBar {{
        color: {color_text};
        background-color: {color_surface};
        text-align: center;
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QProgressBar::chunk {{
        background-color: {color_accent};
    }}
"""

DOWNLOADS_SUMMARY_STYLE = f"""
    QFrame#downloadsSummary {{
        background: {color_surface_elevated};
        border: {border_thin} {color_border_faint};
        border-radius: {border_radius_small};
    }}
"""

DOWNLOADS_ACTIVE_STYLE = f"""
    QFrame#downloadsActiveCard {{
        background: {color_surface_elevated};
        border: {border_thin} {color_border_faint};
        border-radius: {border_radius_large};
    }}
"""

DOWNLOADS_SECTION_STYLE = f"""
    QFrame#downloadsSection {{
        background: {color_surface_elevated};
        border: {border_thin} {color_border_faint};
        border-radius: {border_radius_small};
    }}
"""

STORE_DLC_LIST_STYLE = f"""
    QWidget#storeDlcList {{
        background: {color_surface_elevated};
        border: {border_none};
        border-radius: {border_radius_small};
    }}
"""

STORE_DLC_ROW_STYLE = f"""
    QWidget#storeDlcRow {{
        background: transparent;
        border: {border_none};
    }}
    QWidget#storeDlcRow QLabel, QWidget#storeDlcRow QCheckBox {{
        background: transparent;
        color: {color_text};
    }}
"""

DOWNLOADS_TABLE_STYLE = f"""
    QTableWidget {{
        background: {color_surface_elevated};
        alternate-background-color: {color_surface};
        border: {border_none};
        color: {color_text};
        gridline-color: {color_border_faint};
        font-family: '{font_family}';
        font-size: {font_size_value};
    }}
    QHeaderView::section {{
        background: {color_surface};
        color: {color_text};
        border: {border_none};
        padding: 8px;
        font-family: '{font_family}';
        font-size: {font_size_value};
        font-weight: 600;
    }}
    QTableWidget::item {{
        border-bottom: {border_thin} {color_border_faint};
        padding: 8px;
    }}
"""

# STATUS BAR STYLE
STATUS_BAR_STYLE = f"""
    QStatusBar {{
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
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
        font-size: {font_size_value};
        color: {color_text};
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
        border-top-left-radius: {border_radius_header};
        border-top-right-radius: {border_radius_header};
        border: none;
    }}
"""

# NAVIGATION AREA STYLE (TAB BUTTONS)
NAV_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        border:  {border_none};
    }}
"""

# NAVIGATION TAB BUTTON STYLE
NAV_BUTTON_STYLE = f"""
    NavLabel {{
        background: {color_transparent};
        padding: 6px 3px;
        margin: 10px 0 10px 10px;
        color: {color_nav_inactive};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        text-transform: uppercase;
        border: {color_accent};
        border-radius: 0px;
    }}
    NavLabel[checked = true] {{
        background: {color_transparent};
        color: {color_text};
        font-weight: normal;
        text-decoration: none;
        border-bottom: {border_thin} {color_accent};
        border-radius: 0px;
    }}
    NavLabel:hover {{
        background: {color_transparent};
        color: {color_text};
        border-bottom: {border_thin} {color_nav_inactive};
    }}
    NavLabel[checked = true]:hover {{
        background: {color_transparent};
        color: {color_text};
        border-bottom: {border_thin} {color_accent};
    }}
"""

# SEARCH FIELD STYLE
SEARCH_EDIT_STYLE = f"""
    QLineEdit {{
        background-color: {color_detail_overlay};
        border: {border_thin} {color_border_input};
        border-radius: {border_radius_small};
        padding: 7px 14px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        color: {color_text};
        min-height: 24px;
    }}
    QLineEdit:focus {{
        border: {border_thin} {color_accent};
    }}
"""
# SLIDER_SIZE_STYLE
SLIDER_SIZE_STYLE = f"""
    QWidget {{
        background: {color_transparent};
        height: 25px;
    }}
    QSlider::groove:horizontal {{
        border:  {border_none};
        border-radius: {border_radius_slider};
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
        border-radius: {border_radius_slider_handle};
    }}
"""

# GAME CARD AREA STYLE (QWidget)
LIST_WIDGET_STYLE = f"""
    QWidget {{
        background: none;
        border:  {border_none} transparent;
        border-radius: 25px;
    }}
"""

# ACTION BUTTONS STYLE (SAVE, APPLY, ETC.)
ACTION_BUTTON_STYLE = f"""
    QPushButton {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        color: {color_text};
        font-size: {font_size_normal};
        font-family: '{font_family}';
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border: {border_medium} {color_accent};
    }}
    QPushButton:pressed {{
        background: {color_bg};
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
        color: {color_text};
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

# DRIVES BUTTONS STYLE (FILE MANAGER)
DRIVES_BUTTON_STYLE = f"""
    QPushButton {{
        background: {color_surface};
        border: {border_medium} transparent;
        border-radius: {border_radius_small};
        color: {color_text};
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
        color: {color_text};
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

# TEXT STYLES: HEADINGS AND MAIN CONTENT
TAB_TITLE_STYLE = f"font-family: '{font_family}'; font-size: {font_size_header}; color: {color_text}; background-color: none;"
CONTENT_STYLE = f"""
    QLabel {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        color: {color_text};
        background-color: none;
        border-bottom: {border_thin} {color_border_light};
        padding-bottom: 15px;
    }}
"""
PREVIEW_WIDGET_STYLE = f"""
    QWidget {{
        margin-top: 3px;
        background-color: {color_surface};
        border-radius: {border_radius_small};
    }}
"""

# MAIN PAGES STYLE
# LIBRARY_WIDGET_STYLE
LIBRARY_WIDGET_STYLE = f"""
    QWidget {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {color_library_gradient_start},
            stop:1 {color_library_gradient_end});
        border-radius: 0px;
    }}
"""

# LIBRARY_CONTROL_STYLE
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
CONTAINER_STYLE = """
    QWidget {
        background-color: none;
    }
"""

# OTHER_PAGES_WIDGET_STYLE
OTHER_PAGES_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_surface_elevated};
        border-radius: 0px;
    }}
"""

# CAROUSEL_WIDGET_STYLE
CAROUSEL_WIDGET_STYLE = f"""
    QWidget {{
        background: {color_surface};
        border-radius: 0px;
    }}
"""

THEME_TAB_FOCUS_STYLE = f"""
    QComboBox#themeTabCombo:focus {{
        border: {border_thin} {color_text};
        background-color: {color_accent};
    }}
    QPushButton#themeApplyButton:focus,
    QPushButton#themeDeleteButton:focus {{
        border: {border_thin} {color_text};
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
        border: {border_thin} rgba(255, 255, 255, 0.2);
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
        color: {color_text};
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
        color: {color_text};
        background: {color_transparent};
        border: {border_none} {color_transparent};
        font-family: '{font_family}';
        font-size: {font_size_header};
        font-weight: bold;
    }}
"""

THEME_STORE_DESCRIPTION_STYLE = f"""
    QTextBrowser {{
        color: {color_text};
        background: {color_surface};
        border: {border_thin} rgba(255, 255, 255, 0.2);
        border-radius: {border_radius_small};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        padding: 12px;
    }}
"""

# PORTPROTON SETTINGS TAB STYLES
# PARAMS_TITLE_STYLE
PARAMS_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text};
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

# QMessageBox STYLES (MESSAGE BOXES)
MESSAGE_BOX_STYLE = f"""
    QMessageBox {{
        background: {color_bg};
        border: {border_none};
    }}
    QMessageBox QLabel {{
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QMessageBox QPushButton {{
        background: {color_surface};
        border: {border_none} {color_transparent};
        border-radius: {border_radius_small};
        color: {color_text};
        font-family: '{font_family}';
        padding: 8px 20px;
        min-width: 80px;
    }}
    QMessageBox QPushButton:hover {{
        background: {color_accent};
        border-color: border: {border_thin} {color_accent};
        color: {color_text_accent_hover};
    }}
    QMessageBox QPushButton:focus {{
        border: {border_medium} {color_accent};
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
"""

COMPATIBILITY_REPORT_DIALOG_STYLE = f"""
    QDialog {{
        background: {color_bg};
    }}
    QFrame#compatibilityHeader {{
        background: {color_transparent};
        border: {border_none};
    }}
    QLabel#compatibilityTitle {{
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_header};
        font-weight: 600;
    }}
    QLabel#compatibilitySummary {{
        color: {color_text_muted};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QPlainTextEdit#compatibilityReport {{
        background: {color_surface};
        color: {color_text};
        border: {border_thin} {color_border_subtle};
        border-radius: {border_radius_small};
        padding: 12px;
        font-family: monospace;
        font-size: {font_size_value};
        selection-background-color: {color_accent};
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

# QGroupBox STYLES
QGROUP_BOX_STYLE = f"""
    QGroupBox {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        color: {color_accent};
        border: {border_thin} {color_surface};
        border-radius: {border_radius_small};
        margin-top: 10px;
        margin-right: 10px;
        padding-top: 14px;
        background: {color_transparent};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
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
        color: {color_text};
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
        color: {color_text};
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

SETTINGS_TABLE_COMBOBOX_STYLE = f"""
    QComboBox#settingsTableCombo:hover,
    QComboBox#settingsTableCombo:focus {{
        background: {color_surface};
        border: {border_medium} {color_accent};
        color: {color_text};
    }}
"""

CHECKBOX_STYLE = f"""
    QCheckBox {{
        height: 34px;
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
    QCheckBox::indicator {{
        width: 24px;
        height: 24px;
        border: {border_medium} transparent;
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
        background: {color_bg};
        border: {border_medium} {color_surface_elevated};
    }}
    QCheckBox::indicator:checked:disabled {{
        image: url({theme_manager.get_icon("check", current_theme_name, as_path=True)});
        background: {color_bg};
        border: {border_medium} {color_surface_elevated};
    }}

    QTableWidget::indicator {{
        width: 24px;
        height: 24px;
        border: {border_medium} {color_transparent};
        border-radius: {border_radius_small};
        background: {color_bg};
    }}
    QTableWidget::indicator:unchecked {{
        background: {color_checkbox_unchecked_bg};
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
        color: {color_text};
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

TOOLTIP_STYLE = f"""
    QLabel {{
        background: {color_bg};
        border: {border_thin} {color_surface_hover};
        padding: 8px;
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
    }}
"""

TAB_STYLE = f"""
    QTabWidget::pane {{
        border-top: 1px solid {color_surface};
        background: {color_transparent};
    }}
    QTabBar::tab {{
        background: {color_surface};
        color: {color_text};
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
