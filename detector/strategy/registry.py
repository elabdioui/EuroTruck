from dataclasses import dataclass
from typing import Callable, Optional


# Killzone gating contract:
#   "required"  -> setup only runs when the active killzone is allowed
#   "preferred" -> setup only runs during an active killzone, and only matches
#                  its configured zones when provided
#   "agnostic"  -> setup runs during any active killzone
KillzoneMode = str


@dataclass(frozen=True)
class SetupSpec:
    name: str
    scan: Callable[[dict], Optional[dict]]
    killzone_mode: KillzoneMode
    killzones: tuple[str, ...] = ()
    cooldown_seconds: int = 900


_REGISTRY: dict[str, SetupSpec] = {}


def register(spec: SetupSpec) -> None:
    if spec.name in _REGISTRY:
        raise ValueError(f"Setup already registered: {spec.name}")
    if spec.killzone_mode == "required" and not spec.killzones:
        raise ValueError(f"{spec.name}: killzone_mode=required needs non-empty killzones")
    _REGISTRY[spec.name] = spec


def all_setups() -> list[SetupSpec]:
    return list(_REGISTRY.values())


def runnable_setups(active_kz: Optional[str]) -> list[SetupSpec]:
    """Return the setups eligible to scan for the active killzone.

    The detector is globally killzone-gated: no setup scans outside an active
    killzone. Required and preferred setups with explicit killzones only run
    when the active killzone is one of their configured sessions.
    """
    if active_kz is None:
        return []

    out: list[SetupSpec] = []
    for spec in _REGISTRY.values():
        if spec.killzones and active_kz not in spec.killzones:
            continue
        out.append(spec)
    return out


def clear() -> None:
    """Clear the registry for test isolation."""
    _REGISTRY.clear()
