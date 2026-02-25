"""Tests for the FastAPI web endpoints."""
import json
import pytest
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from ceviche.web.api import app


def uid():
    """Generate short unique suffix for test data."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def client():
    return TestClient(app)


class TestDashboard:
    def test_dashboard_returns_200(self, client):
        r = client.get("/api/dashboard?month=2025-01")
        assert r.status_code == 200
        data = r.json()
        assert "total_expense_count" in data
        assert "by_entity" in data
        assert "compliance" in data

    def test_available_months(self, client):
        r = client.get("/api/dashboard/months")
        assert r.status_code == 200
        months = r.json()
        assert isinstance(months, list)


class TestEntitiesAPI:
    def test_list_entities(self, client):
        r = client.get("/api/entities")
        assert r.status_code == 200
        entities = r.json()
        assert isinstance(entities, list)
        assert len(entities) > 0

    def test_get_entity(self, client):
        r = client.get("/api/entities/1")
        assert r.status_code == 200
        assert "entity_name" in r.json()

    def test_get_entity_not_found(self, client):
        r = client.get("/api/entities/9999")
        assert r.status_code == 404

    def test_create_entity(self, client):
        name = f"API Test Fund {uid()}"
        r = client.post("/api/entities", json={
            "entity_name": name,
            "entity_type": "Fund",
            "committed_capital": 50000000,
        })
        assert r.status_code == 200
        assert r.json()["entity_name"] == name

    def test_update_entity(self, client):
        r = client.put("/api/entities/2", json={"aum": 999000000})
        assert r.status_code == 200


class TestPoliciesAPI:
    def test_list_policies(self, client):
        r = client.get("/api/policies")
        assert r.status_code == 200
        assert len(r.json()) > 0

    def test_create_policy(self, client):
        r = client.post("/api/policies", json={
            "policy_name": f"API Test Policy {uid()}",
            "methodology": "pro_rata_aum",
            "categories": ["legal", "accounting"],
        })
        assert r.status_code == 200


class TestExpensesAPI:
    def test_list_expenses(self, client):
        r = client.get("/api/expenses?month=2025-01")
        assert r.status_code == 200
        data = r.json()
        assert "expenses" in data
        assert "total" in data

    def test_create_expense(self, client):
        r = client.post("/api/expenses", json={
            "date": "2025-06-01",
            "vendor": "API Test Vendor",
            "amount": 10000,
            "category": "legal",
        })
        assert r.status_code == 200
        assert r.json()["vendor"] == "API Test Vendor"

    def test_upload_csv(self, client):
        vendor = f"UploadTest-{uid()}"
        csv = f"date,vendor,description,amount,currency,category,entity_paid,gl_account,notes\n2025-06-15,{vendor},test,1234,USD,other,,,\n".encode()
        r = client.post("/api/expenses/upload", files={"file": ("test.csv", csv, "text/csv")})
        assert r.status_code == 200
        assert r.json()["imported"] >= 1


class TestAllocationAPI:
    def test_preview_allocation(self, client):
        # Use an expense we know exists
        r = client.get("/api/expenses?limit=1")
        if r.json()["expenses"]:
            eid = r.json()["expenses"][0]["expense_id"]
            r = client.get(f"/api/allocate/preview/{eid}")
            assert r.status_code == 200

    def test_allocate_preview_month(self, client):
        r = client.post("/api/allocate", json={"month": "2025-03", "preview": True})
        assert r.status_code == 200
        assert "allocated" in r.json()


class TestJournalEntriesAPI:
    def test_get_journal_entries(self, client):
        r = client.get("/api/journal-entries?month=2025-01")
        assert r.status_code == 200
        assert "entries" in r.json()

    def test_export_csv(self, client):
        r = client.get("/api/journal-entries/export?month=2025-01")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")


class TestComplianceAPI:
    def test_check_all_compliance(self, client):
        r = client.get("/api/compliance?year=2025")
        assert r.status_code == 200
        assert "funds" in r.json()

    def test_check_fund_compliance(self, client):
        r = client.get("/api/compliance/Apex Capital Partners III LP?year=2025")
        assert r.status_code == 200
        assert "compliant" in r.json()


class TestEnumsAPI:
    def test_enums(self, client):
        r = client.get("/api/enums")
        assert r.status_code == 200
        data = r.json()
        assert "entity_types" in data
        assert "expense_categories" in data
        assert "allocation_methods" in data


class TestStaticFiles:
    def test_index_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Entity Allocation" in r.text

    def test_css_loads(self, client):
        r = client.get("/static/css/style.css")
        assert r.status_code == 200

    def test_js_loads(self, client):
        r = client.get("/static/js/app.js")
        assert r.status_code == 200
