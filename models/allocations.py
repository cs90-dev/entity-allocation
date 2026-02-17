"""Allocation and override data models."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from ceviche.db.database import Base


class Allocation(Base):
    __tablename__ = "allocations"

    allocation_id = Column(Integer, primary_key=True, autoincrement=True)
    expense_id = Column(Integer, ForeignKey("expenses.expense_id"), nullable=False)
    target_entity_id = Column(Integer, ForeignKey("entities.entity_id"), nullable=False)
    allocated_amount = Column(Float, nullable=False)
    allocation_percentage = Column(Float, nullable=False)
    methodology_used = Column(String, nullable=False)
    allocation_date = Column(DateTime, default=datetime.utcnow)
    journal_entry_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    expense = relationship("Expense", back_populates="allocations")
    target_entity = relationship("Entity", back_populates="allocations")

    def __repr__(self):
        return (
            f"<Allocation(id={self.allocation_id}, expense={self.expense_id}, "
            f"entity={self.target_entity_id}, amount={self.allocated_amount})>"
        )

    def to_dict(self):
        return {
            "allocation_id": self.allocation_id,
            "expense_id": self.expense_id,
            "target_entity_id": self.target_entity_id,
            "allocated_amount": self.allocated_amount,
            "allocation_percentage": self.allocation_percentage,
            "methodology_used": self.methodology_used,
            "allocation_date": self.allocation_date.isoformat() if self.allocation_date else None,
            "journal_entry_reference": self.journal_entry_reference,
        }


class AllocationOverride(Base):
    __tablename__ = "allocation_overrides"

    override_id = Column(Integer, primary_key=True, autoincrement=True)
    expense_id = Column(Integer, ForeignKey("expenses.expense_id"), nullable=False)
    reason = Column(Text, nullable=False)
    override_by = Column(String, nullable=True)
    original_allocation = Column(Text, default="{}")  # JSON
    new_allocation = Column(Text, default="{}")  # JSON
    approval_status = Column(String, default="pending")
    approved_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    expense = relationship("Expense", foreign_keys=[expense_id])

    def get_original(self) -> dict:
        return json.loads(self.original_allocation or "{}")

    def get_new(self) -> dict:
        return json.loads(self.new_allocation or "{}")

    def __repr__(self):
        return f"<AllocationOverride(id={self.override_id}, expense={self.expense_id})>"
