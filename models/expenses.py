"""Expense data model."""
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import relationship

from ceviche.db.database import Base


class ExpenseCategory(str, enum.Enum):
    LEGAL = "legal"
    ACCOUNTING = "accounting"
    TRAVEL = "travel"
    COMPLIANCE = "compliance"
    INSURANCE = "insurance"
    TECHNOLOGY = "technology"
    RENT = "rent"
    PERSONNEL = "personnel"
    DEAL_EXPENSE = "deal_expense"
    BROKEN_DEAL = "broken_deal"
    FUND_FORMATION = "fund_formation"
    ORGANIZATIONAL = "organizational"
    DUE_DILIGENCE = "due_diligence"
    CONSULTING = "consulting"
    OTHER = "other"


class ExpenseStatus(str, enum.Enum):
    PENDING = "pending"
    ALLOCATED = "allocated"
    REVIEWED = "reviewed"
    POSTED = "posted"


class Expense(Base):
    __tablename__ = "expenses"

    expense_id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    vendor = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    expense_category = Column(SAEnum(ExpenseCategory), nullable=True)
    source_entity_id = Column(Integer, ForeignKey("entities.entity_id"), nullable=True)
    allocation_policy_id = Column(Integer, ForeignKey("allocation_policies.policy_id"), nullable=True)
    status = Column(SAEnum(ExpenseStatus), default=ExpenseStatus.PENDING, nullable=False)
    gl_account_code = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    allocation_policy = relationship("AllocationPolicy", foreign_keys=[allocation_policy_id])
    allocations = relationship("Allocation", back_populates="expense", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Expense(id={self.expense_id}, vendor='{self.vendor}', amount={self.amount})>"

    def to_dict(self):
        return {
            "expense_id": self.expense_id,
            "date": self.date.strftime("%Y-%m-%d") if self.date else None,
            "vendor": self.vendor,
            "description": self.description,
            "amount": self.amount,
            "currency": self.currency,
            "expense_category": self.expense_category.value if self.expense_category else None,
            "source_entity_id": self.source_entity_id,
            "allocation_policy_id": self.allocation_policy_id,
            "status": self.status.value if self.status else None,
            "gl_account_code": self.gl_account_code,
            "notes": self.notes,
        }
