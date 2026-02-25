"""Allocation policy data model."""
import json
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SAEnum

from ceviche.db.database import Base


class AllocationMethod(str, enum.Enum):
    PRO_RATA_AUM = "pro_rata_aum"
    PRO_RATA_COMMITTED = "pro_rata_committed"
    PRO_RATA_INVESTED = "pro_rata_invested"
    DIRECT = "direct"
    HEADCOUNT = "headcount"
    CUSTOM_SPLIT = "custom_split"
    DEAL_SPECIFIC = "deal_specific"


class AllocationPolicy(Base):
    __tablename__ = "allocation_policies"

    policy_id = Column(Integer, primary_key=True, autoincrement=True)
    policy_name = Column(String, nullable=False, unique=True)
    methodology = Column(SAEnum(AllocationMethod), nullable=False)
    applicable_expense_categories = Column(Text, default="[]")  # JSON array
    entity_splits = Column(Text, default="{}")  # JSON: entity_id -> percentage
    target_entity_id = Column(Integer, nullable=True)  # For direct/deal_specific
    effective_date = Column(DateTime, default=datetime.utcnow)
    expiration_date = Column(DateTime, nullable=True)
    lpa_reference = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_categories(self) -> list:
        return json.loads(self.applicable_expense_categories or "[]")

    def set_categories(self, categories: list):
        self.applicable_expense_categories = json.dumps(categories)

    def get_splits(self) -> dict:
        return json.loads(self.entity_splits or "{}")

    def set_splits(self, splits: dict):
        self.entity_splits = json.dumps(splits)

    def __repr__(self):
        return f"<AllocationPolicy(id={self.policy_id}, name='{self.policy_name}', method={self.methodology})>"

    def to_dict(self):
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "methodology": self.methodology.value if self.methodology else None,
            "categories": self.get_categories(),
            "entity_splits": self.get_splits(),
            "target_entity_id": self.target_entity_id,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "lpa_reference": self.lpa_reference,
        }
