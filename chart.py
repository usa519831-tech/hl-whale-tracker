"""가격 차트 + 고래 진입/청산 + 청산 지도"""
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

API = "https://api.hyperliquid.xyz/info"
UP, DN = "#26a69a", "#ef5350"
WHITE, GOLD = "#e8e8e8", "#ffd54f"
GRID, TXT = "rgba(255,255,255,0.07)", "#d0d0d0"
BASE = dict(template="plotly_dark", font=dict(color=TXT, size=12),
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117")


def candles(coin, interval="1h", days=14):
    now = int(time.time() * 1000)
    r = requests.post(API, json={"type": "candleSnapshot", "req": {
        "coin": coin, "interval": interval,
        "startTime": now - days * 86400 * 1000, "endTime": now}}, timeout=30)
    r.raise_for_status()
    d = pd.DataFrame(r.json())
    if d.empty:
        return d
    d["t"] = pd.to_datetime(d.t, unit="ms", utc=True)
    for c in ["o", "h", "l", "c", "v"]:
        d[c] = d[c].astype(float)
    return d


def _size(v, lo=10, hi=26):
    v = np.asarray(v, dtype=float)
    if len(v) == 0 or np.nanmax(v) <= 0:
        return np.full(len(v), lo)
    return lo + np.sqrt(v / np.nanmax(v)) * (hi - lo)


def price_chart(coin, cd, ev, pos, mark, height=560):
    """캔들 + 고래 진입/청산 마커 + 가중평균 진입선"""
    fig = go.Figure()
    fig.add_candlestick(x=cd.t, open=cd.o, high=cd.h, low=cd.l, close=cd.c,
                        increasing_line_color=UP, decreasing_line_color=DN,
                        increasing_fillcolor=UP, decreasing_fillcolor=DN,
                        line_width=1, name="가격", showlegend=False)

    lo, hi = cd.l.min(), cd.h.max()
    pad = (hi - lo) * 0.06

    if ev is not None and len(ev):
        e = ev[ev.ts >= cd.t.min()].copy()
        if len(e):
            e["ntl"] = e.delta.abs() * e.mark
            e["slot"] = e.ts.dt.floor("1h")
            e["grp"] = np.where(e.kind.isin(["OPEN", "ADD"]), "진입", "청산")
            # 같은 시각·방향·유형은 하나로 합쳐 마커 뭉침 방지
            g = (e.groupby(["slot", "side", "grp"])
                   .agg(ntl=("ntl", "sum"), n=("addr", "nunique"),
                        sz=("delta", "sum"), px=("mark", "first")).reset_index())
            g = g.merge(cd[["t", "h", "l"]], left_on="slot", right_on="t", how="left")
            g["h"] = g.h.fillna(g.px); g["l"] = g.l.fillna(g.px)

            spec = [("진입", "LONG", "triangle-up", UP, "롱 진입", -0.30),
                    ("청산", "LONG", "x", WHITE, "롱 청산/축소", -0.78),
                    ("진입", "SHORT", "triangle-down", DN, "숏 진입", +0.30),
                    ("청산", "SHORT", "x", GOLD, "숏 청산/축소", +0.78)]
            for grp, side, sym, col, nm, off in spec:
                q = g[(g.grp == grp) & (g.side == side)]
                if q.empty:
                    continue
                y = (q.l if off < 0 else q.h) + pad * off
                fig.add_scatter(
                    x=q.slot, y=y, mode="markers", name=nm,
                    marker=dict(symbol=sym, size=_size(q.ntl), color=col,
                                line=dict(width=1.2, color="rgba(0,0,0,0.55)")),
                    customdata=np.c_[q.n, q.ntl / 1e6, q.sz.round(2)],
                    hovertemplate=("<b>" + nm + "</b>  %{x|%m-%d %H:%M}<br>"
                                   "고래 %{customdata[0]}명 · $%{customdata[1]:.2f}M<br>"
                                   "순변화 %{customdata[2]} " + coin + "<extra></extra>"))

    if pos is not None and len(pos):
        for g2, col, nm in [(pos[pos.szi > 0], UP, "롱 평균진입"),
                            (pos[pos.szi < 0], DN, "숏 평균진입")]:
            if not len(g2):
                continue
            w = (g2.entryPx * g2.szi.abs()).sum() / g2.szi.abs().sum()
            if lo - pad < w < hi + pad:
                fig.add_hline(y=w, line=dict(color=col, dash="dot", width=1.5),
                              annotation_text=f"{nm} ${w:,.0f}",
                              annotation_position="top left",
                              annotation_font=dict(size=11, color=col))

    fig.add_hline(y=mark, line=dict(color="white", dash="dash", width=1.2),
                  annotation_text=f"현재 ${mark:,.0f}",
                  annotation_position="top left",
                  annotation_font=dict(size=12, color="white"))

    fig.update_layout(height=height, margin=dict(l=8, r=20, t=44, b=8),
                      title=dict(text=f"{coin} 가격 · 고래 진입/청산 지점", x=0.01,
                                 font=dict(size=15)),
                      hovermode="closest", xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.28,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
                      **BASE)
    fig.update_yaxes(range=[lo - pad, hi + pad], gridcolor=GRID, tickformat=",.0f")
    fig.update_xaxes(gridcolor=GRID)
    return fig


def liq_map(coin, pos, mark, height=460, span=0.55):
    """청산 지도 — 가격대별 청산 대기 물량 (레버리지가 낮아 범위를 넓게 잡음)"""
    if pos is None or not len(pos):
        return None
    L, S = pos[pos.szi > 0], pos[pos.szi < 0]
    lo, hi = mark * (1 - span), mark * (1 + span)
    bins = np.linspace(lo, hi, 61)
    ctr = (bins[:-1] + bins[1:]) / 2

    fig = make_subplots(rows=1, cols=2, column_widths=[0.62, 0.38],
                        horizontal_spacing=0.10,
                        subplot_titles=("가격대별 청산 대기 물량",
                                        "현재가로부터의 거리별 누적"))
    for g, col, nm in [(L, UP, "롱 청산"), (S, DN, "숏 청산")]:
        q = g[(g.liqPx > lo) & (g.liqPx < hi)]
        if not len(q):
            continue
        h, _ = np.histogram(q.liqPx, bins=bins, weights=q.notional / 1e6)
        fig.add_bar(x=h, y=ctr, orientation="h", name=nm, marker_color=col,
                    opacity=.88, width=(bins[1] - bins[0]) * .92,
                    hovertemplate=nm + " $%{x:.1f}M<br>$%{y:,.0f}<extra></extra>",
                    row=1, col=1)
    fig.add_hline(y=mark, line=dict(color="white", dash="dash", width=1.4),
                  annotation_text=f"현재 ${mark:,.0f}", annotation_position="right",
                  annotation_font=dict(size=12, color="white"), row=1, col=1)

    # 거리별 누적 (가격이 x% 움직이면 청산되는 물량)
    steps = np.arange(2.5, 45.1, 2.5)
    dn_cum = [L[(L.liqPx >= mark * (1 - s / 100)) & (L.liqPx < mark)].notional.sum() / 1e6
              for s in steps]
    up_cum = [S[(S.liqPx <= mark * (1 + s / 100)) & (S.liqPx > mark)].notional.sum() / 1e6
              for s in steps]
    fig.add_scatter(x=-steps, y=dn_cum, name="하락 시 롱청산", line=dict(color=UP, width=2.5),
                    fill="tozeroy", fillcolor="rgba(38,166,154,0.20)",
                    hovertemplate="하락 %{x:.1f}% → $%{y:.1f}M 청산<extra></extra>",
                    row=1, col=2)
    fig.add_scatter(x=steps, y=up_cum, name="상승 시 숏청산", line=dict(color=DN, width=2.5),
                    fill="tozeroy", fillcolor="rgba(239,83,80,0.20)",
                    hovertemplate="상승 %{x:.1f}% → $%{y:.1f}M 청산<extra></extra>",
                    row=1, col=2)
    fig.add_vline(x=0, line=dict(color="white", dash="dash", width=1.2), row=1, col=2)

    fig.update_layout(height=height, margin=dict(l=8, r=8, t=72, b=8),
                      barmode="overlay", bargap=.04,
                      legend=dict(orientation="h", yanchor="bottom", y=1.10, x=0,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
                      **BASE)
    fig.update_yaxes(gridcolor=GRID, tickformat=",.0f", row=1, col=1)
    fig.update_xaxes(gridcolor=GRID, title_text="$M", row=1, col=1)
    fig.update_yaxes(gridcolor=GRID, title_text="누적 $M", row=1, col=2)
    fig.update_xaxes(gridcolor=GRID, title_text="현재가 대비 %", ticksuffix="%",
                     row=1, col=2)
    return fig


def flow_chart(agg, height=300):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_scatter(x=agg.ts, y=agg.long_ntl / 1e6, name="롱 $M",
                    line=dict(color=UP, width=2.2), fill="tozeroy",
                    fillcolor="rgba(38,166,154,0.18)")
    fig.add_scatter(x=agg.ts, y=agg.short_ntl / 1e6, name="숏 $M",
                    line=dict(color=DN, width=2.2), fill="tozeroy",
                    fillcolor="rgba(239,83,80,0.18)")
    fig.add_scatter(x=agg.ts, y=agg.mark, name="가격",
                    line=dict(color="rgba(255,255,255,0.55)", width=1.4, dash="dot"),
                    secondary_y=True)
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=40, b=8),
                      title=dict(text="고래 롱/숏 명목가 추이", x=0.01,
                                 font=dict(size=15)),
                      legend=dict(orientation="h", y=1.02, x=0.3,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
                      **BASE)
    fig.update_yaxes(gridcolor=GRID, title_text="$M", secondary_y=False)
    fig.update_yaxes(showgrid=False, title_text="가격", secondary_y=True)
    fig.update_xaxes(gridcolor=GRID)
    return fig
