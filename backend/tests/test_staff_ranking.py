"""Best-cleaner selection: skill > load > proximity, with rationale."""

from datetime import datetime

from app.graph.nodes.job_planning_agent import make_job_planning_agent
from app.graph.state import AvailabilityResult, BookingRequest, Slot
from app.models import Appointment, Staff
from app.services.availability import DbAvailabilityProvider, seed_default_staff
from app.services.staff_ranking import (
    RankWeights,
    StaffCandidate,
    StaffRanker,
    explain_choice,
    haversine_km,
)
from tests.helpers import seed_job


def _c(name, *, skills=(), lat=None, lng=None, load=0):
    return StaffCandidate(
        name, name, skills=tuple(skills), latitude=lat, longitude=lng, day_load=load
    )


def test_skill_match_dominates():
    skilled = _c("Pat", skills=["cleaning"], load=9)  # heavy load but has the skill
    unskilled = _c("Robin", skills=["plumbing"], load=0)
    best, _ = StaffRanker().choose([unskilled, skilled], service="deep cleaning")
    assert best.candidate.staff_name == "Pat"
    assert best.skill_match is True


def test_load_breaks_ties_among_skilled():
    busy = _c("Busy", skills=["cleaning"], load=5)
    free = _c("Free", skills=["cleaning"], load=0)
    best, _ = StaffRanker().choose([busy, free], service="cleaning")
    assert best.candidate.staff_name == "Free"


def test_proximity_breaks_ties_when_equal_skill_and_load():
    near = _c("Near", skills=["cleaning"], lat=-27.47, lng=153.02, load=0)
    far = _c("Far", skills=["cleaning"], lat=-28.0, lng=153.4, load=0)
    best, _ = StaffRanker().choose(
        [far, near], service="cleaning", job_latitude=-27.47, job_longitude=153.02
    )
    assert best.candidate.staff_name == "Near"
    assert best.distance_km == 0.0


def test_haversine_zero_for_same_point():
    assert haversine_km(-27.47, 153.02, -27.47, 153.02) == 0.0


def test_explain_choice_deterministic():
    best, _ = StaffRanker(RankWeights()).choose(
        [_c("Sam", skills=["cleaning"])], service="cleaning"
    )
    reason = explain_choice(best, service="cleaning", use_llm=False)
    assert "Sam" in reason and "has skill" in reason


def test_choose_empty_returns_none():
    best, ranked = StaffRanker().choose([], service="cleaning")
    assert best is None and ranked == []


# --- integration with the job_planning node + DB provider -----------------


def test_job_planning_picks_skilled_low_load_cleaner(Session):
    seed_default_staff(
        Session
    )  # Alex(cleaning,contact work) Sam(cleaning,gardening) Jordan(plumbing,contact work)
    # Load up Alex so the other "contact work" cleaner (Jordan) wins.
    job_id = seed_job(Session)
    with Session() as s:
        alex = s.query(Staff).filter(Staff.name == "Alex Taylor").one()
        s.add(
            Appointment(
                job_id=job_id,
                staff_id=alex.id,
                staff_name=alex.name,
                start_date=datetime.fromisoformat("2026-06-20 09:00:00"),
            )
        )
        s.commit()

    provider = DbAvailabilityProvider(session_factory=Session)
    node = make_job_planning_agent(provider)
    state = {
        "booking_request": BookingRequest(service="contact work"),
        "availability": AvailabilityResult(
            available=True, chosen_slot=Slot(date="2026-06-20", time="11:00")
        ),
    }
    out = node(state)
    assert out["availability"].chosen_slot.staff_name == "Jordan Lee"  # skilled + lighter load
    assert out["job_plan"]["staff"] == "Jordan Lee"
    assert "Jordan Lee" in out["job_plan"]["assignment_reason"]


def test_job_planning_falls_back_without_provider():
    node = make_job_planning_agent(provider=None)
    out = node(
        {
            "booking_request": BookingRequest(service="x"),
            "availability": AvailabilityResult(
                chosen_slot=Slot(date="2026-06-20", time="10:00", staff_name="Pre")
            ),
        }
    )
    assert out["job_plan"]["staff"] == "Pre"  # kept what availability picked


def test_no_skill_match_when_no_skills():
    best, _ = StaffRanker().choose([_c("Nobody", skills=[])], service="cleaning")
    assert best.skill_match is False


def test_free_staff_at_excludes_busy_staff(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        alex = s.query(Staff).filter(Staff.name == "Alex Taylor").one()
        s.add(
            Appointment(
                job_id=job_id,
                staff_id=alex.id,
                staff_name=alex.name,
                start_date=datetime.fromisoformat("2026-06-20 11:00:00"),
            )
        )
        s.commit()
    provider = DbAvailabilityProvider(session_factory=Session)
    free = {c.staff_name for c in provider.free_staff_at("2026-06-20", "11:00")}
    assert "Alex Taylor" not in free  # busy at 11:00
    assert {"Sam Rivers", "Jordan Lee"} <= free


def test_explain_choice_is_deterministic():
    best, _ = StaffRanker().choose([_c("Sam", skills=["cleaning"])], service="cleaning")
    assert explain_choice(best) == "Assigned Sam — has skill, load=0."


def _install_fake_llm(monkeypatch, *, raises=False, pick="last"):
    """Fake langchain_openai whose structured-output LLM records the candidate
    payload it was given and returns a StaffChoice."""
    import sys
    import types

    from app.services.staff_ranking import StaffChoice

    seen = {"payloads": [], "kwargs": None}
    mod = types.ModuleType("langchain_openai")

    class _Structured:
        def invoke(self, messages):
            if raises:
                raise RuntimeError("api down")
            import json

            payload = json.loads(messages[-1][1])
            seen["payloads"].append(payload)
            ids = [c["staff_id"] for c in payload["candidates"]]
            if pick == "bogus":
                chosen = "ghost-not-in-set"
            else:
                chosen = ids[-1] if pick == "last" else ids[0]
            return StaffChoice(staff_id=chosen, reason="LLM picked them.")

    class ChatOpenAI:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def with_structured_output(self, schema):
            return _Structured()

    mod.ChatOpenAI = ChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", mod)
    return seen


def test_select_uses_llm_on_a_tie(monkeypatch):
    seen = _install_fake_llm(monkeypatch, pick="last")
    # Two skill-matched, equal-load candidates → a real tie → LLM decides.
    cands = [_c("Aaa", skills=["cleaning"]), _c("Zzz", skills=["cleaning"])]
    chosen, reason = StaffRanker().select(cands, service="cleaning", use_llm=True)
    assert chosen.staff_name == "Zzz"  # LLM picked the last id
    assert reason == "LLM picked them."
    assert seen["payloads"]  # the LLM was actually consulted


def test_select_skips_llm_on_clear_winner(monkeypatch):
    seen = _install_fake_llm(monkeypatch)
    # One has the skill, the other doesn't → score gap >> tie_margin → no LLM.
    cands = [_c("Skilled", skills=["cleaning"]), _c("Unskilled", skills=["plumbing"])]
    chosen, _ = StaffRanker().select(cands, service="cleaning", use_llm=True)
    assert chosen.staff_name == "Skilled"
    assert seen["payloads"] == []  # LLM skipped — clear winner


def test_select_caps_candidates_sent_to_llm_at_top_k(monkeypatch):
    seen = _install_fake_llm(monkeypatch)
    # 8 tied skilled candidates; only top_k (5) should reach the prompt.
    cands = [_c(f"C{i}", skills=["cleaning"]) for i in range(8)]
    StaffRanker(top_k=5).select(cands, service="cleaning", use_llm=True)
    assert len(seen["payloads"][0]["candidates"]) == 5  # O(K), not O(N)


def test_select_caps_output_tokens(monkeypatch):
    seen = _install_fake_llm(monkeypatch, pick="last")
    cands = [_c("Aaa", skills=["cleaning"]), _c("Zzz", skills=["cleaning"])]
    StaffRanker().select(cands, service="cleaning", use_llm=True)
    assert seen["kwargs"]["max_tokens"] == 128  # selection guardrail (default)


def test_select_falls_back_to_deterministic_on_llm_error(monkeypatch):
    _install_fake_llm(monkeypatch, raises=True)
    cands = [_c("Aaa", skills=["cleaning"]), _c("Bbb", skills=["cleaning"])]
    chosen, reason = StaffRanker().select(cands, service="cleaning", use_llm=True)
    assert chosen.staff_name == "Aaa"  # deterministic ranked[0]
    assert "has skill" in reason


def test_select_rejects_llm_id_not_in_candidate_set(monkeypatch):
    _install_fake_llm(monkeypatch, pick="bogus")  # LLM hallucinates an id
    cands = [_c("Aaa", skills=["cleaning"]), _c("Bbb", skills=["cleaning"])]
    chosen, _ = StaffRanker().select(cands, service="cleaning", use_llm=True)
    assert chosen.staff_name == "Aaa"  # rejected → deterministic ranked[0]


def test_select_empty_returns_none():
    assert StaffRanker().select([], service="cleaning") == (None, "")


# --- semantic preference matching -----------------------------------------


class _FakeEmbedder:
    """Deterministic keyword-presence embeddings (no network)."""

    DIMS = ("dog", "anxious", "eco", "pet", "nervous")

    def embed(self, text):
        if not text:
            return None
        t = text.lower()
        return [1.0 if w in t else 0.0 for w in self.DIMS]


def test_preference_breaks_a_tie_in_rank():
    e = _FakeEmbedder()
    dog = _c("Zoe", skills=["cleaning"])  # alphabetically last
    dog.bio_embedding = e.embed("calm and patient with anxious dogs")
    eco = _c("Amy", skills=["cleaning"])
    eco.bio_embedding = e.embed("fast, eco-friendly products")
    # Equal skill + load → 'Amy' would win on name; the dog note flips it to Zoe.
    chosen, reason = StaffRanker().select(
        [eco, dog],
        service="cleaning",
        preference="anxious dogs",
        preference_embedding=e.embed("anxious dogs"),
    )
    assert chosen.staff_name == "Zoe"
    assert "preference match" in reason


def test_preference_absent_falls_back_to_name_order():
    cands = [_c("Amy", skills=["cleaning"]), _c("Zoe", skills=["cleaning"])]
    chosen, reason = StaffRanker().select(cands, service="cleaning")  # no preference
    assert chosen.staff_name == "Amy"
    assert "preference match" not in reason


def test_job_planning_honors_customer_preference(Session):
    embedder = _FakeEmbedder()
    seed_default_staff(Session, embedder=embedder)  # bios embedded on write
    provider = DbAvailabilityProvider(session_factory=Session)
    node = make_job_planning_agent(provider, embedder=embedder)
    state = {
        "booking_request": BookingRequest(
            service="contact work", preferences="calm with anxious dogs"
        ),
        "availability": AvailabilityResult(
            available=True, chosen_slot=Slot(date="2026-06-20", time="11:00")
        ),
    }
    out = node(state)
    # Alex + Jordan both do contact work at equal load; the dog note picks Jordan.
    assert out["availability"].chosen_slot.staff_name == "Jordan Lee"
    assert "preference match" in out["job_plan"]["assignment_reason"]
