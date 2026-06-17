"""Best-cleaner selection.

Scores candidates on skill match, workload, schedule fit, and proximity. The
deterministic ``rank``/``choose`` path is always the fallback;
``select(..., use_llm=True)`` lets an LLM apply the rules to candidate JSON. The
LLM's choice is validated against the candidate set — any issue falls back to
the deterministic pick, so the LLM can never invent a cleaner or bypass the
skill rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel

from .embeddings import cosine


@dataclass
class StaffCandidate:
    staff_id: str
    staff_name: str
    skills: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None
    day_load: int = 0  # number of jobs already booked that day
    booked_times: tuple[str, ...] = ()  # the cleaner's booked hours that day, e.g. ("09:00",)
    bio: str | None = None  # free-text specialties
    bio_embedding: list[float] | None = None  # embedding of the bio (semantic match)


@dataclass(frozen=True)
class RankWeights:
    skill: float = 100.0  # dominant: a cleaner who can do the job wins
    load: float = 10.0  # then balance the team's workload
    proximity: float = 5.0  # then prefer the nearest
    schedule: float = 4.0  # bonus for clustering next to an existing job
    preference: float = 8.0  # semantic match of the customer's note to the bio


@dataclass
class ScoredStaff:
    candidate: StaffCandidate
    score: float
    skill_match: bool
    distance_km: float | None
    reason: str
    preference_similarity: float = 0.0


class StaffChoice(BaseModel):
    """Structured output of the LLM selection."""

    staff_id: str
    reason: str


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _has_skill(candidate: StaffCandidate, service: str | None) -> bool:
    if not service or not candidate.skills:
        return False
    s = service.lower()
    return any(skill.lower() in s or s in skill.lower() for skill in candidate.skills)


def _hour(t: str) -> int:
    return int(t.split(":")[0])


def _is_adjacent(slot_time: str | None, booked_times: tuple[str, ...]) -> bool:
    """True if the requested hour sits next to an already-booked hour (so the
    job clusters with the cleaner's existing schedule)."""
    if not slot_time or not booked_times:
        return False
    h = _hour(slot_time)
    return any(abs(_hour(b) - h) == 1 for b in booked_times)


@dataclass
class StaffRanker:
    weights: RankWeights = field(default_factory=RankWeights)
    # Only the best K candidates go to the LLM (prompt is O(K), not O(N)). When
    # the top score beats the runner-up by >= tie_margin, skip the LLM entirely.
    top_k: int = 5
    tie_margin: float = 5.0

    def rank(
        self,
        candidates: list[StaffCandidate],
        *,
        service: str | None = None,
        slot_time: str | None = None,
        job_latitude: float | None = None,
        job_longitude: float | None = None,
        preference_embedding: list[float] | None = None,
    ) -> list[ScoredStaff]:
        distances: dict[str, float | None] = {}
        for c in candidates:
            if job_latitude is not None and c.latitude is not None and c.longitude is not None:
                distances[c.staff_id] = haversine_km(
                    job_latitude, job_longitude, c.latitude, c.longitude
                )
            else:
                distances[c.staff_id] = None

        max_load = max((c.day_load for c in candidates), default=0) or 1
        known = [d for d in distances.values() if d is not None]
        max_dist = max(known) if known else 1.0

        scored: list[ScoredStaff] = []
        for c in candidates:
            dist = distances[c.staff_id]
            skill = _has_skill(c, service)
            load_penalty = c.day_load / max_load
            prox_penalty = (dist / max_dist) if dist is not None else 0.0
            adjacent = _is_adjacent(slot_time, c.booked_times)
            # Semantic match of the customer's note to the cleaner's bio (0 if
            # either side is missing). cosine() clamps to [0, 1].
            pref_sim = (
                cosine(preference_embedding, c.bio_embedding)
                if preference_embedding and c.bio_embedding
                else 0.0
            )
            score = (
                self.weights.skill * (1.0 if skill else 0.0)
                - self.weights.load * load_penalty
                + self.weights.schedule * (1.0 if adjacent else 0.0)
                - self.weights.proximity * prox_penalty
                + self.weights.preference * pref_sim
            )
            reason = (
                f"{'has skill' if skill else 'no skill match'}, load={c.day_load}"
                + (", clusters with existing job" if adjacent else "")
                + (f", {dist:.1f}km away" if dist is not None else "")
                + (f", preference match {pref_sim:.2f}" if pref_sim > 0 else "")
            )
            scored.append(ScoredStaff(c, score, skill, dist, reason, pref_sim))

        scored.sort(key=lambda s: (-s.score, s.candidate.staff_name))
        return scored

    def choose(self, candidates, **kw) -> tuple[ScoredStaff | None, list[ScoredStaff]]:
        ranked = self.rank(candidates, **kw)
        return (ranked[0] if ranked else None), ranked

    def select(
        self,
        candidates: list[StaffCandidate],
        *,
        service: str | None = None,
        slot_time: str | None = None,
        job_latitude: float | None = None,
        job_longitude: float | None = None,
        preference: str | None = None,
        preference_embedding: list[float] | None = None,
        use_llm: bool = False,
    ) -> tuple[StaffCandidate | None, str]:
        """Pick the best cleaner. LLM-driven when enabled (rules + candidate JSON),
        else deterministic. Returns (candidate, one-line reason)."""
        ranked = self.rank(
            candidates,
            service=service,
            slot_time=slot_time,
            job_latitude=job_latitude,
            job_longitude=job_longitude,
            preference_embedding=preference_embedding,
        )
        if not ranked:
            return None, ""

        best = ranked[0]
        clear_winner = len(ranked) == 1 or (best.score - ranked[1].score) >= self.tie_margin

        if use_llm and not clear_winner:
            choice = _select_with_llm(
                ranked[: self.top_k], service=service, slot_time=slot_time, preference=preference
            )
            if choice is not None:
                return choice

        return best.candidate, f"Assigned {best.candidate.staff_name} — {best.reason}."


def _candidate_payload(scored: ScoredStaff) -> dict:
    """Minimal JSON-serializable view of a candidate for the prompt."""
    c = scored.candidate
    return {
        "staff_id": c.staff_id,
        "name": c.staff_name,
        "skills": list(c.skills),
        "bio": c.bio,
        "booked_times": list(c.booked_times),
        "day_load": c.day_load,
        "distance_km": round(scored.distance_km, 1) if scored.distance_km is not None else None,
        "preference_similarity": round(scored.preference_similarity, 3),
    }


def _select_with_llm(
    ranked: list[ScoredStaff],
    *,
    service: str | None,
    slot_time: str | None,
    preference: str | None = None,
) -> tuple[StaffCandidate, str] | None:
    """Rules-in-prompt LLM selection over the candidates' JSON. Returns None on
    any issue (the caller falls back to the deterministic pick)."""
    try:
        from langchain_openai import ChatOpenAI

        from ..config import get_settings
        from ..core.prompts import STAFF_SELECTION

        by_id = {s.candidate.staff_id: s.candidate for s in ranked}
        user_payload = {
            "service": service,
            "requested_time": slot_time,
            "customer_preference": preference,
            "candidates": [_candidate_payload(s) for s in ranked],
        }
        # Output is tiny ({staff_id, reason}) — cap it as a cost guardrail.
        llm = ChatOpenAI(
            temperature=0,
            timeout=10,
            max_retries=2,
            max_tokens=get_settings().selection_max_tokens,
        ).with_structured_output(StaffChoice)
        choice = llm.invoke([("system", STAFF_SELECTION.text), ("human", json.dumps(user_payload))])
        chosen = by_id.get(choice.staff_id)
        if chosen is None:  # LLM returned an id not in the set — reject
            return None
        return chosen, choice.reason
    except Exception:
        return None


def explain_choice(best: ScoredStaff, *, service: str | None = None, use_llm: bool = False) -> str:
    """One-line deterministic rationale (kept for direct use/tests)."""
    return f"Assigned {best.candidate.staff_name} — {best.reason}."
