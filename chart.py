"""가격 차트 + 고래 진입/청산 + 청산 지도"""
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

API = "https://api.hyperliquid.xyz/info"
# TradingView 기본 다크 테마 색상
UP, DN = "#26a69a", "#ef5350"
UP_F, DN_F = "rgba(38,166,154,0.45)", "rgba(239,83,80,0.45)"
WHITE, GOLD = "#e8e8e8", "#ffd54f"
BG, GRID = "#131722", "#2A2E39"
TXT, CROSS = "#B2B5BE", "#758696"
BASE = dict(template="plotly_dark", font=dict(color=TXT, size=12),
            paper_bgcolor=BG, plot_bgcolor=BG)


# 마커 묶음용 floor 주기 (pandas 고정주기만 허용 — W 는 D 로 대체)
_FLOOR = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
          "1h": "1h", "4h": "4h", "1d": "D", "1w": "D"}

_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
        "4h": 14400, "1d": 86400, "1w": 604800}


def candles(coin, interval="1h", bars=168):
    """interval 은 하이퍼리퀴드 표기( 1m/5m/15m/30m/1h/4h/1d/1w )"""
    now = int(time.time() * 1000)
    span = _SEC.get(interval, 3600) * bars * 1000
    r = requests.post(API, json={"type": "candleSnapshot", "req": {
        "coin": coin, "interval": interval,
        "startTime": now - span, "endTime": now}}, timeout=30)
    r.raise_for_status()
    d = pd.DataFrame(r.json())
    if d.empty:
        return d
    d["t"] = pd.to_datetime(d.t, unit="ms", utc=True)
    for c in ["o", "h", "l", "c", "v"]:
        d[c] = d[c].astype(float)
    return d


def _size(v, lo=7, hi=19):
    v = np.asarray(v, dtype=float)
    if len(v) == 0 or np.nanmax(v) <= 0:
        return np.full(len(v), lo)
    return lo + np.sqrt(v / np.nanmax(v)) * (hi - lo)


def price_chart(coin, cd, ev, pos, mark, height=640, freq="1h"):
    """TradingView 스타일 캔들 + 거래량 + 고래 진입/청산 마커"""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.78, 0.22], vertical_spacing=0.02)

    fig.add_candlestick(
        x=cd.t, open=cd.o, high=cd.h, low=cd.l, close=cd.c,
        increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
        decreasing=dict(line=dict(color=DN, width=1), fillcolor=DN),
        name=coin, showlegend=False,
        hovertext=[f"O {o:,.1f}  H {h:,.1f}  L {l:,.1f}  C {c:,.1f}"
                   for o, h, l, c in zip(cd.o, cd.h, cd.l, cd.c)],
        hoverinfo="text+x", row=1, col=1)

    # 거래량 (캔들 방향 색상)
    vcol = np.where(cd.c >= cd.o, UP_F, DN_F)
    fig.add_bar(x=cd.t, y=cd.v, marker_color=vcol, marker_line_width=0,
                name="거래량", showlegend=False,
                hovertemplate="거래량 %{y:,.1f}<extra></extra>", row=2, col=1)

    lo, hi = cd.l.min(), cd.h.max()
    pad = (hi - lo) * 0.07

    # ── 고래 마커 ──
    if ev is not None and len(ev):
        e = ev[ev.ts >= cd.t.min()].copy()
        if len(e):
            e["ntl"] = e.delta.abs() * e.mark
            e["slot"] = e.ts.dt.floor(_FLOOR.get(freq, "1h"))
            e["grp"] = np.where(e.kind.isin(["OPEN", "ADD"]), "진입", "청산")
            g = (e.groupby(["slot", "side", "grp"])
                   .agg(ntl=("ntl", "sum"), n=("addr", "nunique"),
                        sz=("delta", "sum"), px=("mark", "first")).reset_index())
            g = g.merge(cd[["t", "h", "l"]], left_on="slot", right_on="t", how="left")
            g["h"] = g.h.fillna(g.px); g["l"] = g.l.fillna(g.px)

            for grp, side, sym, col, nm, off in [
                    ("진입", "LONG", "triangle-up", UP, "롱 진입", -0.28),
                    ("청산", "LONG", "x", WHITE, "롱 청산/축소", -0.72),
                    ("진입", "SHORT", "triangle-down", DN, "숏 진입", +0.28),
                    ("청산", "SHORT", "x", GOLD, "숏 청산/축소", +0.72)]:
                q = g[(g.grp == grp) & (g.side == side)]
                if q.empty:
                    continue
                y = (q.l if off < 0 else q.h) + pad * off
                fig.add_scatter(
                    x=q.slot, y=y, mode="markers", name=nm,
                    marker=dict(symbol=sym, size=_size(q.ntl), color=col,
                                line=dict(width=1.2, color=BG)),
                    customdata=np.c_[q.n, q.ntl / 1e6, q.sz.round(2)],
                    hovertemplate=("<b>" + nm + "</b><br>"
                                   "고래 %{customdata[0]}명 · $%{customdata[1]:.2f}M<br>"
                                   "순변화 %{customdata[2]} " + coin + "<extra></extra>"),
                    row=1, col=1)

    # ── 고래 평균 진입가 ──
    if pos is not None and len(pos):
        for g2, col, nm in [(pos[pos.szi > 0], UP, "롱 평균"),
                            (pos[pos.szi < 0], DN, "숏 평균")]:
            if not len(g2):
                continue
            w = (g2.entryPx * g2.szi.abs()).sum() / g2.szi.abs().sum()
            if lo - pad < w < hi + pad:
                fig.add_hline(y=w, line=dict(color=col, dash="dot", width=1.2),
                              row=1, col=1)
                fig.add_annotation(x=1.001, xref="paper", y=w, yref="y",
                                   text=f" {nm} {w:,.0f}", showarrow=False,
                                   xanchor="left", font=dict(size=10, color=BG),
                                   bgcolor=col, borderpad=2)

    # ── 마지막 가격선 + 배지 (TradingView 방식) ──
    last_up = cd.c.iloc[-1] >= cd.o.iloc[-1]
    lc = UP if last_up else DN
    fig.add_hline(y=mark, line=dict(color=lc, dash="dash", width=1), row=1, col=1)
    fig.add_annotation(x=1.001, xref="paper", y=mark, yref="y",
                       text=f" {mark:,.1f} ", showarrow=False, xanchor="left",
                       font=dict(size=11, color="#fff"), bgcolor=lc, borderpad=3)

    o, h, l, c = cd.o.iloc[-1], cd.h.iloc[-1], cd.l.iloc[-1], cd.c.iloc[-1]
    chg = (c / o - 1) * 100
    fig.add_annotation(
        x=0, y=1, xref="paper", yref="paper", xanchor="left", yanchor="bottom",
        showarrow=False, align="left", font=dict(size=12, color=TXT),
        text=(f"<b>{coin}</b>  ·  {freq}    "
              f"O <span style='color:{lc}'>{o:,.1f}</span>  "
              f"H <span style='color:{lc}'>{h:,.1f}</span>  "
              f"L <span style='color:{lc}'>{l:,.1f}</span>  "
              f"C <span style='color:{lc}'>{c:,.1f}</span>  "
              f"<span style='color:{lc}'>{chg:+.2f}%</span>"))

    fig.update_layout(
        height=height, margin=dict(l=6, r=104, t=44, b=6),
        hovermode="x unified", dragmode="pan", bargap=0.15,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.42,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        hoverlabel=dict(bgcolor="#1e222d", bordercolor=GRID,
                        font=dict(color=TXT, size=11)),
        xaxis_rangeslider_visible=False, **BASE)

    # TradingView식 축: 우측 가격축 + 십자선
    fig.update_yaxes(side="right", gridcolor=GRID, zeroline=False,
                     showspikes=True, spikemode="across", spikethickness=1,
                     spikedash="dot", spikecolor=CROSS,
                     range=[lo - pad, hi + pad], tickformat=",.0f", row=1, col=1)
    fig.update_yaxes(side="right", gridcolor=GRID, zeroline=False,
                     showticklabels=True, nticks=3, row=2, col=1)
    fig.update_xaxes(gridcolor=GRID, showspikes=True, spikemode="across",
                     spikethickness=1, spikedash="dot", spikecolor=CROSS,
                     rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(gridcolor=GRID, showspikes=True, spikemode="across",
                     spikethickness=1, spikedash="dot", spikecolor=CROSS, row=2, col=1)
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
