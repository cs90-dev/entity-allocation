"""Shared test fixtures."""
import json
import os
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ceviche.db.database import Base
from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus

# Import all models so they register with Base
import ceviche.models.allocations  # noqa: F401


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_session(db_session):
    """Session pre-loaded with Apex Capital seed data."""
    from ceviche.tests.fixtures.sample_data import load_seed_data
    load_seed_data(db_session)
    return db_session


@pytest.fixture
def sample_entities(db_session):
    """Create a minimal set of entities for testing."""
    gp = Entity(
        entity_name="Test GP LLC",
        entity_type=EntityType.GP,
        status=EntityStatus.ACTIVE,
        headcount=10,
    )
    db_session.add(gp)
    db_session.flush()

    fund1 = Entity(
        entity_name="Test Fund I",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=100_000_000,
        invested_capital=80_000_000,
        aum=90_000_000,
        headcount=3,
        parent_entity_id=gp.entity_id,
    )
    fund2 = Entity(
        entity_name="Test Fund II",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=200_000_000,
        invested_capital=120_000_000,
        aum=180_000_000,
        headcount=7,
        parent_entity_id=gp.entity_id,
    )
    db_session.add_all([fund1, fund2])
    db_session.flush()

    return {"gp": gp, "fund1": fund1, "fund2": fund2}


@pytest.fixture
def sample_policy_aum(db_session):
    """Create a pro-rata AUM policy."""
    policy = AllocationPolicy(
        policy_name="Test AUM Policy",
        methodology=AllocationMethod.PRO_RATA_AUM,
        applicable_expense_categories=json.dumps(["rent", "technology"]),
    )
    db_session.add(policy)
    db_session.flush()
    return policy


@pytest.fixture
def sample_policy_committed(db_session):
    """Create a pro-rata committed capital policy."""
    policy = AllocationPolicy(
        policy_name="Test Committed Policy",
        methodology=AllocationMethod.PRO_RATA_COMMITTED,
        applicable_expense_categories=json.dumps(["legal"]),
    )
    db_session.add(policy)
    db_session.flush()
    return policy


@pytest.fixture
def sample_expense(db_session, sample_entities):
    """Create a sample expense."""
    from datetime import datetime
    expense = Expense(
        date=datetime(2025, 1, 15),
        vendor="Test Vendor",
        description="Test expense",
        amount=100_000,
        currency="USD",
        expense_category=ExpenseCategory.RENT,
        source_entity_id=sample_entities["gp"].entity_id,
        status=ExpenseStatus.PENDING,
    )
    db_session.add(expense)
    db_session.flush()
    return expense


@pytest.fixture
def csv_file(tmp_path):
    """Create a temporary CSV file for import testing."""
    content = """date,vendor,description,amount,currency,category,entity_paid,gl_account,notes
2025-01-15,Kirkland & Ellis,Formation docs,150000,USD,legal,,6100,Fund III formation
2025-01-20,PwC,Annual audit,120000,USD,accounting,,6200,
2025-02-01,Bloomberg,Terminal license,24000,USD,technology,,6600,8 seats
2025-02-15,Delta Airlines,Deal travel,8500,USD,travel,,6300,Project Alpha
2025-03-01,Brookfield,Office rent,125000,USD,rent,,6700,NYC office
"""
    csv_path = tmp_path / "test_expenses.csv"
    csv_path.write_text(content)
    return str(csv_path)
