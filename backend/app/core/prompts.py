"""Central, versioned prompt registry — single source of truth for every LLM prompt.

Only the static instruction text lives here; per-request data is interpolated at
the call site, so untrusted content never goes through ``str.format``. Each
prompt carries a ``version`` and golden tests snapshot the text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


# 1st LLM call: free-text booking message → structured BookingRequest.
BOOKING_EXTRACTION = Prompt(
    name="booking_extraction",
    version="v2",
    text=(
        "Extract the booking request fields from this message. "
        "Capture any customer preferences/notes (e.g. 'calm with anxious dogs', "
        "'fragrance-free') verbatim in the preferences field. "
        "Use ISO date (YYYY-MM-DD) and 24h HH:MM time."
    ),
)

# 2nd LLM call: choose the best cleaner from the bounded top-K candidate set.
STAFF_SELECTION = Prompt(
    name="staff_selection",
    version="v2",
    text=(
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
    ),
)

# Every prompt, for iteration in tests / tooling.
ALL_PROMPTS: tuple[Prompt, ...] = (BOOKING_EXTRACTION, STAFF_SELECTION)
