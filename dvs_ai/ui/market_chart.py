from __future__ import annotations
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

from dvs_ai.ui.frame_paint_scheduler import FramePaintScheduler


class MarketChart(QWidget):
    """Biểu đồ nến + CMF + RSI.

    Trên 15m, vùng Entry/Invalidation/TP lấy trực tiếp từ TradePlan.
    UI không tự tính lại vùng giao dịch.
    """

    PRICE_AXIS_WIDTH = 84

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.timeframe = "15m"
        self.trade_plan = None
        self.direction = None
        self.show_long_candidate = True
        self.show_short_candidate = True
        self.show_signal_markers = True
        self.context = None
        self._render_key = None
        self._paint_scheduler = None
        # Native paint-safety state.  Keep this state local to the widget and
        # never perform blocking file I/O from paintEvent().
        self._paint_in_progress = False
        self._paint_failure_count = 0
        self._paint_invalid_value_count = 0
        self._paint_reentrant_count = 0
        self._last_paint_issue = None
        self.setMinimumHeight(0)

    def set_paint_scheduler(self, scheduler: FramePaintScheduler | None):
        self._paint_scheduler = scheduler

    def request_repaint(self, priority: int = 5):
        if self._paint_scheduler is not None:
            return self._paint_scheduler.request(self, priority)
        self.update()
        return True

    @staticmethod
    def _safe_last(values, default=0.0):
        try:
            value = float(values[-1])
            return value if math.isfinite(value) else float(default)
        except (TypeError, ValueError, IndexError):
            return float(default)

    @staticmethod
    def _finite_float(value, label="value"):
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError(f"non-finite {label}: {converted!r}")
        return converted

    @staticmethod
    def _finite_point(*values):
        try:
            return all(math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError):
            return False

    def _record_paint_issue(self, category, detail):
        # Deliberately memory-only: disk writes in a Qt paint callback can
        # create re-entrancy and latency hazards of their own.
        self._last_paint_issue = {
            "category": str(category),
            "detail": str(detail)[:500],
        }
        if category == "invalid_value":
            self._paint_invalid_value_count += 1
        elif category == "reentrant_paint":
            self._paint_reentrant_count += 1
        else:
            self._paint_failure_count += 1

    def paint_health_snapshot(self):
        """Return a non-blocking, serialization-safe paint health snapshot.

        Runtime telemetry calls this method from its Qt timer on the GUI
        thread, outside ``paintEvent``. Counter updates and snapshot reads are
        therefore ordered by the Qt event loop and require no blocking lock.
        The issue mapping is replaced atomically by ``_record_paint_issue``;
        copy it here so telemetry never retains a mutable widget-owned object.
        """
        last_issue = self._last_paint_issue
        return {
            "invalid_value_count": int(self._paint_invalid_value_count),
            "reentrant_count": int(self._paint_reentrant_count),
            "failure_count": int(self._paint_failure_count),
            "last_issue": dict(last_issue) if isinstance(last_issue, dict) else None,
        }

    def _make_render_key(
        self,
        analysis,
        timeframe,
        trade_plan,
        direction,
        context,
    ):
        plan_key = None
        if trade_plan is not None:
            plan_key = (
                str(getattr(trade_plan, "direction", "")),
                round(float(getattr(trade_plan, "entry_low", 0.0)), 10),
                round(float(getattr(trade_plan, "entry_high", 0.0)), 10),
                round(float(getattr(trade_plan, "invalidation", 0.0)), 10),
                round(float(getattr(trade_plan, "tp1", 0.0)), 10),
                round(float(getattr(trade_plan, "tp2", 0.0)), 10),
            )
        return (
            str(timeframe),
            str(direction),
            len(getattr(analysis, "closes", ()) or ()),
            round(self._safe_last(getattr(analysis, "closes", ())), 10),
            round(self._safe_last(getattr(analysis, "cmf_values", ())), 6),
            round(self._safe_last(getattr(analysis, "rsi_values", ())), 4),
            bool(getattr(analysis, "spring", False)),
            bool(getattr(analysis, "upthrust", False)),
            plan_key,
            str(getattr(context, "action", "")),
            round(float(getattr(context, "confidence_score", 0.0)), 2),
            self.show_long_candidate,
            self.show_short_candidate,
            self.show_signal_markers,
        )

    def set_analysis(
        self, analysis, timeframe: str,
        trade_plan=None, direction=None, context=None
    ):
        render_key = self._make_render_key(
            analysis,
            timeframe,
            trade_plan,
            direction,
            context,
        )
        self.data = analysis
        self.timeframe = timeframe
        self.trade_plan = trade_plan
        self.direction = direction
        self.context = context
        if render_key == self._render_key:
            return False
        self._render_key = render_key
        self.request_repaint(priority=10)
        return True

    def set_signal_markers_visible(self, visible: bool):
        visible = bool(visible)
        if visible == self.show_signal_markers:
            return False
        self.show_signal_markers = visible
        self._render_key = None
        self.request_repaint(priority=10)
        return True

    def set_candidate_visibility(self, show_long: bool, show_short: bool):
        show_long = bool(show_long)
        show_short = bool(show_short)
        if (
            show_long == self.show_long_candidate
            and show_short == self.show_short_candidate
        ):
            return False
        self.show_long_candidate = show_long
        self.show_short_candidate = show_short
        self._render_key = None
        self.request_repaint(priority=10)
        return True

    @staticmethod
    def _map(value, low, high, top, bottom):
        values = tuple(float(v) for v in (value, low, high, top, bottom))
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"non-finite chart coordinate input: {values!r}")
        value, low, high, top, bottom = values
        span = high - low
        if not math.isfinite(span) or abs(span) < 1e-12:
            span = 1e-12
        mapped = bottom - (value - low) / span * (bottom - top)
        if not math.isfinite(mapped):
            raise ValueError(f"non-finite mapped coordinate: {mapped!r}")
        return mapped

    def _panel(self, painter, rect, title):
        painter.fillRect(rect, QColor("#0b1220"))
        painter.setPen(QPen(QColor("#23314a"), 1))
        painter.drawRect(rect)
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            rect.adjusted(8, 4, -self.PRICE_AXIS_WIDTH, -4),
            Qt.AlignmentFlag.AlignTop,
            title,
        )

    def _plot_bounds(self, rect):
        return (
            rect.left() + 8,
            rect.right() - self.PRICE_AXIS_WIDTH,
            rect.top() + 20,
            rect.bottom() - 8,
        )

    def _draw_line(self, painter, values, rect, low, high, color, width=1.8):
        vals = list(values)
        if len(vals) < 2:
            return
        left, right, top, bottom = self._plot_bounds(rect)
        pts = []
        for i, value in enumerate(vals):
            try:
                x = left + i * (right-left) / max(len(vals)-1, 1)
                y = self._map(value, low, high, top, bottom)
            except (TypeError, ValueError, OverflowError) as exc:
                self._record_paint_issue("invalid_value", exc)
                pts.append(None)
                continue
            pts.append(QPointF(x, y))
        painter.setPen(QPen(QColor(color), width))
        for a, b in zip(pts, pts[1:]):
            if a is not None and b is not None:
                painter.drawLine(a, b)

    @staticmethod
    def _legacy_candidate_zones(data):
        close = float(data.closes[-1])
        atr = max(float(data.atr), close * 0.002)

        long_a = max(float(data.support), close - 0.8 * atr)
        long_b = close - 0.2 * atr
        long_low, long_high = sorted((long_a, long_b))

        short_a = close + 0.2 * atr
        short_b = min(float(data.resistance), close + 0.8 * atr)
        short_low, short_high = sorted((short_a, short_b))
        return (long_low, long_high), (short_low, short_high)

    def _draw_zone(
        self, painter, rect, low_value, high_value,
        p_low, p_high, color, label
    ):
        left, right, top, bottom = self._plot_bounds(rect)
        y1 = self._map(high_value, p_low, p_high, top, bottom)
        y2 = self._map(low_value, p_low, p_high, top, bottom)
        zone_rect = QRectF(
            left,
            min(y1, y2),
            max(right-left, 10),
            max(abs(y2-y1), 3.0),
        )
        fill = QColor(color)
        fill.setAlpha(34)
        edge = QColor(color)
        edge.setAlpha(210)
        painter.fillRect(zone_rect, QBrush(fill))
        painter.setPen(QPen(edge, 1.1, Qt.PenStyle.DashLine))
        painter.drawRect(zone_rect)
        painter.setPen(edge)
        painter.drawText(
            zone_rect.adjusted(5, 1, -5, -1),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            label,
        )

    def _draw_level(
        self, painter, rect, value, p_low, p_high,
        color, label, style=Qt.PenStyle.DashLine
    ):
        left, right, top, bottom = self._plot_bounds(rect)
        y = self._map(value, p_low, p_high, top, bottom)
        painter.setPen(QPen(QColor(color), 1.1, style))
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.setPen(QColor(color))
        painter.drawText(int(left+5), int(y-3), label)

    def _draw_price_axis(self, painter, rect, p_low, p_high, levels):
        """Cột giá bên phải, có chống chồng nhãn đơn giản."""
        left, right, top, bottom = self._plot_bounds(rect)
        axis_left = right + 5
        axis_right = rect.right() - 4

        painter.fillRect(
            QRectF(axis_left, rect.top()+1, axis_right-axis_left, rect.height()-2),
            QColor("#0a1120"),
        )
        painter.setPen(QPen(QColor("#23314a"), 1))
        painter.drawLine(QPointF(axis_left, top), QPointF(axis_left, bottom))

        # Mốc trục giá nền.
        painter.setPen(QColor("#94a3b8"))
        for i in range(6):
            value = p_high - (p_high-p_low) * i / 5
            y = top + (bottom-top) * i / 5
            painter.drawLine(QPointF(axis_left, y), QPointF(axis_left+4, y))
            painter.drawText(
                QRectF(axis_left+6, y-9, axis_right-axis_left-7, 18),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"{value:.8g}",
            )

        # Nhãn mức quan trọng. Dịch nhãn khi quá sát nhau.
        prepared = []
        for label, value, color in levels:
            if value is None:
                continue
            y = self._map(float(value), p_low, p_high, top, bottom)
            prepared.append([y, label, float(value), color])
        prepared.sort(key=lambda x: x[0])

        min_gap = 17.0
        last_y = top - min_gap
        for item in prepared:
            item[0] = max(item[0], last_y + min_gap)
            item[0] = min(item[0], bottom)
            last_y = item[0]

        for y, label, value, color in prepared:
            box = QRectF(axis_left+2, y-8, axis_right-axis_left-3, 16)
            fill = QColor(color)
            fill.setAlpha(190)
            painter.fillRect(box, fill)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                box.adjusted(3, 0, -3, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"{label} {value:.8g}",
            )

    def _regime_color(self):
        if self.context is None:
            return QColor("#080f1d")
        regime = str(self.context.regime.regime).upper()
        if "ACCUM" in regime or "REVERSAL" in regime:
            return QColor(5, 46, 35, 58)
        if "DISTR" in regime or "MARKDOWN" in regime:
            return QColor(69, 10, 20, 52)
        if "RANGE" in regime:
            return QColor(38, 25, 77, 48)
        if "TREND" in regime:
            return QColor(7, 38, 62, 44)
        return QColor(8, 15, 29)

    def _draw_score_badges(self, painter, rect):
        """Legacy helper: intentionally not called; scores are shown above chart."""
        if self.context is None:
            return
        long_score = float(self.context.long_entry_score)
        short_score = float(self.context.short_entry_score)
        box_w, box_h, gap = 132, 58, 7
        x2 = rect.right() - self.PRICE_AXIS_WIDTH - 8
        y = rect.top() + 25
        x1 = x2 - box_w*2 - gap
        for x, title, score, color in (
            (x1, "AI LONG SCORE", long_score, "#22c55e"),
            (x1 + box_w + gap, "AI SHORT SCORE", short_score, "#ef4444"),
        ):
            box = QRectF(x, y, box_w, box_h)
            painter.fillRect(box, QColor(8, 18, 33, 220))
            painter.setPen(QPen(QColor("#263753"), 1))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QColor(color))
            painter.drawText(box.adjusted(7, 4, -7, -4),
                             Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                             title)
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(box.adjusted(7, 18, -7, -12),
                             Qt.AlignmentFlag.AlignCenter, f"{score:.0f}/100")
            bar = QRectF(box.left()+9, box.bottom()-10, box.width()-18, 5)
            painter.fillRect(bar, QColor("#1e293b"))
            painter.fillRect(QRectF(bar.left(), bar.top(),
                                   bar.width()*min(score,100)/100, bar.height()),
                             QColor(color))

    def _draw_signal_markers(self, painter, rect, lows, highs, p_low, p_high):
        if not self.show_signal_markers or self.context is None:
            return
        left, right, top, bottom = self._plot_bounds(rect)
        n = len(lows)
        if n < 4:
            return
        step = (right-left)/max(n, 1)
        events = []
        s = self.context.structure
        sm = self.context.smart_entry
        event_text = str(s.liquidity_event).lower()
        if "quét đáy" in event_text:
            idx = min(range(n), key=lambda i: lows[i])
            events.append((idx, lows[idx], "LQ", "#38bdf8", "Liquidity Sweep"))
        if "quét đỉnh" in event_text:
            idx = max(range(n), key=lambda i: highs[i])
            events.append((idx, highs[idx], "LQ", "#f59e0b", "Liquidity Sweep"))
        if self.data.spring or "spring" in str(s.wyckoff_signal).lower():
            idx = min(range(max(0,n-20), n), key=lambda i: lows[i])
            events.append((idx, lows[idx], "S", "#22c55e", "Spring"))
        if self.data.upthrust or "upthrust" in str(s.wyckoff_signal).lower():
            idx = max(range(max(0,n-20), n), key=lambda i: highs[i])
            events.append((idx, highs[idx], "U", "#ef4444", "Upthrust"))
        if sm.weak_hand_score >= 60:
            idx = max(0, n-7)
            events.append((idx, lows[idx], "W", "#a78bfa", "Weak-hand"))
        if sm.absorption_score >= 60:
            idx = max(0, n-4)
            events.append((idx, lows[idx], "A", "#10b981", "Absorption"))
        for idx, price, short, color, label in events[:5]:
            x = left + (idx+0.5)*step
            y = self._map(price, p_low, p_high, top, bottom)
            above = short == "U"
            cy = y - 18 if above else y + 18
            painter.setPen(QPen(QColor(color), 1.5))
            painter.drawLine(QPointF(x, y), QPointF(x, cy))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x, cy), 8, 8)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(x-8, cy-8, 16, 16),
                             Qt.AlignmentFlag.AlignCenter, short)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(x-55, cy+10 if not above else cy-25, 110, 16),
                             Qt.AlignmentFlag.AlignCenter, label)

    def paintEvent(self, event):
        """Qt paint entry point with deterministic painter cleanup.

        A QPainter is always ended in ``finally``.  Re-entrant paint delivery
        is rejected before a native painter is created.  Python exceptions
        abort only the current frame instead of escaping through Qt.
        """
        if self._paint_in_progress:
            self._record_paint_issue("reentrant_paint", "nested paintEvent ignored")
            return

        self._paint_in_progress = True
        painter = QPainter()
        try:
            if not painter.begin(self):
                self._record_paint_issue("painter_begin_failed", "QPainter.begin returned false")
                return
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_event_impl(painter, event)
        except (TypeError, ValueError, OverflowError, IndexError, AttributeError, NameError) as exc:
            self._record_paint_issue("paint_exception", exc)
            # Leave the frame safely blank; the next valid update can repaint.
        finally:
            try:
                if painter.isActive():
                    painter.end()
            finally:
                self._paint_in_progress = False

    def _paint_event_impl(self, painter, event):
        painter.fillRect(self.rect(), QColor("#080f1d"))
        data = self.data

        if data is None or len(getattr(data, "closes", ()) or ()) < 2:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Chọn coin để hiển thị biểu đồ",
            )
            return

        margin = 6
        full = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.fillRect(full, self._regime_color())
        gap = 5
        price_h = int(full.height() * 0.55)
        cmf_h = int(full.height() * 0.21)
        rsi_h = full.height() - price_h - cmf_h - gap*2

        price_rect = QRectF(full.left(), full.top(), full.width(), price_h)
        cmf_rect = QRectF(
            full.left(), price_rect.bottom()+gap, full.width(), cmf_h
        )
        rsi_rect = QRectF(
            full.left(), cmf_rect.bottom()+gap, full.width(), rsi_h
        )

        # Snapshot and validate render data before invoking native drawing.
        raw_ohlc = list(zip(data.opens, data.highs, data.lows, data.closes))[-60:]
        valid_ohlc = []
        for row in raw_ohlc:
            try:
                converted = tuple(self._finite_float(v, "OHLC") for v in row)
            except (TypeError, ValueError, OverflowError) as exc:
                self._record_paint_issue("invalid_value", exc)
                continue
            valid_ohlc.append(converted)
        if len(valid_ohlc) < 2:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Dữ liệu biểu đồ không hợp lệ",
            )
            return
        opens = [row[0] for row in valid_ohlc]
        highs = [row[1] for row in valid_ohlc]
        lows = [row[2] for row in valid_ohlc]
        closes = [row[3] for row in valid_ohlc]

        def finite_series(values):
            result = []
            for value in list(values)[-60:]:
                try:
                    result.append(self._finite_float(value, "indicator"))
                except (TypeError, ValueError, OverflowError) as exc:
                    self._record_paint_issue("invalid_value", exc)
            return result

        cmf = finite_series(data.cmf_values)
        rsi = finite_series(data.rsi_values)
        if len(cmf) < 2:
            cmf = [0.0, 0.0]
        if len(rsi) < 2:
            rsi = [50.0, 50.0]
        plan_is_source = (
            self.trade_plan is not None
            and self.timeframe == "15m"
        )

        if plan_is_source:
            plan_zone = (
                float(self.trade_plan.entry_low),
                float(self.trade_plan.entry_high),
            )
            if str(self.trade_plan.direction).upper() == "LONG":
                long_zone = plan_zone
                short_zone = None
            else:
                long_zone = None
                short_zone = plan_zone
        else:
            # Other timeframes do not own a TradePlan. Keep the old
            # candidate overlays as clearly labelled visual references.
            long_zone, short_zone = self._legacy_candidate_zones(
                data
            )

        price_values = lows + highs
        if self.show_long_candidate and long_zone is not None:
            price_values += list(long_zone)
        if self.show_short_candidate and short_zone is not None:
            price_values += list(short_zone)

        if plan_is_source:
            price_values += [
                float(self.trade_plan.invalidation),
                float(self.trade_plan.tp1),
                float(self.trade_plan.tp2),
            ]

        p_low = min(price_values)
        p_high = max(price_values)
        pad = max((p_high-p_low)*0.08, p_high*0.0005)
        p_low -= pad
        p_high += pad

        self._panel(
            painter,
            price_rect,
            f"GIÁ {self.timeframe} | Close {closes[-1]:.8g} | "
            f"H {max(highs):.8g} L {min(lows):.8g}",
        )

        left, right, top, bottom = self._plot_bounds(price_rect)
        step = (right-left)/max(len(closes), 1)
        body_w = max(2.0, min(8.0, step*0.58))

        if (
            self.show_long_candidate
            and long_zone is not None
            and not plan_is_source
        ):
            self._draw_zone(
                painter,
                price_rect,
                long_zone[0],
                long_zone[1],
                p_low,
                p_high,
                "#22c55e",
                "LONG tham khảo",
            )
        if (
            self.show_short_candidate
            and short_zone is not None
            and not plan_is_source
        ):
            self._draw_zone(
                painter,
                price_rect,
                short_zone[0],
                short_zone[1],
                p_low,
                p_high,
                "#ef4444",
                "SHORT tham khảo",
            )

        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
            x = left + (i+0.5)*step
            y_h = self._map(h, p_low, p_high, top, bottom)
            y_l = self._map(l, p_low, p_high, top, bottom)
            y_o = self._map(o, p_low, p_high, top, bottom)
            y_c = self._map(c, p_low, p_high, top, bottom)
            if not self._finite_point(x, y_h, y_l, y_o, y_c):
                self._record_paint_issue("invalid_value", "non-finite candle geometry")
                continue
            up = c >= o
            color = QColor("#22c55e" if up else "#ef4444")
            painter.setPen(QPen(color, 1))
            painter.drawLine(QPointF(x, y_h), QPointF(x, y_l))
            body_top = min(y_o, y_c)
            body_h = max(abs(y_c-y_o), 1.4)
            painter.fillRect(
                QRectF(x-body_w/2, body_top, body_w, body_h), color
            )

        current_y = self._map(closes[-1], p_low, p_high, top, bottom)
        painter.setPen(
            QPen(QColor("#38bdf8"), 1, Qt.PenStyle.DashLine)
        )
        painter.drawLine(QPointF(left, current_y), QPointF(right, current_y))
        self._draw_signal_markers(painter, price_rect, lows, highs, p_low, p_high)

        axis_levels = [("NOW", closes[-1], "#0284c7")]

        if (
            self.show_long_candidate
            and long_zone is not None
            and not plan_is_source
        ):
            axis_levels += [
                ("L↓", long_zone[0], "#15803d"),
                ("L↑", long_zone[1], "#16a34a"),
            ]
        if (
            self.show_short_candidate
            and short_zone is not None
            and not plan_is_source
        ):
            axis_levels += [
                ("S↓", short_zone[0], "#b91c1c"),
                ("S↑", short_zone[1], "#dc2626"),
            ]

        if plan_is_source:
            plan_color = (
                "#22c55e"
                if self.trade_plan.direction == "LONG"
                else "#ef4444"
            )
            self._draw_zone(
                painter,
                price_rect,
                float(self.trade_plan.entry_low),
                float(self.trade_plan.entry_high),
                p_low,
                p_high,
                plan_color,
                f"PLAN {self.trade_plan.direction}",
            )
            self._draw_level(
                painter, price_rect, float(self.trade_plan.invalidation),
                p_low, p_high, "#f59e0b", "INVALID"
            )
            self._draw_level(
                painter, price_rect, float(self.trade_plan.tp1),
                p_low, p_high, "#38bdf8", "TP1"
            )
            self._draw_level(
                painter, price_rect, float(self.trade_plan.tp2),
                p_low, p_high, "#a78bfa", "TP2"
            )
            axis_levels += [
                ("E↓", float(self.trade_plan.entry_low), plan_color),
                ("E↑", float(self.trade_plan.entry_high), plan_color),
                ("INV", float(self.trade_plan.invalidation), "#d97706"),
                ("TP1", float(self.trade_plan.tp1), "#0284c7"),
                ("TP2", float(self.trade_plan.tp2), "#7c3aed"),
            ]

        self._draw_price_axis(
            painter, price_rect, p_low, p_high, axis_levels
        )

        cmf_low = min(-0.5, min(cmf)-0.05)
        cmf_high = max(0.5, max(cmf)+0.05)
        self._panel(painter, cmf_rect, f"CMF 20 | {cmf[-1]:+.3f}")
        c_left, c_right, cmf_top, cmf_bottom = self._plot_bounds(cmf_rect)
        zero_y = self._map(
            0.0, cmf_low, cmf_high, cmf_top, cmf_bottom
        )
        painter.setPen(
            QPen(QColor("#64748b"), 1, Qt.PenStyle.DashLine)
        )
        painter.drawLine(
            QPointF(c_left, zero_y), QPointF(c_right, zero_y)
        )
        self._draw_line(
            painter, cmf, cmf_rect, cmf_low, cmf_high, "#4ade80", 1.8
        )

        self._panel(painter, rsi_rect, f"RSI 14 | {rsi[-1]:.1f}")
        r_left, r_right, rsi_top, rsi_bottom = self._plot_bounds(rsi_rect)
        for level in (30.0, 50.0, 70.0):
            y = self._map(level, 0.0, 100.0, rsi_top, rsi_bottom)
            painter.setPen(QPen(
                QColor(
                    "#ef4444" if level == 70
                    else "#22c55e" if level == 30
                    else "#64748b"
                ),
                1,
                Qt.PenStyle.DashLine,
            ))
            painter.drawLine(QPointF(r_left, y), QPointF(r_right, y))
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                int(r_right-25), int(y-2), f"{int(level)}"
            )
        self._draw_line(
            painter, rsi, rsi_rect, 0.0, 100.0, "#a78bfa", 1.8
        )
