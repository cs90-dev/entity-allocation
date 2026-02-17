"""CSV expense importer with validation and duplicate detection."""
import csv
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ceviche.models.entities import Entity
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.importers.validators import validate_expense_row

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "date", "vendor", "description", "amount", "currency",
    "category", "entity_paid", "gl_account", "notes",
]


class ImportResult:
    """Result of a CSV import operation."""

    def __init__(self):
        self.imported = 0
        self.skipped = 0
        self.errors = []
        self.duplicates = []
        self.warnings = []

    def to_dict(self):
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "errors": self.errors,
            "duplicates": self.duplicates,
            "warnings": self.warnings,
        }


def import_expenses_csv(session: Session, file_path: str) -> ImportResult:
    """Import expenses from a CSV file."""
    result = ImportResult()

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # Validate headers
            if reader.fieldnames:
                headers = [h.strip().lower() for h in reader.fieldnames]
                missing = [c for c in ["date", "vendor", "amount"] if c not in headers]
                if missing:
                    result.errors.append(f"Missing required columns: {', '.join(missing)}")
                    return result

            for row_num, row in enumerate(reader, start=2):
                # Normalize keys
                row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

                # Validate row
                errors = validate_expense_row(row, row_num)
                if errors:
                    result.errors.extend(errors)
                    result.skipped += 1
                    continue

                # Parse amount
                amount_str = row["amount"].replace(",", "").replace("$", "")
                try:
                    amount = float(amount_str)
                except ValueError:
                    result.errors.append(f"Row {row_num}: Invalid amount '{row['amount']}'")
                    result.skipped += 1
                    continue

                # Parse date
                try:
                    date = _parse_date(row["date"])
                except ValueError as e:
                    result.errors.append(f"Row {row_num}: {e}")
                    result.skipped += 1
                    continue

                # Check for duplicates (same vendor + amount + date)
                existing = (
                    session.query(Expense)
                    .filter(
                        Expense.vendor == row["vendor"],
                        Expense.amount == amount,
                        Expense.date == date,
                    )
                    .first()
                )
                if existing:
                    result.duplicates.append(
                        f"Row {row_num}: Duplicate of expense #{existing.expense_id} "
                        f"({row['vendor']}, ${amount:,.2f}, {date.strftime('%Y-%m-%d')})"
                    )
                    result.skipped += 1
                    continue

                # Parse category
                category = _parse_category(row.get("category", ""))

                # Resolve source entity
                source_entity_id = _resolve_entity(session, row.get("entity_paid", ""))

                expense = Expense(
                    date=date,
                    vendor=row["vendor"],
                    description=row.get("description", ""),
                    amount=amount,
                    currency=row.get("currency", "USD") or "USD",
                    expense_category=category,
                    source_entity_id=source_entity_id,
                    status=ExpenseStatus.PENDING,
                    gl_account_code=row.get("gl_account", "") or None,
                    notes=row.get("notes", "") or None,
                )
                session.add(expense)
                result.imported += 1

            session.commit()

    except FileNotFoundError:
        result.errors.append(f"File not found: {file_path}")
    except Exception as e:
        result.errors.append(f"Import error: {str(e)}")
        session.rollback()

    logger.info(
        f"Import complete: {result.imported} imported, "
        f"{result.skipped} skipped, {len(result.errors)} errors"
    )
    return result


def _parse_date(date_str: str) -> datetime:
    """Parse date from various formats."""
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{date_str}' — expected YYYY-MM-DD or MM/DD/YYYY")


def _parse_category(category_str: str) -> Optional[ExpenseCategory]:
    """Parse expense category string to enum."""
    if not category_str:
        return None
    normalized = category_str.strip().lower().replace(" ", "_")
    try:
        return ExpenseCategory(normalized)
    except ValueError:
        return None


def _resolve_entity(session: Session, entity_name: str) -> Optional[int]:
    """Look up entity by name, return entity_id or None."""
    if not entity_name:
        return None
    entity = session.query(Entity).filter(Entity.entity_name == entity_name).first()
    return entity.entity_id if entity else None
