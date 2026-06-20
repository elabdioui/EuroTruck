"""Format EuroTruck signals into Telegram messages."""

_VERDICT_EMOJI = {"GO": "✅", "NO_GO": "❌", "WAIT": "⏳"}
_KILLZONE_LABEL = {"LONDON": "London", "NY_AM": "NY AM", "NY_PM": "NY PM"}


def _signal_name(signal: dict) -> str:
    setup = str(signal.get("setup", "signal"))
    direction = str(signal.get("direction", "?"))
    killzone = str(signal.get("killzone", "?"))
    setup_slug = setup.replace(" ", "_").replace("+", "_")
    return f"{setup_slug}_{direction}_{killzone}"


def _fmt_price(value: object) -> str:
    try:
        return f"{float(value):.5f}"
    except (TypeError, ValueError):
        return "?"


def _planned_rr(signal: dict) -> float | None:
    try:
        entry = float(signal["entry"])
        sl = float(signal["sl"])
        tp_final = float(signal["tp_final"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(entry - sl)
    return abs(tp_final - entry) / risk if risk else None


def format_alert(
    signal: dict,
    verdict: dict | None,
    provider: str = "",
    news_context: dict | None = None,
) -> str:
    setup = str(signal.get("setup", "?"))
    direction = str(signal.get("direction", "?"))
    pattern = str(signal.get("pattern", "?"))
    killzone = str(signal.get("killzone", ""))
    symbol = str(signal.get("symbol", "EURUSD"))
    killzone_label = _KILLZONE_LABEL.get(killzone, killzone or "hors session")
    outside_killzone = " · ⚠️ hors killzone" if not signal.get("killzone_match", False) else ""

    rr = _planned_rr(signal)
    rr_text = f" · RR {rr:.2f}" if rr is not None else ""
    lines = [
        f"📈 {symbol} · {setup} | {direction} | {killzone_label}{outside_killzone}",
        f"🏷 Signal : #{_signal_name(signal)}",
        f"📊 Pattern : {pattern}",
        (
            f"Entry {_fmt_price(signal.get('entry'))} · "
            f"SL {_fmt_price(signal.get('sl'))} · "
            f"TP1 {_fmt_price(signal.get('tp1'))} · "
            f"TP final {_fmt_price(signal.get('tp_final'))}{rr_text}"
        ),
    ]

    if news_context and news_context.get("red_news_imminent"):
        lines.extend(["", "🔴 News rouge imminente"])

    lines.append("")
    if verdict:
        verdict_name = str(verdict.get("verdict", "?"))
        impact = str(verdict.get("impact_level", "?"))
        provider_tag = f" ({provider})" if provider and provider != "none" else ""
        lines.extend(
            [
                f"🤖 Analyse LLM{provider_tag}",
                f"{_VERDICT_EMOJI.get(verdict_name, '❓')} Verdict: {verdict_name} · Impact: {impact}",
                f"💬 {verdict.get('reason_short', '')}",
                f"⚠️ Risque : {verdict.get('risk_main', '')}",
                f"👉 Action : {verdict.get('action', '')}",
            ]
        )
    else:
        lines.append("🤖 Analyse LLM indisponible")

    return "\n".join(lines)


def format_no_go_news(signal: dict, news_event_title: str) -> str:
    """Message for the optional legacy hard news block."""
    setup = signal.get("setup", "?")
    direction = signal.get("direction", "?")
    return (
        f"⛔ SIGNAL BLOQUÉ — {setup} {direction}\n"
        f"News imminente : {news_event_title}\n"
        "Kill-switch explicite appliqué — pas de trade."
    )
