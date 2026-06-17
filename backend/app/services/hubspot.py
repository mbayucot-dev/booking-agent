"""HubSpot CRM client — pushes the customer contact after a job is confirmed.

Real HTTP (httpx, lazy import) against the HubSpot CRM v3 API using a private-app
token. Activated when HUBSPOT_ACCESS_TOKEN is set; otherwise the workflow uses
the dry-run sync. Conforms to the graph's ``ContactSync`` protocol.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings, get_settings
from ..graph.hubspot import ContactSync, DryRunContactSync


@dataclass
class HubSpotConfig:
    access_token: str
    base_url: str = "https://api.hubapi.com"

    @classmethod
    def from_settings(cls, s: Settings) -> HubSpotConfig:
        if not s.hubspot_configured:
            raise ValueError("Missing HUBSPOT_ACCESS_TOKEN")
        return cls(access_token=s.hubspot_access_token, base_url=s.hubspot_base_url)


class HubSpotClient:
    """Creates/updates a HubSpot contact. Conforms to ContactSync."""

    def __init__(self, config: HubSpotConfig, http=None):
        if http is None:
            import httpx

            http = httpx.Client(
                timeout=30.0,
                headers={"Authorization": f"Bearer {config.access_token}"},
            )
        self._http = http
        self._base = config.base_url.rstrip("/")

    def sync_contact(self, contact: dict) -> dict:
        # contact: {email, firstname, lastname, phone, address}
        resp = self._http.post(
            f"{self._base}/crm/v3/objects/contacts",
            json={"properties": {k: v for k, v in contact.items() if v}},
        )
        if resp.status_code == 409:  # already exists — idempotent no-op
            return {"id": None, "provider": "hubspot", "status": "exists"}
        resp.raise_for_status()
        return {"id": resp.json().get("id"), "provider": "hubspot"}


def build_contact_sync(settings: Settings | None = None) -> ContactSync:
    settings = settings or get_settings()
    # Real push only when the feature flag is on AND a token is configured;
    # otherwise dry-run so the whole flow runs standalone.
    if settings.hubspot_sync_enabled:
        return HubSpotClient(HubSpotConfig.from_settings(settings))
    return DryRunContactSync()
