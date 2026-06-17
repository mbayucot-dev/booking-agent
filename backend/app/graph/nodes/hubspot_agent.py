"""hubspot_agent — push the customer contact to HubSpot after the job is confirmed (post-approval).

Uses the injected ContactSync (real HubSpot client when configured, else
dry-run). Skips cleanly when there's no email.
"""

from __future__ import annotations

from .. import constants as C
from ..hubspot import ContactSync, DryRunContactSync
from ..instrumentation import EventSink, NullEventSink, instrument
from ..state import BookingState


def make_hubspot_agent(sync: ContactSync | None = None, sink: EventSink | None = None):
    sync = sync or DryRunContactSync()
    sink = sink or NullEventSink()

    def hubspot_agent(state: BookingState) -> BookingState:
        req = state.get("booking_request")
        if req is None or not req.email:
            return {"hubspot": {"synced": False, "skipped": "no email"}}
        first, _, last = (req.customer_name or "").partition(" ")
        contact = {
            "email": req.email,
            "firstname": first,
            "lastname": last,
            "phone": req.phone,
            "address": req.address,
        }
        result = sync.sync_contact(contact)
        return {
            "hubspot": {
                "synced": True,
                "id": result.get("id"),
                "provider": result.get("provider"),
            }
        }

    return instrument(C.HUBSPOT, hubspot_agent, sink)
