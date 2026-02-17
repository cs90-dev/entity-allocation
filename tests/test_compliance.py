"""Tests for the LPA compliance engine."""
import pytest
from datetime import datetime

from ceviche.engine.compliance import ComplianceEngine
from ceviche.engine.allocator import AllocationEngine
from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.allocations import Allocation


@pytest.fixture
def compliance_config():
    return {
        "lpa_rules": {
            "funds": {
                "Test Fund I": {
                    "management_fee_cap_pct": 2.0,
                    "org_expense_cap": 500_000,
                    "broken_deal_limit": 200_000,
                    "annual_expense_cap": 2_000_000,
                },
            }
        }
    }


@pytest.fixture
def compliance_entities(db_session):
    gp = Entity(
        entity_name="Compliance GP",
        entity_type=EntityType.GP,
        status=EntityStatus.ACTIVE,
        aum=50_000_000,
    )
    fund = Entity(
        entity_name="Test Fund I",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=100_000_000,
        aum=90_000_000,
    )
    db_session.add_all([gp, fund])
    db_session.flush()
    return {"gp": gp, "fund": fund}


class TestComplianceChecks:
    def test_no_violations_when_under_limits(self, db_session, compliance_entities, compliance_config):
        engine = ComplianceEngine(db_session, compliance_config)
        violations = engine.check_fund_compliance("Test Fund I", 2025)
        # No allocations = no violations
        assert len(violations) == 0

    def test_org_expense_cap_violation(self, db_session, compliance_entities, compliance_config):
        fund = compliance_entities["fund"]

        # Create allocation that exceeds org expense cap
        expense = Expense(
            date=datetime(2025, 3, 1),
            vendor="Formation Vendor",
            amount=600_000,
            expense_category=ExpenseCategory.ORGANIZATIONAL,
            status=ExpenseStatus.ALLOCATED,
        )
        db_session.add(expense)
        db_session.flush()

        alloc = Allocation(
            expense_id=expense.expense_id,
            target_entity_id=fund.entity_id,
            allocated_amount=600_000,
            allocation_percentage=100,
            methodology_used="direct",
        )
        db_session.add(alloc)
        db_session.commit()

        engine = ComplianceEngine(db_session, compliance_config)
        violations = engine.check_fund_compliance("Test Fund I", 2025)

        org_violations = [v for v in violations if v.rule_name == "Organizational Expense Cap"]
        assert len(org_violations) == 1
        assert org_violations[0].excess == 100_000

    def test_check_all_funds(self, db_session, compliance_entities, compliance_config):
        engine = ComplianceEngine(db_session, compliance_config)
        results = engine.check_all_funds(2025)

        assert "Test Fund I" in results
        assert results["Test Fund I"]["compliant"] is True

    def test_fund_not_found(self, db_session, compliance_config):
        engine = ComplianceEngine(db_session, compliance_config)
        violations = engine.check_fund_compliance("Nonexistent Fund", 2025)
        assert len(violations) == 0
