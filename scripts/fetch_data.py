#!/usr/bin/env python3
"""
Fetches OKX spot market data and writes static JSON files.
Also embeds a ticker snapshot directly into index.html so AI/bots can
read data without JavaScript execution.
Run by GitHub Actions every 15 minutes.
"""
import json
import os
import re
import time
import urllib.request

BASE       = 'https://www.okx.com/api/v5'
TOP_N      = 200          # ranks 11-210 (skip top 10 mega-caps/stables)
RANK_START = 10           # 0-indexed → rank 11
TIMEFRAMES = ['5m', '15m', '1H', '4H', '1D']
LIMIT      = 300

os.makedirs('data/candles', exist_ok=True)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; okx-data-bot/1.0)'}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


# ── 1. Tickers ───────────────────────────────────────────────────────────────
print('Fetching tickers…')
raw = fetch(f'{BASE}/market/tickers?instType=SPOT')
assert raw['code'] == '0', f"Tickers error: {raw.get('msg')}"

tickers = [
    {
        'instId':    t['instId'],
        'last':      t['last'],
        'open24h':   t['open24h'],
        'high24h':   t['high24h'],
        'low24h':    t['low24h'],
        'volCcy24h': t.get('volCcy24h', '0'),
        'ts':        t['ts'],
    }
    for t in raw['data']
]

with open('data/tickers.json', 'w') as f:
    json.dump(tickers, f)
print(f'  ✓ {len(tickers)} tickers → data/tickers.json')

# ── 2. Inject tickers + noscript summary into index.html ─────────────────────
print('Injecting snapshot into index.html…')
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

snapshot_json = json.dumps(tickers, separators=(',', ':'))
ticker_block = (
    '<!-- OKX:TICKERS:START -->\n'
    f'<script type="application/json" id="okx-tickers">{snapshot_json}</script>\n'
    '<!-- OKX:TICKERS:END -->'
)
html = re.sub(
    r'<!-- OKX:TICKERS:START -->.*?<!-- OKX:TICKERS:END -->',
    ticker_block,
    html,
    flags=re.DOTALL
)
print(f'  ✓ Embedded {len(tickers)} tickers into index.html')

# ── 3. Top USDT pairs by 24h volume ─────────────────────────────────────────
usdt = [t for t in tickers if t['instId'].endswith('-USDT')]
usdt.sort(key=lambda t: float(t.get('volCcy24h') or 0), reverse=True)
top_pairs = [t['instId'] for t in usdt[RANK_START:RANK_START + TOP_N]]
print(f'  Ranks {RANK_START+1}-{RANK_START+TOP_N}: {", ".join(top_pairs[:5])} …')

# ── 3b. Inject noscript AI-readable summary ───────────────────────────────────
import datetime as _dt
ts_str = _dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
lines = [
    f'OKX Spot Market — Static Snapshot  (updated: {ts_str})',
    '',
    'Data endpoints (no JavaScript needed):',
    '  Tickers    : https://solihunas.github.io/okx/data/tickers.json',
    '  H4  OHLCV  : https://solihunas.github.io/okx/data/h4.json   ← 200 pairs × 200 candles H4',
    '  M15 OHLCV  : https://solihunas.github.io/okx/data/m15.json  ← 200 pairs × 200 candles M15',
    '  Candles    : https://solihunas.github.io/okx/data/candles/{{instId}}-{{bar}}.json',
    '  Index      : https://solihunas.github.io/okx/data/index.json',
    '',
    f'Ranks {RANK_START+1}-{RANK_START+TOP_N} USDT pairs by 24h volume (showing first 30):',
    f'{"Pair":<18} {"Price":>14} {"24h%":>8} {"Vol24h(USDT)":>20}',
    '-' * 64,
]
usdt_map = {t['instId']: t for t in usdt}
for inst in top_pairs[:30]:
    t = usdt_map[inst]
    try:
        price  = float(t['last'])
        open_  = float(t['open24h'])
        chg    = (price - open_) / open_ * 100 if open_ else 0
        vol    = float(t.get('volCcy24h') or 0)
        lines.append(f'{inst:<18} {price:>14.6g} {chg:>+7.2f}% {vol:>20,.0f}')
    except Exception:
        lines.append(inst)
summary_text = '\n'.join(lines)
noscript_replacement = (
    '<!-- OKX:NOSCRIPT:START -->\n'
    f'<noscript><pre id="okx-static-summary">\n{summary_text}\n</pre></noscript>\n'
    '<!-- OKX:NOSCRIPT:END -->'
)
html = re.sub(
    r'<!-- OKX:NOSCRIPT:START -->.*?<!-- OKX:NOSCRIPT:END -->',
    noscript_replacement,
    html,
    flags=re.DOTALL
)
print('  ✓ Updated noscript summary in index.html')

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('  ✓ index.html written')

# ── 4. Candles for each top pair ─────────────────────────────────────────────
available = {}
errors    = []

for inst in top_pairs:
    for bar in TIMEFRAMES:
        try:
            url = f'{BASE}/market/candles?instId={inst}&bar={bar}&limit={LIMIT}'
            raw = fetch(url)
            if raw['code'] != '0' or not raw.get('data'):
                continue
            candles = [
                {'t': int(c[0]), 'o': c[1], 'h': c[2], 'l': c[3], 'c': c[4],
                 'v': c[5], 'vc': c[6] if len(c) > 6 else '0'}
                for c in reversed(raw['data'])
            ]
            fname = f'{inst}-{bar}.json'
            with open(f'data/candles/{fname}', 'w') as f:
                json.dump(candles, f)
            available.setdefault(inst, []).append(bar)
            time.sleep(0.12)
        except Exception as e:
            errors.append(f'{inst}/{bar}: {e}')

if errors:
    print(f'  Errors: {errors}')
print(f'  ✓ Candles for {len(available)} pairs × {TIMEFRAMES}')

# ── 5. Index ──────────────────────────────────────────────────────────────────
index = {
    'updated':   int(time.time() * 1000),
    'note':      'Static JSON updated every 15 min by GitHub Actions. No JavaScript needed.',
    'endpoints': {
        'tickers': 'https://solihunas.github.io/okx/data/tickers.json',
        'candles': 'https://solihunas.github.io/okx/data/candles/{instId}-{bar}.json',
        'index':   'https://solihunas.github.io/okx/data/index.json',
    },
    'available_candles': available,
}
with open('data/index.json', 'w') as f:
    json.dump(index, f, indent=2)
print('  ✓ data/index.json written.')

# ── 6. Aggregate all candles into data/candles/all.json ──────────────────────
print('Building data/candles/all.json…')
all_candles = {}
for fname in sorted(os.listdir('data/candles')):
    if fname.endswith('.json') and fname != 'all.json':
        key = fname[:-5]   # strip .json  →  e.g. "BTC-USDT-15m"
        with open(f'data/candles/{fname}', 'r') as f:
            all_candles[key] = json.load(f)

aggregate = {
    'generated': int(time.time() * 1000),
    'pairs':     all_candles,
}
with open('data/candles/all.json', 'w') as f:
    json.dump(aggregate, f)
print(f'  ✓ all.json: {len(all_candles)} keys written.')

# ── 7. H4 and M15 aggregate files (AI-readable, compact array format) ─────────
print('Building data/h4.json and data/m15.json…')
for tf_label, tf_fname in [('4H', 'h4'), ('15m', 'm15')]:
    pairs_data = {}
    for inst in top_pairs:
        fpath = f'data/candles/{inst}-{tf_label}.json'
        if os.path.exists(fpath):
            with open(fpath) as f:
                candles = json.load(f)
            # Compact array: [ts_ms, open, high, low, close, vol_base, vol_usdt]
            # Take last 200 candles (most recent), oldest-first order
            pairs_data[inst] = [
                [c['t'], c['o'], c['h'], c['l'], c['c'], c['v'], c.get('vc', '0')]
                for c in candles[-200:]
            ]
    out = {
        'generated':  int(time.time() * 1000),
        'timeframe':  tf_label,
        'candles':    200,
        'pairs_count': len(pairs_data),
        'fields':     ['timestamp_ms', 'open', 'high', 'low', 'close', 'volume_base', 'volume_usdt'],
        'note':       f'OKX spot {tf_label} OHLCV. 200 pairs ranked 11-210 by USDT volume. Updated every 15 min.',
        'pairs':      pairs_data,
    }
    outfile = f'data/{tf_fname}.json'
    with open(outfile, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    size_kb = os.path.getsize(outfile) // 1024
    print(f'  ✓ {outfile}: {len(pairs_data)} pairs × 200 candles ({size_kb} KB)')

print('Done.')
