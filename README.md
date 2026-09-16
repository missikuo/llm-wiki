# LLM Wiki Skeleton

> An agent-oriented local knowledge-base skeleton. It separates distilled knowledge, immutable evidence, derived navigation, and local runtime state.

[中文](#中文) · [English](#english)

## 中文

### 这是什么

这是一个面向任务执行 Agent 的本地知识库骨架，而不是某个具体人的知识内容发布包。它提供目录约定、可检索 Markdown 元数据、只读发现工具和最小治理规则；请在自己的副本中添加知识页与原始证据。

仓库有意不包含个人偏好、项目记录、原始资料、运行事件、Obsidian 设置或本地路径。

### 快速开始

需要 Python 和 PowerShell。克隆后在仓库根目录执行：

```powershell
& .\scripts\wiki.ps1 discover "任务目标或症状"
python .\scripts\wiki.py index --write
python .\scripts\scan_links.py --strict
```

先在 `entities/`、`concepts/`、`comparisons/`、`queries/` 或 `specs/` 新增带 YAML frontmatter 的 Markdown 页面，再运行 `index --write` 生成导航。

### 结构

| 位置 | 用途 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Agent 的启动、发现与停止约定 |
| [`SCHEMA.md`](SCHEMA.md) | 内容、元数据和写入治理的事实源 |
| `entities/`、`concepts/`、`comparisons/`、`queries/`、`specs/` | 经提炼的知识页 |
| `raw/` | 不可改写的原始证据 |
| `maps/`、[`index.md`](index.md) | 任务路由与派生索引 |
| `scripts/` | 发现、索引、事件与链接检查工具 |
| `.obsidian/`、`.local/` | 本地状态；由 `.gitignore` 排除 |

### 边界

- 当前用户指令、实际系统事实与时效性官方来源优先于 Wiki 内容。
- Wiki 页面是背景和证据，不是外部写入或权限变更的授权。
- `raw/` 摄入后保持不可改写；运行事件应保留在 `.local/`。
- 公开复用前请自行选择许可证；本仓库未附带许可证。

## English

### What is this?

This is a local knowledge-base skeleton for task-executing agents, not a publication of any one person's knowledge. It provides directory conventions, discoverable Markdown metadata, read-only discovery tools, and minimal governance. Add your own knowledge pages and source evidence in your copy.

The repository intentionally excludes personal preferences, project records, raw source material, runtime events, Obsidian settings, and local paths.

### Quick start

Python and PowerShell are required. From the repository root after cloning, run:

```powershell
& .\scripts\wiki.ps1 discover "task goal or symptom"
python .\scripts\wiki.py index --write
python .\scripts\scan_links.py --strict
```

Create Markdown pages with YAML frontmatter in `entities/`, `concepts/`, `comparisons/`, `queries/`, or `specs/`, then run `index --write` to generate navigation.

### Layout

| Location | Purpose |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Agent bootstrap, discovery, and stopping conventions |
| [`SCHEMA.md`](SCHEMA.md) | Source of truth for content, metadata, and write governance |
| `entities/`, `concepts/`, `comparisons/`, `queries/`, `specs/` | Distilled knowledge pages |
| `raw/` | Immutable source evidence |
| `maps/`, [`index.md`](index.md) | Task routing and derived index |
| `scripts/` | Discovery, indexing, event, and link-checking tools |
| `.obsidian/`, `.local/` | Local state excluded by `.gitignore` |

### Boundaries

- Current user instructions, facts from the live system, and time-sensitive official sources take precedence over Wiki content.
- Wiki pages are context and evidence, not authorization for external writes or permission changes.
- Keep captured `raw/` material immutable and runtime events inside `.local/`.
- Choose a license before enabling public reuse; this repository does not include one.
