"""Validation utilities for expense data."""


def validate_expense_row(row: dict, row_num: int) -> list[str]:
    """Validate a single expense row from CSV import. Returns list of error strings."""
    errors = []

    # Required fields
    if not row.get("date"):
        errors.append(f"Row {row_num}: Missing required field 'date'")
    if not row.get("vendor"):
        errors.append(f"Row {row_num}: Missing required field 'vendor'")
    if not row.get("amount"):
        errors.append(f"Row {row_num}: Missing required field 'amount'")

    # Amount validation
    if row.get("amount"):
        amount_str = row["amount"].replace(",", "").replace("$", "")
        try:
            amount = float(amount_str)
            if amount <= 0:
                errors.append(f"Row {row_num}: Amount must be positive (got {amount})")
            if amount > 100_000_000:
                errors.append(
                    f"Row {row_num}: Amount ${amount:,.2f} seems unusually large — please verify"
                )
        except ValueError:
            errors.append(f"Row {row_num}: Invalid amount format '{row['amount']}'")

    # Currency validation
    currency = row.get("currency", "USD")
    if currency and currency.upper() not in ["USD", "EUR", "GBP", "CAD", "CHF", "JPY", "AUD"]:
        errors.append(f"Row {row_num}: Unsupported currency '{currency}'")

    # Vendor name length
    if row.get("vendor") and len(row["vendor"]) > 200:
        errors.append(f"Row {row_num}: Vendor name exceeds 200 characters")

    return errors
