"""risk_review_agent — lightweight risk assessment before the approval gate.

Every booking creates mutating actions, so approval is always required; the
score/flags just give the reviewer context (e.g. an after-hours booking).
"""

from __future__ import annotations

from ..state import BookingState


def risk_review_agent(state: BookingState) -> BookingState:
    plan = state.get("job_plan") or {}
    flags: list[str] = []

    time = plan.get("time")
    if time:
        hour = int(time.split(":")[0])
        if hour < 7 or hour >= 18:
            flags.append("out_of_hours")
    if not plan.get("staff"):
        flags.append("no_staff_assigned")

    return {
        "risk": {
            "score": len(flags),
            "flags": flags,
            "requires_approval": True,  # mutations always gated
        }
    }
