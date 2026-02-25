"""Tests for the CSV importer."""
import pytest
from datetime import datetime

from ceviche.importers.csv_importer import import_expenses_csv
from ceviche.models.expenses import Expense


class TestCSVImporter:
    def test_import_valid_csv(self, db_session, csv_file):
        result = import_expenses_csv(db_session, csv_file)

        assert result.imported == 5
        assert result.skipped == 0
        assert len(result.errors) == 0

    def test_imported_expenses_exist(self, db_session, csv_file):
        import_expenses_csv(db_session, csv_file)

        expenses = db_session.query(Expense).all()
        assert len(expenses) == 5

        # Check first expense
        kirkland = db_session.query(Expense).filter(
            Expense.vendor == "Kirkland & Ellis"
        ).first()
        assert kirkland is not None
        assert kirkland.amount == 150_000
        assert kirkland.date == datetime(2025, 1, 15)

    def test_duplicate_detection(self, db_session, csv_file):
        # Import twice
        result1 = import_expenses_csv(db_session, csv_file)
        result2 = import_expenses_csv(db_session, csv_file)

        assert result1.imported == 5
        assert result2.imported == 0
        assert len(result2.duplicates) == 5

    def test_file_not_found(self, db_session):
        result = import_expenses_csv(db_session, "/nonexistent/path.csv")
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower()

    def test_invalid_amount(self, db_session, tmp_path):
        csv_content = """date,vendor,description,amount,currency,category,entity_paid,gl_account,notes
2025-01-15,TestVendor,Test,not_a_number,USD,legal,,,
"""
        csv_path = tmp_path / "bad_amount.csv"
        csv_path.write_text(csv_content)

        result = import_expenses_csv(db_session, str(csv_path))
        assert result.imported == 0
        assert result.skipped == 1

    def test_missing_required_fields(self, db_session, tmp_path):
        csv_content = """date,vendor,description,amount,currency,category
,TestVendor,Test,1000,USD,legal
2025-01-15,,Test,1000,USD,legal
2025-01-15,TestVendor,Test,,USD,legal
"""
        csv_path = tmp_path / "missing_fields.csv"
        csv_path.write_text(csv_content)

        result = import_expenses_csv(db_session, str(csv_path))
        assert result.skipped == 3

    def test_date_format_variants(self, db_session, tmp_path):
        csv_content = """date,vendor,description,amount,currency,category,entity_paid,gl_account,notes
01/15/2025,Vendor A,Test A,1000,USD,legal,,,
2025-01-16,Vendor B,Test B,2000,USD,legal,,,
"""
        csv_path = tmp_path / "date_formats.csv"
        csv_path.write_text(csv_content)

        result = import_expenses_csv(db_session, str(csv_path))
        assert result.imported == 2
