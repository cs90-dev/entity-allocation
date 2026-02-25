"""Reporting module for allocation summaries and analytics."""
import csv
import io
import logging
from datetime import datetime
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from ceviche.models.entities import Entity
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.models.allocations import Allocation

logger = logging.getLogger(__name__)


def monthly_summary(session: Session, year: int, month: int) -> dict:
    """Generate a monthly allocation summary."""
    start = datetime(year, month, 1)
    end = datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)

    # Total expenses
    total_expenses = (
        session.query(func.count(Expense.expense_id), func.sum(Expense.amount))
        .filter(Expense.date >= start, Expense.date < end)
        .first()
    )

    # Allocated vs pending
    status_breakdown = (
        session.query(Expense.status, func.count(Expense.expense_id), func.sum(Expense.amount))
        .filter(Expense.date >= start, Expense.date < end)
        .group_by(Expense.status)
        .all()
    )

    # By entity
    entity_totals = (
        session.query(
            Entity.entity_name,
            Entity.entity_type,
            func.sum(Allocation.allocated_amount),
            func.count(Allocation.allocation_id),
        )
        .join(Allocation, Entity.entity_id == Allocation.target_entity_id)
        .join(Expense, Allocation.expense_id == Expense.expense_id)
        .filter(Expense.date >= start, Expense.date < end)
        .group_by(Entity.entity_name, Entity.entity_type)
        .all()
    )

    # By category
    category_totals = (
        session.query(
            Expense.expense_category,
            func.count(Expense.expense_id),
            func.sum(Expense.amount),
        )
        .filter(Expense.date >= start, Expense.date < end)
        .group_by(Expense.expense_category)
        .all()
    )

    # By methodology
    method_totals = (
        session.query(
            Allocation.methodology_used,
            func.count(Allocation.allocation_id),
            func.sum(Allocation.allocated_amount),
        )
        .join(Expense, Allocation.expense_id == Expense.expense_id)
        .filter(Expense.date >= start, Expense.date < end)
        .group_by(Allocation.methodology_used)
        .all()
    )

    return {
        "period": f"{year}-{month:02d}",
        "total_expense_count": total_expenses[0] or 0,
        "total_expense_amount": float(total_expenses[1] or 0),
        "status_breakdown": [
            {"status": s[0].value if s[0] else "unknown", "count": s[1], "amount": float(s[2] or 0)}
            for s in status_breakdown
        ],
        "by_entity": [
            {
                "entity": e[0],
                "type": e[1].value if e[1] else "",
                "allocated_amount": float(e[2] or 0),
                "allocation_count": e[3],
            }
            for e in entity_totals
        ],
        "by_category": [
            {
                "category": c[0].value if c[0] else "uncategorized",
                "count": c[1],
                "amount": float(c[2] or 0),
            }
            for c in category_totals
        ],
        "by_methodology": [
            {"method": m[0], "count": m[1], "amount": float(m[2] or 0)}
            for m in method_totals
        ],
    }


def entity_report(
    session: Session, entity_name: str, year: int, quarter: int = None
) -> dict:
    """Generate an allocation report for a specific entity."""
    entity = session.query(Entity).filter(Entity.entity_name == entity_name).first()
    if not entity:
        return {"error": f"Entity '{entity_name}' not found"}

    query = (
        session.query(Allocation, Expense)
        .join(Expense, Allocation.expense_id == Expense.expense_id)
        .filter(
            Allocation.target_entity_id == entity.entity_id,
            extract("year", Expense.date) == year,
        )
    )

    if quarter:
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 3
        query = query.filter(
            extract("month", Expense.date) >= start_month,
            extract("month", Expense.date) < end_month,
        )

    results = query.all()

    expenses_detail = []
    total = 0.0
    by_category = defaultdict(float)
    by_vendor = defaultdict(float)

    for alloc, expense in results:
        total += alloc.allocated_amount
        cat = expense.expense_category.value if expense.expense_category else "other"
        by_category[cat] += alloc.allocated_amount
        by_vendor[expense.vendor] += alloc.allocated_amount
        expenses_detail.append({
            "date": expense.date.strftime("%Y-%m-%d"),
            "vendor": expense.vendor,
            "description": expense.description,
            "total_amount": expense.amount,
            "allocated_amount": alloc.allocated_amount,
            "percentage": alloc.allocation_percentage,
            "method": alloc.methodology_used,
            "category": cat,
        })

    period = f"Q{quarter} {year}" if quarter else str(year)

    return {
        "entity": entity.entity_name,
        "entity_type": entity.entity_type.value,
        "period": period,
        "total_allocated": total,
        "expense_count": len(expenses_detail),
        "by_category": dict(by_category),
        "top_vendors": dict(sorted(by_vendor.items(), key=lambda x: -x[1])[:10]),
        "expenses": expenses_detail,
    }


def category_report(
    session: Session, category: str, year: int
) -> dict:
    """Report on a specific expense category across all entities."""
    try:
        cat_enum = ExpenseCategory(category)
    except ValueError:
        return {"error": f"Invalid category '{category}'"}

    results = (
        session.query(Allocation, Expense, Entity)
        .join(Expense, Allocation.expense_id == Expense.expense_id)
        .join(Entity, Allocation.target_entity_id == Entity.entity_id)
        .filter(
            Expense.expense_category == cat_enum,
            extract("year", Expense.date) == year,
        )
        .all()
    )

    by_entity = defaultdict(float)
    by_month = defaultdict(float)
    total = 0.0

    for alloc, expense, entity in results:
        by_entity[entity.entity_name] += alloc.allocated_amount
        month_key = expense.date.strftime("%Y-%m")
        by_month[month_key] += alloc.allocated_amount
        total += alloc.allocated_amount

    return {
        "category": category,
        "year": year,
        "total": total,
        "by_entity": dict(by_entity),
        "by_month": dict(sorted(by_month.items())),
    }


def variance_report(session: Session, year: int, month: int) -> dict:
    """Compare current month allocations to prior month."""
    current = monthly_summary(session, year, month)

    if month == 1:
        prior_year, prior_month = year - 1, 12
    else:
        prior_year, prior_month = year, month - 1

    prior = monthly_summary(session, prior_year, prior_month)

    # Build entity-level variance
    current_by_entity = {e["entity"]: e["allocated_amount"] for e in current["by_entity"]}
    prior_by_entity = {e["entity"]: e["allocated_amount"] for e in prior["by_entity"]}

    all_entities = set(list(current_by_entity.keys()) + list(prior_by_entity.keys()))
    entity_variance = []
    for name in sorted(all_entities):
        curr = current_by_entity.get(name, 0)
        prev = prior_by_entity.get(name, 0)
        change = curr - prev
        pct_change = (change / prev * 100) if prev != 0 else (100.0 if curr > 0 else 0.0)
        entity_variance.append({
            "entity": name,
            "current": curr,
            "prior": prev,
            "change": change,
            "pct_change": round(pct_change, 1),
        })

    return {
        "current_period": current["period"],
        "prior_period": prior["period"],
        "total_current": current["total_expense_amount"],
        "total_prior": prior["total_expense_amount"],
        "total_change": current["total_expense_amount"] - prior["total_expense_amount"],
        "by_entity": entity_variance,
    }


def export_report_csv(data: list[dict], output_path: str) -> str:
    """Export report data to CSV."""
    if not data:
        return ""

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    return output_path
