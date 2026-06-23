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
TOP_N      = 30
TIMEFRAMES = ['15m', '4H']
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

# ── 2. Inject tickers into index.html (AI-readable without JS) ───────────────
print('Injecting snapshot into index.html…')
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

snapshot_json = json.dumps(tickers, separators=(',', ':'))
replacement = (
    '<!-- OKX:TICKERS:START -->\n'
    f'<script type="application/json" id="okx-tickers">{snapshot_json}</script>\n'
    '<!-- OKX:TICKERS:END -->'
)
html_new = re.sub(
    r'<!-- OKX:TICKERS:START -->.*?<!-- OKX:TICKERS:END -->',
    replacement,
    html,
    flags=re.DOTALL
)
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_new)
print(f'  ✓ Embedded {len(tickers)} tickers into index.html')

# ── 3. Top USDT pairs by 24h volume ─────────────────────────────────────────
usdt = [t for t in tickers if t['instId'].endswith('-USDT')]
usdt.sort(key=lambda t: float(t.get('volCcy24h') or 0), reverse=True)
top_pairs = [t['instId'] for t in usdt[:TOP_N]]
print(f'  Top {TOP_N}: {", ".join(top_pairs[:5])} …')

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
                {'t': int(c[0]), 'o': c[1], 'h': c[2], 'l': c[3], 'c': c[4], 'v': c[5]}
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
print('Done.')
