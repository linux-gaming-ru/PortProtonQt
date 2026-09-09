import os
import re
import shlex
from typing import Any

from PySide6.QtGui import (
    QPainter,
    QColor,
    QDesktopServices,
    QHideEvent,
    QShowEvent,
    QPainterPath,
    QIcon,
    QPen,
    QLinearGradient,
    QEnterEvent,
    QFocusEvent,
    QMouseEvent,
    QPaintEvent,
)
from PySide6.QtCore import QEvent, Signal, Property, Qt, QUrl, QTimer, QSize
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QStackedLayout,
    QLabel,
    QSizePolicy,
)
from portprotonqt.image_utils import (
    cleanup_animated_cover,
    load_pixmap_async,
    round_corners,
    set_animated_cover,
    set_animated_cover_paused,
    update_animated_cover_size,
)
from portprotonqt.localization import _
from portprotonqt.config import (
    WINDOWS_LAUNCH_EXTENSIONS,
    favorites_config,
    game_config,
    ui_config,
)
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.custom_widgets import ClickableLabel
from portprotonqt.animations import GameCardAnimations
from portprotonqt.icon_extractor import get_exe_icon_cache_path

PROTONDB_TIERS = ("platinum", "gold", "silver", "bronze", "borked", "pending")


def is_valid_protondb_tier(tier: str | None) -> bool:
    """Check if ProtonDB tier is supported."""
    return bool(tier) and tier.lower() in PROTONDB_TIERS


class SourceCorner(QWidget):

    def __init__(
        self,
        icon: str | QIcon | None = None,
        config: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        cfg = config or {}
        self._color = QColor(cfg.get("ribbon_color", "#3f424d"))
        self._fold_color = QColor(cfg.get("ribbon_fold_color", "#00000096"))
        self._cfg = cfg
        self.setFixedSize(0, 0)
        self._visible = False

    def paintEvent(self, event: object) -> None:
        if not self._visible:
            return
        w = self.width()
        h = self.height()
        cfg = self._cfg
        if w < cfg.get("min_widget_size", 4) or h < cfg.get("min_widget_size", 4):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        shadow_path = self._create_shadow_path(w, h)
        painter.setPen(QPen(self._fold_color, cfg.get("peel_shadow_width", 3)))
        painter.drawPath(shadow_path)

        path = self._create_path(w, h)
        painter.setBrush(self._create_gradient(w, h))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        fold_path = self._create_fold_path(w, h)
        painter.setBrush(self._color.darker(cfg.get("fold_darker", 132)))
        painter.drawPath(fold_path)
        self._draw_icon(painter, w, h)

    def _create_gradient(self, w: int, h: int) -> QLinearGradient:
        cfg = self._cfg
        gradient = QLinearGradient(
            w * cfg.get("peel_start_ratio", 0.32),
            h,
            w,
            h * cfg.get("peel_start_ratio", 0.32),
        )
        gradient.setColorAt(
            cfg.get("gradient_start", 0.0),
            self._color.lighter(cfg.get("gradient_lighter", 145)),
        )
        gradient.setColorAt(
            cfg.get("gradient_end", 1.0),
            self._color.darker(cfg.get("gradient_darker", 112)),
        )
        return gradient

    def _create_path(self, w: int, h: int) -> QPainterPath:
        cfg = self._cfg
        path = QPainterPath()
        path.moveTo(w, h)
        path.lineTo(w * cfg.get("peel_start_ratio", 0.32), h)
        path.quadTo(
            w * cfg.get("peel_mid_ratio", 0.58),
            h,
            w * cfg.get("peel_end_ratio", 0.82),
            h * cfg.get("peel_mid_ratio", 0.58),
        )
        path.quadTo(
            w,
            h * cfg.get("peel_mid_ratio", 0.58),
            w,
            h * cfg.get("peel_start_ratio", 0.32),
        )
        path.lineTo(w, h)
        path.closeSubpath()
        return path

    def _create_fold_path(self, w: int, h: int) -> QPainterPath:
        cfg = self._cfg
        fold_path = QPainterPath()
        fold_path.moveTo(w, h)
        fold_path.lineTo(w * cfg.get("fold_start_ratio", 0.60), h)
        fold_path.quadTo(
            w * cfg.get("fold_end_ratio", 0.92),
            h * cfg.get("fold_end_ratio", 0.92),
            w,
            h * cfg.get("fold_start_ratio", 0.60),
        )
        fold_path.lineTo(w, h)
        fold_path.closeSubpath()
        return fold_path

    def _create_shadow_path(self, w: int, h: int) -> QPainterPath:
        cfg = self._cfg
        shadow_path = QPainterPath()
        shadow_path.moveTo(w * cfg.get("peel_start_ratio", 0.32), h)
        shadow_path.quadTo(
            w * cfg.get("peel_mid_ratio", 0.58),
            h,
            w * cfg.get("peel_end_ratio", 0.82),
            h * cfg.get("peel_mid_ratio", 0.58),
        )
        shadow_path.quadTo(
            w,
            h * cfg.get("peel_mid_ratio", 0.58),
            w,
            h * cfg.get("peel_start_ratio", 0.32),
        )
        return shadow_path

    def _draw_icon(self, painter: QPainter, w: int, h: int) -> None:
        if not self._icon:
            return

        from portprotonqt.qt_utils import get_device_pixel_ratio

        cfg = self._cfg
        dpr = get_device_pixel_ratio()
        icon_size = max(cfg.get("min_icon_size", 8), int(w * cfg.get("icon_size_ratio", 0.25)))
        render_size = int(icon_size * dpr)

        if isinstance(self._icon, str):
            pixmap = QIcon(self._icon).pixmap(QSize(render_size, render_size))
        elif isinstance(self._icon, QIcon):
            pixmap = self._icon.pixmap(QSize(render_size, render_size))
        else:
            return

        center_ratio = cfg.get("icon_center_ratio", 0.84)
        painter.drawPixmap(
            int(w * center_ratio - icon_size / 2),
            int(h * center_ratio - icon_size / 2),
            icon_size,
            icon_size,
            pixmap
        )

    def setVisible(self, visible: bool) -> None:
        self._visible = visible
        super().setVisible(visible)

    def refresh_source_theme(self, config: dict, icon: str | QIcon | None) -> None:
        """Refresh source-corner visuals for a live theme change."""
        self._cfg = config
        self._icon = icon
        self._color = QColor(config.get("ribbon_color", "#3f424d"))
        self._fold_color = QColor(config.get("ribbon_fold_color", "#00000096"))
        self.update()


class AnimatedCard(QFrame):
    animation_base_size: tuple[int, int]
    borderWidthChanged = Signal()
    gradientAngleChanged = Signal()
    scaleChanged = Signal()
    hoverChanged = Signal(str, bool)
    focusChanged = Signal(str, bool)
    clicked = Signal()

    def setup_card_animations(self, theme: Any, layout_config: dict) -> None:
        self.theme = theme
        self.card_layout_cfg = layout_config
        self._borderWidth = layout_config.get(
            "default_border_width", theme.GAME_CARD_ANIMATION["default_border_width"]
        )
        self._gradientAngle = layout_config.get(
            "gradient_start_angle", theme.GAME_CARD_ANIMATION["gradient_start_angle"]
        )
        self._scale = layout_config.get(
            "default_scale", theme.GAME_CARD_ANIMATION["default_scale"]
        )
        self._hovered = False
        self._focused = False
        self._hover_sound_pending = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.animations = GameCardAnimations(self, theme)
        self.animations.setup_animations()

    def update_scale(self) -> None:
        width, height = self.animation_base_size
        self.setFixedSize(int(width * self._scale), int(height * self._scale))

    def getBorderWidth(self) -> int:
        return self._borderWidth

    def setBorderWidth(self, value: int) -> None:
        self._borderWidth = value
        self.borderWidthChanged.emit()
        self.update()

    def getGradientAngle(self) -> float:
        return self._gradientAngle

    def setGradientAngle(self, value: float) -> None:
        self._gradientAngle = value
        self.gradientAngleChanged.emit()
        self.update()

    def getScale(self) -> float:
        return self._scale

    def setScale(self, value: float) -> None:
        self._scale = value
        self.update_scale()
        self.scaleChanged.emit()

    borderWidth = Property(int, getBorderWidth, setBorderWidth, notify=borderWidthChanged)
    gradientAngle = Property(float, getGradientAngle, setGradientAngle, notify=gradientAngleChanged)
    scale = Property(float, getScale, setScale, notify=scaleChanged)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self.animations.paint_border(QPainter(self))

    def enterEvent(self, event: QEnterEvent) -> None:
        self.raise_()
        self._hover_sound_pending = True
        self.animations.handle_enter_event()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover_sound_pending = False
        self.animations.handle_leave_event()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._hover_sound_pending:
            from portprotonqt.sound_manager import SoundManager
            SoundManager().play("navigate")
            self._hover_sound_pending = False
        super().mouseMoveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.raise_()
        if QApplication.activeWindow() is not None and event.reason() not in (
            Qt.FocusReason.ActiveWindowFocusReason,
            Qt.FocusReason.MouseFocusReason,
        ):
            from portprotonqt.sound_manager import SoundManager
            SoundManager().play("navigate")
        self.animations.handle_focus_in_event()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.animations.handle_focus_out_event()
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def click(self) -> None:
        self.clicked.emit()


class GameCard(AnimatedCard):
    editShortcutRequested = Signal(str, str, str)
    deleteGameRequested = Signal(str, str)
    addToMenuRequested = Signal(str, str)
    removeFromMenuRequested = Signal(str)
    addToDesktopRequested = Signal(str, str)
    removeFromDesktopRequested = Signal(str)
    addToSteamRequested = Signal(str, str, str)
    removeFromSteamRequested = Signal(str, str)
    openGameFolderRequested = Signal(str, str)

    def __init__(
        self, name, description, cover_path, appid, controller_support, exec_line,
        last_launch, formatted_playtime, protondb_tier, anticheat_status,
        last_launch_ts, playtime_seconds, game_source, anticheat_slug="",
        ppdb_id="", ppdb_rating="", protondb_appid="", *, select_callback, theme=None,
        card_width=250, parent=None, context_menu_manager=None
    ):
        super().__init__(parent)
        self.name = name
        self.description = description
        self.cover_path = cover_path
        self.appid = appid
        self.controller_support = controller_support
        self.exec_line = exec_line
        self.last_launch = last_launch
        self.formatted_playtime = formatted_playtime
        self.protondb_tier = protondb_tier
        self.anticheat_status = anticheat_status
        self.anticheat_slug = anticheat_slug or ""
        self.ppdb_id = ppdb_id or ""
        self.ppdb_rating = ppdb_rating or ""
        self.protondb_appid = protondb_appid or appid
        self.game_source = game_source
        self.autoinstall_exe_name = ""
        self.last_launch_ts = last_launch_ts
        self.playtime_seconds = playtime_seconds
        self.base_card_width = card_width
        self.base_pixmap = None
        self.base_font_size = None
        self.animated_cover_path = ""

        self.select_callback = select_callback
        self.context_menu_manager = context_menu_manager
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.theme_manager = ThemeManager()
        self.theme = theme if theme is not None else self.theme_manager.apply_theme(ui_config.get_theme())

        self.display_filter = game_config.get_display_filter()
        self.badge_view_mode = ui_config.get_badge_view_mode()
        self.current_theme_name = ui_config.get_theme()
        parent_mode = parent.property("library_layout_mode") if parent is not None else None
        self.layout_mode = str(
            parent_mode or getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")
        ).lower()
        self.list_layout = self.layout_mode in {"list", "vertical"}
        self.vertical_layout = self.layout_mode == "vertical"
        self.horizontal_layout = self.layout_mode in {"horizontal", "horizontal_top"}
        self.economy_mode = ui_config.get_economy_mode()
        self.missing_executable_path = self._get_missing_executable_path()

        self.steam_visible = str(game_source).lower() == "steam"
        self.gog_visible = str(game_source).lower() == "gog"
        self.egs_visible = str(game_source).lower() == "egs"
        self.portproton_visible = str(game_source).lower() == "portproton"
        self.ppdb_visible = bool(self.ppdb_id) and not self.economy_mode

        if self.vertical_layout:
            config_name = "GAME_CARD_VERTICAL"
        elif self.list_layout:
            config_name = "GAME_CARD_LIST"
        elif self.horizontal_layout:
            config_name = "GAME_CARD_HORIZONTAL"
        else:
            config_name = "GAME_CARD_GRID"
        self.card_layout_cfg = getattr(self.theme, config_name, {})
        default_margin = 8 if self.list_layout else 20
        self.base_extra_margin = self.card_layout_cfg.get("extra_margin", default_margin)
        card_style_name = (
            "GAME_CARD_VERTICAL_STYLE"
            if self.vertical_layout
            else "GAME_CARD_WINDOW_STYLE"
        )
        self.setProperty("theme_style_name", card_style_name)
        card_style = (
            self.theme.GAME_CARD_VERTICAL_STYLE
            if self.vertical_layout
            else self.theme.GAME_CARD_WINDOW_STYLE
        )
        self.setStyleSheet(card_style)
        self.setup_card_animations(self.theme, self.card_layout_cfg)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(self.theme.shadow_blur_radius)
        self.shadow.setColor(QColor(self.theme.color_shadow_card))
        self.shadow.setOffset(*self.theme.shadow_offset)
        self.setGraphicsEffect(self.shadow)

        if self.list_layout:
            self.layout_ = QHBoxLayout(self)
            self.layout_.setSpacing(self.card_layout_cfg.get("spacing", 12))
        else:
            self.layout_ = QVBoxLayout(self)
            self.layout_.setSpacing(self.card_layout_cfg.get("spacing", 5))
        self.layout_.setContentsMargins(self.base_extra_margin // 2, self.base_extra_margin // 2, self.base_extra_margin // 2, self.base_extra_margin // 2)

        self.coverWidget = QWidget()
        if self.list_layout:
            self.coverWidget.setProperty("theme_style_name", "COVER_WIDGET_STYLE")
            self.coverWidget.setStyleSheet(self.theme.COVER_WIDGET_STYLE)
        coverLayout = QStackedLayout(self.coverWidget)
        coverLayout.setContentsMargins(0, 0, 0, 0)
        coverLayout.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self.coverLabel = QLabel()
        self.coverLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coverLabel.setStyleSheet(self.theme.COVER_LABEL_STYLE)
        if self.missing_executable_path or (
            str(self.game_source).lower() in ("gog", "egs")
            and self.exec_line.startswith(("gog://install/", "egs://install/"))
        ):
            self.coverOpacity = QGraphicsOpacityEffect(self.coverLabel)
            self.coverOpacity.setOpacity(self.theme.missing_exe_cover_opacity)
            self.coverLabel.setGraphicsEffect(self.coverOpacity)
        coverLayout.addWidget(self.coverLabel)

        self._load_cover_image(cover_path or "")

        self.favoriteLabel = ClickableLabel(self.coverWidget)
        self.favoriteLabel.clicked.connect(self.toggle_favorite)
        self.is_favorite = self.name in set(favorites_config.get_games())
        self.update_favorite_icon()
        self.favoriteLabel.raise_()
        if self.list_layout:
            self.favoriteLabel.setVisible(False)

        if not self.economy_mode and is_valid_protondb_tier(protondb_tier):
            icon = self.theme_manager.get_icon("platinum-gold", self.current_theme_name, as_path=True)
            self.protondbLabel = ClickableLabel(
                "ProtonDB",
                icon=icon,
                parent=self.coverWidget,
                font_scale_factor=0.06
            )
            self.protondbLabel.setStyleSheet(self.theme.get_protondb_badge_style(protondb_tier))
            self.protondbLabel.setCardWidth(card_width)
        else:
            self.protondbLabel = ClickableLabel("", parent=self.coverWidget)
            self.protondbLabel.setVisible(False)

        steam_icon = self.theme_manager.get_icon("badge_steam", as_path=True)
        corner_config = self.theme.get_source_corner_config()
        self.steamLabel = SourceCorner(
            icon=steam_icon,
            config=corner_config,
            parent=self.coverWidget,
        )
        self.steamLabel.setVisible(self.steam_visible and not self.vertical_layout)

        gog_icon = self.theme_manager.get_icon("badge_gog", as_path=True)
        self.gogLabel = SourceCorner(
            icon=gog_icon,
            config=corner_config,
            parent=self.coverWidget,
        )
        self.gogLabel.setVisible(self.gog_visible and not self.vertical_layout)

        egs_icon = self.theme_manager.get_icon("badge_egs", as_path=True)
        self.egsLabel = SourceCorner(
            icon=egs_icon,
            config=corner_config,
            parent=self.coverWidget,
        )
        self.egsLabel.setVisible(self.egs_visible and not self.vertical_layout)

        portproton_icon = self.theme_manager.get_icon("badge_portproton", as_path=True)
        self.portprotonLabel = SourceCorner(
            icon=portproton_icon,
            config=corner_config,
            parent=self.coverWidget,
        )
        self.portprotonLabel.setVisible(
            self.portproton_visible and not self.vertical_layout
        )

        if self.ppdb_visible:
            self.ppdbLabel = ClickableLabel(
                "PPDB",
                icon=portproton_icon,
                parent=self.coverWidget,
                font_scale_factor=0.06
            )
            if self.ppdb_rating:
                self.ppdbLabel.setStyleSheet(self.theme.get_ppdb_badge_style(self.ppdb_rating))
            else:
                self.ppdbLabel.setStyleSheet(self.theme.STEAM_BADGE_STYLE)
            self.ppdbLabel.setCardWidth(card_width)
        else:
            self.ppdbLabel = ClickableLabel("", parent=self.coverWidget)
            self.ppdbLabel.setVisible(False)

        anticheat_text = "" if self.economy_mode else self.getAntiCheatText(anticheat_status)
        if anticheat_text:
            icon_filename = self.getAntiCheatIconFilename(anticheat_status)
            icon = self.theme_manager.get_icon(icon_filename, self.current_theme_name, as_path=True)
            self.anticheatLabel = ClickableLabel(
                anticheat_text,
                icon=icon,
                parent=self.coverWidget,
                font_scale_factor=0.06
            )
            self.anticheatLabel.setStyleSheet(self.theme.get_anticheat_badge_style(anticheat_status))
            self.anticheatLabel.setCardWidth(card_width)
        else:
            self.anticheatLabel = ClickableLabel("", parent=self.coverWidget)
            self.anticheatLabel.setVisible(False)

        self.protondbLabel.clicked.connect(self.open_protondb_report)
        self.ppdbLabel.clicked.connect(self.open_ppdb_page)
        self.anticheatLabel.clicked.connect(self.open_weanticheatyet_page)

        self.layout_.addWidget(self.coverWidget)

        self.nameLabel = QLabel(self._get_display_name())
        if self.list_layout:
            self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.nameLabel.setContentsMargins(0, 0, 10, 0)
        else:
            self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.horizontal_layout:
            self.nameLabel.setWordWrap(True)
        name_style = (
            self.theme.GAME_CARD_VERTICAL_NAME_STYLE
            if self.vertical_layout
            else self.theme.GAME_CARD_NAME_LABEL_STYLE
        )
        self.nameLabel.setStyleSheet(name_style)
        if self.vertical_layout:
            self.nameLabel.setProperty(
                "theme_style_name", "GAME_CARD_VERTICAL_NAME_STYLE"
            )
        if self.vertical_layout:
            stretches = self.theme.GAME_CARD_VERTICAL["column_stretches"]
            self.layout_.addWidget(self.nameLabel, stretches[0])
            for text, stretch in zip(
                (self.last_launch, self.formatted_playtime, str(self.game_source)),
                stretches[1:],
                strict=True,
            ):
                label = QLabel(text)
                label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                label.setProperty(
                    "theme_style_name", "GAME_CARD_COLUMN_LABEL_STYLE"
                )
                label.setStyleSheet(self.theme.GAME_CARD_COLUMN_LABEL_STYLE)
                self.layout_.addWidget(label, stretch)
        else:
            self.layout_.addWidget(self.nameLabel)
        if self.list_layout and not self.vertical_layout:
            self.layout_.addStretch()

        font_size = self.nameLabel.font().pointSizeF()
        self.base_font_size = font_size if font_size > 0 else 10.0

        self.update_scale()

        # Force initial layout update to ensure correct geometry
        self.updateGeometry()
        parent = self.parentWidget()
        if parent:
            layout = parent.layout()
            if layout:
                layout.invalidate()
            parent.updateGeometry()

    def refresh_theme(self, theme: Any) -> None:
        """Refresh cached card visuals after a live theme change."""
        old_theme = self.theme
        old_layout_cfg = self.card_layout_cfg
        self.theme = theme
        if self.vertical_layout:
            config_name = "GAME_CARD_VERTICAL"
        elif self.list_layout:
            config_name = "GAME_CARD_LIST"
        elif self.horizontal_layout:
            config_name = "GAME_CARD_HORIZONTAL"
        else:
            config_name = "GAME_CARD_GRID"
        self.card_layout_cfg = getattr(theme, config_name, {})
        default_margin = 8 if self.list_layout else 20
        self.base_extra_margin = self.card_layout_cfg.get("extra_margin", default_margin)
        spacing = self.card_layout_cfg.get("spacing", 12 if self.list_layout else 5)
        self.layout_.setSpacing(spacing)
        margin = self.base_extra_margin // 2
        self.layout_.setContentsMargins(margin, margin, margin, margin)
        self.shadow.setBlurRadius(theme.shadow_blur_radius)
        self.shadow.setColor(QColor(theme.color_shadow_card))
        self.shadow.setOffset(*theme.shadow_offset)
        if hasattr(self, "coverOpacity"):
            self.coverOpacity.setOpacity(theme.missing_exe_cover_opacity)
        if is_valid_protondb_tier(self.protondb_tier):
            self.protondbLabel.setStyleSheet(
                theme.get_protondb_badge_style(self.protondb_tier)
            )
        if self.ppdb_id:
            ppdb_style = (
                theme.get_ppdb_badge_style(self.ppdb_rating)
                if self.ppdb_rating
                else theme.STEAM_BADGE_STYLE
            )
            self.ppdbLabel.setStyleSheet(ppdb_style)
        if self.getAntiCheatText(self.anticheat_status):
            self.anticheatLabel.setStyleSheet(
                theme.get_anticheat_badge_style(self.anticheat_status)
            )
        corner_config = theme.get_source_corner_config()
        for label, icon_name in (
            (self.steamLabel, "badge_steam"),
            (self.gogLabel, "badge_gog"),
            (self.egsLabel, "badge_egs"),
            (self.portprotonLabel, "badge_portproton"),
        ):
            icon = self.theme_manager.get_icon(
                icon_name, self.current_theme_name, as_path=True
            )
            label.refresh_source_theme(corner_config, icon)
        if (
            old_theme.GAME_CARD_ANIMATION != theme.GAME_CARD_ANIMATION
            or old_layout_cfg != self.card_layout_cfg
        ):
            self.animations.refresh_theme(theme)
        else:
            self.animations.theme = theme
        self.update_favorite_icon()
        layout_changed = (
            old_layout_cfg != self.card_layout_cfg
            or old_theme.COMPACT_CARD != theme.COMPACT_CARD
            or old_theme.favoriteLabelSize != theme.favoriteLabelSize
            or old_theme.favoriteLabelIconSize != theme.favoriteLabelIconSize
        )
        if layout_changed:
            self.update_scale()
        else:
            self.update()

    def on_cover_loaded(self, pixmap):
        self.animated_cover_path = ""
        self.base_pixmap = pixmap
        self.update_cover_pixmap()

    def _load_cover_image(self, cover_path: str) -> None:
        if self.list_layout:
            cover_size = self.card_layout_cfg.get("cover_load_size", 64)
            width = cover_size
            height = cover_size
        else:
            width = self.base_card_width
            layout_config = getattr(self, "card_layout_cfg", {})
            height = int(self.base_card_width * layout_config.get("cover_aspect_ratio", 1.5))
        if self._set_animated_cover(cover_path, width, height):
            return
        fallback_exe, fallback_icon_path = self._get_exe_icon_fallback()
        load_pixmap_async(
            cover_path,
            width,
            height,
            self.on_cover_loaded,
            app_name=str(self.appid or ""),
            fallback_exe=fallback_exe,
            fallback_icon_path=fallback_icon_path,
        )

    def _get_exe_icon_fallback(self) -> tuple[str, str]:
        exe_path = self._extract_executable_path(self.exec_line)
        if not exe_path or not os.path.isfile(exe_path):
            return "", ""
        if not exe_path.lower().endswith(".exe"):
            return "", ""
        return exe_path, get_exe_icon_cache_path(exe_path)

    def _set_animated_cover(self, cover_path: str, width: int, height: int) -> bool:
        if not cover_path or not os.path.isfile(cover_path):
            return False
        radius = self.card_layout_cfg.get("cover_radius", 8 if self.list_layout else 15)
        if not set_animated_cover(self.coverLabel, cover_path, width, height, radius):
            return False
        self.animated_cover_path = cover_path
        self.base_pixmap = None
        return True

    def _update_animated_cover_size(self) -> None:
        default_radius = 8 if self.list_layout else 15
        radius = int(self.card_layout_cfg.get("cover_radius", default_radius) * self._scale)
        update_animated_cover_size(
            self.coverLabel,
            self.coverLabel.width(),
            self.coverLabel.height(),
            radius,
        )

    def set_animated_cover_paused(self, paused: bool) -> None:
        if not self.animated_cover_path:
            return
        set_animated_cover_paused(self.coverLabel, paused)

    def stop_background_activity(self) -> None:
        self.set_animated_cover_paused(True)
        self._hovered = False
        self._focused = False
        if hasattr(self, 'animations') and self.animations:
            self.animations.cleanup()

    def update_cover_pixmap(self):
        # Check if the coverLabel still exists before trying to update it
        # This prevents the "Internal C++ object already deleted" error when
        # the widget has been destroyed but the async callback still executes
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return

        if self.animated_cover_path:
            self._update_animated_cover_size()
            return

        if self.base_pixmap and not self.base_pixmap.isNull():
            if self.list_layout:
                target_width = self.coverLabel.width() if self.coverLabel.width() > 0 else 56
                target_height = self.coverLabel.height() if self.coverLabel.height() > 0 else 56
                radius = int(self.card_layout_cfg.get("cover_radius", 8) * self._scale)
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
            else:
                target_width = int(self.base_card_width * self._scale)
                cover_ratio = self.card_layout_cfg.get("cover_aspect_ratio", 1.5)
                target_height = int(target_width * cover_ratio)
                radius = int(self.card_layout_cfg.get("cover_radius", 15) * self._scale)
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
            scaled_pixmap = self.base_pixmap.scaled(
                target_width,
                target_height,
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
            rounded_pixmap = round_corners(scaled_pixmap, radius)
            try:
                self.coverLabel.setPixmap(rounded_pixmap)
            except RuntimeError:
                # Handle the case where the Qt object was deleted between the check and the call
                pass

    def _position_badges(self, current_width):
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return

        right_margin = int(8 * self._scale)
        badge_spacing = int(current_width * 0.02)
        top_y = int(10 * self._scale)
        cover_height = self.coverWidget.height()
        hidden_badges = self.badge_view_mode == "hidden"
        badge_y_positions = []
        protondb_visible = is_valid_protondb_tier(self.protondb_tier) and not self.economy_mode
        anticheat_visible = bool(self.getAntiCheatText(self.anticheat_status)) and not self.economy_mode

        info_badges = [
            (protondb_visible, self.protondbLabel),
            (self.ppdb_visible, self.ppdbLabel),
            (anticheat_visible, self.anticheatLabel),
        ]

        for is_visible, badge in info_badges:
            if not is_visible or badge is None or hidden_badges:
                if badge is not None:
                    badge.setVisible(False)
                continue
            badge_x = current_width - badge.width() - right_margin
            badge_y = badge_y_positions[-1] + badge_spacing if badge_y_positions else top_y
            try:
                if self.list_layout:
                    full_text_width = badge.fontMetrics().horizontalAdvance(badge.text())
                    icon_size = getattr(badge, "_icon_size", 0)
                    icon_space = getattr(badge, "_icon_space", 0)
                    has_icon = badge.icon() is not None
                    required_width = full_text_width + 4
                    if has_icon:
                        required_width += icon_size + icon_space

                    fits_horizontally = badge.width() <= (current_width - right_margin)
                    fits_vertically = (badge_y + badge.height()) <= cover_height
                    fits_content = required_width <= badge.width()
                    if not (fits_horizontally and fits_vertically and fits_content):
                        badge.setVisible(False)
                        continue

                badge.setVisible(True)
                badge.move(int(badge_x), int(badge_y))
                badge_y_positions.append(badge_y + badge.height())
            except RuntimeError:
                pass

        ribbon_cfg = getattr(self.theme, "SOURCE_CORNER", {})
        ribbon_size = int(current_width * ribbon_cfg.get("size_ratio", 0.28))
        ribbon_size = max(ribbon_size, int(ribbon_cfg.get("min_size", 54) * self._scale))
        source_ribbons = [
            (self.steam_visible and not self.vertical_layout, self.steamLabel),
            (self.gog_visible and not self.vertical_layout, self.gogLabel),
            (self.egs_visible and not self.vertical_layout, self.egsLabel),
            (self.portproton_visible and not self.vertical_layout, self.portprotonLabel),
        ]

        for is_visible, ribbon in source_ribbons:
            if not is_visible or ribbon is None:
                if ribbon is not None:
                    ribbon.setVisible(False)
                continue
            try:
                ribbon.setFixedSize(ribbon_size, ribbon_size)
                ribbon.move(current_width - ribbon_size, cover_height - ribbon_size)
                ribbon.setVisible(True)
                ribbon.raise_()
            except RuntimeError:
                pass

        try:
            self.anticheatLabel.raise_()
            self.ppdbLabel.raise_()
            self.protondbLabel.raise_()
            self.portprotonLabel.raise_()
            self.gogLabel.raise_()
            self.egsLabel.raise_()
            self.steamLabel.raise_()
        except RuntimeError:
            pass

    def update_scale(self):
        # Check if the card has been destroyed before updating
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return

        scaled_width = int(self.base_card_width * self._scale)
        scaled_extra = int(self.base_extra_margin * self._scale)
        self.layout_.setContentsMargins(scaled_extra // 2, scaled_extra // 2, scaled_extra // 2, scaled_extra // 2)
        if self.list_layout:
            row_height = max(
                self.card_layout_cfg.get("min_row_height", 68),
                int(self.card_layout_cfg.get("row_height", 72) * self._scale),
            )
            icon_size = max(
                self.card_layout_cfg.get("min_cover_size", 48),
                int(self.card_layout_cfg.get("cover_size", 56) * self._scale),
            )
            margin_left = self.card_layout_cfg.get("cover_left_margin", 10)
            if self.vertical_layout:
                self.setMinimumWidth(0)
                self.setFixedHeight(row_height + scaled_extra)
                self.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed,
                )
            else:
                self.setFixedSize(scaled_width + scaled_extra, row_height + scaled_extra)
            self.coverWidget.setFixedSize(icon_size + margin_left, icon_size)
            self.coverWidget.setContentsMargins(margin_left, 0, 0, 0)
            self.coverLabel.setFixedSize(icon_size, icon_size)
        else:
            small_card_mode = self.base_card_width < self.theme.COMPACT_CARD["width_threshold"]
            height_ratio = (
                self.theme.COMPACT_CARD["height_ratio"]
                if small_card_mode else self.card_layout_cfg.get("card_height_ratio", 1.8)
            )
            scaled_height = int(self.base_card_width * height_ratio * self._scale)
            self.setFixedSize(scaled_width + scaled_extra, scaled_height + scaled_extra)
            cover_ratio = self.card_layout_cfg.get("cover_aspect_ratio", 1.5)
            cover_height = int(scaled_width * cover_ratio)
            self.coverWidget.setFixedSize(scaled_width, cover_height)
            self.coverLabel.setFixedSize(scaled_width, cover_height)

        self.update_cover_pixmap()

        favorite_size = (int(self.theme.favoriteLabelSize[0] * self._scale), int(self.theme.favoriteLabelSize[1] * self._scale))
        favorite_icon_size = int(self.theme.favoriteLabelIconSize * self._scale)
        self.favoriteLabel.setFixedSize(*favorite_size)
        self.favoriteLabel.setIconSize(favorite_icon_size, 0)
        self.favoriteLabel.move(int(8 * self._scale), int(8 * self._scale))

        badge_host_width = self.coverWidget.width()
        badge_width = int(badge_host_width * 2 / 3)
        icon_size = max(12, int(badge_host_width * 0.06))
        icon_space = max(2, int(badge_host_width * 0.012))
        compact_badge_width = int(badge_host_width * 0.12)
        compact_badge_width = max(compact_badge_width, icon_size + icon_space + 8)
        small_card_mode = not self.list_layout and self.base_card_width < self.theme.COMPACT_CARD["width_threshold"]
        compact_badge = self.badge_view_mode == "compact" or small_card_mode
        hidden_badges = self.badge_view_mode == "hidden"
        protondb_visible = is_valid_protondb_tier(self.protondb_tier) and not self.economy_mode
        anticheat_visible = bool(self.getAntiCheatText(self.anticheat_status)) and not self.economy_mode
        info_badge_visibility = [
            (protondb_visible, self.protondbLabel),
            (self.ppdb_visible, self.ppdbLabel),
            (anticheat_visible, self.anticheatLabel),
        ]
        for is_visible, label in info_badge_visibility:
            if label is not None:
                try:
                    label.setIconSize(icon_size, icon_space)
                    label.setCardWidth(scaled_width)
                    label.setCompactMode(
                        compact_badge,
                        compact_badge_width,
                        badge_width,
                        self._on_badge_width_changed
                    )
                    label.setVisible(is_visible and not hidden_badges)
                except RuntimeError:
                    pass

        self._position_badges(badge_host_width)

        if self.base_font_size is not None:
            try:
                font = self.nameLabel.font()
                title_scale = self.theme.COMPACT_CARD["title_scale"] if small_card_mode else 1.0
                new_font_size = self.base_font_size * self._scale * title_scale
                if new_font_size > 0:
                    font.setPointSizeF(new_font_size)
                    self.nameLabel.setFont(font)
                    if small_card_mode:
                        max_title_width = max(1, int(scaled_width * 0.9))
                        self.nameLabel.setText(self._get_compact_display_name(max_title_width))
                    else:
                        self.nameLabel.setText(self._get_display_name())
            except RuntimeError:
                # Handle the case where the Qt object was deleted
                pass

        try:
            self.shadow.setBlurRadius(int(self.theme.shadow_blur_radius * self._scale))
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            pass

        try:
            self.updateGeometry()
            self.update()
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            pass

        # Ensure parent layout is updated safely
        try:
            parent = self.parentWidget()
            if parent:
                layout = parent.layout()
                if layout:
                    layout.invalidate()
                    layout.activate()
                    layout.update()
                parent.updateGeometry()
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            pass

    def update_card_size(self, new_width: int):
        self.base_card_width = new_width
        self._load_cover_image(self.cover_path or "")
        self.update_scale()

    def update_badge_visibility(self, display_filter: str):
        # Check if the card has been destroyed before updating
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return

        self.display_filter = display_filter
        self.economy_mode = ui_config.get_economy_mode()
        self.steam_visible = str(self.game_source).lower() == "steam"
        self.gog_visible = str(self.game_source).lower() == "gog"
        self.egs_visible = str(self.game_source).lower() == "egs"
        self.portproton_visible = str(self.game_source).lower() == "portproton"
        self.ppdb_visible = bool(self.ppdb_id) and not self.economy_mode
        protondb_visible = is_valid_protondb_tier(self.protondb_tier) and not self.economy_mode
        anticheat_visible = bool(self.getAntiCheatText(self.anticheat_status)) and not self.economy_mode

        hidden_badges = self.badge_view_mode == "hidden"
        show_source_ribbons = self.vertical_layout is not True

        try:
            self.steamLabel.setVisible(self.steam_visible and show_source_ribbons)
            self.gogLabel.setVisible(self.gog_visible and show_source_ribbons)
            self.egsLabel.setVisible(self.egs_visible and show_source_ribbons)
            self.portprotonLabel.setVisible(
                self.portproton_visible and show_source_ribbons
            )
            self.ppdbLabel.setVisible(self.ppdb_visible and not hidden_badges)
            self.protondbLabel.setVisible(protondb_visible and not hidden_badges)
            self.anticheatLabel.setVisible(anticheat_visible and not hidden_badges)
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            return

        badge_host_width = self.coverWidget.width()
        self._position_badges(badge_host_width)

        # Update layout after visibility changes
        self.updateGeometry()
        parent = self.parentWidget()
        if parent:
            layout = parent.layout()
            if layout:
                layout.invalidate()
                layout.update()
            parent.updateGeometry()

    def _on_badge_width_changed(self):
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return
        badge_host_width = self.coverWidget.width()
        self._position_badges(badge_host_width)

    def update_badge_view_mode(self, badge_view_mode: str):
        """Update badge rendering mode."""
        self.badge_view_mode = badge_view_mode if badge_view_mode in ("detailed", "compact", "hidden") else "detailed"
        self.update_scale()

    def _show_context_menu(self, pos):
        if self.context_menu_manager:
            self.context_menu_manager.show_context_menu(self, pos)

    @staticmethod
    def getAntiCheatText(status: str) -> str:
        if not status:
            return ""
        translations = {
            "supported": _("Supported"),
            "running": _("Running"),
            "planned": _("Planned"),
            "broken":  _("Broken"),
            "denied": _("Denied")
        }
        return translations.get(status.lower(), "")

    @staticmethod
    def getAntiCheatIconFilename(status: str) -> str:
        status = status.lower()
        if status in ("supported"):
            return "ac_supported"
        elif status in ("running"):
            return "ac_running"
        elif status in ("planned"):
            return "ac_planned"
        elif status in ("denied"):
            return "ac_denied"
        elif status in ("broken"):
            return "ac_broken"
        return ""

    def _get_missing_executable_path(self) -> str:
        if str(self.game_source).lower() != "portproton":
            return ""
        exe_path = self._extract_executable_path(self.exec_line)
        if not exe_path:
            return ""
        if not exe_path.lower().endswith(WINDOWS_LAUNCH_EXTENSIONS):
            return ""
        return "" if os.path.exists(exe_path) else exe_path

    def _get_display_name(self) -> str:
        if not self.missing_executable_path:
            return self.name
        return f"{_('Missing EXE')}: {self.name}"

    def _get_compact_display_name(self, max_width: int) -> str:
        text = self._get_display_name()
        text = text.replace("_", " ")
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        words = text.split()
        if not words:
            return text

        metrics = self.nameLabel.fontMetrics()
        lines = []
        current_line = ""
        for index, word in enumerate(words):
            candidate = f"{current_line} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= max_width:
                current_line = candidate
                continue
            if not current_line:
                current_line = metrics.elidedText(word, Qt.TextElideMode.ElideRight, max_width)
                continue
            if len(lines) >= self.theme.COMPACT_CARD["title_lines"] - 1:
                rest = " ".join([current_line, *words[index:]]).strip()
                lines.append(metrics.elidedText(rest, Qt.TextElideMode.ElideRight, max_width))
                return "\n".join(lines)
            if current_line:
                lines.append(current_line)
            current_line = word

        if current_line:
            if len(lines) >= self.theme.COMPACT_CARD["title_lines"]:
                lines[-1] = metrics.elidedText(lines[-1], Qt.TextElideMode.ElideRight, max_width)
            else:
                lines.append(current_line)
        return "\n".join(lines[:self.theme.COMPACT_CARD["title_lines"]])

    @staticmethod
    def _extract_executable_path(exec_line: str) -> str:
        try:
            parts = shlex.split(exec_line or "")
        except ValueError:
            return ""
        if not parts:
            return ""
        if "--silent" in parts:
            silent_index = parts.index("--silent")
            if len(parts) <= silent_index + 1:
                return ""
            return os.path.expanduser(parts[silent_index + 1])
        for part in reversed(parts):
            if part.lower().endswith(WINDOWS_LAUNCH_EXTENSIONS):
                return os.path.expanduser(part)
        return ""

    def open_ppdb_page(self):
        if self.ppdb_id:
            QDesktopServices.openUrl(QUrl(f"https://linux-gaming.ru/game/{self.ppdb_id}"))

    def open_protondb_report(self):
        url = QUrl(f"https://www.protondb.com/app/{self.protondb_appid}")
        QDesktopServices.openUrl(url)

    def open_weanticheatyet_page(self):
        if self.anticheat_slug:
            url = QUrl(f"https://areweanticheatyet.com/game/{self.anticheat_slug}")
        else:
            formatted_name = self.name.lower().replace(" ", "-")
            url = QUrl(f"https://areweanticheatyet.com/game/{formatted_name}")
        QDesktopServices.openUrl(url)

    def update_favorite_icon(self):
        # Check if the card has been destroyed before updating
        if not hasattr(self, 'coverLabel') or self.coverLabel is None:
            return

        try:
            icon_name = "star_fav_full" if self.is_favorite else "star_fav"
            icon = self.theme_manager.get_icon(icon_name, self.current_theme_name, as_path=True)
            self.favoriteLabel.setText("")
            self.favoriteLabel.setIcon(icon)
            self.favoriteLabel.setStyleSheet(self.theme.FAVORITE_LABEL_STYLE)
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            return

        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'game_library_manager'):
                    # Access using getattr with default to avoid Ruff B009 warning
                    manager = getattr(parent, 'game_library_manager', None)
                    if manager is not None:
                        QTimer.singleShot(0, manager.update_game_grid)
                    break
                parent = parent.parent()
        except RuntimeError:
            # Handle the case where the Qt object was deleted
            pass

    def toggle_favorite(self):
        favorites = favorites_config.get_games()
        favorites_set = set(favorites)
        if self.is_favorite:
            if self.name in favorites_set:
                favorites.remove(self.name)
            self.is_favorite = False
        else:
            if self.name not in favorites_set:
                favorites.append(self.name)
            self.is_favorite = True
        favorites_config.set_games(favorites)
        self.update_favorite_icon()

    def hideEvent(self, event: QHideEvent) -> None:
        self.set_animated_cover_paused(True)
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        self.set_animated_cover_paused(False)
        super().showEvent(event)

    def click(self) -> None:
        game_data = {
            "name": self.name,
            "description": self.description,
            "cover_path": self.cover_path,
            "appid": self.appid,
            "controller_support": self.controller_support,
            "exec_line": self.exec_line,
            "last_launch": self.last_launch,
            "formatted_playtime": self.formatted_playtime,
            "playtime_seconds": self.playtime_seconds,
            "protondb_tier": self.protondb_tier,
            "game_source": self.game_source,
            "anticheat_status": self.anticheat_status,
            "anticheat_slug": self.anticheat_slug,
            "ppdb_id": self.ppdb_id,
            "ppdb_rating": self.ppdb_rating,
            "protondb_appid": self.protondb_appid,
            "autoinstall_exe_name": getattr(self, "autoinstall_exe_name", ""),
        }
        self.select_callback(game_data)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.click()
        super().mousePressEvent(event)

    def cleanup(self):
        """Clean up animations to prevent memory leaks when the card is destroyed."""
        if hasattr(self, 'coverLabel') and self.coverLabel is not None:
            cleanup_animated_cover(self.coverLabel)
        if hasattr(self, 'animations') and self.animations:
            try:
                self.animations.cleanup()
            except RuntimeError:
                # Object already deleted
                pass

    def __del__(self):
        """Destructor to ensure cleanup happens."""
        try:
            self.cleanup()
        except RuntimeError:
            # Object already deleted
            pass
