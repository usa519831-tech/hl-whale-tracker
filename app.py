#!/usr/bin/env python3
"""하이퍼리퀴드 고래 추적 대시보드 (Streamlit)"""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import chart as ch

API = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

st.set_page_config("고래 추적", "🐋", layout="wide")

GREEN, RED, GREY = "#26a69a", "#ef5350", "#8b8b8b"


def post(body, tries=3):
    for k in range(tries):
        try:
            r = requests.post(API, json=body, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception:
            if k == tries - 1:
                return None
    return None


@st.cache_data(ttl=120)
def market_ctx():
    j = post({"type": "metaAndAssetCtxs"})
    if not j:
        return {}
    meta, ctx = j
    return {u["name"]: {"mark": float(ctx[i]["markPx"]),
                        "oi": float(ctx[i]["openInterest"]),
                        "funding": float(ctx[i]["funding"]),
                        "prevDay": float(ctx[i]["prevDayPx"])}
            for i, u in enumerate(meta["universe"])}


@st.cache_data(ttl=1800)
def top_accounts(min_value, cap):
    rows = requests.get(LB, timeout=180).json()["leaderboardRows"]
    df = pd.DataFrame([{"addr": x["ethAddress"], "av": float(x["accountValue"])}
                       for x in rows]).sort_values("av", ascending=False)
    return df[df.av >= min_value].head(cap)


@st.cache_data(ttl=300, show_spinner="고래 포지션 조회 중…")
def live_positions(addrs, coin):
    def one(a):
        j = post({"type": "clearinghouseState", "user": a})
        if not j:
            return []
        av = float(j.get("marginSummary", {}).get("accountValue", 0))
        out = []
        for p in j.get("assetPositions", []):
            q = p["position"]
            if q["coin"] != coin or float(q["szi"]) == 0:
                continue
            out.append({"addr": a, "av": av, "szi": float(q["szi"]),
                        "entryPx": float(q["entryPx"] or np.nan),
                        "notional": float(q["positionValue"]),
                        "upnl": float(q["unrealizedPnl"]),
                        "liqPx": float(q["liquidationPx"] or np.nan),
                        "lev": q["leverage"]["value"]})
        return out
    res = []
    with ThreadPoolExecutor(6) as ex:
        for r in ex.map(one, addrs):
            res.extend(r)
    return pd.DataFrame(res)


@st.cache_data(ttl=180, show_spinner=False)
def get_candles(coin, days):
    try:
        return ch.candles(coin, "1h", days)
    except Exception:
        return pd.DataFrame()


def load_csv(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return pd.DataFrame()
    d = pd.read_csv(p)
    if "ts" in d:
        d["ts"] = pd.to_datetime(d.ts, utc=True, format="mixed")
    return d


# ─────────────────────────── UI ───────────────────────────
st.title("🐋 하이퍼리퀴드 고래 포지션 추적")

ctx = market_ctx()
coins = [c for c in ["BTC", "ETH", "SOL"] if c in ctx] or sorted(ctx)[:3]

c1, c2, c3 = st.columns([1, 1, 2])
coin = c1.selectbox("종목", coins)
minv = c2.selectbox("계정 규모", [("$10M+", 10e6), ("$5M+", 5e6), ("$1M+", 1e6)],
                    format_func=lambda x: x[0])[1]
mode = c3.radio("데이터", ["실시간 조회", "수집된 이력"], horizontal=True)

m = ctx.get(coin, {})
mark = m.get("mark", np.nan)

if mode == "실시간 조회":
    acc = top_accounts(minv, 800)
    st.caption(f"대상 계정 {len(acc):,}개 · 합계 ${acc.av.sum()/1e9:.2f}B")
    pos = live_positions(tuple(acc.addr.tolist()), coin)
else:
    pos = load_csv(f"positions_{coin}.csv")
    if not pos.empty:
        st.caption(f"최종 수집 {pos.ts.max():%Y-%m-%d %H:%M} UTC")

if pos.empty:
    st.warning("포지션 데이터가 없습니다. 수집기를 먼저 실행하세요.")
    st.stop()

L, Sh = pos[pos.szi > 0], pos[pos.szi < 0]
ln, sn = L.notional.sum(), Sh.notional.sum()
wl = (L.entryPx * L.szi).sum() / L.szi.sum() if len(L) else np.nan
ws = (Sh.entryPx * Sh.szi.abs()).sum() / Sh.szi.abs().sum() if len(Sh) else np.nan

k = st.columns(5)
k[0].metric(f"{coin} 현재가", f"${mark:,.0f}",
            f"{(mark/m.get('prevDay', mark)-1)*100:+.2f}% (24h)")
k[1].metric("추적 고래", f"{pos.addr.nunique()}명",
            f"OI의 {pos.szi.abs().sum()/m.get('oi',1)*100:.1f}%")
k[2].metric("롱", f"${ln/1e6:,.0f}M", f"{len(L)}명 · 미실현 ${L.upnl.sum()/1e6:+.1f}M")
k[3].metric("숏", f"${sn/1e6:,.0f}M", f"{len(Sh)}명 · 미실현 ${Sh.upnl.sum()/1e6:+.1f}M")
k[4].metric("롱 비중", f"{ln/(ln+sn)*100:.1f}%" if ln+sn else "-",
            f"순 {pos.szi.sum():+,.1f} {coin}")

e1, e2 = st.columns(2)
# 손익 부호는 방향 기준: 롱은 (현재/진입-1), 숏은 그 반대
e1.metric("롱 가중평균 진입가", f"${wl:,.0f}" if wl == wl else "-",
          f"손익 {(mark/wl-1)*100:+.2f}%" if wl == wl else "")
e2.metric("숏 가중평균 진입가", f"${ws:,.0f}" if ws == ws else "-",
          f"손익 {-(mark/ws-1)*100:+.2f}%" if ws == ws else "")

st.divider()

# ══ 가격 차트 + 고래 진입/청산 ══
h1, h2 = st.columns([4, 1])
h1.subheader("가격 · 고래 진입/청산 지점")
days = h2.select_slider("기간", [3, 7, 14, 30], value=14,
                        format_func=lambda d: f"{d}일", label_visibility="collapsed")
cd = get_candles(coin, days)
ev = load_csv(f"events_{coin}.csv")

if cd.empty:
    st.warning("캔들 데이터를 불러오지 못했습니다.")
else:
    st.plotly_chart(ch.price_chart(coin, cd, ev, pos, mark), use_container_width=True)
    st.caption("▲ 롱 진입 · ▼ 숏 진입 · ✕ 청산/축소 — 마커 크기 = 포지션 규모 "
               "· 점선 = 고래 가중평균 진입가. 마우스를 올리면 고래 수와 금액이 나옵니다.")

# ══ 청산 지도 ══
st.subheader("청산 지도")
lm = ch.liq_map(coin, pos, mark)
if lm is not None:
    st.plotly_chart(lm, use_container_width=True)
    dn = pos[(pos.szi > 0) & (pos.liqPx >= mark * 0.75) & (pos.liqPx < mark)].notional.sum()
    up = pos[(pos.szi < 0) & (pos.liqPx <= mark * 1.25) & (pos.liqPx > mark)].notional.sum()
    st.caption(f"현재가에서 **25% 하락** 시 롱 **${dn/1e6:,.0f}M** 청산 · "
               f"**25% 상승** 시 숏 **${up/1e6:,.0f}M** 청산. "
               "고래 대부분이 3~5배 저레버리지라 청산가가 멀리 있습니다.")

# ── 이력 차트 ──
agg = load_csv(f"agg_{coin}.csv")
if len(agg) > 1:
    st.plotly_chart(ch.flow_chart(agg), use_container_width=True)
elif len(agg) == 1:
    st.info("스냅샷이 1개뿐입니다. 30분마다 자동 수집되니 잠시 후 추이가 나타납니다.")

# ── 이벤트 ──
ev = load_csv(f"events_{coin}.csv")
if len(ev):
    st.subheader("포지션 변화 감지")
    e = ev.sort_values("ts", ascending=False).head(40).copy()
    e["시각"] = e.ts.dt.strftime("%m-%d %H:%M")
    e["지갑"] = e.addr.str[:10] + ".."
    e["변화"] = e.delta.round(3)
    e["가격"] = e.mark.round(1)
    st.dataframe(e[["시각", "지갑", "kind", "side", "변화", "가격"]]
                 .rename(columns={"kind": "유형", "side": "방향"}),
                 width="stretch", hide_index=True, height=300)

# ── 개별 고래 ──
st.subheader("개별 고래 포지션")
t = pos.nlargest(30, "notional").copy()
t["방향"] = np.where(t.szi > 0, "롱", "숏")
t["수량"] = t.szi.abs().round(3)
t["손익%"] = (t.upnl / (t.notional - t.upnl) * 100).round(2)
t["청산까지%"] = ((t.liqPx / mark - 1) * 100).round(1)
t["명목$M"] = (t.notional/1e6).round(2)
t["미실현$K"] = (t.upnl/1e3).round(1)
t["자산$M"] = (t.av/1e6).round(1)
t["지갑"] = t.addr.str[:12] + ".."
st.dataframe(t[["지갑", "방향", "수량", "entryPx", "명목$M", "미실현$K",
                "손익%", "liqPx", "청산까지%", "lev", "자산$M"]]
             .rename(columns={"entryPx": "진입가", "liqPx": "청산가", "lev": "레버"}),
             width="stretch", hide_index=True, height=420)

st.caption("데이터: Hyperliquid 공개 API · 온체인 포지션이므로 실제 값입니다. "
           "투자 조언이 아닙니다.")
