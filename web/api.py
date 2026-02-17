"""FastAPI backend for Entity Allocation Web UI."""
import io
import json
import os
import tempfile
import csv as csv_mod
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ceviche.db.database import get_session, init_db, get_engine
from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.allocations import Allocation, AllocationOverride
from ceviche.engine.allocator import AllocationEngine, AllocationError
from ceviche.engine.compliance import ComplianceEngine
from ceviche.engine.journal_entries import JournalEntryGenerator
from ceviche.engine.categorizer import categorize_with_ai
from ceviche.importers.csv_importer import import_expenses_csv
from ceviche.reports.summary import monthly_summary, entity_report, category_report, variance_report

import yaml

app = FastAPI(title="Entity Allocation", description="PE Multi-Entity Expense Allocation Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def get_db():
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
    db_path = os.path.expanduser(config.get("database", {}).get("path", "~/.ceviche/ceviche.db"))
    os.environ.setdefault("CEVICHE_DB", db_path)
    return get_session(db_path)


def get_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    return {}


def _auto_init():
    """Auto-initialize DB and seed data on first run (for cloud deploys)."""
    config = get_config()
    db_path = os.path.expanduser(config.get("database", {}).get("path", "~/.ceviche/ceviche.db"))
    os.environ.setdefault("CEVICHE_DB", db_path)
    if not os.path.exists(db_path):
        from ceviche.db.database import init_db as _init_db
        _init_db(db_path)
        session = get_session(db_path)
        try:
            from ceviche.tests.fixtures.sample_data import load_seed_data
            load_seed_data(session)
        finally:
            session.close()

_auto_init()


# ─── Root ────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path) as f:
        return f.read()


# ─── Dashboard ───────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def dashboard(month: str = Query(None, description="YYYY-MM")):
    session = get_db()
    try:
        if not month:
            month = datetime.utcnow().strftime("%Y-%m")
        dt = datetime.strptime(month, "%Y-%m")
        data = monthly_summary(session, dt.year, dt.month)

        # Get pending count
        pending = session.query(Expense).filter(Expense.status == ExpenseStatus.PENDING).count()
        allocated = session.query(Expense).filter(Expense.status == ExpenseStatus.ALLOCATED).count()

        # Get compliance status for all funds
        config = get_config()
        compliance_engine = ComplianceEngine(session, config)
        compliance = compliance_engine.check_all_funds(dt.year)

        return {
            **data,
            "pending_count": pending,
            "allocated_count": allocated,
            "compliance": compliance,
        }
    finally:
        session.close()


@app.get("/api/dashboard/months")
async def available_months():
    """Get list of months that have expense data."""
    session = get_db()
    try:
        from sqlalchemy import func, distinct, extract
        months = (
            session.query(
                extract("year", Expense.date).label("year"),
                extract("month", Expense.date).label("month"),
            )
            .distinct()
            .order_by(extract("year", Expense.date).desc(), extract("month", Expense.date).desc())
            .all()
        )
        return [{"value": f"{int(m.year)}-{int(m.month):02d}", "label": f"{int(m.year)}-{int(m.month):02d}"} for m in months]
    finally:
        session.close()


# ─── Entities ────────────────────────────────────────────────────────────────────

class EntityCreate(BaseModel):
    entity_name: str
    entity_type: str
    committed_capital: float = 0
    invested_capital: float = 0
    aum: float = 0
    headcount: float = 0
    parent_entity_id: Optional[int] = None
    vintage_year: Optional[int] = None


class EntityUpdate(BaseModel):
    entity_name: Optional[str] = None
    committed_capital: Optional[float] = None
    invested_capital: Optional[float] = None
    aum: Optional[float] = None
    headcount: Optional[float] = None
    status: Optional[str] = None


@app.get("/api/entities")
async def list_entities():
    session = get_db()
    try:
        entities = session.query(Entity).order_by(Entity.entity_type, Entity.entity_name).all()
        return [e.to_dict() for e in entities]
    finally:
        session.close()


@app.get("/api/entities/{entity_id}")
async def get_entity(entity_id: int):
    session = get_db()
    try:
        entity = session.query(Entity).get(entity_id)
        if not entity:
            raise HTTPException(404, "Entity not found")
        children = session.query(Entity).filter(Entity.parent_entity_id == entity_id).all()
        data = entity.to_dict()
        data["children"] = [c.to_dict() for c in children]
        return data
    finally:
        session.close()


@app.post("/api/entities")
async def create_entity(body: EntityCreate):
    session = get_db()
    try:
        entity = Entity(
            entity_name=body.entity_name,
            entity_type=EntityType(body.entity_type),
            status=EntityStatus.ACTIVE,
            committed_capital=body.committed_capital,
            invested_capital=body.invested_capital,
            aum=body.aum,
            headcount=body.headcount,
            parent_entity_id=body.parent_entity_id,
            vintage_year=body.vintage_year,
        )
        session.add(entity)
        session.commit()
        return entity.to_dict()
    except Exception as e:
        session.rollback()
        raise HTTPException(400, str(e))
    finally:
        session.close()


@app.put("/api/entities/{entity_id}")
async def update_entity(entity_id: int, body: EntityUpdate):
    session = get_db()
    try:
        entity = session.query(Entity).get(entity_id)
        if not entity:
            raise HTTPException(404, "Entity not found")
        if body.entity_name is not None:
            entity.entity_name = body.entity_name
        if body.committed_capital is not None:
            entity.committed_capital = body.committed_capital
        if body.invested_capital is not None:
            entity.invested_capital = body.invested_capital
        if body.aum is not None:
            entity.aum = body.aum
        if body.headcount is not None:
            entity.headcount = body.headcount
        if body.status is not None:
            entity.status = EntityStatus(body.status)
        session.commit()
        return entity.to_dict()
    except Exception as e:
        session.rollback()
        raise HTTPException(400, str(e))
    finally:
        session.close()


# ─── Policies ────────────────────────────────────────────────────────────────────

class PolicyCreate(BaseModel):
    policy_name: str
    methodology: str
    categories: list = []
    entity_splits: dict = {}
    target_entity_id: Optional[int] = None
    lpa_reference: Optional[str] = None


@app.get("/api/policies")
async def list_policies():
    session = get_db()
    try:
        policies = session.query(AllocationPolicy).all()
        return [p.to_dict() for p in policies]
    finally:
        session.close()


@app.get("/api/policies/{policy_id}")
async def get_policy(policy_id: int):
    session = get_db()
    try:
        policy = session.query(AllocationPolicy).get(policy_id)
        if not policy:
            raise HTTPException(404, "Policy not found")
        return policy.to_dict()
    finally:
        session.close()


@app.post("/api/policies")
async def create_policy(body: PolicyCreate):
    session = get_db()
    try:
        policy = AllocationPolicy(
            policy_name=body.policy_name,
            methodology=AllocationMethod(body.methodology),
            target_entity_id=body.target_entity_id,
            lpa_reference=body.lpa_reference,
        )
        policy.set_categories(body.categories)
        if body.entity_splits:
            policy.set_splits(body.entity_splits)
        session.add(policy)
        session.commit()
        return policy.to_dict()
    except Exception as e:
        session.rollback()
        raise HTTPException(400, str(e))
    finally:
        session.close()


# ─── Expenses ────────────────────────────────────────────────────────────────────

@app.get("/api/expenses")
async def list_expenses(
    status: Optional[str] = None,
    month: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    session = get_db()
    try:
        query = session.query(Expense)
        if status:
            query = query.filter(Expense.status == ExpenseStatus(status))
        if month:
            dt = datetime.strptime(month, "%Y-%m")
            start = datetime(dt.year, dt.month, 1)
            end = datetime(dt.year, dt.month + 1, 1) if dt.month < 12 else datetime(dt.year + 1, 1, 1)
            query = query.filter(Expense.date >= start, Expense.date < end)
        if category:
            query = query.filter(Expense.expense_category == ExpenseCategory(category))

        total = query.count()
        expenses = query.order_by(Expense.date.desc()).offset(offset).limit(limit).all()

        results = []
        for e in expenses:
            d = e.to_dict()
            if e.source_entity_id:
                src = session.query(Entity).get(e.source_entity_id)
                d["source_entity_name"] = src.entity_name if src else None
            else:
                d["source_entity_name"] = None
            # Include allocation info
            allocs = session.query(Allocation).filter(Allocation.expense_id == e.expense_id).all()
            d["allocations"] = [{
                "entity_id": a.target_entity_id,
                "entity_name": session.query(Entity).get(a.target_entity_id).entity_name if session.query(Entity).get(a.target_entity_id) else "?",
                "amount": a.allocated_amount,
                "percentage": a.allocation_percentage,
                "method": a.methodology_used,
            } for a in allocs]
            results.append(d)

        return {"expenses": results, "total": total}
    finally:
        session.close()


class ExpenseCreate(BaseModel):
    date: str
    vendor: str
    description: str = ""
    amount: float
    currency: str = "USD"
    category: str = "other"
    source_entity_id: Optional[int] = None
    gl_account_code: Optional[str] = None


@app.post("/api/expenses")
async def create_expense(body: ExpenseCreate):
    session = get_db()
    try:
        expense = Expense(
            date=datetime.strptime(body.date, "%Y-%m-%d"),
            vendor=body.vendor,
            description=body.description,
            amount=body.amount,
            currency=body.currency,
            expense_category=ExpenseCategory(body.category),
            source_entity_id=body.source_entity_id,
            status=ExpenseStatus.PENDING,
            gl_account_code=body.gl_account_code,
        )
        session.add(expense)
        session.commit()
        return expense.to_dict()
    except Exception as e:
        session.rollback()
        raise HTTPException(400, str(e))
    finally:
        session.close()


@app.post("/api/expenses/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Upload CSV file for expense import."""
    session = get_db()
    try:
        # Save uploaded file to temp location
        content = await file.read()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp:
            tmp.write(content.decode('utf-8-sig'))
            tmp_path = tmp.name

        result = import_expenses_csv(session, tmp_path)
        os.unlink(tmp_path)

        return result.to_dict()
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        session.close()


# ─── Allocation ──────────────────────────────────────────────────────────────────

class AllocateRequest(BaseModel):
    expense_ids: list = []
    month: Optional[str] = None
    preview: bool = False
    recalculate: bool = False


@app.post("/api/allocate")
async def allocate(body: AllocateRequest):
    session = get_db()
    try:
        engine = AllocationEngine(session)

        if body.month:
            dt = datetime.strptime(body.month, "%Y-%m")
            results = engine.allocate_month(dt.year, dt.month, preview=body.preview, recalculate=body.recalculate)
            return results

        elif body.expense_ids:
            all_results = []
            errors = []
            for eid in body.expense_ids:
                expense = session.query(Expense).get(eid)
                if not expense:
                    errors.append({"expense_id": eid, "error": "Not found"})
                    continue
                try:
                    splits = engine.allocate_expense(expense, preview=body.preview)
                    all_results.append({
                        "expense_id": expense.expense_id,
                        "vendor": expense.vendor,
                        "amount": expense.amount,
                        "allocations": splits,
                    })
                except AllocationError as e:
                    errors.append({"expense_id": eid, "vendor": expense.vendor, "error": str(e)})
            return {"allocated": all_results, "errors": errors}

        raise HTTPException(400, "Provide expense_ids or month")
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        session.close()


@app.get("/api/allocate/preview/{expense_id}")
async def preview_allocation(expense_id: int):
    session = get_db()
    try:
        engine = AllocationEngine(session)
        expense = session.query(Expense).get(expense_id)
        if not expense:
            raise HTTPException(404, "Expense not found")
        try:
            splits = engine.allocate_expense(expense, preview=True)
            return {
                "expense_id": expense.expense_id,
                "vendor": expense.vendor,
                "amount": expense.amount,
                "category": expense.expense_category.value if expense.expense_category else None,
                "allocations": splits,
            }
        except AllocationError as e:
            return {"expense_id": expense_id, "error": str(e), "allocations": []}
    finally:
        session.close()


# ─── Override ────────────────────────────────────────────────────────────────────

class OverrideRequest(BaseModel):
    new_splits: dict  # {entity_id_str: percentage_decimal}
    reason: str


@app.post("/api/expenses/{expense_id}/override")
async def override_allocation(expense_id: int, body: OverrideRequest):
    session = get_db()
    try:
        expense = session.query(Expense).get(expense_id)
        if not expense:
            raise HTTPException(404, "Expense not found")

        total = sum(body.new_splits.values())
        if abs(total - 1.0) > 0.001:
            raise HTTPException(400, f"Splits must sum to 1.0 (got {total})")

        # Save original
        existing = session.query(Allocation).filter(Allocation.expense_id == expense_id).all()
        original = {str(a.target_entity_id): a.allocation_percentage for a in existing}

        ovr = AllocationOverride(
            expense_id=expense_id,
            reason=body.reason,
            original_allocation=json.dumps(original),
            new_allocation=json.dumps(body.new_splits),
            approval_status="approved",
        )
        session.add(ovr)

        for a in existing:
            session.delete(a)

        for entity_id_str, pct in body.new_splits.items():
            entity_id = int(entity_id_str)
            alloc = Allocation(
                expense_id=expense_id,
                target_entity_id=entity_id,
                allocated_amount=round(expense.amount * pct, 2),
                allocation_percentage=pct * 100,
                methodology_used="manual_override",
                journal_entry_reference=f"OVERRIDE-{expense_id}",
            )
            session.add(alloc)

        expense.status = ExpenseStatus.ALLOCATED
        session.commit()
        return {"status": "ok", "expense_id": expense_id}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(400, str(e))
    finally:
        session.close()


# ─── Journal Entries ─────────────────────────────────────────────────────────────

@app.get("/api/journal-entries")
async def get_journal_entries(month: str = Query(...)):
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
        generator = JournalEntryGenerator(session)
        entries = generator.generate_for_month(dt.year, dt.month)
        return {"entries": entries, "count": len(entries)}
    finally:
        session.close()


@app.get("/api/journal-entries/export")
async def export_journal_entries(month: str = Query(...)):
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
        generator = JournalEntryGenerator(session)
        entries = generator.generate_for_month(dt.year, dt.month)

        output = io.StringIO()
        if entries:
            writer = csv_mod.DictWriter(output, fieldnames=entries[0].keys())
            writer.writeheader()
            writer.writerows(entries)

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=journal_entries_{month}.csv"},
        )
    finally:
        session.close()


# ─── Compliance ──────────────────────────────────────────────────────────────────

@app.get("/api/compliance")
async def check_compliance(year: Optional[int] = None):
    session = get_db()
    try:
        config = get_config()
        engine = ComplianceEngine(session, config)
        y = year or datetime.utcnow().year
        results = engine.check_all_funds(y)
        return {"year": y, "funds": results}
    finally:
        session.close()


@app.get("/api/compliance/{fund_name}")
async def check_fund_compliance(fund_name: str, year: Optional[int] = None):
    session = get_db()
    try:
        config = get_config()
        engine = ComplianceEngine(session, config)
        y = year or datetime.utcnow().year
        violations = engine.check_fund_compliance(fund_name, y)
        return {
            "fund": fund_name,
            "year": y,
            "compliant": len(violations) == 0,
            "violations": [v.to_dict() for v in violations],
        }
    finally:
        session.close()


# ─── Reports ─────────────────────────────────────────────────────────────────────

@app.get("/api/reports/by-entity")
async def report_by_entity(entity: str, year: int, quarter: Optional[int] = None):
    session = get_db()
    try:
        return entity_report(session, entity, year, quarter)
    finally:
        session.close()


@app.get("/api/reports/by-category")
async def report_by_category_endpoint(category: str, year: int):
    session = get_db()
    try:
        return category_report(session, category, year)
    finally:
        session.close()


@app.get("/api/reports/variance")
async def report_variance_endpoint(month: str):
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
        return variance_report(session, dt.year, dt.month)
    finally:
        session.close()


# ─── Enums ───────────────────────────────────────────────────────────────────────

@app.get("/api/enums")
async def get_enums():
    return {
        "entity_types": [e.value for e in EntityType],
        "entity_statuses": [e.value for e in EntityStatus],
        "expense_categories": [e.value for e in ExpenseCategory],
        "expense_statuses": [e.value for e in ExpenseStatus],
        "allocation_methods": [e.value for e in AllocationMethod],
    }
