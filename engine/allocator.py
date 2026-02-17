"""Core allocation engine supporting 7 allocation methodologies."""
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.orm import Session

from ceviche.models.entities import Entity, EntityStatus, EntityType
from ceviche.models.expenses import Expense, ExpenseStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.allocations import Allocation

logger = logging.getLogger(__name__)

# Don't allocate amounts below this threshold
MIN_ALLOCATION_THRESHOLD = Decimal("0.01")


class AllocationError(Exception):
    """Raised when allocation cannot be completed."""
    pass


class AllocationEngine:
    """Core engine for allocating expenses across PE entities."""

    def __init__(self, session: Session):
        self.session = session

    def allocate_expense(
        self,
        expense: Expense,
        policy: Optional[AllocationPolicy] = None,
        preview: bool = False,
    ) -> list[dict]:
        """
        Allocate a single expense based on its policy.

        Returns list of allocation dicts (preview mode) or persisted Allocation objects.
        """
        if policy is None:
            policy = self._resolve_policy(expense)

        if policy is None:
            raise AllocationError(
                f"No allocation policy found for expense {expense.expense_id} "
                f"(category: {expense.expense_category})"
            )

        method = policy.methodology
        logger.info(
            f"Allocating expense {expense.expense_id} (${expense.amount:,.2f}) "
            f"using method: {method.value}"
        )

        # Calculate the splits based on methodology
        if method == AllocationMethod.PRO_RATA_AUM:
            splits = self._calc_pro_rata(expense, "aum")
        elif method == AllocationMethod.PRO_RATA_COMMITTED:
            splits = self._calc_pro_rata(expense, "committed_capital")
        elif method == AllocationMethod.PRO_RATA_INVESTED:
            splits = self._calc_pro_rata(expense, "invested_capital")
        elif method == AllocationMethod.DIRECT:
            splits = self._calc_direct(expense, policy)
        elif method == AllocationMethod.HEADCOUNT:
            splits = self._calc_pro_rata(expense, "headcount")
        elif method == AllocationMethod.CUSTOM_SPLIT:
            splits = self._calc_custom_split(expense, policy)
        elif method == AllocationMethod.DEAL_SPECIFIC:
            splits = self._calc_deal_specific(expense, policy)
        else:
            raise AllocationError(f"Unknown allocation method: {method}")

        # Apply rounding and minimum threshold
        splits = self._apply_rounding(splits, expense.amount)

        if preview:
            return splits

        # Persist allocations
        return self._persist_allocations(expense, policy, splits)

    def allocate_month(
        self, year: int, month: int, preview: bool = False, recalculate: bool = False
    ) -> list[dict]:
        """Allocate all pending expenses for a given month."""
        from datetime import date

        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

        query = (
            self.session.query(Expense)
            .filter(Expense.date >= start, Expense.date < end)
        )

        if not recalculate:
            query = query.filter(Expense.status == ExpenseStatus.PENDING)
        else:
            # For recalculation, remove existing allocations first
            expenses = query.all()
            for exp in expenses:
                self.session.query(Allocation).filter(
                    Allocation.expense_id == exp.expense_id
                ).delete()
                exp.status = ExpenseStatus.PENDING
            self.session.commit()
            query = (
                self.session.query(Expense)
                .filter(
                    Expense.date >= start,
                    Expense.date < end,
                    Expense.status == ExpenseStatus.PENDING,
                )
            )

        expenses = query.all()
        all_results = []
        errors = []

        for expense in expenses:
            try:
                result = self.allocate_expense(expense, preview=preview)
                all_results.append({
                    "expense_id": expense.expense_id,
                    "vendor": expense.vendor,
                    "amount": expense.amount,
                    "allocations": result,
                })
            except AllocationError as e:
                errors.append({
                    "expense_id": expense.expense_id,
                    "vendor": expense.vendor,
                    "error": str(e),
                })

        return {"allocated": all_results, "errors": errors}

    def _resolve_policy(self, expense: Expense) -> Optional[AllocationPolicy]:
        """Find the applicable allocation policy for an expense."""
        # First check if expense has a directly assigned policy
        if expense.allocation_policy_id:
            return self.session.query(AllocationPolicy).get(expense.allocation_policy_id)

        # Otherwise, find policy by matching expense category
        if expense.expense_category is None:
            return None

        category = expense.expense_category.value
        now = datetime.utcnow()

        policies = (
            self.session.query(AllocationPolicy)
            .filter(AllocationPolicy.effective_date <= now)
            .all()
        )

        for policy in policies:
            if policy.expiration_date and policy.expiration_date < now:
                continue
            categories = policy.get_categories()
            if category in categories:
                return policy

        return None

    def _get_active_fund_entities(self) -> list[Entity]:
        """Get all active fund-type entities for pro-rata calculations."""
        return (
            self.session.query(Entity)
            .filter(
                Entity.status == EntityStatus.ACTIVE,
                Entity.entity_type.in_([EntityType.FUND, EntityType.GP]),
            )
            .all()
        )

    def _calc_pro_rata(self, expense: Expense, metric_field: str) -> list[dict]:
        """Calculate pro-rata allocation based on a numeric metric."""
        entities = self._get_active_fund_entities()
        if not entities:
            raise AllocationError("No active entities found for pro-rata allocation")

        total_metric = sum(getattr(e, metric_field, 0) or 0 for e in entities)
        if total_metric == 0:
            raise AllocationError(
                f"Total {metric_field} across active entities is zero — "
                f"cannot perform pro-rata allocation"
            )

        amount = Decimal(str(expense.amount))
        splits = []
        for entity in entities:
            entity_metric = Decimal(str(getattr(entity, metric_field, 0) or 0))
            if entity_metric <= 0:
                continue
            pct = entity_metric / Decimal(str(total_metric))
            allocated = amount * pct
            splits.append({
                "entity_id": entity.entity_id,
                "entity_name": entity.entity_name,
                "percentage": float(pct * 100),
                "amount": float(allocated),
            })

        return splits

    def _calc_direct(self, expense: Expense, policy: AllocationPolicy) -> list[dict]:
        """100% direct charge to a single entity."""
        target_id = policy.target_entity_id or expense.source_entity_id
        if target_id is None:
            raise AllocationError(
                f"Direct charge policy '{policy.policy_name}' has no target entity "
                f"and expense has no source entity"
            )

        entity = self.session.query(Entity).get(target_id)
        if entity is None:
            raise AllocationError(f"Target entity {target_id} not found")

        return [{
            "entity_id": entity.entity_id,
            "entity_name": entity.entity_name,
            "percentage": 100.0,
            "amount": expense.amount,
        }]

    def _calc_custom_split(self, expense: Expense, policy: AllocationPolicy) -> list[dict]:
        """Allocate based on custom-defined percentage splits."""
        splits_def = policy.get_splits()
        if not splits_def:
            raise AllocationError(
                f"Custom split policy '{policy.policy_name}' has no defined splits"
            )

        # Validate splits sum to ~100%
        total_pct = sum(splits_def.values())
        if abs(total_pct - 1.0) > 0.001:
            raise AllocationError(
                f"Custom split percentages sum to {total_pct*100:.1f}%, not 100%"
            )

        amount = Decimal(str(expense.amount))
        splits = []
        for entity_id_str, pct in splits_def.items():
            entity_id = int(entity_id_str)
            entity = self.session.query(Entity).get(entity_id)
            if entity is None:
                raise AllocationError(f"Entity {entity_id} in custom split not found")
            if entity.status == EntityStatus.LIQUIDATED:
                raise AllocationError(
                    f"Entity '{entity.entity_name}' is liquidated — cannot allocate"
                )

            allocated = amount * Decimal(str(pct))
            splits.append({
                "entity_id": entity.entity_id,
                "entity_name": entity.entity_name,
                "percentage": float(pct * 100),
                "amount": float(allocated),
            })

        return splits

    def _calc_deal_specific(self, expense: Expense, policy: AllocationPolicy) -> list[dict]:
        """100% to the portfolio company or fund associated with a deal."""
        target_id = policy.target_entity_id
        if target_id is None:
            # Try to infer from expense source
            target_id = expense.source_entity_id

        if target_id is None:
            raise AllocationError(
                "Deal-specific allocation requires a target entity"
            )

        entity = self.session.query(Entity).get(target_id)
        if entity is None:
            raise AllocationError(f"Target entity {target_id} not found")

        return [{
            "entity_id": entity.entity_id,
            "entity_name": entity.entity_name,
            "percentage": 100.0,
            "amount": expense.amount,
        }]

    def _apply_rounding(self, splits: list[dict], total_amount: float) -> list[dict]:
        """
        Round allocations to 2 decimal places.
        Assign rounding remainder to the largest allocation.
        Filter out allocations below minimum threshold.
        """
        total = Decimal(str(total_amount))

        # Round each amount
        for s in splits:
            s["amount"] = float(
                Decimal(str(s["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )

        # Filter out sub-threshold allocations
        splits = [s for s in splits if Decimal(str(s["amount"])) >= MIN_ALLOCATION_THRESHOLD]

        if not splits:
            return splits

        # Handle rounding difference
        allocated_total = sum(Decimal(str(s["amount"])) for s in splits)
        diff = float(total - allocated_total)

        if abs(diff) >= 0.01:
            # Assign remainder to largest allocation
            largest = max(splits, key=lambda s: s["amount"])
            largest["amount"] = float(
                Decimal(str(largest["amount"])) + Decimal(str(diff))
            )
            largest["amount"] = float(
                Decimal(str(largest["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )

        return splits

    def _persist_allocations(
        self, expense: Expense, policy: AllocationPolicy, splits: list[dict]
    ) -> list[dict]:
        """Save allocation records to the database."""
        now = datetime.utcnow()
        je_prefix = f"JE-{now.strftime('%Y%m')}-{expense.expense_id}"

        for i, split in enumerate(splits):
            alloc = Allocation(
                expense_id=expense.expense_id,
                target_entity_id=split["entity_id"],
                allocated_amount=split["amount"],
                allocation_percentage=split["percentage"],
                methodology_used=policy.methodology.value,
                allocation_date=now,
                journal_entry_reference=f"{je_prefix}-{i+1:03d}",
            )
            self.session.add(alloc)

        expense.status = ExpenseStatus.ALLOCATED
        expense.allocation_policy_id = policy.policy_id
        self.session.commit()

        logger.info(
            f"Expense {expense.expense_id} allocated to {len(splits)} entities"
        )
        return splits
