"""Approval gate graph.

A focused, compilable graph that demonstrates the human-in-the-loop gate::

    prepare_payloads -> human_approval --(approved)--> execution_agent
                                       |                  -> email -> audit_log -> END
                                       \\-(rejected)--> handle_rejection -> END

Compiled with a checkpointer so ``interrupt()`` can pause and later resume on
the same ``thread_id``. The mutation executor is injected so tests can prove no
mutation runs before approval.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import constants as C
from .audit import AuditWriter, NullAuditWriter
from .checkpointing import default_checkpointer
from .email import DryRunEmailSender, EmailSender
from .instrumentation import EventSink, NullEventSink, instrument
from .nodes.audit_log import make_audit_log
from .nodes.email_agent import make_email_agent
from .nodes.human_approval import (
    ActionExecutor,
    RecordingExecutor,
    make_execute_actions,
    make_handle_rejection,
    make_human_approval,
    prepare_payloads,
)
from .state import BookingState


def build_approval_graph(
    executor: ActionExecutor | None = None,
    sink: EventSink | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    audit_writer: AuditWriter | None = None,
    email_sender: EmailSender | None = None,
):
    executor = executor or RecordingExecutor()
    sink = sink or NullEventSink()
    checkpointer = checkpointer or default_checkpointer()
    audit_writer = audit_writer or NullAuditWriter()
    email_sender = email_sender or DryRunEmailSender()

    g = StateGraph(BookingState)
    g.add_node(C.PREPARE_PAYLOADS, instrument(C.PREPARE_PAYLOADS, prepare_payloads, sink))
    g.add_node(C.HUMAN_APPROVAL, make_human_approval(sink))
    g.add_node(C.EXECUTION, make_execute_actions(executor, sink))
    g.add_node(C.EMAIL, make_email_agent(email_sender, sink))
    g.add_node(C.AUDIT_LOG, make_audit_log(audit_writer, sink))
    g.add_node(C.HANDLE_REJECTION, make_handle_rejection(sink))

    g.add_edge(START, C.PREPARE_PAYLOADS)
    g.add_edge(C.PREPARE_PAYLOADS, C.HUMAN_APPROVAL)
    g.add_conditional_edges(
        C.HUMAN_APPROVAL,
        lambda s: s["approval_route"],
        {"approved": C.EXECUTION, "rejected": C.HANDLE_REJECTION},
    )
    # Approved path: execute mutations, send the confirmation email, then audit.
    g.add_edge(C.EXECUTION, C.EMAIL)
    g.add_edge(C.EMAIL, C.AUDIT_LOG)
    g.add_edge(C.AUDIT_LOG, END)
    g.add_edge(C.HANDLE_REJECTION, END)

    return g.compile(checkpointer=checkpointer)
