#!/usr/bin/env python3
"""LLM WIKI 链接健康扫描：报告所有未解析的 wikilinks、markdown 链接与 sources。

用法（在仓库任意位置）：
    python scripts/scan_links.py            # 打印报告，退出码恒为 0
    python scripts/scan_links.py --strict   # 可维护层存在未解析引用时退出码 1

约定：
- 只读扫描，不修改任何文件；修复动作由 agent 人工判断后进行并登记 log.md
- raw/ 与历史记录的问题只报告，不阻断严格模式
- 忽略围栏代码块与行内代码中的 [[示例]]，避免把语法演示当链接
"""

import re
import shlex
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".obsidian", ".local", "node_modules", "__pycache__", ".trash"}
HISTORY_FILES = {"log.md", "queries/query-log.md"}  # 只追加的审计文件
READONLY_DIRS = {"raw"}

FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
WIKILINK_RE = re.compile(r"!?\[\[([^\[\]]+)\]\]")
MDLINK_RE = re.compile(r"\[[^\[\]\n]*\]\((<[^>]+>|[^)\s]+)(?:\s+[\"'][^\n]*?[\"'])?\)")
SOURCES_RE = re.compile(r"^sources\s*:\s*(.*)$")
BLOCK_ITEM_RE = re.compile(r"^\s+-\s*(.*?)\s*$")
FIELD_RE = re.compile(r"^([a-z_][a-z0-9_-]*)\s*:\s*(.*?)\s*$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVIEWED_TYPES = {"entity", "concept", "comparison", "project", "summary", "spec"}
REVIEW_STATUSES = {"draft", "reviewed"}


def strip_code(text: str) -> str:
    text = FENCE_RE.sub(lambda match: '\n' * match.group().count('\n'), text)
    return INLINE_CODE_RE.sub(lambda match: ' ' * len(match.group()), text)


def split_target(raw: str) -> str | None:
    """'页面\\|别名' / '页面|别名' / '页面#标题' / '#标题' -> 页面名（无别名/锚点），同页锚点返回 None"""
    target = re.split(r"\\?\|", raw)[0].strip().rstrip("\\")
    target = target.split("#", 1)[0].strip()
    return target or None


def frontmatter_sources(text: str) -> list[tuple[str, int]]:
    """读取 YAML frontmatter 中的 sources，支持行内列表与缩进块列表。"""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return []

    for i, line in enumerate(lines[1:end], 1):
        match = SOURCES_RE.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if value.startswith("[") and "]" in value:
            lexer = shlex.shlex(value[1 : value.rfind("]")], posix=True)
            lexer.whitespace = ","
            lexer.whitespace_split = True
            lexer.commenters = ""
            return [(item.strip(), i + 1) for item in lexer if item.strip()]
        if value:
            return [(value.strip("'\""), i + 1)]

        sources = []
        for j in range(i + 1, end):
            item = BLOCK_ITEM_RE.match(lines[j])
            if not item:
                if lines[j].strip():
                    break
                continue
            source = item.group(1).split(" #", 1)[0].strip().strip("'\"")
            if source:
                sources.append((source, j + 1))
        return sources
    return []


def frontmatter_fields(text: str) -> dict[str, tuple[str, int]]:
    """读取 frontmatter 的顶层标量字段，值保留为文本。"""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}

    fields = {}
    for i, line in enumerate(lines[1:end], 1):
        match = FIELD_RE.match(line)
        if not match:
            continue
        value = match.group(2).split(" #", 1)[0].strip().strip("'\"")
        fields[match.group(1).lower()] = (value, i + 1)
    return fields


def field_list(text: str, field: str) -> list[str]:
    without_sources = re.sub(r'^sources\s*:.*(?:\n[ \t]+-.*)*', '', text, flags=re.M)
    renamed = re.sub(r'^' + re.escape(field) + r'\s*:', 'sources:', without_sources, flags=re.M)
    return [value for value, _ in frontmatter_sources(renamed)]


def metadata_issues(text: str, rel: str = 'concepts/example.md', allowed_tags=None) -> list[tuple[str, int]]:
    """Validate maintainable pages, not raw snapshots or append-only history."""
    if rel.split('/')[0] not in {'entities', 'concepts', 'comparisons', 'queries', 'maps', 'specs'} or rel in HISTORY_FILES:
        return []
    fields = frontmatter_fields(text)
    page_type, type_line = fields.get("type", ("", 1))
    issues = []
    for key in ('title', 'created', 'updated', 'type', 'tags', 'sources', 'summary', 'aliases'):
        if key not in fields or (key not in {'tags', 'sources', 'aliases'} and not fields[key][0]):
            issues.append((f'{key} 缺失', 1))
    for key in ('tags', 'sources', 'aliases', 'verification_evidence'):
        if key in fields:
            value, line = fields[key]
            if value and not (value.startswith('[') and value.endswith(']')):
                issues.append((f'{key} 必须为列表', line))
    if page_type not in REVIEWED_TYPES | {'query'}:
        issues.append((f'type 非法：{page_type or "<empty>"}', type_line))
    for key in ('created', 'updated', 'last_verified'):
        if key not in fields:
            continue
        value, line = fields[key]
        try:
            if not DATE_RE.fullmatch(value) or date.fromisoformat(value) > date.today():
                raise ValueError(value)
        except ValueError:
            issues.append((f'{key} 非法或为未来日期：{value}', line))
    if 'created' in fields and 'updated' in fields and fields['created'][0] > fields['updated'][0]:
        issues.append(('updated 早于 created', fields['updated'][1]))
    if not field_list(text, 'aliases'):
        issues.append(('aliases 至少包含一个检索别名', fields.get('aliases', ('', 1))[1]))
    if allowed_tags is not None:
        for tag in field_list(text, 'tags'):
            if tag not in allowed_tags:
                issues.append((f'未登记 tag：{tag}', fields.get('tags', ('', 1))[1]))
    confidence = fields.get('confidence', ('', 1))[0]
    if confidence and confidence not in {'high', 'medium', 'low'}:
        issues.append(('confidence 非法', fields['confidence'][1]))
    if page_type != 'query' and len(frontmatter_sources(text)) <= 1 and not confidence:
        issues.append(('单一/缺失来源必须标 confidence', 1))
    status = fields.get('verification_status', ('unchecked', 1))[0]
    if status not in {'unchecked', 'verified', 'stale'}:
        issues.append(('verification_status 非法', 1))
    if status == 'verified':
        for key in ('last_verified', 'verification_scope', 'verification_evidence'):
            if not fields.get(key, ('',))[0]:
                issues.append((f'verified 缺少 {key}', 1))
        if not field_list(text, 'verification_evidence'):
            issues.append(('verified 没有核验依据', 1))

    if page_type in REVIEWED_TYPES:
        review_status, review_line = fields.get("review_status", ("", type_line))
        if not review_status:
            issues.append((f"review_status 缺失（type: {page_type}）", review_line))
        elif review_status not in REVIEW_STATUSES:
            issues.append((f"review_status 非法：{review_status}", review_line))

    return issues


def is_actionable(rel: str) -> bool:
    """只有可维护层的引用缺口才应阻断严格模式。"""
    parts = rel.split("/")
    return rel not in HISTORY_FILES and parts[0] not in READONLY_DIRS and "_archive" not in parts


def build_index():
    """全库文件索引：无扩展名 basename 与相对路径（均小写）-> 真实相对路径"""
    by_base, by_path = set(), set()
    for p in ROOT.rglob("*"):
        if p.is_dir() or any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        rel = p.relative_to(ROOT).as_posix()
        by_base.add(p.stem.lower())
        by_path.add(rel.lower())
        by_path.add(Path(rel).with_suffix("").as_posix().lower())
    return by_base, by_path


def resolve(target: str, by_base: set, by_path: set) -> bool:
    t = target.replace("\\", "/").removeprefix("./").lower()
    return t in by_base or t in by_path


def routing_issues(root: Path):
    routing = root / 'maps/task-routing.md'
    if not routing.is_file():
        return [('任务路由入口缺失', 1)]
    issues = []
    for line, text in enumerate(routing.read_text(encoding='utf-8').splitlines(), 1):
        for target in re.findall(r'`((?:entities|concepts|comparisons|queries|specs)/[^`]+\.md)`', text):
            if not (root / target).is_file():
                issues.append(('路由目标缺失：' + target, line))
    return issues


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    by_base, by_path = build_index()
    schema = (ROOT / 'SCHEMA.md').read_text(encoding='utf-8')
    tag_heading = re.search(r'^## (?:Tags|Tag 分类)\s*$', schema, re.M)
    allowed_tags = None
    if tag_heading:
        tag_section = re.split(r'\n## ', schema[tag_heading.end():], maxsplit=1)[0]
        allowed_tags = set()
        for line in tag_section.splitlines():
            if not line.startswith('- ') or not re.search(r'[:：]', line):
                continue
            values = re.split(r'[:：]', line, maxsplit=1)[1]
            allowed_tags.update(tag.strip() for tag in re.split(r'[、,]', values) if tag.strip())
    alias_locations = defaultdict(list)
    canonical_targets = {}

    wiki_refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    md_refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    source_refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    metadata_refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for issue, line in routing_issues(ROOT):
        metadata_refs[issue].append(('maps/task-routing.md', line))
    n_files = n_links = 0

    for md in sorted(ROOT.rglob("*.md")):
        rel = md.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in md.relative_to(ROOT).parts):
            continue
        n_files += 1
        raw_text = md.read_text(encoding="utf-8", errors="replace")
        fields = frontmatter_fields(raw_text)
        for issue, line in metadata_issues(raw_text, rel, allowed_tags):
            metadata_refs[issue].append((rel, line))
        if rel.split('/')[0] in {'entities', 'concepts', 'comparisons', 'queries', 'maps', 'specs'} and rel not in HISTORY_FILES:
            for alias in field_list(raw_text, 'aliases'):
                alias_locations[alias.casefold()].append((rel, fields.get('canonical', (rel, 1))[0]))
        references = frontmatter_sources(raw_text)
        references += [(value, fields.get('verification_evidence', ('', 1))[1]) for value in field_list(raw_text, 'verification_evidence')]
        if 'canonical' in fields:
            references.append(fields['canonical'])
            canonical_targets[rel] = fields['canonical'][0]
        for source, line in references:
            if source.startswith(("http://", "https://", "mailto:")):
                continue
            n_links += 1
            if not (ROOT / source.split('#', 1)[0]).is_file():
                source_refs[source].append((rel, line))

        text = strip_code(raw_text)
        for m in WIKILINK_RE.finditer(text):
            target = split_target(m.group(1))
            if target is None:
                continue
            n_links += 1
            if not resolve(target, by_base, by_path):
                line = text[: m.start()].count("\n") + 1
                wiki_refs[target].append((rel, line))
        for m in MDLINK_RE.finditer(text):
            path = m.group(1).strip('<>').split('#', 1)[0]
            if not path or path.startswith(("http://", "https://", "mailto:")):
                continue
            n_links += 1
            candidates = [ROOT / path, md.parent / path]
            if not any(c.is_file() for c in candidates):
                line = text[: m.start()].count("\n") + 1
                md_refs[path].append((rel, line))

    for alias, locations in alias_locations.items():
        if len({canonical for _, canonical in locations}) > 1:
            metadata_refs['歧义 aliases：' + alias].extend((rel, 1) for rel, _ in locations)
    for origin in canonical_targets:
        target = canonical_targets[origin]
        if target.split('/')[0] not in {'entities', 'concepts', 'comparisons', 'queries', 'specs'}:
            metadata_refs['canonical 必须指向知识正文：' + target].append((origin, 1))
        seen, current = set(), origin
        while current in canonical_targets:
            if current in seen:
                metadata_refs['canonical 循环：' + origin].append((origin, 1))
                break
            seen.add(current)
            current = canonical_targets[current]
    print(f"扫描 {n_files} 个 md 文件，共 {n_links} 个链接")
    if not wiki_refs and not md_refs and not source_refs and not metadata_refs:
        print("✓ 全部链接可解析")
        return 0

    all_refs = (
        ("未解析 wikilinks", wiki_refs),
        ("未解析 markdown 链接", md_refs),
        ("未解析 frontmatter sources", source_refs),
        ("frontmatter 元数据问题", metadata_refs),
    )
    for title, refs in all_refs:
        if not refs:
            continue
        print(f"\n{title}（{len(refs)} 个目标）：")
        for target, locations in sorted(refs.items(), key=lambda kv: -len(kv[1])):
            nonactionable_only = not any(is_actionable(rel) for rel, _ in locations)
            flag = "  [仅历史记录/只读层，不修]" if nonactionable_only else ""
            print(f"  - {target}（{len(locations)} 处）{flag}")
            for rel, line in locations:
                print(f"      {rel}:{line}")

    actionable = any(
        is_actionable(rel)
        for _, refs in all_refs
        for locations in refs.values()
        for rel, _ in locations
    )
    return 1 if "--strict" in sys.argv and actionable else 0


if __name__ == "__main__":
    sys.exit(main())
