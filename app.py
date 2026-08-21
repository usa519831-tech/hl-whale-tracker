#!/usr/bin/env python3
"""하이퍼리퀴드 고래 추적 대시보드 (Streamlit)"""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

import chart as ch
import tv

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


@st.cache_data(ttl=20)
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


@st.cache_data(ttl=3600)
def top_accounts(min_value, cap):
    """수집기가 저장한 상위 계정 캐시를 우선 사용 (36MB 다운로드 회피)"""
    p = os.path.join(DATA, "leaderboard_top.csv")
    if os.path.exists(p):
        df = pd.read_csv(p)
    else:
        rows = requests.get(LB, timeout=180).json()["leaderboardRows"]
        df = pd.DataFrame([{"addr": x["ethAddress"], "av": float(x["accountValue"])}
                           for x in rows])
    df = df.sort_values("av", ascending=False)
    return df[df.av >= min_value].head(cap)


@st.cache_data(ttl=25, show_spinner="고래 포지션 조회 중…")
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
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(one, addrs):
            res.extend(r)
    return pd.DataFrame(res)


@st.cache_data(ttl=180, show_spinner=False)
def get_candles(coin, interval, bars):
    try:
        return ch.candles(coin, interval, bars)
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
mode = c3.radio("데이터", ["수집된 이력 (빠름)", "실시간 조회"], horizontal=True,
                help="수집된 이력은 30분마다 자동 저장된 스냅샷이라 즉시 열립니다. "
                     "실시간 조회는 지금 이 순간을 보지만 10초 안팎 걸립니다.")

m = ctx.get(coin, {})
mark = m.get("mark", np.nan)

AUTO = {"끄기": 0, "30초": 30, "1분": 60, "3분": 180, "5분": 300}
if mode == "실시간 조회":
    a1, a2 = st.columns([1, 4])
    sec = AUTO[a1.selectbox("자동 갱신", list(AUTO), index=2)]
    if sec:
        n = st_autorefresh(interval=sec * 1000, key="auto")
        a2.caption(f"⟳ {sec}초마다 자동 갱신 중 · 이번 세션 {n}회 · "
                   f"{pd.Timestamp.now(tz='Asia/Seoul'):%H:%M:%S} 기준 "
                   "(브라우저 탭이 열려 있는 동안만 동작합니다)")
    acc = top_accounts(minv, 800)
    pos = live_positions(tuple(acc.addr.tolist()), coin)
    st.caption(f"실시간 · 대상 계정 {len(acc):,}개 · 합계 \\${acc.av.sum()/1e9:.2f}B")
else:
    pos = load_csv(f"positions_{coin}.csv")
    if not pos.empty:
        age = (pd.Timestamp.now(tz="UTC") - pos.ts.max()).total_seconds() / 60
        st.caption(f"수집 스냅샷 · {pos.ts.max():%m-%d %H:%M} UTC ({age:.0f}분 전) "
                   f"· 5분마다 자동 수집")

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
k[1].metric("추적 고래", f"{pos.addr.nunique()}명", delta_color="off", delta=
            f"OI의 {pos.szi.abs().sum()/m.get('oi',1)*100:.1f}%")
k[2].metric("롱", f"${ln/1e6:,.0f}M",
            f"{len(L)}명 · 미실현 ${L.upnl.sum()/1e6:+.1f}M", delta_color="off")
k[3].metric("숏", f"${sn/1e6:,.0f}M",
            f"{len(Sh)}명 · 미실현 ${Sh.upnl.sum()/1e6:+.1f}M", delta_color="off")
k[4].metric("롱 비중", f"{ln/(ln+sn)*100:.1f}%" if ln+sn else "-",
            f"순 {pos.szi.sum():+,.1f} {coin}", delta_color="off")

e1, e2 = st.columns(2)
# 손익 부호는 방향 기준: 롱은 (현재/진입-1), 숏은 그 반대
e1.metric("롱 가중평균 진입가 · 손익", f"${wl:,.0f}" if wl == wl else "-",
          f"{(mark/wl-1)*100:+.2f}%" if wl == wl else None)
e2.metric("숏 가중평균 진입가 · 손익", f"${ws:,.0f}" if ws == ws else "-",
          f"{-(mark/ws-1)*100:+.2f}%" if ws == ws else None)

st.divider()

# ══ 차트 ══
cc = st.columns([1.1, 1.4, 2.5])
tf_label = cc[0].selectbox("기간", tv.TF_ORDER, index=tv.TF_ORDER.index("1시간"))
tv_iv, hl_iv, n_bars = tv.TF[tf_label]
ex_label = cc[1].selectbox("TradingView 거래소", list(tv.EXCHANGES))

tab1, tab2 = st.tabs(["TradingView 차트", "고래 진입/청산 마커"])

with tab1:
    sym = tv.tv_symbol(coin, ex_label)
    st.caption(f"심볼 `{sym}` · {tf_label} — 차트 안에서 지표·그림도구를 자유롭게 쓸 수 있습니다.")
    components.html(tv.widget_html(sym, tv_iv, height=620), height=640, scrolling=False)
    st.caption("‘Invalid symbol’ 이 뜨면 위에서 다른 거래소를 선택하세요. "
               "하이퍼리퀴드는 TradingView 미지원일 수 있습니다.")

with tab2:
    cd = get_candles(coin, hl_iv, n_bars)
    ev = load_csv(f"events_{coin}.csv")
    if cd.empty:
        st.warning("캔들 데이터를 불러오지 못했습니다.")
    else:
        st.plotly_chart(
            ch.price_chart(coin, cd, ev, pos, mark, freq=hl_iv),
            use_container_width=True,
            config={"scrollZoom": True, "displaylogo": False,
                    "doubleClick": "reset", "displayModeBar": True,
                    "modeBarButtonsToRemove": ["select2d", "lasso2d",
                                               "toggleSpikelines", "autoScale2d"],
                    "toImageButtonOptions": {"format": "png", "scale": 2}})
        st.caption("▲ 롱 진입 · ▼ 숏 진입 · ✕ 청산/축소 — 마커 크기 = 포지션 규모 · "
                   "가로 음영 = 청산 밀집 구간(진할수록 물량 많음) · 점선 = 고래 평균 진입가")
        st.caption("📱 모바일: 두 손가락으로 확대/축소, 한 손가락으로 이동, "
                   "두 번 탭하면 원래대로. PC: 스크롤로 확대, 드래그로 이동")

# ══ 하단 섹션 메뉴 ══
st.divider()
sec = st.tabs(["💥 청산 지도", "📈 명목가 추이", "🔔 변화 감지", "🐋 개별 고래"])

with sec[0]:
    lm = ch.liq_map(coin, pos, mark)
    if lm is not None:
        st.plotly_chart(lm, use_container_width=True,
                        config={"scrollZoom": True, "displaylogo": False,
                                "doubleClick": "reset", "displayModeBar": True,
                                "modeBarButtonsToRemove": ["select2d", "lasso2d",
                                                           "toggleSpikelines", "autoScale2d"],
                                "toImageButtonOptions": {"format": "png", "scale": 2}})
        dn = pos[(pos.szi > 0) & (pos.liqPx >= mark * 0.75) & (pos.liqPx < mark)].notional.sum()
        up = pos[(pos.szi < 0) & (pos.liqPx <= mark * 1.25) & (pos.liqPx > mark)].notional.sum()
        st.caption(f"현재가에서 **25% 하락** 시 롱 **\\${dn/1e6:,.0f}M** 청산 · "
                   f"**25% 상승** 시 숏 **\\${up/1e6:,.0f}M** 청산. "
                   "고래 대부분이 3~5배 저레버리지라 청산가가 멀리 있습니다.")


with sec[1]:
    agg = load_csv(f"agg_{coin}.csv")

    if len(agg) > 1:
        st.plotly_chart(ch.flow_chart(agg), use_container_width=True,
                        config={"scrollZoom": True, "displaylogo": False,
                                "doubleClick": "reset",
                                "modeBarButtonsToRemove": ["select2d", "lasso2d",
                                                           "toggleSpikelines", "autoScale2d"]})

        a0, a1 = agg.iloc[0], agg.iloc[-1]
        hrs = (a1.ts - a0.ts).total_seconds() / 3600
        d_px = (a1.mark / a0.mark - 1) * 100
        d_l = (a1.long_ntl / a0.long_ntl - 1) * 100 if a0.long_ntl else 0
        d_s = (a1.short_ntl / a0.short_ntl - 1) * 100 if a0.short_ntl else 0

        st.caption(f"측정 구간 {a0.ts:%m-%d %H:%M} ~ {a1.ts:%m-%d %H:%M} UTC ({hrs:.0f}시간) · "
                   f"스냅샷 {len(agg)}개")

        m = st.columns(4)
        m[0].metric("가격", f"${a1.mark:,.0f}", f"{d_px:+.2f}%")
        m[1].metric("롱 명목가", f"${a1.long_ntl/1e6:,.0f}M", f"{d_l:+.1f}%")
        m[2].metric("숏 명목가", f"${a1.short_ntl/1e6:,.0f}M", f"{d_s:+.1f}%")
        m[3].metric("실질 증감 (롱−숏)", f"{(d_l-d_px) - (d_s-d_px):+.1f}%p",
                    f"롱 {d_l-d_px:+.1f} · 숏 {d_s-d_px:+.1f}", delta_color="off")

        # 자동 해석
        net_l, net_s = d_l - d_px, d_s - d_px
        if abs(net_l - net_s) < 3:
            verdict = "양쪽이 비슷하게 움직였습니다 — 뚜렷한 쏠림 없음"
        elif net_s > net_l:
            verdict = (f"**숏이 롱보다 {net_s-net_l:.0f}%p 더 늘었습니다.** "
                       f"가격이 {'올랐는데도' if d_px > 0 else '내리는 가운데'} 숏이 붙고 있습니다")
        else:
            verdict = (f"**롱이 숏보다 {net_l-net_s:.0f}%p 더 늘었습니다.** "
                       f"가격이 {'오르는 흐름에 롱이 따라붙고' if d_px > 0 else '내렸는데도 롱이 들어오고'} 있습니다")
        st.info(f"📊 {verdict}")

        with st.expander("이 차트 읽는 법"):
            st.markdown(f"""
    **명목가(notional)** 는 `보유수량 × 현재가`입니다. 증거금이 아니라
    **실제 시장에 걸려 있는 금액**입니다.

    그래서 선이 올라가는 데는 두 가지 원인이 섞여 있습니다.

    1. 고래가 **포지션을 늘렸다** (진짜 신호)
    2. 수량은 그대로인데 **가격이 올라서** 명목가가 커졌다 (착시)

    둘을 가르려면 가격 변화를 빼야 합니다. 위 카드의 **실질 증감**이 그 값입니다.

    ```
    실질 증감 = 명목가 변화% − 가격 변화%
    ```

    현재 구간: 가격 {d_px:+.2f}% · 롱 명목 {d_l:+.1f}% → 실질 **{net_l:+.1f}%**
    　　　　　　　　　　　　　 숏 명목 {d_s:+.1f}% → 실질 **{net_s:+.1f}%**

    **같이 보면 좋은 것**

    - **미실현 손익** — 어느 쪽이 물려 있는지. 손실 중인데 명목가가 늘면 물타기입니다
    - **가중평균 진입가** — 오르고 있으면 더 높은 가격에 신규 진입이 계속 들어온다는 뜻
    - **전체 OI 대비 비중** — 고래가 시장에서 차지하는 몫. 이게 커지면 개미가 빠지고 고래가 채우는 국면

    **주의**

    명목가는 **조회 대상 고래 수**에 비례합니다. 계정 규모 기준(`$10M+` / `$5M+`)을
    바꾸면 값이 통째로 달라지므로, 추이를 볼 때는 같은 기준으로 모인 구간만 비교하세요.
    수집기는 항상 `$5M` 기준으로 저장합니다.
    """)
    elif len(agg) == 1:
        st.info("스냅샷이 1개뿐입니다. 5분마다 자동 수집되니 잠시 후 추이가 나타납니다.")
    else:
        st.info("수집된 이력이 아직 없습니다.")


with sec[2]:
    ev = load_csv(f"events_{coin}.csv")
    if len(ev):
        # 롱/숏 증감을 부호 전환까지 정확히 분해
        _dl = np.maximum(ev.szi, 0) - np.maximum(ev.szi_prev, 0)
        _ds = np.maximum(-ev.szi, 0) - np.maximum(-ev.szi_prev, 0)
        lv = (_dl * ev.mark) / 1e6
        sv = (_ds * ev.mark) / 1e6
        l_up, l_dn = lv[lv > 0].sum(), -lv[lv < 0].sum()
        s_up, s_dn = sv[sv > 0].sum(), -sv[sv < 0].sum()
        l_net, s_net = l_up - l_dn, s_up - s_dn
        gross = l_up + s_up

        f = st.columns(4)
        f[0].metric("롱 증가", f"${l_up:,.0f}M", f"감소 ${l_dn:,.0f}M", delta_color="off")
        f[1].metric("숏 증가", f"${s_up:,.0f}M", f"감소 ${s_dn:,.0f}M", delta_color="off")
        f[2].metric("롱 순증감", f"${l_net:+,.0f}M",
                    f"신규 매수 비중 {l_up/gross*100:.0f}%" if gross else "-",
                    delta_color="off")
        f[3].metric("숏 순증감", f"${s_net:+,.0f}M",
                    f"신규 매도 비중 {s_up/gross*100:.0f}%" if gross else "-",
                    delta_color="off")

        # 롱 vs 숏 신규 진입 비율 막대
        if gross > 0:
            lp = l_up / gross * 100
            st.markdown(
                f"""<div style="display:flex;height:26px;border-radius:5px;overflow:hidden;
                     font-size:12px;font-weight:600;margin:2px 0 10px 0">
                  <div style="width:{lp:.1f}%;background:#26a69a;color:#0e1117;
                       display:flex;align-items:center;justify-content:center">
                       롱 {lp:.0f}%</div>
                  <div style="width:{100-lp:.1f}%;background:#ef5350;color:#0e1117;
                       display:flex;align-items:center;justify-content:center">
                       숏 {100-lp:.0f}%</div>
                </div>""", unsafe_allow_html=True)
            if abs(lp - 50) < 5:
                st.caption("↔ 신규 진입이 롱·숏 비슷하게 갈렸습니다")
            elif lp > 50:
                st.caption(f"↑ 신규 진입 금액의 {lp:.0f}%가 **롱** 쪽입니다")
            else:
                st.caption(f"↓ 신규 진입 금액의 {100-lp:.0f}%가 **숏** 쪽입니다")

        fb = ch.flow_bars(ev)
        if fb is not None:
            st.plotly_chart(fb, use_container_width=True,
                            config={"scrollZoom": True, "displaylogo": False,
                                    "doubleClick": "reset",
                                    "modeBarButtonsToRemove": ["select2d", "lasso2d",
                                                               "toggleSpikelines",
                                                               "autoScale2d"]})

        st.caption(f"직전 스냅샷 대비 \\$100K 이상 변화만 기록 · 총 {len(ev):,}건 · "
                   "OPEN 신규진입 · ADD 증액 · REDUCE 감액 · CLOSE 전량청산 · FLIP 방향전환")
        e = ev.sort_values("ts", ascending=False).head(40).copy()
        e["시각"] = e.ts.dt.strftime("%m-%d %H:%M")
        e["지갑"] = e.addr.str[:10] + ".."
        e["변화"] = e.delta.round(3)
        e["규모$M"] = (e.delta.abs() * e.mark / 1e6).round(2)
        e["가격"] = e.mark.round(1)
        # 저장된 라벨이 부호 전환을 놓친 경우 보정
        e.loc[(e.szi_prev * e.szi < 0) & (e.szi_prev != 0) & (e.szi != 0), "kind"] = "FLIP"
        st.dataframe(e[["시각", "지갑", "kind", "side", "변화", "규모$M", "가격"]]
                     .rename(columns={"kind": "유형", "side": "방향"}),
                     width="stretch", hide_index=True, height=380)
    else:
        st.info("아직 감지된 변화가 없습니다. 스냅샷이 2개 이상 쌓이면 나타납니다.")


with sec[3]:
    st.caption(f"명목가 상위 30명 · 조회된 고래 {pos.addr.nunique()}명 중")
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
