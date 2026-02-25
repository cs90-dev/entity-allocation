"""Tests for the core allocation engine."""
import json
import pytest
from datetime import datetime

from ceviche.engine.allocator import AllocationEngine, AllocationError
from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.allocations import Allocation


class TestProRataAUM:
    """Test pro-rata AUM allocation methodology."""

    def test_basic_aum_allocation(self, db_session, sample_entities, sample_policy_aum, sample_expense):
        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(sample_expense, sample_policy_aum, preview=True)

        assert len(splits) == 2
        # Fund I: 90M AUM, Fund II: 180M AUM -> 1/3 and 2/3
        total_aum = 90_000_000 + 180_000_000
        expected_f1 = round(100_000 * 90_000_000 / total_aum, 2)
        expected_f2 = round(100_000 * 180_000_000 / total_aum, 2)

        f1_split = next(s for s in splits if s["entity_name"] == "Test Fund I")
        f2_split = next(s for s in splits if s["entity_name"] == "Test Fund II")

        assert abs(f1_split["amount"] - expected_f1) < 0.02
        assert abs(f2_split["amount"] - expected_f2) < 0.02

    def test_amounts_sum_to_total(self, db_session, sample_entities, sample_policy_aum, sample_expense):
        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(sample_expense, sample_policy_aum, preview=True)

        total_allocated = sum(s["amount"] for s in splits)
        assert abs(total_allocated - sample_expense.amount) < 0.01

    def test_percentages_sum_to_100(self, db_session, sample_entities, sample_policy_aum, sample_expense):
        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(sample_expense, sample_policy_aum, preview=True)

        total_pct = sum(s["percentage"] for s in splits)
        assert abs(total_pct - 100.0) < 0.1


class TestProRataCommitted:
    """Test pro-rata committed capital allocation."""

    def test_committed_capital_allocation(self, db_session, sample_entities, sample_policy_committed):
        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Kirkland & Ellis",
            description="Legal review",
            amount=60_000,
            currency="USD",
            expense_category=ExpenseCategory.LEGAL,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(expense, sample_policy_committed, preview=True)

        # Fund I: 100M committed, Fund II: 200M committed -> 1/3 and 2/3
        f1_split = next(s for s in splits if s["entity_name"] == "Test Fund I")
        f2_split = next(s for s in splits if s["entity_name"] == "Test Fund II")

        assert abs(f1_split["amount"] - 20_000) < 0.01
        assert abs(f2_split["amount"] - 40_000) < 0.01


class TestDirectCharge:
    """Test direct charge allocation."""

    def test_direct_charge_100_pct(self, db_session, sample_entities):
        policy = AllocationPolicy(
            policy_name="Direct to Fund I",
            methodology=AllocationMethod.DIRECT,
            target_entity_id=sample_entities["fund1"].entity_id,
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Test Vendor",
            amount=50_000,
            expense_category=ExpenseCategory.FUND_FORMATION,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(expense, policy, preview=True)

        assert len(splits) == 1
        assert splits[0]["entity_id"] == sample_entities["fund1"].entity_id
        assert splits[0]["percentage"] == 100.0
        assert splits[0]["amount"] == 50_000


class TestCustomSplit:
    """Test custom percentage split allocation."""

    def test_custom_split_allocation(self, db_session, sample_entities):
        policy = AllocationPolicy(
            policy_name="Custom 60/40",
            methodology=AllocationMethod.CUSTOM_SPLIT,
            entity_splits=json.dumps({
                str(sample_entities["fund1"].entity_id): 0.6,
                str(sample_entities["fund2"].entity_id): 0.4,
            }),
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="McKinsey",
            amount=100_000,
            expense_category=ExpenseCategory.CONSULTING,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(expense, policy, preview=True)

        f1_split = next(s for s in splits if s["entity_id"] == sample_entities["fund1"].entity_id)
        f2_split = next(s for s in splits if s["entity_id"] == sample_entities["fund2"].entity_id)

        assert abs(f1_split["amount"] - 60_000) < 0.01
        assert abs(f2_split["amount"] - 40_000) < 0.01

    def test_custom_split_invalid_sum(self, db_session, sample_entities):
        policy = AllocationPolicy(
            policy_name="Bad Split",
            methodology=AllocationMethod.CUSTOM_SPLIT,
            entity_splits=json.dumps({
                str(sample_entities["fund1"].entity_id): 0.5,
                str(sample_entities["fund2"].entity_id): 0.3,
            }),
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Test",
            amount=100_000,
            expense_category=ExpenseCategory.OTHER,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        with pytest.raises(AllocationError, match="not 100%"):
            engine.allocate_expense(expense, policy, preview=True)


class TestHeadcountAllocation:
    """Test headcount-based allocation."""

    def test_headcount_allocation(self, db_session, sample_entities):
        policy = AllocationPolicy(
            policy_name="Headcount",
            methodology=AllocationMethod.HEADCOUNT,
            applicable_expense_categories=json.dumps(["personnel"]),
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 31),
            vendor="ADP",
            amount=100_000,
            expense_category=ExpenseCategory.PERSONNEL,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(expense, policy, preview=True)

        # GP: 10 HC, Fund I: 3 HC, Fund II: 7 HC -> total 20
        total_hc = 10 + 3 + 7
        gp_split = next(s for s in splits if s["entity_name"] == "Test GP LLC")
        assert abs(gp_split["percentage"] - (10 / total_hc * 100)) < 0.1


class TestAllocationPersistence:
    """Test that allocations are properly persisted."""

    def test_allocation_creates_records(self, db_session, sample_entities, sample_policy_aum, sample_expense):
        engine = AllocationEngine(db_session)
        engine.allocate_expense(sample_expense, sample_policy_aum, preview=False)

        allocations = db_session.query(Allocation).filter(
            Allocation.expense_id == sample_expense.expense_id
        ).all()

        assert len(allocations) == 2
        assert sample_expense.status == ExpenseStatus.ALLOCATED

    def test_allocation_journal_entry_refs(self, db_session, sample_entities, sample_policy_aum, sample_expense):
        engine = AllocationEngine(db_session)
        engine.allocate_expense(sample_expense, sample_policy_aum, preview=False)

        allocations = db_session.query(Allocation).filter(
            Allocation.expense_id == sample_expense.expense_id
        ).all()

        for a in allocations:
            assert a.journal_entry_reference is not None
            assert a.journal_entry_reference.startswith("JE-")


class TestPolicyResolution:
    """Test automatic policy resolution by category."""

    def test_resolves_policy_by_category(self, db_session, sample_entities, sample_policy_aum):
        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Bloomberg",
            amount=24_000,
            expense_category=ExpenseCategory.TECHNOLOGY,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        # Should auto-resolve to sample_policy_aum which covers "technology"
        splits = engine.allocate_expense(expense, preview=True)
        assert len(splits) == 2

    def test_no_policy_raises_error(self, db_session, sample_entities):
        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Unknown",
            amount=1000,
            expense_category=ExpenseCategory.OTHER,
            source_entity_id=sample_entities["gp"].entity_id,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        with pytest.raises(AllocationError, match="No allocation policy"):
            engine.allocate_expense(expense, preview=True)


class TestMonthlyAllocation:
    """Test batch monthly allocation."""

    def test_allocate_month(self, db_session, sample_entities, sample_policy_aum):
        # Create multiple expenses in Jan 2025
        for i in range(5):
            expense = Expense(
                date=datetime(2025, 1, 10 + i),
                vendor=f"Vendor {i}",
                amount=10_000 * (i + 1),
                expense_category=ExpenseCategory.TECHNOLOGY,
                source_entity_id=sample_entities["gp"].entity_id,
                status=ExpenseStatus.PENDING,
            )
            db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        results = engine.allocate_month(2025, 1, preview=False)

        assert len(results["allocated"]) == 5
        assert len(results["errors"]) == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_aum_raises_error(self, db_session):
        gp = Entity(
            entity_name="Zero GP",
            entity_type=EntityType.GP,
            status=EntityStatus.ACTIVE,
            aum=0,
        )
        fund = Entity(
            entity_name="Zero Fund",
            entity_type=EntityType.FUND,
            status=EntityStatus.ACTIVE,
            aum=0,
        )
        db_session.add_all([gp, fund])
        db_session.flush()

        policy = AllocationPolicy(
            policy_name="AUM Zero",
            methodology=AllocationMethod.PRO_RATA_AUM,
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Test",
            amount=50_000,
            expense_category=ExpenseCategory.RENT,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        with pytest.raises(AllocationError, match="zero"):
            engine.allocate_expense(expense, policy, preview=True)

    def test_liquidated_entity_excluded_from_custom(self, db_session, sample_entities):
        sample_entities["fund1"].status = EntityStatus.LIQUIDATED
        db_session.flush()

        policy = AllocationPolicy(
            policy_name="Split with Liquidated",
            methodology=AllocationMethod.CUSTOM_SPLIT,
            entity_splits=json.dumps({
                str(sample_entities["fund1"].entity_id): 0.5,
                str(sample_entities["fund2"].entity_id): 0.5,
            }),
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Test",
            amount=100_000,
            expense_category=ExpenseCategory.OTHER,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        with pytest.raises(AllocationError, match="liquidated"):
            engine.allocate_expense(expense, policy, preview=True)

    def test_rounding_preserves_total(self, db_session):
        """Test that rounding always preserves the total amount."""
        # Create 3 entities with uneven AUM to force rounding
        gp = Entity(entity_name="R GP", entity_type=EntityType.GP, status=EntityStatus.ACTIVE, aum=33)
        f1 = Entity(entity_name="R F1", entity_type=EntityType.FUND, status=EntityStatus.ACTIVE, aum=33)
        f2 = Entity(entity_name="R F2", entity_type=EntityType.FUND, status=EntityStatus.ACTIVE, aum=34)
        db_session.add_all([gp, f1, f2])
        db_session.flush()

        policy = AllocationPolicy(
            policy_name="Rounding Test",
            methodology=AllocationMethod.PRO_RATA_AUM,
        )
        db_session.add(policy)
        db_session.flush()

        expense = Expense(
            date=datetime(2025, 1, 15),
            vendor="Test",
            amount=100.00,
            expense_category=ExpenseCategory.RENT,
            status=ExpenseStatus.PENDING,
        )
        db_session.add(expense)
        db_session.flush()

        engine = AllocationEngine(db_session)
        splits = engine.allocate_expense(expense, policy, preview=True)

        total = sum(s["amount"] for s in splits)
        assert abs(total - 100.00) < 0.01
