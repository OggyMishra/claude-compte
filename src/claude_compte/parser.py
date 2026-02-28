"""Core JSONL parsing, deduplication, and aggregation for Claude Code sessions."""

import json
import os
from pathlib import Path

# API-equivalent pricing per token
MODEL_PRICING = {
    "opus-4.5": {"input": 5 / 1e6, "output": 25 / 1e6, "cacheWrite": 6.25 / 1e6, "cacheRead": 0.50 / 1e6},
    "opus-4.6": {"input": 5 / 1e6, "output": 25 / 1e6, "cacheWrite": 6.25 / 1e6, "cacheRead": 0.50 / 1e6},
    "opus-4.0": {"input": 15 / 1e6, "output": 75 / 1e6, "cacheWrite": 18.75 / 1e6, "cacheRead": 1.50 / 1e6},
    "opus-4.1": {"input": 15 / 1e6, "output": 75 / 1e6, "cacheWrite": 18.75 / 1e6, "cacheRead": 1.50 / 1e6},
    "sonnet": {"input": 3 / 1e6, "output": 15 / 1e6, "cacheWrite": 3.75 / 1e6, "cacheRead": 0.30 / 1e6},
    "haiku-4.5": {"input": 1 / 1e6, "output": 5 / 1e6, "cacheWrite": 1.25 / 1e6, "cacheRead": 0.10 / 1e6},
    "haiku-3.5": {"input": 0.80 / 1e6, "output": 4 / 1e6, "cacheWrite": 1.00 / 1e6, "cacheRead": 0.08 / 1e6},
}


def get_pricing(model: str | None) -> dict:
    if not model:
        return MODEL_PRICING["sonnet"]
    m = model.lower()
    if "opus" in m:
        if "4-6" in m or "4.6" in m:
            return MODEL_PRICING["opus-4.6"]
        if "4-5" in m or "4.5" in m:
            return MODEL_PRICING["opus-4.5"]
        if "4-1" in m or "4.1" in m:
            return MODEL_PRICING["opus-4.1"]
        return MODEL_PRICING["opus-4.0"]
    if "sonnet" in m:
        return MODEL_PRICING["sonnet"]
    if "haiku" in m:
        if "4-5" in m or "4.5" in m:
            return MODEL_PRICING["haiku-4.5"]
        return MODEL_PRICING["haiku-3.5"]
    return MODEL_PRICING["sonnet"]


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _cache_path() -> Path:
    return _claude_dir() / "compte-cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _cache_path().write_text(json.dumps(cache))
    except Exception:
        pass


def _cache_key(file_path: str) -> str | None:
    try:
        stat = os.stat(file_path)
        return f"{file_path}:{stat.st_mtime_ns}:{stat.st_size}"
    except Exception:
        return None


def parse_jsonl_file(file_path: str) -> dict:
    """Read a JSONL file, deduplicate by message.id (last-write-wins), return assistant entries + user messages."""
    message_map: dict[str, dict] = {}
    user_messages: list[dict] = []

    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            if entry.get("isSidechain"):
                continue
            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            msg = entry.get("message")
            if not msg:
                continue

            if entry_type == "user" and msg.get("role") == "user":
                user_messages.append(entry)

            if entry_type == "assistant" and msg.get("id"):
                message_map[msg["id"]] = entry

    return {"assistantEntries": list(message_map.values()), "userMessages": user_messages}


def extract_session_data(assistant_entries: list[dict], user_messages: list[dict]) -> list[dict]:
    """Pair user prompts with assistant responses, extract token usage."""
    queries = []

    user_timeline = []
    for e in user_messages:
        if e.get("isMeta"):
            continue
        content = e.get("message", {}).get("content")
        if isinstance(content, str) and (
            content.startswith("<local-command") or content.startswith("<command-name")
        ):
            continue
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        else:
            text = None
        user_timeline.append({
            "text": text or None,
            "timestamp": e.get("timestamp"),
            "uuid": e.get("uuid"),
        })

    user_idx = 0

    for entry in assistant_entries:
        msg = entry.get("message", {})
        usage = msg.get("usage")
        if not usage:
            continue

        model = msg.get("model", "unknown")
        if model == "<synthetic>":
            continue

        # Find most recent user message before this assistant response
        while (
            user_idx < len(user_timeline) - 1
            and user_timeline[user_idx + 1]["timestamp"] is not None
            and entry.get("timestamp") is not None
            and user_timeline[user_idx + 1]["timestamp"] <= entry["timestamp"]
        ):
            user_idx += 1
        user_msg = user_timeline[user_idx] if user_idx < len(user_timeline) else None

        pricing = get_pricing(model)
        input_tokens = usage.get("input_tokens", 0)
        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens

        cost = (
            input_tokens * pricing["input"]
            + cache_creation_tokens * pricing["cacheWrite"]
            + cache_read_tokens * pricing["cacheRead"]
            + output_tokens * pricing["output"]
        )

        tools = []
        has_thinking = False
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "tool_use" and block.get("name"):
                    tools.append(block["name"])
                if block.get("type") == "thinking":
                    has_thinking = True

        queries.append({
            "messageId": msg.get("id"),
            "userPrompt": user_msg["text"] if user_msg else None,
            "userTimestamp": user_msg["timestamp"] if user_msg else None,
            "assistantTimestamp": entry.get("timestamp"),
            "model": model,
            "inputTokens": input_tokens,
            "cacheCreationTokens": cache_creation_tokens,
            "cacheReadTokens": cache_read_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
            "cost": cost,
            "tools": tools,
            "hasThinking": has_thinking,
        })

    return queries


def _empty_result() -> dict:
    return {
        "sessions": [],
        "dailyUsage": [],
        "modelBreakdown": [],
        "topPrompts": [],
        "projects": [],
        "toolStats": [],
        "totals": {
            "totalTokens": 0, "totalInput": 0, "totalOutput": 0,
            "totalCacheCreation": 0, "totalCacheRead": 0, "totalCost": 0,
            "totalSessions": 0, "totalQueries": 0, "totalThinkingTurns": 0,
            "cacheHitRate": 0, "avgTokensPerSession": 0, "avgTokensPerQuery": 0,
        },
    }


def parse_all_sessions(force_refresh: bool = False) -> dict:
    claude_dir = _claude_dir()
    projects_dir = claude_dir / "projects"

    if not projects_dir.exists():
        return _empty_result()

    cache = {} if force_refresh else _load_cache()
    new_cache: dict[str, list] = {}

    # Read history.jsonl for display text
    history_path = claude_dir / "history.jsonl"
    session_first_prompt: dict[str, str] = {}
    if history_path.exists():
        try:
            with open(history_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    sid = entry.get("sessionId")
                    display = (entry.get("display") or "").strip()
                    if sid and display and sid not in session_first_prompt:
                        if display.startswith("/") and len(display) < 30:
                            continue
                        session_first_prompt[sid] = display
        except Exception:
            pass

    # Discover project directories
    try:
        project_dirs = [
            d.name for d in projects_dir.iterdir()
            if d.is_dir()
        ]
    except Exception:
        return _empty_result()

    sessions = []
    daily_map: dict[str, dict] = {}
    model_map: dict[str, dict] = {}
    all_prompts: list[dict] = []
    tool_frequency: dict[str, int] = {}

    for project_dir in project_dirs:
        dir_path = projects_dir / project_dir
        try:
            files = [f for f in dir_path.iterdir() if f.suffix == ".jsonl"]
        except Exception:
            continue

        for file_path in files:
            session_id = file_path.stem
            ck = _cache_key(str(file_path))

            if ck and ck in cache:
                queries = cache[ck]
                new_cache[ck] = queries
            else:
                try:
                    parsed = parse_jsonl_file(str(file_path))
                except Exception:
                    continue

                if not parsed["assistantEntries"]:
                    continue
                queries = extract_session_data(parsed["assistantEntries"], parsed["userMessages"])
                if ck:
                    new_cache[ck] = queries

            if not queries:
                continue

            # Aggregate session
            input_tokens = 0
            output_tokens = 0
            cache_creation_tokens = 0
            cache_read_tokens = 0
            cost = 0.0
            thinking_turns = 0

            for q in queries:
                input_tokens += q["inputTokens"]
                output_tokens += q["outputTokens"]
                cache_creation_tokens += q["cacheCreationTokens"]
                cache_read_tokens += q["cacheReadTokens"]
                cost += q["cost"]
                if q["hasThinking"]:
                    thinking_turns += 1
                for tool in q["tools"]:
                    tool_frequency[tool] = tool_frequency.get(tool, 0) + 1

            total_tokens = input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens

            first_timestamp = None
            for q in queries:
                if q.get("assistantTimestamp"):
                    first_timestamp = q["assistantTimestamp"]
                    break
            if not first_timestamp:
                for q in queries:
                    if q.get("userTimestamp"):
                        first_timestamp = q["userTimestamp"]
                        break

            date = first_timestamp.split("T")[0] if first_timestamp else "unknown"

            # Primary model
            model_counts: dict[str, int] = {}
            for q in queries:
                model_counts[q["model"]] = model_counts.get(q["model"], 0) + 1
            primary_model = max(model_counts, key=model_counts.get) if model_counts else "unknown"

            first_prompt = session_first_prompt.get(session_id)
            if not first_prompt:
                for q in queries:
                    if q.get("userPrompt"):
                        first_prompt = q["userPrompt"]
                        break
            if not first_prompt:
                first_prompt = "(no prompt)"

            # Per-prompt grouping
            current_prompt = None
            p_input = p_output = p_cache_create = p_cache_read = 0
            p_cost = 0.0

            def flush_prompt():
                nonlocal current_prompt, p_input, p_output, p_cache_create, p_cache_read, p_cost
                if current_prompt and (p_input + p_output + p_cache_create + p_cache_read) > 0:
                    all_prompts.append({
                        "prompt": current_prompt[:300],
                        "inputTokens": p_input,
                        "outputTokens": p_output,
                        "cacheCreationTokens": p_cache_create,
                        "cacheReadTokens": p_cache_read,
                        "totalTokens": p_input + p_output + p_cache_create + p_cache_read,
                        "cost": p_cost,
                        "date": date,
                        "sessionId": session_id,
                        "model": primary_model,
                    })

            for q in queries:
                if q.get("userPrompt") and q["userPrompt"] != current_prompt:
                    flush_prompt()
                    current_prompt = q["userPrompt"]
                    p_input = p_output = p_cache_create = p_cache_read = 0
                    p_cost = 0.0
                p_input += q["inputTokens"]
                p_output += q["outputTokens"]
                p_cache_create += q["cacheCreationTokens"]
                p_cache_read += q["cacheReadTokens"]
                p_cost += q["cost"]
            flush_prompt()

            total_tool_calls = sum(len(q["tools"]) for q in queries)

            sessions.append({
                "sessionId": session_id,
                "project": project_dir,
                "date": date,
                "timestamp": first_timestamp,
                "firstPrompt": first_prompt[:200],
                "model": primary_model,
                "queryCount": len(queries),
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "cacheCreationTokens": cache_creation_tokens,
                "cacheReadTokens": cache_read_tokens,
                "totalTokens": total_tokens,
                "cost": cost,
                "thinkingTurns": thinking_turns,
                "totalToolCalls": total_tool_calls,
                "toolDensity": total_tool_calls / len(queries) if queries else 0,
            })

            # Daily aggregation
            if date != "unknown":
                if date not in daily_map:
                    daily_map[date] = {
                        "date": date, "inputTokens": 0, "outputTokens": 0,
                        "cacheCreationTokens": 0, "cacheReadTokens": 0,
                        "totalTokens": 0, "cost": 0, "sessions": 0, "queries": 0,
                    }
                d = daily_map[date]
                d["inputTokens"] += input_tokens
                d["outputTokens"] += output_tokens
                d["cacheCreationTokens"] += cache_creation_tokens
                d["cacheReadTokens"] += cache_read_tokens
                d["totalTokens"] += total_tokens
                d["cost"] += cost
                d["sessions"] += 1
                d["queries"] += len(queries)

            # Model aggregation
            for q in queries:
                qm = q["model"]
                if qm in ("<synthetic>", "unknown"):
                    continue
                if qm not in model_map:
                    model_map[qm] = {
                        "model": qm, "inputTokens": 0, "outputTokens": 0,
                        "cacheCreationTokens": 0, "cacheReadTokens": 0,
                        "totalTokens": 0, "cost": 0, "queryCount": 0,
                    }
                mm = model_map[qm]
                mm["inputTokens"] += q["inputTokens"]
                mm["outputTokens"] += q["outputTokens"]
                mm["cacheCreationTokens"] += q["cacheCreationTokens"]
                mm["cacheReadTokens"] += q["cacheReadTokens"]
                mm["totalTokens"] += q["totalTokens"]
                mm["cost"] += q["cost"]
                mm["queryCount"] += 1

    _save_cache(new_cache)

    sessions.sort(key=lambda s: s["totalTokens"], reverse=True)

    daily_usage = sorted(daily_map.values(), key=lambda d: d["date"])
    model_breakdown = sorted(model_map.values(), key=lambda m: m["totalTokens"], reverse=True)
    top_prompts = sorted(all_prompts, key=lambda p: p["totalTokens"], reverse=True)[:50]

    # Project aggregation
    project_map: dict[str, dict] = {}
    for session in sessions:
        proj = session["project"]
        if proj not in project_map:
            project_map[proj] = {
                "project": proj, "inputTokens": 0, "outputTokens": 0,
                "cacheCreationTokens": 0, "cacheReadTokens": 0,
                "totalTokens": 0, "cost": 0, "sessionCount": 0, "queryCount": 0,
            }
        p = project_map[proj]
        p["inputTokens"] += session["inputTokens"]
        p["outputTokens"] += session["outputTokens"]
        p["cacheCreationTokens"] += session["cacheCreationTokens"]
        p["cacheReadTokens"] += session["cacheReadTokens"]
        p["totalTokens"] += session["totalTokens"]
        p["cost"] += session["cost"]
        p["sessionCount"] += 1
        p["queryCount"] += session["queryCount"]
    projects = sorted(project_map.values(), key=lambda p: p["totalTokens"], reverse=True)

    # Totals
    total_input = sum(s["inputTokens"] for s in sessions)
    total_output = sum(s["outputTokens"] for s in sessions)
    total_cache_creation = sum(s["cacheCreationTokens"] for s in sessions)
    total_cache_read = sum(s["cacheReadTokens"] for s in sessions)
    total_tokens = total_input + total_output + total_cache_creation + total_cache_read
    total_cost = sum(s["cost"] for s in sessions)
    total_queries = sum(s["queryCount"] for s in sessions)
    total_thinking_turns = sum(s["thinkingTurns"] for s in sessions)

    cache_hit_rate = (
        total_cache_read / (total_cache_read + total_cache_creation + total_input)
        if (total_cache_read + total_cache_creation + total_input) > 0
        else 0
    )

    tool_stats = sorted(
        [{"name": name, "count": count} for name, count in tool_frequency.items()],
        key=lambda t: t["count"],
        reverse=True,
    )

    return {
        "sessions": sessions,
        "dailyUsage": daily_usage,
        "modelBreakdown": model_breakdown,
        "topPrompts": top_prompts,
        "projects": projects,
        "toolStats": tool_stats,
        "totals": {
            "totalTokens": total_tokens,
            "totalInput": total_input,
            "totalOutput": total_output,
            "totalCacheCreation": total_cache_creation,
            "totalCacheRead": total_cache_read,
            "totalCost": total_cost,
            "totalSessions": len(sessions),
            "totalQueries": total_queries,
            "totalThinkingTurns": total_thinking_turns,
            "cacheHitRate": cache_hit_rate,
            "avgTokensPerSession": round(total_tokens / len(sessions)) if sessions else 0,
            "avgTokensPerQuery": round(total_tokens / total_queries) if total_queries else 0,
        },
    }
