# claude-compte

Local token usage analytics dashboard for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Parses your `~/.claude/projects/` session files and serves an interactive dashboard — all data stays on your machine.

## What it shows

- **Overview** — GitHub-style usage heatmap, daily token chart, model breakdown donut
- **Projects** — token usage per project with session/turn counts and API-equivalent cost
- **Sessions** — best/worst efficiency rankings, clickable session detail modals
- **Tools** — tool usage frequency across all sessions
- **Optimize** — actionable tips based on your usage patterns (cache efficiency, session length, model choice, etc.)

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/your-username/claude-compte.git
cd claude-compte
uv venv && uv pip install -e .
```

## Usage

```bash
# Start the dashboard (opens browser automatically)
uv run claude-compte

# Custom port
uv run claude-compte --port 8080

# Don't open browser
uv run claude-compte --no-open
```

The dashboard will be available at `http://localhost:3456` (or your chosen port).

## How it works

1. Scans `~/.claude/projects/*/` for `.jsonl` session files
2. Deduplicates streaming entries by `message.id` (last-write-wins)
3. Extracts token usage (input, cache write, cache read, output), model, tools, and thinking blocks
4. Aggregates by session, day, model, and project
5. Caches parsed results in `~/.claude/compte-cache.json` for fast reloads
6. Serves a FastAPI backend on localhost with a single-page dashboard frontend

## Project structure

```
claude-compte/
├── pyproject.toml
├── .python-version
└── src/claude_compte/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py          # CLI: --port, --no-open
    ├── server.py       # FastAPI app, /api/usage endpoint
    ├── parser.py       # JSONL parsing, dedup, aggregation
    ├── optimizer.py    # Usage optimization tips
    └── static/
        ├── index.html  # Dashboard SPA
        └── chart.min.js
```

## Privacy

All data is read locally from `~/.claude/` and served only on `127.0.0.1`. Nothing leaves your machine.
