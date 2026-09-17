"""Plotly helpers with one look: the desk palette (desk.reporting.style), the Mar–Aug 2022 window shaded, dated event
markers and a small SIM watermark in the top-right corner of every figure.

    fig = charts.line_chart(df, "date", {"cum_pnl_m": "Cumulative P&L"}, y_title="₹ million",
                            events=data.event_markers())
    charts.band_marker(fig, "2022-10-31", lo, hi, point=pnl, text_lo="−₹105.4 m", text_hi="+₹334.3 m")
    charts.show(fig)
    components.source_caption([...], {...})          # every chart gets its caption

Helpers are generic: they take plain columns / lists and never read files or know about a particular table. Values are
plotted as given, so scale (₹ → ₹ million) in the page, where the unit is also named.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from desk import SIM_LABEL, WINDOW_END, WINDOW_START
from desk.reporting.style import FACTOR_COLORS, FACTOR_LABELS, PALETTE, PNL_BUCKETS

FONT = "Source Sans Pro, Helvetica Neue, Arial, sans-serif"
GRID = "#e6e9ef"
MUTED = "#8a8f98"
COLORWAY = [PALETTE["lme"], PALETTE["mcx"], PALETTE["fx"], PALETTE["freight"], FACTOR_COLORS["grade_spread"],
            FACTOR_COLORS["roll_term_structure"], PALETTE["loss"], PALETTE["neutral"]]
WINDOW_LABEL = f"{WINDOW_START:%b}–{WINDOW_END:%b %Y} window"

DateLike = str | dt.date | pd.Timestamp


def bucket_label(key: str, wrap: bool = False) -> str:
    """FACTOR_LABELS on one line, or on two (`wrap`, for axis labels) where the canonical label has a line break."""
    return FACTOR_LABELS.get(key, key).replace("\n", "<br>" if wrap else " ")


def bucket_color(key: str) -> str:
    return FACTOR_COLORS.get(key, PALETTE["neutral"])


def _ts(x: DateLike) -> pd.Timestamp:
    return pd.Timestamp(x)


def finish(fig: go.Figure, *, title: str | None = None, height: int = 380, x_title: str | None = None,
           y_title: str | None = None, legend: bool = True, watermark: bool = True) -> go.Figure:
    """Apply the shared layout: white ground, light grid, title and legend above the plot, SIM watermark in the
    bottom-right corner of the plot area."""
    fig.update_layout(
        template="plotly_white", colorway=COLORWAY, height=height,
        font=dict(family=FONT, size=12, color="#262730"),
        title=dict(text=title, x=0, xanchor="left", y=0.98, yanchor="top", font=dict(size=15)) if title else None,
        margin=dict(l=10, r=10, t=(64 if title else 30) if legend else (44 if title else 16), b=10),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=11)),
        hovermode="x unified", hoverlabel=dict(font=dict(family=FONT)),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    fig.update_xaxes(title_text=x_title, gridcolor=GRID, zeroline=False, showline=True, linecolor="#c9ced6",
                     automargin=True)
    fig.update_yaxes(title_text=y_title, gridcolor=GRID, zerolinecolor="#9aa1ab", zerolinewidth=1, automargin=True)
    if watermark:
        fig.add_annotation(text=SIM_LABEL, xref="paper", yref="paper", x=1, y=0, xanchor="right", yanchor="bottom",
                           xshift=-4, yshift=4, showarrow=False, font=dict(size=10, color=MUTED),
                           bgcolor="rgba(255,255,255,0.7)")
    return fig


def shade_window(fig: go.Figure, start: DateLike = WINDOW_START, end: DateLike = WINDOW_END,
                 label: str | None = WINDOW_LABEL) -> go.Figure:
    """Shade the headline trading window on a date x-axis."""
    fig.add_vrect(x0=_ts(start), x1=_ts(end), fillcolor=PALETTE["band"], opacity=0.45, line_width=0, layer="below")
    if label:
        fig.add_annotation(x=_ts(start), y=0, xref="x", yref="paper", text=label, showarrow=False, xanchor="left",
                           yanchor="bottom", xshift=4, yshift=4, font=dict(size=10, color=MUTED))
    return fig


def mark_events(fig: go.Figure, events: Iterable[tuple[DateLike, str]], color: str = PALETTE["loss"]) -> go.Figure:
    """Dotted vertical lines, labels stacked from the top of the plot, e.g. data.event_markers()."""
    for i, (when, label) in enumerate(sorted(events, key=lambda e: _ts(e[0]))):
        x = _ts(when)
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, xref="x", yref="paper",
                      line=dict(color=color, width=1, dash="dot"), opacity=0.7)
        fig.add_annotation(x=x, y=1, xref="x", yref="paper", text=f"{label} ({x:%#d-%b})", showarrow=False,
                           xanchor="left", yanchor="top", xshift=3, yshift=-2 - 15 * i,
                           font=dict(size=10, color=color), bgcolor="rgba(255,255,255,0.75)")
    return fig


def line_chart(df: pd.DataFrame, x: str, series: Mapping[str, str], *, colors: Mapping[str, str] | None = None,
               dashes: Mapping[str, str] | None = None, title: str | None = None, y_title: str | None = None,
               x_title: str | None = None, shade: bool = True, events: Iterable[tuple[DateLike, str]] = (),
               height: int = 380, hover_format: str = ",.1f") -> go.Figure:
    """Time series: one trace per column in `series` ({column: legend label}); dates may be ISO strings."""
    xs = pd.to_datetime(df[x])
    fig = go.Figure()
    for col, label in series.items():
        fig.add_trace(go.Scatter(
            x=xs, y=df[col], name=label, mode="lines",
            line=dict(width=2 if not (dashes and col in dashes) else 1.4,
                      color=(colors or {}).get(col), dash=(dashes or {}).get(col)),
            hovertemplate=f"%{{y:{hover_format}}}<extra>{label}</extra>"))
    if shade:
        shade_window(fig)
    mark_events(fig, events)
    return finish(fig, title=title, height=height, x_title=x_title, y_title=y_title)


def band_marker(fig: go.Figure, x: DateLike, lo: float, hi: float, point: float | None = None, *,
                label: str = "sensitivity band", text_lo: str | None = None, text_hi: str | None = None,
                text_point: str | None = None, color: str = PALETTE["loss"]) -> go.Figure:
    """A vertical band (lo..hi) at one x, with the point estimate on it: the headline P&L's anchor-premium band."""
    xx = _ts(x)
    fig.add_trace(go.Scatter(x=[xx, xx], y=[lo, hi], mode="lines+markers", name=label,
                             line=dict(color=color, width=5), marker=dict(symbol="line-ew", size=16, color=color,
                                                                          line=dict(width=3, color=color)),
                             hoverinfo="skip"))
    for y, text in ((lo, text_lo), (hi, text_hi)):
        if text:
            fig.add_annotation(x=xx, y=y, text=text, showarrow=False, xanchor="right", xshift=-10,
                               font=dict(size=11, color=color))
    if point is not None:
        fig.add_trace(go.Scatter(x=[xx], y=[point], mode="markers", name=text_point or "point estimate",
                                 marker=dict(size=9, color=PALETTE["pnl"], line=dict(width=1.5, color="white")),
                                 hoverinfo="skip", showlegend=False))
        if text_point:
            fig.add_annotation(x=xx, y=point, text=text_point, showarrow=False, xanchor="right", xshift=-12,
                               yshift=12, font=dict(size=11, color=PALETTE["pnl"]))
    return fig


def bar_chart(labels: Sequence[str], values: Sequence[float], *, colors: Sequence[str] | str | None = None,
              orientation: str = "h", title: str | None = None, value_title: str | None = None,
              text: Sequence[str] | None = None, height: int | None = None) -> go.Figure:
    """Bars in the given order (top-to-bottom when horizontal). `text` labels each bar: in a value column to the right
    of the plot when horizontal (it never collides with long category labels), above/below the bar when vertical."""
    horiz = orientation == "h"
    labels, values = list(labels), list(values)
    shown = list(text) if text is not None else None
    fig = go.Figure(go.Bar(
        x=values if horiz else labels, y=labels if horiz else values, orientation=orientation,
        marker_color=colors or COLORWAY[0], text=None if horiz else shown, textposition="outside",
        cliponaxis=False, textfont=dict(size=11), customdata=shown,
        hovertemplate="%{customdata}<extra></extra>" if shown else None))
    fig = finish(fig, title=title, height=height or max(260, 42 * len(labels) + 90), legend=False,
                 x_title=value_title if horiz else None, y_title=None if horiz else value_title)
    if horiz:
        fig.update_yaxes(autorange="reversed", showgrid=False, ticklabelstandoff=6)
        fig.update_xaxes(zeroline=True, zerolinecolor="#9aa1ab", nticks=5, tickangle=0)
        if shown:
            for label, t in zip(labels, shown):
                fig.add_annotation(x=1, y=label, xref="paper", yref="y", text=t, showarrow=False, xanchor="left",
                                   xshift=8, font=dict(size=11, color="#262730"))
            fig.update_layout(margin=dict(r=12 + 7 * max(len(t) for t in shown)))
    else:
        lo, hi = min(0.0, *values), max(0.0, *values)
        pad = 0.15 * ((hi - lo) or 1.0) if shown else 0.0
        fig.update_yaxes(range=[lo - pad if lo < 0 else lo, hi + pad if hi > 0 else hi])
    fig.update_layout(hovermode="closest")
    return fig


def waterfall(steps: Sequence[tuple[str, float]], *, colors: Sequence[str] | None = None, total_label: str = "Total",
              title: str | None = None, y_title: str | None = None, text: Sequence[str] | None = None,
              height: int = 420) -> go.Figure:
    """Floating bars that accumulate `steps` left to right, then a total bar. `colors` per step (e.g. bucket_color)."""
    labels, bases, heights, cols = [], [], [], []
    running = 0.0
    for i, (label, v) in enumerate(steps):
        labels.append(label)
        bases.append(running if v >= 0 else running + v)
        heights.append(abs(v))
        cols.append((colors[i] if colors else (PALETTE["gain"] if v >= 0 else PALETTE["loss"])))
        running += v
    labels.append(total_label)
    bases.append(min(0.0, running))
    heights.append(abs(running))
    cols.append(PALETTE["pnl"])
    shown = list(text) if text is not None else [f"{v:+,.1f}" for _, v in steps] + [f"{running:,.1f}"]
    fig = go.Figure(go.Bar(x=labels, y=heights, base=bases, marker_color=cols, text=shown, textposition="outside",
                           cliponaxis=False, hovertemplate="%{x}: %{text}<extra></extra>"))
    fig.add_hline(y=0, line_color="#9aa1ab", line_width=1)
    fig = finish(fig, title=title, height=height, y_title=y_title, legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(tickangle=-25)
    return fig


def bucket_waterfall(totals: Mapping[str, float], *, scale: float = 1e6, title: str | None = None,
                     y_title: str = "₹ million", text: Sequence[str] | None = None) -> go.Figure:
    """Attribution waterfall in the fixed PNL_BUCKETS order with FACTOR_COLORS (same order as the PNG charts)."""
    steps = [(bucket_label(b), totals.get(b, 0.0) / scale) for b in PNL_BUCKETS]
    return waterfall(steps, colors=[bucket_color(b) for b in PNL_BUCKETS], title=title, y_title=y_title, text=text)


def heatmap(z: pd.DataFrame, *, title: str | None = None, x_title: str | None = None, y_title: str | None = None,
            colorscale: str | list = "RdYlGn", zmid: float | None = 0.0, text_format: str = ",.0f",
            colorbar_title: str | None = None, height: int | None = None) -> go.Figure:
    """Heatmap of a wide DataFrame (index = rows, columns = columns), values printed in each cell."""
    fig = go.Figure(go.Heatmap(
        z=z.values, x=[str(c) for c in z.columns], y=[str(i) for i in z.index], colorscale=colorscale, zmid=zmid,
        texttemplate=f"%{{z:{text_format}}}", textfont=dict(size=10), hoverongaps=False,
        colorbar=dict(title=colorbar_title, thickness=12)))
    fig = finish(fig, title=title, height=height or max(300, 28 * len(z.index) + 120), x_title=x_title,
                 y_title=y_title, legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(showgrid=False, type="category", autorange="reversed")
    return fig


def histogram(values: Sequence[float] | pd.Series, *, markers: Sequence[tuple[float, str] | tuple[float, str, str]] = (),
              nbins: int = 80, title: str | None = None, x_title: str | None = None, y_title: str = "paths",
              color: str = PALETTE["lme"], height: int = 380) -> go.Figure:
    """Distribution with labelled vertical markers, e.g. [(var99, "99 % VaR", PALETTE["loss"])]."""
    fig = go.Figure(go.Histogram(x=list(values), nbinsx=nbins, marker_color=color, opacity=0.8, name="distribution"))
    for i, m in enumerate(markers):
        x, label = m[0], m[1]
        c = m[2] if len(m) > 2 else PALETTE["loss"]
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, xref="x", yref="paper", line=dict(color=c, width=1.6,
                                                                                               dash="dash"))
        fig.add_annotation(x=x, y=1 - 0.08 * i, xref="x", yref="paper", text=label, showarrow=False, xanchor="left",
                           xshift=4, yanchor="top", font=dict(size=11, color=c))
    fig = finish(fig, title=title, height=height, x_title=x_title, y_title=y_title, legend=False)
    fig.update_layout(hovermode="closest", bargap=0.02)
    return fig


def show(fig: go.Figure, key: str | None = None) -> None:
    """Render with the app's own layout (theme=None keeps these colours) and a lean mode bar."""
    st.plotly_chart(fig, theme=None, key=key, width="stretch",
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
