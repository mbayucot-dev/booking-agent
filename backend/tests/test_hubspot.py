"""HubSpot contact sync: client (mocked HTTP), factory, node, and gating."""

import httpx
import pytest

from app.config import Settings
from app.graph.hubspot import DryRunContactSync
from app.graph.nodes.hubspot_agent import make_hubspot_agent
from app.graph.state import BookingRequest
from app.services.hubspot import HubSpotClient, HubSpotConfig, build_contact_sync

REQ = BookingRequest(
    customer_name="John Doe", email="john@example.com", phone="0400000000", address="12 Queen St"
)


def _client(handler) -> HubSpotClient:
    cfg = HubSpotConfig(access_token="tok")
    return HubSpotClient(cfg, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_client_creates_contact():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        captured["path"] = request.url.path
        return httpx.Response(201, json={"id": "hs-1"})

    res = _client(handler).sync_contact({"email": "a@x.com", "firstname": "A", "phone": None})
    assert res == {"id": "hs-1", "provider": "hubspot"}
    assert captured["path"].endswith("/crm/v3/objects/contacts")
    assert captured["body"]["properties"] == {"email": "a@x.com", "firstname": "A"}  # None dropped


def test_client_treats_409_as_existing():
    res = _client(lambda r: httpx.Response(409)).sync_contact({"email": "a@x.com"})
    assert res["status"] == "exists"


def test_client_raises_on_error():
    with pytest.raises(httpx.HTTPStatusError):
        _client(lambda r: httpx.Response(500)).sync_contact({"email": "a@x.com"})


def test_config_requires_token():
    with pytest.raises(ValueError):
        HubSpotConfig.from_settings(Settings())


def test_factory_dryrun_without_token_real_with_token():
    assert isinstance(build_contact_sync(Settings()), DryRunContactSync)
    assert isinstance(build_contact_sync(Settings(hubspot_access_token="t")), HubSpotClient)


def test_feature_flag_forces_dryrun_even_with_token():
    # Standalone-test mode: token present but the flag disables the real push.
    s = Settings(hubspot_access_token="t", feature_hubspot_sync=False)
    assert s.hubspot_configured is True
    assert s.hubspot_sync_enabled is False
    assert isinstance(build_contact_sync(s), DryRunContactSync)


# --- node -----------------------------------------------------------------


def test_node_syncs_contact_and_splits_name():
    sync = DryRunContactSync()
    node = make_hubspot_agent(sync)
    out = node({"run_id": "r", "booking_request": REQ})
    assert out["hubspot"]["synced"] is True
    assert sync.synced[0] == {
        "email": "john@example.com",
        "firstname": "John",
        "lastname": "Doe",
        "phone": "0400000000",
        "address": "12 Queen St",
    }


def test_node_skips_without_email():
    sync = DryRunContactSync()
    out = make_hubspot_agent(sync)(
        {"run_id": "r", "booking_request": BookingRequest(customer_name="X")}
    )
    assert out["hubspot"]["synced"] is False
    assert sync.synced == []


# --- workflow integration -------------------------------------------------


def test_workflow_pushes_contact_after_approval(Session):
    from app.graph.email import DryRunEmailSender
    from app.services.run_service import WorkflowRunner
    from tests.helpers import make_booking_executor, make_provider

    sync = DryRunContactSync()
    runner = WorkflowRunner(
        session_factory=Session,
        executor=make_booking_executor(Session),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
        contact_sync=sync,
    )
    message = (
        "Create a booking for John Doe for contact work on December 20, 2028 at 10am. "
        "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
    )
    started = runner.start(message)
    assert sync.synced == []  # not before approval
    runner.resume(started.run_id, approved=True)
    assert len(sync.synced) == 1  # contact pushed after the job is confirmed
    assert sync.synced[0]["email"] == "john@example.com"
