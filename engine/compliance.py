"""LPA compliance rules engine."""
import logging
from datetime import datetime
from typing import Optional

import yaml
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from ceviche.models.entities import Entity, EntityType
from ceviche.models.expenses import Expense, ExpenseCategory
from ceviche.models.allocations import Allocation

logger = logging.getLogger(__name__)


class ComplianceViolation:
    """Represents a single compliance violation."""

    def __init__(self, rule_name: str, entity_name: str, description: str,
                 limit: float, actual: float, severity: str = "warning"):
        self.rule_name = rule_name
        self.entity_name = entity_name
        self.description = description
        self.limit = limit
        self.actual = actual
        self.severity = severity
        self.excess = actual - limit

    def to_dict(self):
        return {
            "rule": self.rule_name,
            "entity": self.entity_name,
            "description": self.description,
            "limit": self.limit,
            "actual": self.actual,
            "excess": self.excess,
            "severity": self.severity,
        }


class ComplianceEngine:
    """Check allocations against LPA-defined rules and limits."""

    def __init__(self, session: Session, config: dict = None):
        self.session = session
        self.config = config or {}
        self.lpa_rules = self.config.get("lpa_rules", {})

    @classmethod
    def from_config_file(cls, session: Session, config_path: str):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        return cls(session, config)

    def check_fund_compliance(
        self, fund_name: str, year: int = None
    ) -> list[ComplianceViolation]:
        """Run all compliance checks for a specific fund."""
        year = year or datetime.utcnow().year
        violations = []

        entity = (
            self.session.query(Entity)
            .filter(Entity.entity_name == fund_name)
            .first()
        )
        if not entity:
            logger.warning(f"Fund '{fund_name}' not found")
            return violations

        fund_rules = self._get_fund_rules(fund_name)
        if not fund_rules:
            logger.info(f"No LPA rules configured for '{fund_name}'")
            return violations

        # Check management fee cap
        if "management_fee_cap_pct" in fund_rules:
            v = self._check_mgmt_fee_cap(entity, fund_rules, year)
            if v:
                violations.append(v)

        # Check organizational expense cap
        if "org_expense_cap" in fund_rules:
            v = self._check_org_expense_cap(entity, fund_rules, year)
            if v:
                violations.append(v)

        # Check broken deal expense limit
        if "broken_deal_limit" in fund_rules:
            v = self._check_broken_deal_limit(entity, fund_rules, year)
            if v:
                violations.append(v)

        # Check annual expense cap (total)
        if "annual_expense_cap" in fund_rules:
            v = self._check_annual_expense_cap(entity, fund_rules, year)
            if v:
                violations.append(v)

        return violations

    def check_all_funds(self, year: int = None) -> dict:
        """Run compliance checks across all funds."""
        year = year or datetime.utcnow().year
        results = {}

        funds = (
            self.session.query(Entity)
            .filter(Entity.entity_type == EntityType.FUND)
            .all()
        )

        for fund in funds:
            violations = self.check_fund_compliance(fund.entity_name, year)
            results[fund.entity_name] = {
                "violations": [v.to_dict() for v in violations],
                "compliant": len(violations) == 0,
            }

        return results

    def _get_fund_rules(self, fund_name: str) -> dict:
        """Get LPA rules for a specific fund from config."""
        fund_configs = self.lpa_rules.get("funds", {})
        return fund_configs.get(fund_name, {})

    def _get_allocated_total(
        self,
        entity: Entity,
        year: int,
        categories: list[str] = None,
    ) -> float:
        """Sum allocated amounts for an entity in a given year, optionally filtered by category."""
        query = (
            self.session.query(func.coalesce(func.sum(Allocation.allocated_amount), 0))
            .join(Expense, Allocation.expense_id == Expense.expense_id)
            .filter(
                Allocation.target_entity_id == entity.entity_id,
                extract("year", Expense.date) == year,
            )
        )
        if categories:
            cat_enums = [ExpenseCategory(c) for c in categories if c in ExpenseCategory.__members__.values()]
            if cat_enums:
                query = query.filter(Expense.expense_category.in_(cat_enums))

        result = query.scalar()
        return float(result or 0)

    def _check_mgmt_fee_cap(
        self, entity: Entity, rules: dict, year: int
    ) -> Optional[ComplianceViolation]:
        """Check if management fees exceed LPA cap (% of committed capital)."""
        cap_pct = rules["management_fee_cap_pct"]
        cap_amount = (entity.committed_capital or 0) * cap_pct / 100.0

        actual = self._get_allocated_total(
            entity, year, categories=["personnel", "rent", "technology", "insurance"]
        )

        if actual > cap_amount:
            return ComplianceViolation(
                rule_name="Management Fee Cap",
                entity_name=entity.entity_name,
                description=(
                    f"Management-related expenses (${actual:,.2f}) exceed "
                    f"{cap_pct}% of committed capital (${cap_amount:,.2f})"
                ),
                limit=cap_amount,
                actual=actual,
                severity="critical",
            )
        return None

    def _check_org_expense_cap(
        self, entity: Entity, rules: dict, year: int
    ) -> Optional[ComplianceViolation]:
        """Check organizational expense cap."""
        cap = rules["org_expense_cap"]
        actual = self._get_allocated_total(
            entity, year, categories=["organizational", "fund_formation"]
        )

        if actual > cap:
            return ComplianceViolation(
                rule_name="Organizational Expense Cap",
                entity_name=entity.entity_name,
                description=(
                    f"Organizational expenses (${actual:,.2f}) exceed "
                    f"cap of ${cap:,.2f}"
                ),
                limit=cap,
                actual=actual,
                severity="critical",
            )
        return None

    def _check_broken_deal_limit(
        self, entity: Entity, rules: dict, year: int
    ) -> Optional[ComplianceViolation]:
        """Check broken deal expense limit."""
        limit = rules["broken_deal_limit"]
        actual = self._get_allocated_total(entity, year, categories=["broken_deal"])

        if actual > limit:
            return ComplianceViolation(
                rule_name="Broken Deal Expense Limit",
                entity_name=entity.entity_name,
                description=(
                    f"Broken deal expenses (${actual:,.2f}) exceed "
                    f"limit of ${limit:,.2f}"
                ),
                limit=limit,
                actual=actual,
                severity="warning",
            )
        return None

    def _check_annual_expense_cap(
        self, entity: Entity, rules: dict, year: int
    ) -> Optional[ComplianceViolation]:
        """Check total annual expense cap."""
        cap = rules["annual_expense_cap"]
        actual = self._get_allocated_total(entity, year)

        if actual > cap:
            return ComplianceViolation(
                rule_name="Annual Expense Cap",
                entity_name=entity.entity_name,
                description=(
                    f"Total annual expenses (${actual:,.2f}) exceed "
                    f"cap of ${cap:,.2f}"
                ),
                limit=cap,
                actual=actual,
                severity="critical",
            )
        return None
