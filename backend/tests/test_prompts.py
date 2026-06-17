"""Golden tests for the prompt registry — a prompt change must be an
intentional, reviewed diff, never a silent regression."""

from app.core.prompts import ALL_PROMPTS, BOOKING_EXTRACTION, STAFF_SELECTION


def test_registry_invariants():
    names = [p.name for p in ALL_PROMPTS]
    assert len(names) == len(set(names))  # unique names
    for p in ALL_PROMPTS:
        assert p.name and p.version and p.text.strip()  # all populated


def test_booking_extraction_prompt_is_pinned():
    assert BOOKING_EXTRACTION.version == "v2"
    assert BOOKING_EXTRACTION.text == (
        "Extract the booking request fields from this message. "
        "Capture any customer preferences/notes (e.g. 'calm with anxious dogs', "
        "'fragrance-free') verbatim in the preferences field. "
        "Use ISO date (YYYY-MM-DD) and 24h HH:MM time."
    )


def test_staff_selection_prompt_has_the_business_rules_in_order():
    assert STAFF_SELECTION.version == "v2"
    text = STAFF_SELECTION.text
    # The five ranked rules, in priority order.
    for n, keyword in [
        ("1.", "skill matching"),
        ("2.", "lightest workload"),
        ("3.", "clusters next to"),
        ("4.", "nearest"),
        ("5.", "customer_preference"),
    ]:
        assert n in text and keyword in text
    positions = [text.index(f"{i}.") for i in range(1, 6)]
    assert positions == sorted(positions)
    # Hard guard: the model may only choose from the provided candidates.
    assert "Choose ONLY from the provided candidates" in text


def test_staff_selection_prompt_text_is_pinned():
    # Full snapshot — any edit must update this assertion deliberately.
    assert STAFF_SELECTION.text == (
        "You are a dispatcher choosing the best cleaner for a job. Apply these "
        "rules in priority order:\n"
        "1. The cleaner MUST have a skill matching the service.\n"
        "2. Prefer the lightest workload that day (fewest booked jobs).\n"
        "3. Prefer a schedule that clusters next to an existing booked time "
        "(reduces travel/idle).\n"
        "4. Prefer the nearest cleaner (smallest distance_km).\n"
        "5. Honor the customer_preference where possible (higher "
        "preference_similarity / matching bio).\n"
        "Choose ONLY from the provided candidates. Return the chosen staff_id "
        "and a one-sentence reason."
    )
