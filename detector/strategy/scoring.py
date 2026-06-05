"""Shared confluence scoring used by all tiers."""
from config import cfg


def _score_confluences(confluences: list[str]) -> int:
    """Weighted confluence score capped at 10.

    Each label is matched against cfg.CONFLUENCE_WEIGHTS by exact key first,
    then by prefix (so 'OTE_0.618' matches the 'OTE' key).
    Unknown labels contribute 1 point each as a safe default.
    """
    weights = cfg.CONFLUENCE_WEIGHTS
    total = 0
    for label in confluences:
        if label in weights:
            total += weights[label]
        else:
            prefix_match = next((w for w in weights if label.startswith(w)), None)
            total += weights[prefix_match] if prefix_match else 1
    return min(10, total)
