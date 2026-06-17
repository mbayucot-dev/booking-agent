"""The full booking workflow — the components assembled into one graph.

    chat_trigger -> extract -> validation
        invalid ───────────────────────────────────────────────► final_response
        valid -> customer -> availability_subgraph
                    escalate ───────────────────────────────────► final_response
                    found -> job_planning -> risk_review -> prepare_payloads
                          -> human_approval (interrupt)
                                rejected ────────────────────────► final_response
                                approved -> execution_agent -> hubspot -> email
                                         -> audit_log -> memory ──► final_response
    final_response -> END

Compiled with a checkpointer so the human_approval interrupt can pause and later
resume on the same thread (run) id. Every node is instrumented; the availability
subgraph emits its own sub-step events through the same sink.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ..services.embeddings import Embedder, NullEmbedder
from . import constants as C
from .audit import AuditWriter, NullAuditWriter
from .availability_provider import AvailabilityProvider, GenerativeFakeProvider
from .availability_subgraph import build_availability_subgraph
from .checkpointing import default_checkpointer
from .email import DryRunEmailSender, EmailSender
from .hubspot import ContactSync, DryRunContactSync
from .instrumentation import EventSink, NullEventSink, instrument
from .memory import InMemoryMemoryStore, MemoryStore
from .nodes.audit_log import make_audit_log
from .nodes.chat_trigger import chat_trigger
from .nodes.customer_agent import make_customer_agent
from .nodes.email_agent import make_email_agent
from .nodes.extract_booking_request import extract_booking_request
from .nodes.final_response import final_response
from .nodes.hubspot_agent import make_hubspot_agent
from .nodes.human_approval import (
    ActionExecutor,
    RecordingExecutor,
    make_execute_actions,
    make_human_approval,
    prepare_payloads,
)
from .nodes.job_planning_agent import make_job_planning_agent
from .nodes.memory_agent import make_memory_agent
from .nodes.risk_review_agent import risk_review_agent
from .nodes.validation_agent import validation_agent
from .state import BookingState

# Retry transient failures (LLM / external API / DB blips) on the I/O nodes.
# Idempotent by design (the execution node dedupes via the ledger), so safe.
_IO_RETRY = RetryPolicy(max_attempts=3)


def _route_after_validation(state: BookingState) -> str:
    return "ok" if state["validation"].ok else "invalid"


def _route_after_availability(state: BookingState) -> str:
    return "escalate" if state["availability"].escalate else "ok"


def build_workflow_graph(
    *,
    executor: ActionExecutor | None = None,
    email_sender: EmailSender | None = None,
    provider: AvailabilityProvider | None = None,
    sink: EventSink | None = None,
    audit_writer: AuditWriter | None = None,
    memory_store: MemoryStore | None = None,
    contact_sync: ContactSync | None = None,
    embedder: Embedder | None = None,
    rationale_llm: bool = False,
    checkpointer: BaseCheckpointSaver | None = None,
):
    executor = executor or RecordingExecutor()
    email_sender = email_sender or DryRunEmailSender()
    provider = provider or GenerativeFakeProvider()
    sink = sink or NullEventSink()
    audit_writer = audit_writer or NullAuditWriter()
    memory_store = memory_store or InMemoryMemoryStore()
    contact_sync = contact_sync or DryRunContactSync()
    embedder = embedder or NullEmbedder()
    checkpointer = checkpointer or default_checkpointer()

    def node(name, fn):
        return instrument(name, fn, sink)

    g = StateGraph(BookingState)
    g.add_node(C.CHAT_TRIGGER, node(C.CHAT_TRIGGER, chat_trigger))
    # extract calls the LLM; retry transient failures (it still rule-falls-back).
    g.add_node(C.EXTRACT, node(C.EXTRACT, extract_booking_request), retry_policy=_IO_RETRY)
    g.add_node(C.VALIDATION, node(C.VALIDATION, validation_agent))
    g.add_node(C.CUSTOMER, node(C.CUSTOMER, make_customer_agent(memory_store)))
    g.add_node(C.AVAILABILITY, build_availability_subgraph(provider, sink))
    g.add_node(
        C.JOB_PLANNING,
        node(
            C.JOB_PLANNING,
            make_job_planning_agent(provider, embedder=embedder, use_llm=rationale_llm),
        ),
        retry_policy=_IO_RETRY,  # embeddings + optional LLM rerank
    )
    g.add_node(C.RISK_REVIEW, node(C.RISK_REVIEW, risk_review_agent))
    g.add_node(C.PREPARE_PAYLOADS, node(C.PREPARE_PAYLOADS, prepare_payloads))
    g.add_node(C.HUMAN_APPROVAL, make_human_approval(sink))
    # Side-effecting nodes are NOT auto-retried at the node level on purpose:
    # execution is covered by the idempotency ledger + the run-level retry
    # endpoint, and email isn't idempotent (a node retry could double-send).
    g.add_node(C.EXECUTION, make_execute_actions(executor, sink))
    g.add_node(C.HUBSPOT, make_hubspot_agent(contact_sync, sink))
    g.add_node(C.EMAIL, make_email_agent(email_sender, sink))
    g.add_node(C.AUDIT_LOG, make_audit_log(audit_writer, sink))
    g.add_node(C.MEMORY, make_memory_agent(memory_store, sink))
    g.add_node(C.FINAL_RESPONSE, node(C.FINAL_RESPONSE, final_response))

    g.add_edge(START, C.CHAT_TRIGGER)
    g.add_edge(C.CHAT_TRIGGER, C.EXTRACT)
    g.add_edge(C.EXTRACT, C.VALIDATION)
    g.add_conditional_edges(
        C.VALIDATION,
        _route_after_validation,
        {"ok": C.CUSTOMER, "invalid": C.FINAL_RESPONSE},
    )
    g.add_edge(C.CUSTOMER, C.AVAILABILITY)
    g.add_conditional_edges(
        C.AVAILABILITY,
        _route_after_availability,
        {"ok": C.JOB_PLANNING, "escalate": C.FINAL_RESPONSE},
    )
    g.add_edge(C.JOB_PLANNING, C.RISK_REVIEW)
    g.add_edge(C.RISK_REVIEW, C.PREPARE_PAYLOADS)
    g.add_edge(C.PREPARE_PAYLOADS, C.HUMAN_APPROVAL)
    g.add_conditional_edges(
        C.HUMAN_APPROVAL,
        lambda s: s["approval_route"],
        {"approved": C.EXECUTION, "rejected": C.FINAL_RESPONSE},
    )
    g.add_edge(C.EXECUTION, C.HUBSPOT)
    g.add_edge(C.HUBSPOT, C.EMAIL)
    g.add_edge(C.EMAIL, C.AUDIT_LOG)
    g.add_edge(C.AUDIT_LOG, C.MEMORY)
    g.add_edge(C.MEMORY, C.FINAL_RESPONSE)
    g.add_edge(C.FINAL_RESPONSE, END)

    return g.compile(checkpointer=checkpointer)
