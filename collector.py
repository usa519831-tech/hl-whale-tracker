#!/usr/bin/env python3
"""
하이퍼리퀴드 고래 포지션 스냅샷 수집기 (GitHub Actions cron 용)

실행할 때마다:
  1) 리더보드에서 자산 상위 계정 선별
  2) 각 계정의 포지션 조회
  3) 종목별 집계를 data/agg_{COIN}.csv 에 append
  4) 개별 포지션을 data/positions_{COIN}.csv 에 덮어쓰기 (최신 상태)
  5) 직전 스냅샷과 비교해 신규진입/청산을 data/events_{COIN}.csv 에 append

저장소 용량을 위해 집계는 append, 개별 포지션은 최신본만 유지합니다.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

API = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
COINS = [c.strip() for c in os.getenv("COINS", "BTC,ETH,SOL").split(",") if c.strip()]
MIN_VALUE = float(os.getenv("MIN_VALUE", "5e6"))
MAX_ACCOUNTS = int(os.getenv("MAX_ACCOUNTS", "800"))
WORKERS = int(os.getenv("WORKERS", "12"))

S = requests.Session()
S.headers.update({"Content-Type": "application/json"})


def post(body, tries=4):
    for k in range(tries):
        try:
            r = S.post(API, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(2.0 * (k + 1)); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if k == tries - 1:
                return None
            time.sleep(1.0 * (k + 1))
    return None


def leaderboard():
    r = S.get(LB, timeout=180)
    r.raise_for_status()
    rows = r.json()["leaderboardRows"]
    df = pd.DataFrame([{"addr": x["ethAddress"], "av": float(x["accountValue"])}
                       for x in rows])
    return df.sort_values("av", ascending=False)


def market_ctx():
    j = post({"type": "metaAndAssetCtxs"})
    if not j:
        raise SystemExit("metaAndAssetCtxs 실패")
    meta, ctx = j
    out = {}
    for i, u in enumerate(meta["universe"]):
        c = ctx[i]
        out[u["name"]] = {"mark": float(c["markPx"]),
                          "oi": float(c["openInterest"]),
                          "funding": float(c["funding"]),
                          "premium": float(c.get("premium") or 0)}
    return out


def fetch_all(addrs):
    rows = []
    def one(a):
        j = post({"type": "clearinghouseState", "user": a})
        if not j:
            return []
        av = float(j.get("marginSummary", {}).get("accountValue", 0))
        res = []
        for p in j.get("assetPositions", []):
            q = p["position"]
            szi = float(q["szi"])
            if szi == 0 or q["coin"] not in COINS:
                continue
            res.append({
                "addr": a, "av": av, "coin": q["coin"], "szi": szi,
                "entryPx": float(q["entryPx"]) if q.get("entryPx") else np.nan,
                "notional": float(q["positionValue"]),
                "upnl": float(q["unrealizedPnl"]),
                "liqPx": float(q["liquidationPx"]) if q.get("liquidationPx") else np.nan,
                "lev": q["leverage"]["value"], "levType": q["leverage"]["type"],
            })
        return res
    with ThreadPoolExecutor(WORKERS) as ex:
        for r in ex.map(one, addrs):
            rows.extend(r)
    return pd.DataFrame(rows)


def append_csv(path, df):
    """컬럼이 늘거나 줄어도 깨지지 않게 정렬해서 덧붙인다."""
    if df.empty:
        return
    if not os.path.exists(path):
        df.to_csv(path, index=False)
        return
    old = pd.read_csv(path)
    if list(old.columns) == list(df.columns):
        df.to_csv(path, mode="a", header=False, index=False)
    else:                       # 스키마가 바뀐 경우 전체 재작성
        pd.concat([old, df], ignore_index=True).to_csv(path, index=False)


def main():
    os.makedirs(DATA, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    print(f"[{ts:%Y-%m-%d %H:%M} UTC] 수집 시작  종목={COINS}  "
          f"기준 ${MIN_VALUE/1e6:.0f}M")

    lb = leaderboard()
    sel = lb[lb.av >= MIN_VALUE].head(MAX_ACCOUNTS)
    print(f"  대상 계정 {len(sel):,}개 (합계 ${sel.av.sum()/1e9:.2f}B)")

    # 앱이 36MB 리더보드를 매번 받지 않도록 상위 계정만 캐시
    sel.head(1500).to_csv(f"{DATA}/leaderboard_top.csv", index=False)

    ctx = market_ctx()
    pos = fetch_all(sel.addr.tolist())
    if pos.empty:
        print("  포지션 없음 — 종료"); return
    print(f"  포지션 {len(pos):,}건 / 고래 {pos.addr.nunique():,}명")

    for coin in COINS:
        c = pos[pos.coin == coin].copy()
        if c.empty:
            continue
        m = ctx.get(coin, {})
        mark, oi = m.get("mark", np.nan), m.get("oi", np.nan)
        L, Sh = c[c.szi > 0], c[c.szi < 0]

        agg = {
            "ts": ts.isoformat(), "coin": coin, "mark": mark, "oi": oi,
            # 표본 기준을 함께 기록 — 기준이 바뀌면 명목가 비교가 무의미해짐
            "min_value": MIN_VALUE, "n_accounts": len(sel),
            "funding": m.get("funding", np.nan), "premium": m.get("premium", np.nan),
            "n_whales": c.addr.nunique(), "n_long": len(L), "n_short": len(Sh),
            "long_sz": L.szi.sum(), "short_sz": -Sh.szi.sum(),
            "long_ntl": L.notional.sum(), "short_ntl": Sh.notional.sum(),
            "long_upnl": L.upnl.sum(), "short_upnl": Sh.upnl.sum(),
            "wavg_entry_long": (L.entryPx * L.szi).sum() / L.szi.sum() if len(L) else np.nan,
            "wavg_entry_short": (Sh.entryPx * Sh.szi.abs()).sum() / Sh.szi.abs().sum() if len(Sh) else np.nan,
            "net_sz": c.szi.sum(),
            "tracked_oi_pct": c.szi.abs().sum() / oi * 100 if oi else np.nan,
        }
        append_csv(f"{DATA}/agg_{coin}.csv", pd.DataFrame([agg]))

        # 변화 감지
        pth = f"{DATA}/positions_{coin}.csv"
        if os.path.exists(pth):
            prev = pd.read_csv(pth)
            m2 = c[["addr", "szi", "entryPx", "notional"]].merge(
                prev[["addr", "szi"]], on="addr", how="outer", suffixes=("", "_prev"))
            m2["szi"] = m2.szi.fillna(0.0)
            m2["szi_prev"] = m2.szi_prev.fillna(0.0)
            m2["delta"] = m2.szi - m2.szi_prev
            ch = m2[m2.delta.abs() * mark >= 100_000].copy()   # $100K 이상 변화만
            if not ch.empty:
                ch["kind"] = np.where(ch.szi_prev == 0, "OPEN",
                              np.where(ch.szi == 0, "CLOSE",
                              np.where(ch.szi.abs() > ch.szi_prev.abs(), "ADD", "REDUCE")))
                ch["side"] = np.where(ch.szi > 0, "LONG",
                              np.where(ch.szi < 0, "SHORT",
                              np.where(ch.szi_prev > 0, "LONG", "SHORT")))
                ch["ts"] = ts.isoformat(); ch["coin"] = coin; ch["mark"] = mark
                cols = ["ts", "coin", "addr", "kind", "side", "szi_prev", "szi",
                        "delta", "entryPx", "mark"]
                append_csv(f"{DATA}/events_{coin}.csv", ch[cols])
                print(f"  {coin}: 변화 {len(ch)}건 "
                      f"(신규 {int((ch.kind=='OPEN').sum())}, 청산 {int((ch.kind=='CLOSE').sum())})")

        c["ts"] = ts.isoformat()
        c.to_csv(pth, index=False)
        print(f"  {coin}: 롱 {len(L)}명 {L.notional.sum()/1e6:,.0f}M / "
              f"숏 {len(Sh)}명 {Sh.notional.sum()/1e6:,.0f}M  (OI의 {agg['tracked_oi_pct']:.1f}%)")

    # 용량 관리 — 집계 파일이 커지면 오래된 행부터 정리
    for coin in COINS:
        p = f"{DATA}/agg_{coin}.csv"
        if os.path.exists(p):
            d = pd.read_csv(p)
            if len(d) > 20000:
                d.tail(20000).to_csv(p, index=False)
        p = f"{DATA}/events_{coin}.csv"
        if os.path.exists(p):
            d = pd.read_csv(p)
            if len(d) > 50000:
                d.tail(50000).to_csv(p, index=False)
    print("완료")


if __name__ == "__main__":
    main()
