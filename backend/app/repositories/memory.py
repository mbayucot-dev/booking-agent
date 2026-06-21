"""Repository for long-term customer memory (upsert by customer_key+type)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CustomerMemory


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, customer_key: str, memory_type: str, content: dict) -> CustomerMemory:
        row = CustomerMemory(
            customer_key=customer_key, memory_type=memory_type, content=content
        )
        self.session.add(row)
        try:
            self.session.commit()
            return row
        except IntegrityError:
            # uq_customer_memory: a concurrent writer inserted the same key first.
            # Rollback, re-read the winner, and update its content.
            self.session.rollback()
            row = self.session.scalar(
                select(CustomerMemory).where(
                    CustomerMemory.customer_key == customer_key,
                    CustomerMemory.memory_type == memory_type,
                )
            )
            if row is None:
                raise
            row.content = content
            self.session.commit()
            return row

    def list_for(self, customer_key: str) -> list[CustomerMemory]:
        return list(
            self.session.scalars(
                select(CustomerMemory)
                .where(CustomerMemory.customer_key == customer_key)
                .order_by(CustomerMemory.memory_type)
            )
        )
