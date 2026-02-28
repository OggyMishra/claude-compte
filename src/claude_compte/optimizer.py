"""Generate optimization tips based on Claude Code usage patterns."""


def _format_project_name(name: str) -> str:
    return name.replace("-", "/", 1).replace("-", "/") if name.startswith("-") else name.replace("-", "/")


def _format_tokens(n: int) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return str(n)


def generate_optimizations(data: dict) -> list[dict]:
    tips: list[dict] = []
    totals = data["totals"]
    sessions = data["sessions"]
    model_breakdown = data["modelBreakdown"]
    daily_usage = data["dailyUsage"]

    if totals["totalSessions"] == 0:
        return tips

    # 1. Cache hit rate
    if totals["cacheHitRate"] < 0.5 and totals["totalSessions"] > 3:
        tips.append({
            "id": "low-cache-hit",
            "icon": "cache",
            "title": "Low cache hit rate",
            "description": (
                f"Your cache hit rate is {totals['cacheHitRate'] * 100:.0f}%. "
                "Try keeping sessions open longer instead of starting new ones frequently. "
                "Claude Code caches your conversation context \u2014 reusing a session means less re-reading."
            ),
            "impact": "high",
        })
    elif totals["cacheHitRate"] >= 0.8 and totals["totalSessions"] > 3:
        tips.append({
            "id": "great-cache",
            "icon": "check",
            "title": "Great cache reuse",
            "description": (
                f"Your cache hit rate is {totals['cacheHitRate'] * 100:.0f}% \u2014 "
                "you're efficiently reusing conversation context. Keep it up!"
            ),
            "impact": "positive",
        })

    # 2. Short sessions
    short_sessions = [s for s in sessions if s["queryCount"] <= 3]
    if len(short_sessions) > len(sessions) * 0.5 and len(sessions) > 5:
        tips.append({
            "id": "many-short-sessions",
            "icon": "session",
            "title": "Many short sessions",
            "description": (
                f"{len(short_sessions)} of your {len(sessions)} sessions have 3 or fewer turns. "
                "Each new session requires Claude to re-read your project context. "
                "Try staying in one session for related tasks."
            ),
            "impact": "medium",
        })

    # 3. Heavy tool usage
    avg_tool_density = sum(s["toolDensity"] for s in sessions) / len(sessions) if sessions else 0
    if avg_tool_density > 3 and totals["totalQueries"] > 10:
        tips.append({
            "id": "high-tool-density",
            "icon": "tool",
            "title": "High tool usage per turn",
            "description": (
                f"Claude averages {avg_tool_density:.1f} tool calls per response. "
                "Providing more context upfront (paste relevant code, describe file locations) "
                "can help Claude work with fewer tool calls."
            ),
            "impact": "medium",
        })

    # 4. Thinking usage
    if totals["totalThinkingTurns"] > 0 and totals["totalQueries"] > 0:
        thinking_ratio = totals["totalThinkingTurns"] / totals["totalQueries"]
        if thinking_ratio > 0.3:
            tips.append({
                "id": "heavy-thinking",
                "icon": "think",
                "title": "Extended thinking is active often",
                "description": (
                    f"{thinking_ratio * 100:.0f}% of responses use extended thinking. "
                    "For simpler tasks (renaming, small edits), try using /fast mode to skip "
                    "extended thinking and get faster responses."
                ),
                "impact": "low",
            })

    # 5. Model usage — Opus heavy
    opus_models = [m for m in model_breakdown if "opus" in m["model"].lower()]
    opus_tokens = sum(m["totalTokens"] for m in opus_models)
    if opus_tokens > totals["totalTokens"] * 0.5 and totals["totalTokens"] > 0:
        tips.append({
            "id": "opus-heavy",
            "icon": "model",
            "title": "Heavy Opus usage",
            "description": (
                f"{opus_tokens / totals['totalTokens'] * 100:.0f}% of your tokens go to Opus models. "
                "Sonnet handles most coding tasks well and uses fewer tokens per turn. "
                "Consider reserving Opus for complex architecture decisions."
            ),
            "impact": "medium",
        })

    # 6. Single project dominance
    projects = data["projects"]
    if len(projects) > 1:
        top_project = projects[0]
        ratio = top_project["totalTokens"] / totals["totalTokens"] if totals["totalTokens"] else 0
        if ratio > 0.7:
            tips.append({
                "id": "project-concentration",
                "icon": "project",
                "title": "Concentrated on one project",
                "description": (
                    f"{ratio * 100:.0f}% of your tokens go to "
                    f"\"{_format_project_name(top_project['project'])}\". "
                    "This is typical for focused work \u2014 just be aware this project drives most of your usage."
                ),
                "impact": "info",
            })

    # 7. Large input-to-output ratio
    if totals["totalOutput"] > 0 and totals["totalInput"] > 0:
        total_input_all = totals["totalInput"] + totals["totalCacheCreation"] + totals["totalCacheRead"]
        ratio = total_input_all / totals["totalOutput"]
        if ratio > 20:
            tips.append({
                "id": "high-input-ratio",
                "icon": "input",
                "title": "Very high input-to-output ratio",
                "description": (
                    f"Claude is reading {ratio:.0f}x more tokens than it outputs. "
                    "This often means large codebases being re-scanned. Try using /compact to reduce "
                    "context size, or use more specific file references in your prompts."
                ),
                "impact": "medium",
            })

    # 8. Usage spikes
    if len(daily_usage) > 7:
        recent7 = daily_usage[-7:]
        avg7 = sum(d["totalTokens"] for d in recent7) / 7
        max_day = max(recent7, key=lambda d: d["totalTokens"])
        if max_day["totalTokens"] > avg7 * 3 and avg7 > 0:
            tips.append({
                "id": "usage-spike",
                "icon": "spike",
                "title": "Usage spike detected",
                "description": (
                    f"{max_day['date']} used {_format_tokens(max_day['totalTokens'])} tokens \u2014 "
                    f"{max_day['totalTokens'] / avg7:.1f}x your 7-day average. "
                    "Heavy days are normal during complex tasks, but if this was unintentional, "
                    "review that day's sessions."
                ),
                "impact": "info",
            })

    return tips
