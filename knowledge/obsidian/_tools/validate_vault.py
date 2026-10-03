#!/usr/bin/env python3
"""Validate links, evidence fields, units, and non-cash classification offline."""
import datetime
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'_data/manifest.json').read_text())
sources = {s['id']:s for s in json.loads((root/'_data/sources.json').read_text())}
deals = json.loads((root/'_data/deals.json').read_text())
files = list(root.rglob('*.md'))
names = {p.stem for p in files}
errors=[]
for p in files:
    t=p.read_text()
    if p.name != 'README.md' and not t.startswith('---\n'):
        errors.append(f'Missing frontmatter: {p.relative_to(root)}')
    for link in re.findall(r'\[\[([^]|#]+)',t):
        if link not in names: errors.append(f'Broken link {link}: {p.relative_to(root)}')
    if '\u2014' in t: errors.append(f'Em dash: {p.relative_to(root)}')
for n in manifest['notes']:
    if not (root/n['path']).is_file(): errors.append('Missing note: '+n['path'])
    if not set(n['source_ids']) <= set(sources): errors.append('Unknown note source: '+n['id'])
seen=set()
for d in deals:
    if d['id'] in seen: errors.append('Duplicate deal ID: '+d['id'])
    seen.add(d['id'])
    if d['reported_gain_usd'] <= 0: errors.append('Non-positive selected gain: '+d['id'])
    if d['realized_irr'] is not None or d['realized_cash_profit_usd'] is not None:
        errors.append('Unsupported cash-return field: '+d['id'])
    if d['cost_basis_usd'] is not None: errors.append('Unsupported basis: '+d['id'])
    if not set(d['source_ids']) <= set(sources): errors.append('Unknown source: '+d['id'])
    if not (root/d['note_path']).is_file(): errors.append('Missing case: '+d['id'])
    if d['closing_date']:
        try: datetime.date.fromisoformat(d['closing_date'])
        except ValueError: errors.append('Invalid closing date: '+d['id'])
        if d['date_precision'] != 'day': errors.append('Date precision mismatch: '+d['id'])
    if d['transaction_type']=='joint_venture_non_cash_contribution':
        if d['disclosed_value_type']!='deemed_contribution_value' or d['evidence_status']!='completed_non_cash_contribution_positive_reported_gain':
            errors.append('Non-cash classification mismatch: '+d['id'])
    if d['transaction_type']=='joint_venture_interest_sale' and d['gain_scope']!='seller_share':
        errors.append('JV gain scope missing: '+d['id'])
    if d['source_ids']==['slg2021jv'] and d['disclosed_value_type']!='gross_whole_asset_valuation':
        errors.append('Whole-asset valuation mislabeled: '+d['id'])
if manifest['topic_count']!=len([n for n in manifest['notes'] if n['kind']=='operational_knowledge']):errors.append('Topic count mismatch')
if manifest['deal_count']!=len(deals): errors.append('Deal count mismatch')
if len(seen)!=53: errors.append('Expected curated evidence records changed; review source selection')
if errors:
    print('\n'.join(errors))
    raise SystemExit(1)
print(json.dumps({'status':'passed','markdown_files':len(files),'topics':manifest['topic_count'],'templates':manifest['template_count'],'transaction_records':len(deals),'primary_sources':len(sources),'unresolved_wikilinks':0,'unsupported_cash_profit_or_irr':0},indent=2))
