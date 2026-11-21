"""Detail page widgets for PortProtonQt."""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QWidget,
    QScrollArea,
    QBoxLayout,
    QSizePolicy,
    QScroller,
    QLayout,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices

from portprotonqt.custom_widgets import ClickableLabel, AutoSizeButton
from portprotonqt.game_card import GameCard, SourceCorner, is_valid_protondb_tier
from portprotonqt.localization import _
from portprotonqt.config import ui_config
from portprotonqt.theme_manager import ThemeManager


def _apply_badge_view_mode(badge: ClickableLabel, theme) -> None:
    """Apply configured badge view mode."""
    mode = ui_config.get_badge_view_mode()
    compact_mode = mode == "compact"
    badge_cfg = getattr(theme, "BADGE", {})
    badge.setCompactMode(compact_mode, badge_cfg.get("compact_width", 30), badge_cfg.get("width", 200))
    badge.setVisible(mode != "hidden")


def create_scroll_area(parent: QWidget, theme) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    """Create scroll area with content widget and main layout."""
    page_layout = QVBoxLayout(parent)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(0)

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    scroll_area.setStyleSheet(theme.SCROLL_STYLE + theme.TRANSPARENT_BACKGROUND_STYLE)
    QScroller.grabGesture(scroll_area.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

    scroll_content = QWidget()
    scroll_area.setWidget(scroll_content)
    page_layout.addWidget(scroll_area)

    main_layout = QVBoxLayout(scroll_content)
    main_layout.setContentsMargins(30, 30, 30, 30)
    main_layout.setSpacing(20)

    return scroll_area, scroll_content, main_layout


def create_back_button(
    parent_layout: QVBoxLayout,
    theme,
    theme_manager,
    on_click: Callable[..., None],
) -> AutoSizeButton:
    """Create back button with standard styling."""
    if getattr(theme, "DETAIL_PAGE_LAYOUT_MODE", None) == "compact":
        # create a hidden placeholder button
        dummy = AutoSizeButton()
        dummy.setVisible(False)
        return dummy
    back_button = AutoSizeButton(_("Back"), icon=theme_manager.get_icon("back", as_path=True))
    back_button.setFixedWidth(100)
    back_button.setStyleSheet(theme.ADDGAME_BACK_BUTTON_STYLE)
    back_button.setProperty("sound_event", "back")
    back_button.clicked.connect(on_click)
    parent_layout.addWidget(back_button, alignment=Qt.AlignmentFlag.AlignLeft)
    return back_button


def create_content_frame(
    parent_layout: QVBoxLayout,
    theme,
) -> tuple[QFrame, QBoxLayout]:
    """Create content frame."""
    content_frame = QFrame()
    content_frame.setProperty("theme_style_name", "DETAIL_CONTENT_FRAME_STYLE")
    content_frame.setStyleSheet(theme.DETAIL_CONTENT_FRAME_STYLE)
    content_frame_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, content_frame)
    content_frame_layout.setContentsMargins(20, 20, 20, 20)
    content_frame_layout.setSpacing(40)
    parent_layout.addWidget(content_frame)
    return content_frame, content_frame_layout


def create_cover_frame(
    parent: QWidget,
    theme,
    image_label: QLabel,
    favorite_icon_name: str | None = None,
    on_favorite_click: Callable[[], str | None] | None = None,
    badges: list | None = None,
    cover_width: int | None = None,
    cover_height: int | None = None,
    game_source: str = "",
    theme_manager: ThemeManager | None = None,
) -> QFrame:
    """Create cover frame with image, favorite icon, and badges."""
    cover_cfg = getattr(theme, "COVER", {})
    cover_w = cover_width if cover_width is not None else cover_cfg.get("width", 300)
    cover_h = cover_height if cover_height is not None else cover_cfg.get("height", 450)
    cover_frame = QFrame()
    cover_frame.setFixedSize(cover_w, cover_h)
    cover_frame.setStyleSheet(theme.COVER_FRAME_STYLE)

    _setup_cover_shadow(cover_frame, theme)

    cover_layout = QVBoxLayout(cover_frame)
    cover_layout.setContentsMargins(0, 0, 0, 0)
    cover_layout.addWidget(image_label, alignment=Qt.AlignmentFlag.AlignCenter)

    if favorite_icon_name and on_favorite_click:
        _add_favorite_label(cover_frame, favorite_icon_name, theme, on_favorite_click)

    if badges:
        _position_badges(cover_frame, badges, cover_w, theme)

    _add_source_corner(cover_frame, game_source, theme, theme_manager, cover_w, cover_h)

    return cover_frame


def _add_source_corner(
    cover_frame: QFrame,
    game_source: str,
    theme,
    theme_manager: ThemeManager | None,
    cover_width: int,
    cover_height: int,
) -> None:
    """Add source corner badge to cover frame."""
    source = game_source.lower()
    if source not in ("steam", "gog", "egs", "portproton", "native") or theme_manager is None:
        return

    icon_name = f"badge_{source}"
    icon = theme_manager.get_icon(icon_name, as_path=True)
    if not icon:
        return

    corner_config = theme.get_source_corner_config()
    ribbon = SourceCorner(
        icon=icon,
        config=corner_config,
        parent=cover_frame,
    )
    ribbon_size = int(cover_width * corner_config.get("size_ratio", 0.28))
    ribbon_size = max(ribbon_size, int(corner_config.get("min_size", 54)))
    ribbon.setFixedSize(ribbon_size, ribbon_size)
    ribbon.move(cover_width - ribbon_size, cover_height - ribbon_size)
    ribbon.setVisible(True)
    ribbon.raise_()


def create_compact_detail_header(
    parent: QWidget,
    theme,
    cover_frame: QFrame,
    title: str,
) -> QWidget:
    """Create compact detail header with cover and title."""
    header_widget = QWidget(parent)
    header_layout = QHBoxLayout(header_widget)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(
        getattr(
            theme,
            "detailCompactHeaderSpacing",
            theme.portProtonPageHorizontalSpacing,
        )
    )
    header_layout.addWidget(cover_frame, alignment=Qt.AlignmentFlag.AlignCenter)
    header_widget.setFixedHeight(cover_frame.height())

    title_frame = QFrame(header_widget)
    title_frame.setProperty("theme_style_name", "COMPACT_DETAILS_WIDGET_STYLE")
    title_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    title_frame.setMaximumHeight(cover_frame.height())
    title_frame.setStyleSheet(theme.COMPACT_DETAILS_WIDGET_STYLE)
    title_layout = QVBoxLayout(title_frame)
    title_layout.setContentsMargins(
        *getattr(theme, "detailCompactTitleMargins", theme.portProtonPageMargins)
    )
    title_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    title_label = QLabel(title)
    title_label.setWordWrap(True)
    title_label.setProperty("theme_style_name", "COMPACT_DETAIL_PAGE_TITLE_STYLE")
    title_label.setStyleSheet(theme.COMPACT_DETAIL_PAGE_TITLE_STYLE)
    title_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignVCenter)
    header_layout.addWidget(title_frame, stretch=1)
    return header_widget


def create_compact_layout_panel(parent: QWidget, theme, content_layout: QLayout) -> QWidget:
    """Create compact panel for an existing layout."""
    panel = QWidget(parent)
    panel.setProperty("theme_style_name", "COMPACT_PLAYTIME_WIDGET_STYLE")
    panel.setStyleSheet(theme.COMPACT_PLAYTIME_WIDGET_STYLE)
    panel.setLayout(content_layout)
    content_layout.setContentsMargins(
        *getattr(
            theme,
            "detailCompactDescriptionMargins",
            theme.portProtonPageMargins,
        )
    )
    return panel


def create_compact_description_panel(
    parent: QWidget, theme, description: str
) -> QWidget:
    """Create compact description block."""
    desc_widget = QWidget(parent)
    desc_widget.setProperty("theme_style_name", "COMPACT_DETAILS_WIDGET_STYLE")
    desc_widget.setStyleSheet(theme.COMPACT_DETAILS_WIDGET_STYLE)
    desc_layout = QVBoxLayout(desc_widget)
    desc_layout.setContentsMargins(
        *getattr(
            theme,
            "detailCompactDescriptionMargins",
            theme.portProtonPageMargins,
        )
    )
    desc_label = QLabel(description)
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(theme.COMPACT_DETAIL_PAGE_DESC_STYLE)
    desc_layout.addWidget(desc_label)
    return desc_widget


def create_detail_separator(theme) -> QFrame:
    """Create detail page separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(theme.DETAIL_PAGE_LINE_STYLE)
    return line


def _setup_cover_shadow(cover_frame: QFrame, theme) -> None:
    """Add shadow effect to cover frame."""
    shadow = QGraphicsDropShadowEffect(cover_frame)
    shadow.setBlurRadius(theme.shadow_blur_radius)
    shadow.setColor(QColor(theme.color_shadow_detail))
    shadow.setOffset(*theme.shadow_offset)
    cover_frame.setGraphicsEffect(shadow)


def _add_favorite_label(
    cover_frame: QFrame, favorite_icon_name: str, theme, on_favorite_click: Callable[[], str | None] | None = None
) -> None:
    """Add favorite label to cover frame."""
    favorite_label = ClickableLabel(cover_frame)
    favorite_icon_size = theme.favoriteLabelIconSize
    favorite_label.setFixedSize(*theme.favoriteLabelSize)
    favorite_label.setIconSize(favorite_icon_size, 0)
    favorite_label.setStyleSheet(theme.FAVORITE_LABEL_STYLE)
    favorite_label.setIcon(ThemeManager().get_icon(favorite_icon_name, as_path=True))
    if on_favorite_click:
        def handle_click() -> None:
            result = on_favorite_click()
            if isinstance(result, str) and result in ("star_fav_full", "star_fav"):
                favorite_label.setIcon(ThemeManager().get_icon(result, as_path=True))
        favorite_label.clicked.connect(handle_click)
    favorite_label.move(8, 8)
    favorite_label.raise_()


def _position_badges(cover_frame: QFrame, badges: list, cover_width: int, theme) -> None:
    """Position badges on cover frame."""
    badge_cfg = getattr(theme, "BADGE", {})
    badge_y_positions = []

    for badge_data in badges:
        badge = badge_data["label"]
        badge.setParent(cover_frame)
        badge.setCompactRelayoutCallback(
            lambda: _position_badges(cover_frame, badges, cover_width, theme)
        )
        if badge.isHidden():
            continue
        badge_x = cover_width - badge.width() - badge_cfg.get("right_margin", 8)

        if badge_y_positions:
            badge_y = badge_y_positions[-1] + badge_cfg.get("spacing", 5)
        else:
            badge_y = badge_cfg.get("top_y", 10)

        badge.move(badge_x, badge_y)
        badge_y_positions.append(badge_y + badge.height())
        badge.raise_()


def create_protondb_badge(
    parent: QWidget,
    protondb_tier: str,
    appid: str,
    main_window,
) -> tuple[ClickableLabel | None, bool]:
    """Create ProtonDB badge."""
    if not is_valid_protondb_tier(protondb_tier):
        return None, False

    icon = main_window.theme_manager.get_icon("platinum-gold", main_window.current_theme_name, as_path=True)

    badge = ClickableLabel(
        "ProtonDB",
        icon=icon,
        parent=parent,
        icon_size=getattr(main_window.theme, "BADGE", {}).get("icon_size", 16),
        icon_space=3,
    )
    badge.setStyleSheet(main_window.theme.get_protondb_badge_style(protondb_tier))
    _apply_badge_view_mode(badge, main_window.theme)
    badge.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl(f"https://www.protondb.com/app/{appid}"))
    )
    return badge, True


def create_portproton_badge(
    parent: QWidget,
    main_window,
    ppdb_id: str = "",
    ppdb_rating: str = "",
) -> ClickableLabel:
    """Create PPDB badge."""
    portproton_icon = main_window.theme_manager.get_icon("badge_portproton", as_path=True)
    badge = ClickableLabel(
        "PPDB",
        icon=portproton_icon,
        parent=parent,
        icon_size=getattr(main_window.theme, "BADGE", {}).get("icon_size", 16),
        icon_space=5,
    )
    if ppdb_rating:
        badge.setStyleSheet(main_window.theme.get_ppdb_badge_style(ppdb_rating))
    else:
        badge.setStyleSheet(main_window.theme.STEAM_BADGE_STYLE)
    _apply_badge_view_mode(badge, main_window.theme)
    badge.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl(f"https://linux-gaming.ru/game/{ppdb_id}"))
    )
    return badge


def create_anticheat_badge(
    parent: QWidget,
    anticheat_status: str,
    game_name: str,
    anticheat_slug: str,
    main_window,
) -> tuple[ClickableLabel | None, bool]:
    """Create WeAntiCheatYet badge."""
    anticheat_text = GameCard.getAntiCheatText(anticheat_status)
    if not anticheat_text:
        return None, False

    icon_filename = GameCard.getAntiCheatIconFilename(anticheat_status)
    icon = main_window.theme_manager.get_icon(icon_filename, main_window.current_theme_name, as_path=True)

    badge = ClickableLabel(
        anticheat_text,
        icon=icon,
        parent=parent,
        icon_size=getattr(main_window.theme, "BADGE", {}).get("icon_size", 16),
        icon_space=3,
    )
    badge.setStyleSheet(main_window.theme.get_anticheat_badge_style(anticheat_status))
    _apply_badge_view_mode(badge, main_window.theme)
    if anticheat_slug:
        anticheat_url = f"https://areweanticheatyet.com/game/{anticheat_slug}"
    else:
        anticheat_url = f"https://areweanticheatyet.com/game/{game_name.lower().replace(' ', '-')}"
    badge.clicked.connect(
        lambda: QDesktopServices.openUrl(
            QUrl(anticheat_url)
        )
    )
    return badge, True


def create_details_widget(
    parent: QWidget,
    main_window,
    title: str,
    description: str,
    game_info_layout: QVBoxLayout | None = None,
    controller_support: str | None = None,
    buttons_layout: QLayout | None = None,
    show_description: bool = True,
) -> QWidget:
    """Create details widget with title, description, and optional content."""
    details_widget = QWidget()
    details_widget.setProperty("theme_style_name", "DETAILS_WIDGET_STYLE")
    details_widget.setStyleSheet(main_window.theme.DETAILS_WIDGET_STYLE)

    details_layout = QVBoxLayout(details_widget)
    details_layout.setContentsMargins(20, 20, 20, 20)
    details_layout.setSpacing(15)

    has_description = show_description and bool(description.strip())
    is_compact_layout = not has_description and game_info_layout is None and not controller_support
    if is_compact_layout:
        details_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
    else:
        details_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    _add_details_header(details_layout, main_window.theme, title)
    if has_description:
        _add_details_description(details_layout, main_window.theme, description)

    if game_info_layout:
        details_layout.addWidget(
            create_compact_layout_panel(
                parent, main_window.theme, game_info_layout
            )
        )

    if controller_support:
        _add_controller_support(details_layout, main_window.theme, controller_support)

    if buttons_layout:
        if not is_compact_layout:
            details_layout.addStretch(1)
        details_layout.addLayout(buttons_layout)

    return details_widget


def _add_details_header(layout: QVBoxLayout, theme, title: str) -> None:
    """Add title and divider line to details layout."""
    title_label = QLabel(title)
    title_label.setProperty("theme_style_name", "DETAIL_PAGE_TITLE_STYLE")
    title_label.setStyleSheet(theme.DETAIL_PAGE_TITLE_STYLE)
    layout.addWidget(title_label)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(theme.DETAIL_PAGE_LINE_STYLE)
    layout.addWidget(line)


def _add_details_description(layout: QVBoxLayout, theme, description: str) -> None:
    """Add description label to details layout."""
    desc_label = QLabel(description)
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(theme.DETAIL_PAGE_DESC_STYLE)
    layout.addWidget(desc_label)


def _add_controller_support(layout: QVBoxLayout, theme, controller_support: str) -> None:
    """Add controller support label to details layout."""
    cs = controller_support.lower()
    translated_cs = _get_controller_support_text(cs)
    gamepad_label = QLabel(_("Gamepad Support: {0}").format(translated_cs))
    gamepad_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    gamepad_label.setStyleSheet(theme.GAMEPAD_SUPPORT_VALUE_STYLE)
    layout.addWidget(gamepad_label, alignment=Qt.AlignmentFlag.AlignCenter)


def _get_controller_support_text(cs: str) -> str:
    """Get translated controller support text."""
    if cs == "full":
        return _("full")
    elif cs == "partial":
        return _("partial")
    elif cs == "none":
        return _("none")
    return ""
