"""Demo seeding: populates every table, idempotent, and sets up the
returning-customer + load/proximity demo."""

import app.seeds as seeds
from app.models import Appointment, Client, Contact, CustomerMemory, Job, Staff
from app.seeds import DEMO_APPOINTMENTS, seed_all


def test_seed_all_populates_every_table(Session):
    summary = seed_all(Session)
    assert summary == {
        "staff": 3,
        "clients": 2,
        "contacts": 2,
        "memories": 3,
        "appointments": len(DEMO_APPOINTMENTS),
    }
    with Session() as s:
        assert s.query(Staff).count() == 3
        assert s.query(Client).count() == 2
        assert s.query(Contact).count() == 2
        assert s.query(CustomerMemory).count() == 3
        assert s.query(Job).count() == len(DEMO_APPOINTMENTS)
        assert s.query(Appointment).count() == len(DEMO_APPOINTMENTS)


def test_seed_all_is_idempotent(Session):
    seed_all(Session)
    second = seed_all(Session)
    assert second == {"staff": 0, "clients": 0, "contacts": 0, "memories": 0, "appointments": 0}
    with Session() as s:
        assert s.query(Client).count() == 2  # not duplicated
        assert s.query(Appointment).count() == len(DEMO_APPOINTMENTS)


def test_seeded_schedule_creates_load_differences(Session):
    seed_all(Session)
    with Session() as s:
        alex = s.query(Staff).filter(Staff.name == "Alex Taylor").one()
        assert s.query(Appointment).filter(Appointment.staff_id == alex.id).count() == 2
        jordan = s.query(Staff).filter(Staff.name == "Jordan Lee").one()
        assert s.query(Appointment).filter(Appointment.staff_id == jordan.id).count() == 0


def test_seeded_returning_customer_has_preference_note(Session):
    seed_all(Session)
    with Session() as s:
        pref = (
            s.query(CustomerMemory)
            .filter(
                CustomerMemory.customer_key == "priya@example.com",
                CustomerMemory.memory_type == "preference",
            )
            .one()
        )
    assert pref.content["note"] == "calm with anxious dogs"


def test_seed_all_embeds_bios_when_embedder_given(Session):
    class _FakeEmbedder:
        def embed(self, text):
            return [1.0, 0.0] if text else None

    seed_all(Session, embedder=_FakeEmbedder())
    with Session() as s:
        embeddings = [st.bio_embedding for st in s.query(Staff).all()]
    assert all(e == [1.0, 0.0] for e in embeddings)  # every seeded bio embedded


def test_seed_all_skips_appointment_for_unknown_staff(Session, monkeypatch):
    monkeypatch.setattr(seeds, "DEMO_APPOINTMENTS", [("Ghost Cleaner", "cleaning", "09:00")])
    summary = seed_all(Session)
    assert summary["appointments"] == 0  # unknown staff name → skipped, no crash
