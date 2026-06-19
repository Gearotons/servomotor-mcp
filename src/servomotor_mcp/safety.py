"""Safety rails for the M17 MCP server.

These checks live in the server, NOT in the LLM. The model can hallucinate a tool call;
the rails are what make that safe. Three guarantees:

1. **Alias allow-list** — only motors the operator configured can be driven.
2. **Position limits** — absolute/relative targets are clamped to a per-motor software
   range so the LLM can't command an axis into a mechanical hard stop.
3. **Speed clamp** — requested speeds are capped to a configured maximum.

Limits are loaded from env (``GEAROTONS_LIMITS``) or passed in for tests. A move that
violates a limit is clamped (not silently dropped) and the clamp is reported back to the
LLM in the tool result, so it can see what actually happened and adjust.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


class SafetyError(ValueError):
    """Raised when a request cannot be made safe (e.g. unknown/disallowed motor)."""


@dataclass(frozen=True)
class MotorLimits:
    min_deg: float = -360.0
    max_deg: float = 360.0
    max_speed: float = 360.0  # deg/s


@dataclass
class SafetyPolicy:
    allowed: frozenset[str]
    limits: dict[str, MotorLimits]
    default: MotorLimits = MotorLimits()

    # --- construction -----------------------------------------------------------------

    @classmethod
    def from_env(cls, allowed_aliases: tuple[str, ...]) -> "SafetyPolicy":
        """Build a policy from ``GEAROTONS_LIMITS`` (JSON) plus the configured aliases.

        ``GEAROTONS_LIMITS`` example:
            {"x": {"min_deg": -180, "max_deg": 180, "max_speed": 300}}
        Any alias without an explicit entry uses the conservative default range.
        """
        raw = os.environ.get("GEAROTONS_LIMITS", "{}")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SafetyError(f"GEAROTONS_LIMITS is not valid JSON: {exc}") from exc
        limits = {
            alias: MotorLimits(
                min_deg=float(cfg.get("min_deg", -360.0)),
                max_deg=float(cfg.get("max_deg", 360.0)),
                max_speed=float(cfg.get("max_speed", 360.0)),
            )
            for alias, cfg in parsed.items()
        }
        return cls(allowed=frozenset(allowed_aliases), limits=limits)

    # --- checks -----------------------------------------------------------------------

    def require_allowed(self, alias: str) -> str:
        if alias not in self.allowed:
            raise SafetyError(
                f"motor {alias!r} is not in the allow-list {sorted(self.allowed)}; "
                "refusing to drive it."
            )
        return alias

    def limits_for(self, alias: str) -> MotorLimits:
        return self.limits.get(alias, self.default)

    def clamp_absolute(self, alias: str, degrees: float) -> tuple[float, str | None]:
        """Clamp an absolute target to the motor's range. Returns (value, note|None)."""
        lim = self.limits_for(alias)
        clamped = max(lim.min_deg, min(lim.max_deg, degrees))
        note = None
        if clamped != degrees:
            note = f"target {degrees}° clamped to {clamped}° (range {lim.min_deg}..{lim.max_deg})"
        return clamped, note

    def clamp_relative(
        self, alias: str, current_deg: float, delta_deg: float
    ) -> tuple[float, str | None]:
        """Clamp a relative move so the resulting absolute position stays in range.

        Returns the *allowed delta* and an optional note.
        """
        target = current_deg + delta_deg
        clamped_target, _ = self.clamp_absolute(alias, target)
        allowed_delta = clamped_target - current_deg
        note = None
        if allowed_delta != delta_deg:
            note = (
                f"relative move {delta_deg}° clamped to {allowed_delta}° to stay within "
                f"{self.limits_for(alias).min_deg}..{self.limits_for(alias).max_deg}"
            )
        return allowed_delta, note

    def clamp_speed(self, alias: str, speed: float | None) -> tuple[float | None, str | None]:
        if speed is None:
            return None, None
        lim = self.limits_for(alias)
        clamped = max(0.0, min(lim.max_speed, speed))
        note = None
        if clamped != speed:
            note = f"speed {speed} deg/s clamped to {clamped} (max {lim.max_speed})"
        return clamped, note
