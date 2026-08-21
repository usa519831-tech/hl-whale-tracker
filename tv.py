"""TradingView 위젯 임베드 + 타임프레임 매핑"""

# TradingView 표준 기간 → (위젯 interval 코드, 하이퍼리퀴드 candle interval, 기본 표시 봉수)
TF = {
    "1분":   ("1",   "1m",  240),
    "5분":   ("5",   "5m",  288),
    "15분":  ("15",  "15m", 192),
    "30분":  ("30",  "30m", 192),
    "1시간": ("60",  "1h",  168),
    "4시간": ("240", "4h",  180),
    "1일":   ("D",   "1d",  180),
    "1주":   ("W",   "1w",  104),
}
TF_ORDER = list(TF)

EXCHANGES = {
    "BINANCE 무기한": "BINANCE:{c}USDT.P",
    "BINANCE 현물":   "BINANCE:{c}USDT",
    "BYBIT 무기한":   "BYBIT:{c}USDT.P",
    "OKX 무기한":     "OKX:{c}USDT.P",
    "COINBASE":       "COINBASE:{c}USD",
    "HYPERLIQUID":    "HYPERLIQUID:{c}USD",
}


def tv_symbol(coin, exchange_label):
    return EXCHANGES.get(exchange_label, "BINANCE:{c}USDT.P").format(c=coin)


def widget_html(symbol, interval, height=620, theme="dark", studies=None):
    """TradingView Advanced Chart 위젯 HTML"""
    studies = studies or []
    st_json = "[" + ",".join(f'"{s}"' for s in studies) + "]"
    return f"""
<div class="tradingview-widget-container" style="height:{height}px;width:100%">
  <div id="tv_chart" style="height:{height}px;width:100%"></div>
</div>
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script type="text/javascript">
new TradingView.widget({{
  "container_id": "tv_chart",
  "autosize": true,
  "symbol": "{symbol}",
  "interval": "{interval}",
  "timezone": "Asia/Seoul",
  "theme": "{theme}",
  "style": "1",
  "locale": "kr",
  "toolbar_bg": "#0e1117",
  "enable_publishing": false,
  "hide_side_toolbar": false,
  "allow_symbol_change": true,
  "withdateranges": true,
  "details": true,
  "studies": {st_json},
  "backgroundColor": "#0e1117",
  "gridColor": "rgba(255,255,255,0.06)"
}});
</script>
"""
