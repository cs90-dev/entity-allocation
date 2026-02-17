"""Journal entry generation for NetSuite / QuickBooks export."""
import csv
import io
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import extract

from ceviche.models.entities import Entity
from ceviche.models.expenses import Expense, ExpenseStatus, ExpenseCategory
from ceviche.models.allocations import Allocation

logger = logging.getLogger(__name__)

# Default GL account mapping by expense category
DEFAULT_GL_ACCOUNTS = {
    ExpenseCategory.LEGAL: ("6100", "Legal Fees"),
    ExpenseCategory.ACCOUNTING: ("6200", "Accounting & Audit"),
    ExpenseCategory.TRAVEL: ("6300", "Travel & Entertainment"),
    ExpenseCategory.COMPLIANCE: ("6400", "Compliance & Regulatory"),
    ExpenseCategory.INSURANCE: ("6500", "Insurance"),
    ExpenseCategory.TECHNOLOGY: ("6600", "Technology & Software"),
    ExpenseCategory.RENT: ("6700", "Rent & Occupancy"),
    ExpenseCategory.PERSONNEL: ("6800", "Personnel & Compensation"),
    ExpenseCategory.DEAL_EXPENSE: ("6900", "Deal Expenses"),
    ExpenseCategory.BROKEN_DEAL: ("6950", "Broken Deal Costs"),
    ExpenseCategory.FUND_FORMATION: ("7100", "Fund Formation"),
    ExpenseCategory.ORGANIZATIONAL: ("7200", "Organizational Expenses"),
    ExpenseCategory.DUE_DILIGENCE: ("7300", "Due Diligence"),
    ExpenseCategory.CONSULTING: ("7400", "Consulting Fees"),
    ExpenseCategory.OTHER: ("7900", "Other Expenses"),
}

INTERCOMPANY_RECEIVABLE = ("1500", "Intercompany Receivable")
INTERCOMPANY_PAYABLE = ("2500", "Intercompany Payable")


class JournalEntryGenerator:
    """Generate journal entries from allocations."""

    def __init__(self, session: Session):
        self.session = session

    def generate_for_month(self, year: int, month: int) -> list[dict]:
        """Generate all journal entries for a given month."""
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

        expenses = (
            self.session.query(Expense)
            .filter(
                Expense.date >= start,
                Expense.date < end,
                Expense.status.in_([ExpenseStatus.ALLOCATED, ExpenseStatus.REVIEWED, ExpenseStatus.POSTED]),
            )
            .all()
        )

        journal_entries = []
        je_counter = 1

        for expense in expenses:
            allocations = (
                self.session.query(Allocation)
                .filter(Allocation.expense_id == expense.expense_id)
                .all()
            )

            if not allocations:
                continue

            source_entity = (
                self.session.query(Entity).get(expense.source_entity_id)
                if expense.source_entity_id else None
            )
            source_name = source_entity.entity_name if source_entity else "Unknown"

            gl_code, gl_name = self._get_gl_account(expense)
            je_id = f"JE-{year}{month:02d}-{je_counter:04d}"

            # Credit entry: paying entity (credit to expense or intercompany payable)
            journal_entries.append({
                "date": expense.date.strftime("%Y-%m-%d"),
                "journal_entry_id": je_id,
                "entity": source_name,
                "account_code": INTERCOMPANY_RECEIVABLE[0],
                "account_name": INTERCOMPANY_RECEIVABLE[1],
                "debit": round(expense.amount, 2),
                "credit": 0.00,
                "memo": f"{expense.vendor} - {expense.description or expense.expense_category.value}",
                "class": expense.expense_category.value if expense.expense_category else "",
                "department": "",
            })

            # Debit entries: each receiving entity
            for alloc in allocations:
                target_entity = self.session.query(Entity).get(alloc.target_entity_id)
                target_name = target_entity.entity_name if target_entity else "Unknown"

                journal_entries.append({
                    "date": expense.date.strftime("%Y-%m-%d"),
                    "journal_entry_id": je_id,
                    "entity": target_name,
                    "account_code": gl_code,
                    "account_name": gl_name,
                    "debit": 0.00,
                    "credit": 0.00,
                    "memo": f"{expense.vendor} - allocated ({alloc.allocation_percentage:.1f}%)",
                    "class": expense.expense_category.value if expense.expense_category else "",
                    "department": "",
                })
                # Debit to expense account on receiving entity
                journal_entries[-1]["debit"] = round(alloc.allocated_amount, 2)

                # Corresponding credit to intercompany payable on receiving entity
                journal_entries.append({
                    "date": expense.date.strftime("%Y-%m-%d"),
                    "journal_entry_id": je_id,
                    "entity": target_name,
                    "account_code": INTERCOMPANY_PAYABLE[0],
                    "account_name": INTERCOMPANY_PAYABLE[1],
                    "debit": 0.00,
                    "credit": round(alloc.allocated_amount, 2),
                    "memo": f"IC payable - {expense.vendor}",
                    "class": expense.expense_category.value if expense.expense_category else "",
                    "department": "",
                })

            je_counter += 1

        logger.info(f"Generated {len(journal_entries)} journal entry lines for {year}-{month:02d}")
        return journal_entries

    def export_csv(self, journal_entries: list[dict], output_path: str = None) -> str:
        """Export journal entries to CSV format."""
        headers = [
            "date", "journal_entry_id", "entity", "account_code",
            "account_name", "debit", "credit", "memo", "class", "department",
        ]

        if output_path:
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(journal_entries)
            return output_path

        # Return as string
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(journal_entries)
        return output.getvalue()

    def _get_gl_account(self, expense: Expense) -> tuple[str, str]:
        """Get GL account code and name for an expense."""
        if expense.gl_account_code:
            return expense.gl_account_code, ""

        if expense.expense_category and expense.expense_category in DEFAULT_GL_ACCOUNTS:
            return DEFAULT_GL_ACCOUNTS[expense.expense_category]

        return DEFAULT_GL_ACCOUNTS[ExpenseCategory.OTHER]
