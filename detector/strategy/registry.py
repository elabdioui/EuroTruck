from dataclasses import dataclass
from typing import Callable, Optional


# Killzone gating contract:
#   "required"  -> setup only runs when the active killzone is allowed
#   "preferred" -> setup always runs, but killzone_match is false outside its zones
#   "agnostic"  -> setup always runs and is not tied to a killzone
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

    Required setups only run in one of their configured killzones. Preferred
    and agnostic setups always run; downstream signal tagging records whether
    a preferred setup matched its configured killzone.
    """
    out: list[SetupSpec] = []
    for spec in _REGISTRY.values():
        if spec.killzone_mode == "required":
            if active_kz is None or active_kz not in spec.killzones:
                continue
        out.append(spec)
    return out


def clear() -> None:
    """Clear the registry for test isolation."""
    _REGISTRY.clear()
