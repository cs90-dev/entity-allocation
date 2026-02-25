"""Entity data model for PE firm legal entities."""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from ceviche.db.database import Base


class EntityType(str, enum.Enum):
    GP = "GP"
    FUND = "Fund"
    PORTCO = "PortCo"
    SPV = "SPV"


class EntityStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LIQUIDATED = "liquidated"


class Entity(Base):
    __tablename__ = "entities"

    entity_id = Column(Integer, primary_key=True, autoincrement=True)
    entity_name = Column(String, nullable=False, unique=True)
    entity_type = Column(SAEnum(EntityType), nullable=False)
    status = Column(SAEnum(EntityStatus), default=EntityStatus.ACTIVE, nullable=False)
    committed_capital = Column(Float, default=0.0)
    invested_capital = Column(Float, default=0.0)
    aum = Column(Float, default=0.0)
    headcount = Column(Float, default=0.0)
    parent_entity_id = Column(Integer, ForeignKey("entities.entity_id"), nullable=True)
    vintage_year = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("Entity", remote_side=[entity_id], backref="children")
    allocations = relationship("Allocation", back_populates="target_entity")

    def __repr__(self):
        return f"<Entity(id={self.entity_id}, name='{self.entity_name}', type={self.entity_type})>"

    def to_dict(self):
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type.value if self.entity_type else None,
            "status": self.status.value if self.status else None,
            "committed_capital": self.committed_capital,
            "invested_capital": self.invested_capital,
            "aum": self.aum,
            "headcount": self.headcount,
            "parent_entity_id": self.parent_entity_id,
            "vintage_year": self.vintage_year,
        }
