#!/usr/bin/env python3
"""Small local discovery and evidence queue. No model, network, or background process."""
import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scan_links import frontmatter_fields, field_list

ROOT = Path(__file__).resolve().parent.parent
PAGE_DIRS = ('entities', 'concepts', 'comparisons', 'queries', 'maps', 'specs')
KINDS = {'discovered', 'applied', 'skipped', 'failed', 'gap', 'corrected', 'unreported', 'resolved'}


def pages(root=ROOT):
    result = []
    for directory in PAGE_DIRS:
        for path in sorted((root / directory).glob('*.md')):
            if path.name == 'query-log.md':
                continue
            text = path.read_text(encoding='utf-8')
            fields = {key: value for key, (value, _) in frontmatter_fields(text).items()}
            result.append(dict(path=path.relative_to(root).as_posix(),
                               title=fields.get('title', path.stem),
                               summary=fields.get('summary', ''),
                               aliases=field_list(text, 'aliases'),
                               canonical=fields.get('canonical', ''),
                               review_status=fields.get('review_status', ''),
                               verification_status=fields.get('verification_status', 'unchecked'),
                               revision=hashlib.sha256(path.read_bytes()).hexdigest(),
                               last_verified=fields.get('last_verified', ''),
                               verification_scope=fields.get('verification_scope', '')))
    return result


def route_rows(root=ROOT):
    for line in (root / 'maps/task-routing.md').read_text(encoding='utf-8').splitlines():
        if not line.startswith('| '):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) == 4 and '`' in cells[2]:
            yield dict(task=cells[0], terms=[s.strip() for s in cells[1].split('、')],
                       paths=re.findall(r'`([^`]+\.md)`', cells[2]), boundary=cells[3])


def discover(query, root=ROOT):
    query = query.casefold().strip()
    catalog = {p['path']: p for p in pages(root)}
    hits = {}

    def add(path, score, terms, boundary=''):
        if path not in catalog:
            return
        page = catalog[path]
        path = page['canonical'] or path
        if path not in catalog:
            return
        hit = hits.setdefault(path, dict(catalog[path], score=0, matched=[], boundary=[]))
        hit['score'] += score
        hit['matched'] = sorted(set(hit['matched'] + terms))
        if boundary and boundary not in hit['boundary']:
            hit['boundary'].append(boundary)

    for page in catalog.values():
        terms = [page['title'], Path(page['path']).stem] + page['aliases']
        found = [term for term in terms if len(term) >= 2 and term.casefold() in query]
        if found:
            add(page['path'], 20 + max(map(len, found)), found)
    for row in route_rows(root):
        found = [term for term in row['terms'] if len(term) >= 2 and term.casefold() in query]
        if found:
            for i, path in enumerate(row['paths']):
                add(path, 10 + min(max(map(len, found)), 10) - i, found, row['boundary'])
    result = sorted(hits.values(), key=lambda hit: (-hit['score'], hit['path']))[:3]
    for hit in result:
        for key in ('aliases', 'canonical', 'score'):
            hit.pop(key)
    return result


def index_text(root=ROOT):
    catalog = pages(root)
    lines = ['# Wiki Index', '', '> 由 `python scripts/wiki.py index --write` 从页面元数据生成；请修改页面的 title / summary / aliases，不手改本表。',
             '> 知识是候选证据；draft 不代表用户已审定。任务发现使用 maps/task-routing.md 或 discover 命令。', '']
    for directory in PAGE_DIRS:
        group = [p for p in catalog if p['path'].startswith(directory + '/')]
        if not group:
            continue
        lines += ['## ' + directory.title(), '']
        for page in group:
            lines.append(f"- [[{page['path'][:-3]}|{page['title']}]] — {page['summary']} · 检索词：{' / '.join(page['aliases'])}")
        lines.append('')
    lines += ['## 审计', '', '- [[queries/query-log|检索影响记录]] — 同批知识维护的使用证据；运行事件与待处理反馈用 `python scripts/wiki.py pending`。', '']
    return '\n'.join(lines)


def events(root=ROOT):
    result = []
    for path in sorted((root / '.local/events').glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        result.append(data)
    return sorted(result, key=lambda item: (item['at'], item['id']))


def valid_evidence(value, root):
    if re.match(r'^https://[^\s]+$', value):
        return True
    path = value.split('#', 1)[0]
    path = re.sub(r':\d+$', '', path)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.is_file()


def record(data, root=ROOT):
    """One immutable file per event; exclusive create makes retries/concurrent calls idempotent."""
    if not isinstance(data, dict):
        raise ValueError('Event must be a JSON object')
    data = dict(data)
    allowed = {'task', 'kind', 'page', 'impact', 'evidence', 'resolves'}
    if set(data) - allowed:
        raise ValueError('Unknown event fields')
    for field in ('task', 'kind'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError('Missing ' + field)
    if data['kind'] not in KINDS or len(data['task']) > 180:
        raise ValueError('Invalid kind/task')
    for field in ('page', 'impact', 'evidence', 'resolves'):
        data.setdefault(field, '')
        if not isinstance(data[field], str) or len(data[field]) > 1200:
            raise ValueError('Invalid or oversized ' + field)
    if data['page']:
        page = (root / data['page']).resolve()
        if not page.is_relative_to(root.resolve()) or data['page'] not in {p['path'] for p in pages(root)}:
            raise ValueError('Page must be an existing maintainable knowledge page')
    if data['kind'] in {'applied', 'failed', 'gap', 'corrected', 'resolved'}:
        if not data['impact'].strip() or not valid_evidence(data['evidence'], root):
            raise ValueError('An impact and a locatable evidence file/HTTPS URL are required')
    if data['kind'] == 'resolved':
        target = next((e for e in events(root) if e['id'] == data['resolves']), None)
        if not target or target['kind'] not in {'failed', 'gap', 'corrected', 'unreported'}:
            raise ValueError('Resolution must reference an existing feedback event')
    elif data['resolves']:
        raise ValueError('Only a resolution can close feedback')
    # Do not accept credentials or full transcripts into the compact queue.
    if re.search(r'(?i)bearer\s+\S+|sk-[a-z0-9_-]{16,}|(?:api[_-]?key|password|token)\s*[:=]\s*\S{8,}', ' '.join(data.values())):
        raise ValueError('Possible secret: record a redacted evidence locator instead')
    data['page_revision'] = hashlib.sha256((root / data['page']).read_bytes()).hexdigest() if data['page'] else ''
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
    event_id = hashlib.sha256(encoded.encode()).hexdigest()[:24]
    output = dict(data, id=event_id, at=datetime.now(timezone.utc).isoformat())
    folder = root / '.local/events'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (event_id + '.json')
    # Write fully before publishing, so a concurrent reader never sees partial JSON.
    temporary = folder / (event_id + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    try:
        os.link(temporary, target)
    except FileExistsError:
        pass
    finally:
        temporary.unlink()
    return json.loads(target.read_text(encoding='utf-8'))


def pending(root=ROOT):
    all_events = events(root)
    resolved = {e['resolves'] for e in all_events if e['kind'] == 'resolved'}
    reported = {e['task'] for e in all_events if e['kind'] in {'applied', 'skipped', 'failed', 'gap', 'corrected'}}
    return [e for e in all_events if e['kind'] in {'failed', 'gap', 'corrected', 'unreported'}
            and e['id'] not in resolved and not (e['kind'] == 'unreported' and e['task'] in reported)]


def stats(root=ROOT):
    all_events = events(root)
    discovery_tasks = {e['task'] for e in all_events if e['kind'] == 'discovered'}
    outcomes = {e['task'] for e in all_events if e['kind'] in {'applied', 'skipped', 'failed', 'gap', 'corrected'}}
    return dict(observed_discovery_tasks=len(discovery_tasks), reported_tasks=len(discovery_tasks & outcomes),
                pending=len(pending(root)), events=len(all_events),
                note='Only observed events; not a recall rate or proof of improved task quality.')


def check_sources(root=ROOT, accept_new=False):
    """Freeze normalized text/binary digests; never accept a changed or deleted old source."""
    manifest = root / 'maps/source-inventory.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    current = {}
    for path in sorted((root / 'raw').rglob('*')):
        if path.is_file() and path.name != '.gitkeep':
            content = path.read_text(encoding='utf-8').encode() if path.suffix == '.md' else path.read_bytes()
            current[path.relative_to(root).as_posix()] = hashlib.sha256(content).hexdigest()
    changed = [path for path, digest in previous.items() if current.get(path) != digest]
    new = sorted(set(current) - set(previous))
    if changed:
        raise ValueError('Raw evidence changed or disappeared: ' + ', '.join(changed))
    if new and accept_new:
        manifest.write_text(json.dumps(current, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    elif new:
        raise ValueError('New sources need an authorized intake inventory: ' + ', '.join(new))
    return dict(sources=len(current), accepted_new=len(new) if accept_new else 0,
                note='Baseline detects later changes; it does not authenticate historical capture or old embedded hashes. Markdown SHA256 uses UTF-8 with LF line endings.')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('discover', help='Read-only bounded discovery, return at most three candidates')
    search.add_argument('query')
    index = sub.add_parser('index', help='Check or regenerate the derived index')
    index.add_argument('--write', action='store_true')
    sub.add_parser('record', help='Read one JSON evidence event from stdin')
    sub.add_parser('pending', help='Read-only unresolved feedback')
    sub.add_parser('stats', help='Read-only observed event counts')
    sources = sub.add_parser('sources', help='Check immutable raw evidence against the inventory')
    sources.add_argument('--accept-new', action='store_true', help='Authorized intake only: add new sources, never overwrite old digests')
    args = parser.parse_args()
    if args.command == 'discover':
        print(json.dumps(discover(args.query), ensure_ascii=False, indent=2))
    elif args.command == 'index':
        expected = index_text()
        if args.write:
            (ROOT / 'index.md').write_text(expected, encoding='utf-8', newline='\n')
        elif (ROOT / 'index.md').read_text(encoding='utf-8') != expected:
            parser.exit(1, 'index.md is stale; run index --write within a Wiki maintenance batch\n')
        print('index: OK')
    else:
        try:
            result = check_sources(accept_new=args.accept_new) if args.command == 'sources' else record(json.load(sys.stdin)) if args.command == 'record' else pending() if args.command == 'pending' else stats()
        except (ValueError, OSError) as error:
            parser.exit(1, str(error) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
