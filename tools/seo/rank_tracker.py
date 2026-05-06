# -*- coding: utf-8 -*-
"""
Rank tracker integrado al cron de reporte-marfil.

Cada vez que main.py corre:
  - Verifica si ya hay snapshot de HOY en seo/snapshots/
  - Si no, llama DataForSEO ranked_keywords y crea uno
  - Compara con el snapshot anterior y guarda seo/evolution.json
  - main.py lee seo/evolution.json y lo expone en dashboard.json

Idempotente: si snapshot del día ya existe, no hace nada (no consume créditos).

Costo DataForSEO: ~$0.05 por snapshot diario = ~$1.50/mes.

Endpoint usado: /v3/dataforseo_labs/google/ranked_keywords/live
"""
import os
import json
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# CTR table (Google avg by SERP position)
CTR = {1: 0.30, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
       6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018}


def ctr_for_position(pos):
    if pos is None:
        return 0
    if pos in CTR:
        return CTR[pos]
    if pos <= 10:
        return 0.018
    return 0.005


def _dfs_post(login, password, endpoint, payload):
    auth = base64.b64encode(f'{login}:{password}'.encode()).decode()
    url = f'https://api.dataforseo.com{endpoint}'
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': f'Basic {auth}',
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_rankings(domain, location_code, language, login, password, limit=200):
    payload = [{
        'target': domain,
        'location_code': location_code,
        'language_code': language,
        'limit': limit,
        'order_by': ['ranked_serp_element.serp_item.rank_group,asc'],
    }]
    result = _dfs_post(login, password, '/v3/dataforseo_labs/google/ranked_keywords/live', payload)
    tasks = result.get('tasks', [])
    if not tasks or tasks[0].get('status_code') != 20000:
        msg = tasks[0].get('status_message') if tasks else 'no tasks'
        logger.warning(f"DataForSEO ranked_keywords error: {msg}")
        return []
    items = tasks[0].get('result', [{}])[0].get('items', [])
    out = []
    for it in items:
        kd = it.get('keyword_data', {}) or {}
        info = kd.get('keyword_info', {}) or {}
        elem = it.get('ranked_serp_element', {}).get('serp_item', {}) or {}
        out.append({
            'keyword':  kd.get('keyword', ''),
            'position': elem.get('rank_group', 0),
            'volume':   info.get('search_volume', 0) or 0,
            'url':      elem.get('url', ''),
        })
    return out


def take_daily_snapshot(domain, snapshots_dir, login, password, location_code=2170, language='es'):
    """Take snapshot only if today's doesn't already exist."""
    today = datetime.now().strftime('%Y%m%d')
    snap_path = snapshots_dir / f'{today}.json'
    if snap_path.exists():
        logger.info(f"Snapshot for {today} already exists - skip API call")
        with open(snap_path, encoding='utf-8') as f:
            return json.load(f)
    if not login or not password:
        logger.warning("DataForSEO credentials missing - skipping rank tracker")
        return None

    logger.info(f"Taking new rank snapshot for {domain}...")
    rankings = fetch_rankings(domain, location_code, language, login, password)
    snapshot = {
        'date': today,
        'datetime': datetime.now().isoformat(),
        'domain': domain,
        'total_keywords': len(rankings),
        'rankings': rankings,
    }
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(f"Snapshot saved: {len(rankings)} keywords")
    return snapshot


def find_previous(snapshots_dir, current_date):
    if not snapshots_dir.exists():
        return None
    snapshots = sorted([p for p in snapshots_dir.glob('*.json') if p.stem != current_date])
    if not snapshots:
        return None
    with open(snapshots[-1], encoding='utf-8') as f:
        return json.load(f)


def compare(latest, previous):
    if previous is None:
        return None
    prev_map = {r['keyword']: r for r in previous['rankings']}
    cur_map  = {r['keyword']: r for r in latest['rankings']}

    keywords = []
    for kw, cur in cur_map.items():
        prev = prev_map.get(kw)
        cur_pos = cur.get('position', 999)
        cur_vol = cur.get('volume', 0) or 0
        cur_clicks = round(cur_vol * ctr_for_position(cur_pos))
        if prev is None:
            keywords.append({
                'keyword': kw, 'current_position': cur_pos, 'previous_position': None,
                'change': None, 'status': 'new', 'volume': cur_vol,
                'estimated_clicks_per_month': cur_clicks, 'url': cur.get('url',''),
            })
        else:
            prev_pos = prev.get('position', 999)
            change = prev_pos - cur_pos
            status = 'stable' if cur_pos == prev_pos else ('up' if cur_pos < prev_pos else 'down')
            keywords.append({
                'keyword': kw, 'current_position': cur_pos, 'previous_position': prev_pos,
                'change': change, 'status': status, 'volume': cur_vol,
                'estimated_clicks_per_month': cur_clicks, 'url': cur.get('url',''),
            })
    for kw, prev in prev_map.items():
        if kw not in cur_map:
            keywords.append({
                'keyword': kw, 'current_position': None,
                'previous_position': prev.get('position', 999), 'change': None,
                'status': 'lost', 'volume': prev.get('volume', 0) or 0,
                'estimated_clicks_per_month': 0, 'url': prev.get('url',''),
            })

    movements = {
        'up':     sum(1 for k in keywords if k['status']=='up'),
        'down':   sum(1 for k in keywords if k['status']=='down'),
        'stable': sum(1 for k in keywords if k['status']=='stable'),
        'new':    sum(1 for k in keywords if k['status']=='new'),
        'lost':   sum(1 for k in keywords if k['status']=='lost'),
    }
    total_now  = sum(k.get('estimated_clicks_per_month',0) for k in keywords if k['status']!='lost')
    total_prev = sum(round((prev_map[k['keyword']].get('volume',0) or 0) * ctr_for_position(prev_map[k['keyword']].get('position',999)))
                     for k in keywords if k['status']!='new' and k['keyword'] in prev_map)
    return {
        'snapshot_date': latest['date'],
        'previous_date': previous['date'],
        'total_keywords_now':  latest['total_keywords'],
        'total_keywords_prev': previous['total_keywords'],
        'movements': movements,
        'estimated_clicks': {
            'current_per_month':  total_now,
            'previous_per_month': total_prev,
            'delta':              total_now - total_prev,
        },
        'keywords': sorted(keywords, key=lambda k: -(k.get('volume',0) or 0)),
    }


def update_evolution(repo_root):
    """Main entry: take snapshot if needed, compare, save evolution.json."""
    seo_dir = repo_root / 'seo'
    snapshots_dir = seo_dir / 'snapshots'
    domain = os.environ.get('SEO_DOMAIN', 'modamarfil.com.co')
    location_code = int(os.environ.get('SEO_LOCATION_CODE', '2170'))
    language = os.environ.get('SEO_LANGUAGE', 'es')
    login = os.environ.get('DATAFORSEO_LOGIN', '')
    password = os.environ.get('DATAFORSEO_PASSWORD', '')

    latest = take_daily_snapshot(domain, snapshots_dir, login, password, location_code, language)
    if latest is None:
        return None

    previous = find_previous(snapshots_dir, latest['date'])
    if previous is None:
        evolution = {
            'snapshot_date': latest['date'],
            'previous_date': None,
            'total_keywords_now':  latest['total_keywords'],
            'total_keywords_prev': 0,
            'movements': {'up':0,'down':0,'stable':0,'new':latest['total_keywords'],'lost':0},
            'estimated_clicks': {
                'current_per_month':  sum(round((r.get('volume',0) or 0) * ctr_for_position(r.get('position',999))) for r in latest['rankings']),
                'previous_per_month': 0,
                'delta':              0,
            },
            'keywords': [
                {'keyword': r['keyword'], 'current_position': r.get('position'),
                 'previous_position': None, 'change': None, 'status': 'new',
                 'volume': r.get('volume', 0),
                 'estimated_clicks_per_month': round((r.get('volume',0) or 0) * ctr_for_position(r.get('position',999))),
                 'url': r.get('url','')}
                for r in latest['rankings']
            ],
        }
    else:
        evolution = compare(latest, previous)

    evo_path = seo_dir / 'evolution.json'
    seo_dir.mkdir(parents=True, exist_ok=True)
    with open(evo_path, 'w', encoding='utf-8') as f:
        json.dump(evolution, f, ensure_ascii=False, indent=2)
    logger.info(f"Evolution saved: {evolution['movements']}")
    return evolution
