"""Format alert signals into Telegram messages."""
from datetime import datetime, timezone
import pytz


_TIER_EMOJI = {"S": "🔥", "A": "⭐", "B": "👁️"}
_VERDICT_EMOJI = {"GO": "✅", "NO_GO": "❌", "WAIT": "⏳"}
_KILLZONE_LABEL = {"LONDON": "London Open", "NY_AM": "NY AM", "NY_PM": "NY PM"}
_MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def _fmt_time(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        morocco = dt.astimezone(_MOROCCO_TZ)
        return morocco.strftime("%H:%M (Maroc)")
    except Exception:
        return ts_str


def _signal_name(signal: dict) -> str:
    tier = signal.get("tier", "?")
    direction = signal.get("direction", "?")
    pattern = signal.get("pattern", "?")
    killzone = signal.get("killzone", "?")
    pattern_slug = pattern.replace(" ", "").replace("+", "_")
    return f"T{tier}_{direction}_{killzone}_{pattern_slug}"


def format_alert(signal: dict, verdict: dict | None, provider: str = "") -> str:
    tier = signal.get("tier", "?")
    direction = signal.get("direction", "?")
    pattern = signal.get("pattern", "?")
    killzone = signal.get("killzone", "?")
    symbol = signal.get("symbol", "XAUUSD")

    entry_low = signal.get("entry_zone_low", 0)
    entry_high = signal.get("entry_zone_high", 0)
    sl = signal.get("stop_loss", 0)
    tp = signal.get("take_profit", 0)
    confluences = signal.get("confluences", [])
    score = signal.get("confluence_score", 0)
    winrate = int(signal.get("estimated_winrate", 0) * 100)

    tier_emoji = _TIER_EMOJI.get(tier, "📊")
    kz_label = _KILLZONE_LABEL.get(killzone, killzone)
    time_str = _fmt_time(signal.get("timestamp", ""))

    confluences_str = " | ".join(confluences) if confluences else "—"
    name = _signal_name(signal)

    header = f"{tier_emoji} TIER {tier} — {symbol} {direction}"
    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━",
        f"🏷 Signal : #{name}",
        f"🕐 {time_str} ({kz_label})",
        f"📊 Pattern : {pattern}",
        f"📍 Zone entrée : {entry_low:.2f} — {entry_high:.2f}",
        f"🛑 SL : {sl:.2f}",
        f"🎯 TP : {tp:.2f}",
        f"🔗 Confluences : {confluences_str}",
        f"📈 Score : {score}/10  |  WR estimé : ~{winrate}%",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if verdict:
        v = verdict.get("verdict", "?")
        reason = verdict.get("reason_short", "")
        risk = verdict.get("risk_main", "")
        action = verdict.get("action", "")
        v_emoji = _VERDICT_EMOJI.get(v, "❓")
        provider_tag = f" ({provider})" if provider and provider != "none" else ""

        lines += [
            f"🤖 VERDICT LLM{provider_tag}",
            f"{v_emoji} {v}",
            "",
            f"💬 {reason}",
            f"⚠️ Risque : {risk}",
            f"👉 Action : {action}",
        ]
    else:
        lines += [
            "🤖 Verdict LLM : indisponible (signal brut)",
        ]

    return "\n".join(lines)


def format_no_go_news(signal: dict, news_event_title: str) -> str:
    """Message for automatic kill-switch due to red news."""
    tier = signal.get("tier", "?")
    direction = signal.get("direction", "?")
    return (
        f"⛔ SIGNAL BLOQUÉ — Tier {tier} {direction}\n"
        f"News rouge imminente : {news_event_title}\n"
        f"Règle kill-switch appliquée — pas de trade."
    )
