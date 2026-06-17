"""Canonical workflow node names.

Single source of truth for node identity: the backend graph, the supervisor
router, and the React Flow node definitions all reference the same names so the
live canvas can map run_events → nodes by id.
"""

from __future__ import annotations

CHAT_TRIGGER = "chat_trigger"
SUPERVISOR = "supervisor_agent"
EXTRACT = "extract_booking_request"
VALIDATION = "validation_agent"

CUSTOMER = "customer_agent"
AVAILABILITY = "availability_subgraph"
JOB_PLANNING = "job_planning_agent"
COMMUNICATION = "communication_agent"
RISK_REVIEW = "risk_review_agent"
HUMAN_APPROVAL = "human_approval"
EXECUTION = "execution_agent"  # books into the local datastore (post-approval)
HUBSPOT = "hubspot_agent"  # push contact to HubSpot CRM (post-approval)
EMAIL = "email_agent"
AUDIT_LOG = "audit_log"
MEMORY = "memory_agent"
FINAL_RESPONSE = "final_response"

# --- Availability subgraph sub-steps ---
AV_CHECK_REQUESTED = "check_requested_slot"
AV_SEARCH_STAFF = "search_same_day_staff"
AV_SEARCH_SAME_DAY = "search_same_day_slots"
AV_SEARCH_NEXT_DAY = "search_next_day_slots"
AV_RANK = "rank_alternative_slots"
AV_DECISION = "alternative_decision"

# Availability loop limits.
AV_MAX_ATTEMPTS = 3
AV_MAX_SEARCH_DAYS = 7

# --- Human approval gate ---
PREPARE_PAYLOADS = "prepare_payloads"  # builds prepared (un-executed) actions
HANDLE_REJECTION = "handle_rejection"

# Mutating actions that may only execute *after* human approval.
MUTATING_ACTIONS: frozenset[str] = frozenset(
    {
        "create_client",
        "create_contact",
        "create_job",
        "schedule_job",
        "send_confirmation_email",
        "refund",
        "cancel",
    }
)

# Linear progression the supervisor walks.
PHASE_1_ORDER: tuple[str, ...] = (EXTRACT, VALIDATION)
