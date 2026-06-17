"""HubSpot contact-sync seam for the graph layer.

Like the email/audit seams, the graph depends on an abstract ``ContactSync``,
not on HubSpot. The real client lives in the services layer; tests/dev use
:class:`DryRunContactSync`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ContactSync(Protocol):
    def sync_contact(self, contact: dict) -> dict: ...


@dataclass
class DryRunContactSync:
    """Records contacts instead of pushing to a CRM (default until configured)."""

    synced: list[dict] = field(default_factory=list)

    def sync_contact(self, contact: dict) -> dict:
        self.synced.append(contact)
        return {"id": None, "provider": "dry-run", "dry_run": True}
