"""Sample seed data for Apex Capital Management PE firm."""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus


def load_seed_data(session: Session):
    """Load comprehensive seed data for testing."""
    _load_entities(session)
    _load_policies(session)
    _load_expenses(session)
    session.commit()


def _load_entities(session: Session):
    """Create all PE firm entities."""
    # GP / Management Company
    gp = Entity(
        entity_name="Apex Capital Management LLC",
        entity_type=EntityType.GP,
        status=EntityStatus.ACTIVE,
        committed_capital=0,
        invested_capital=0,
        aum=0,
        headcount=25,
    )
    session.add(gp)
    session.flush()

    # Fund I — fully invested, mature
    fund1 = Entity(
        entity_name="Apex Capital Partners I LP",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=200_000_000,
        invested_capital=200_000_000,
        aum=180_000_000,
        headcount=5,
        parent_entity_id=gp.entity_id,
        vintage_year=2018,
    )
    session.add(fund1)

    # Fund II — partially invested
    fund2 = Entity(
        entity_name="Apex Capital Partners II LP",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=400_000_000,
        invested_capital=300_000_000,
        aum=350_000_000,
        headcount=8,
        parent_entity_id=gp.entity_id,
        vintage_year=2021,
    )
    session.add(fund2)

    # Fund III — early stage
    fund3 = Entity(
        entity_name="Apex Capital Partners III LP",
        entity_type=EntityType.FUND,
        status=EntityStatus.ACTIVE,
        committed_capital=600_000_000,
        invested_capital=150_000_000,
        aum=580_000_000,
        headcount=12,
        parent_entity_id=gp.entity_id,
        vintage_year=2024,
    )
    session.add(fund3)
    session.flush()

    # Portfolio Companies — Fund I
    portcos_f1 = [
        ("Meridian Health Systems", fund1.entity_id),
        ("TechNova Solutions Inc", fund1.entity_id),
    ]
    for name, parent_id in portcos_f1:
        session.add(Entity(
            entity_name=name,
            entity_type=EntityType.PORTCO,
            status=EntityStatus.ACTIVE,
            parent_entity_id=parent_id,
        ))

    # Portfolio Companies — Fund II
    portcos_f2 = [
        ("CloudBridge Analytics", fund2.entity_id),
        ("GreenPath Energy Corp", fund2.entity_id),
    ]
    for name, parent_id in portcos_f2:
        session.add(Entity(
            entity_name=name,
            entity_type=EntityType.PORTCO,
            status=EntityStatus.ACTIVE,
            parent_entity_id=parent_id,
        ))

    # Portfolio Company — Fund III
    session.add(Entity(
        entity_name="Atlas Logistics LLC",
        entity_type=EntityType.PORTCO,
        status=EntityStatus.ACTIVE,
        parent_entity_id=fund3.entity_id,
    ))

    # SPV / Co-Invest Vehicles
    session.add(Entity(
        entity_name="Apex Co-Invest I LLC",
        entity_type=EntityType.SPV,
        status=EntityStatus.ACTIVE,
        committed_capital=50_000_000,
        invested_capital=50_000_000,
        aum=55_000_000,
        parent_entity_id=fund2.entity_id,
    ))

    session.add(Entity(
        entity_name="Apex Co-Invest II LLC",
        entity_type=EntityType.SPV,
        status=EntityStatus.ACTIVE,
        committed_capital=75_000_000,
        invested_capital=30_000_000,
        aum=72_000_000,
        parent_entity_id=fund3.entity_id,
    ))

    session.flush()


def _load_policies(session: Session):
    """Create allocation policies."""
    # Get entity IDs for custom splits
    fund1 = session.query(Entity).filter(Entity.entity_name == "Apex Capital Partners I LP").first()
    fund2 = session.query(Entity).filter(Entity.entity_name == "Apex Capital Partners II LP").first()
    fund3 = session.query(Entity).filter(Entity.entity_name == "Apex Capital Partners III LP").first()
    gp = session.query(Entity).filter(Entity.entity_name == "Apex Capital Management LLC").first()

    policies = [
        AllocationPolicy(
            policy_name="Standard OpEx - AUM",
            methodology=AllocationMethod.PRO_RATA_AUM,
            applicable_expense_categories=json.dumps(["rent", "technology", "insurance"]),
        ),
        AllocationPolicy(
            policy_name="Standard OpEx - Committed",
            methodology=AllocationMethod.PRO_RATA_COMMITTED,
            applicable_expense_categories=json.dumps(["legal", "accounting", "compliance"]),
        ),
        AllocationPolicy(
            policy_name="Personnel Allocation",
            methodology=AllocationMethod.HEADCOUNT,
            applicable_expense_categories=json.dumps(["personnel"]),
        ),
        AllocationPolicy(
            policy_name="Travel - Direct to GP",
            methodology=AllocationMethod.DIRECT,
            applicable_expense_categories=json.dumps(["travel"]),
            target_entity_id=gp.entity_id,
        ),
        AllocationPolicy(
            policy_name="Deal Expenses",
            methodology=AllocationMethod.DEAL_SPECIFIC,
            applicable_expense_categories=json.dumps(["deal_expense", "due_diligence", "broken_deal"]),
        ),
        AllocationPolicy(
            policy_name="Fund Formation - Direct",
            methodology=AllocationMethod.DIRECT,
            applicable_expense_categories=json.dumps(["fund_formation", "organizational"]),
            target_entity_id=fund3.entity_id,
        ),
        AllocationPolicy(
            policy_name="Custom Office Split",
            methodology=AllocationMethod.CUSTOM_SPLIT,
            applicable_expense_categories=json.dumps(["consulting"]),
            entity_splits=json.dumps({
                str(fund1.entity_id): 0.20,
                str(fund2.entity_id): 0.35,
                str(fund3.entity_id): 0.45,
            }),
        ),
    ]

    for p in policies:
        session.add(p)
    session.flush()


def _load_expenses(session: Session):
    """Create 55+ sample expenses across categories."""
    gp = session.query(Entity).filter(Entity.entity_name == "Apex Capital Management LLC").first()
    fund3 = session.query(Entity).filter(Entity.entity_name == "Apex Capital Partners III LP").first()

    expenses = [
        # Legal
        ("2025-01-05", "Kirkland & Ellis LLP", "Fund III formation documents", 150000, "legal", "fund_formation"),
        ("2025-01-10", "Kirkland & Ellis LLP", "Fund III side letter negotiations", 85000, "legal", None),
        ("2025-01-15", "Simpson Thacher & Bartlett", "CloudBridge acquisition agreement", 200000, "legal", "deal_expense"),
        ("2025-01-20", "Ropes & Gray LLP", "SEC regulatory compliance review", 45000, "legal", "compliance"),
        ("2025-02-01", "Davis Polk & Wardwell", "Annual fund compliance review", 75000, "legal", None),
        ("2025-02-15", "Latham & Watkins", "Atlas Logistics purchase agreement", 180000, "legal", "deal_expense"),
        ("2025-02-28", "Skadden Arps", "LP advisory committee matters", 35000, "legal", None),
        ("2025-03-10", "Goodwin Procter", "Broken deal - Project Phoenix", 95000, "legal", "broken_deal"),
        ("2025-03-15", "Sullivan & Cromwell", "Tax structuring advice", 60000, "legal", None),

        # Accounting & Audit
        ("2025-01-30", "PricewaterhouseCoopers", "Annual fund audit - Fund I", 120000, "accounting", None),
        ("2025-01-30", "PricewaterhouseCoopers", "Annual fund audit - Fund II", 135000, "accounting", None),
        ("2025-02-15", "PricewaterhouseCoopers", "Annual fund audit - Fund III", 100000, "accounting", None),
        ("2025-03-01", "KPMG", "Tax return preparation - all entities", 85000, "accounting", None),
        ("2025-03-15", "Ernst & Young", "Portfolio company valuation support", 55000, "accounting", None),
        ("2025-03-31", "Deloitte", "K-1 preparation and distribution", 40000, "accounting", None),

        # Technology
        ("2025-01-01", "Bloomberg LP", "Terminal licenses (8 seats)", 192000, "technology", None),
        ("2025-01-01", "PitchBook Data", "Annual subscription", 36000, "technology", None),
        ("2025-01-01", "Datasite (Merrill)", "Virtual data room - annual", 48000, "technology", None),
        ("2025-02-01", "Microsoft 365", "Enterprise licenses - 30 users", 18000, "technology", None),
        ("2025-02-15", "Salesforce", "CRM - Investor Relations module", 24000, "technology", None),
        ("2025-03-01", "Carta", "Cap table management - all entities", 15000, "technology", None),
        ("2025-01-15", "AWS", "Cloud infrastructure", 8500, "technology", None),
        ("2025-02-15", "AWS", "Cloud infrastructure", 9200, "technology", None),
        ("2025-03-15", "AWS", "Cloud infrastructure", 8800, "technology", None),

        # Insurance
        ("2025-01-01", "Marsh McLennan", "D&O insurance - GP", 95000, "insurance", None),
        ("2025-01-01", "Chubb Insurance", "E&O professional liability", 75000, "insurance", None),
        ("2025-01-15", "AIG", "Cyber liability insurance", 35000, "insurance", None),
        ("2025-02-01", "Aon Risk Solutions", "Fiduciary liability insurance", 42000, "insurance", None),

        # Rent & Occupancy
        ("2025-01-01", "Brookfield Properties", "NYC office lease - January", 125000, "rent", None),
        ("2025-02-01", "Brookfield Properties", "NYC office lease - February", 125000, "rent", None),
        ("2025-03-01", "Brookfield Properties", "NYC office lease - March", 125000, "rent", None),
        ("2025-01-15", "CBRE", "SF satellite office", 28000, "rent", None),
        ("2025-02-15", "CBRE", "SF satellite office", 28000, "rent", None),
        ("2025-03-15", "CBRE", "SF satellite office", 28000, "rent", None),

        # Travel & Entertainment
        ("2025-01-12", "American Express Travel", "LP annual meeting - venue & catering", 45000, "travel", None),
        ("2025-01-18", "Delta Air Lines", "Partner travel - deal sourcing", 12500, "travel", None),
        ("2025-02-05", "United Airlines", "Team travel - portfolio company visits", 8900, "travel", None),
        ("2025-02-20", "Marriott International", "ILPA conference hotel", 6500, "travel", None),
        ("2025-03-08", "Delta Air Lines", "Due diligence travel - Project Atlas", 15000, "travel", "due_diligence"),
        ("2025-03-22", "Hilton Hotels", "Investor roadshow hotels", 9800, "travel", None),

        # Compliance & Regulatory
        ("2025-01-15", "ACA Compliance Group", "Annual compliance program", 65000, "compliance", None),
        ("2025-02-01", "SEC", "Form ADV filing fee", 2500, "compliance", None),
        ("2025-03-01", "CompliGlobal", "AML/KYC screening service", 18000, "compliance", None),

        # Consulting
        ("2025-01-20", "McKinsey & Company", "Market study - healthcare sector", 175000, "consulting", None),
        ("2025-02-10", "Bain & Company", "Commercial due diligence - Project Atlas", 125000, "consulting", "due_diligence"),
        ("2025-03-05", "BCG", "Operational improvement plan - Meridian Health", 95000, "consulting", None),

        # Personnel
        ("2025-01-31", "ADP Payroll", "January payroll - all staff", 450000, "personnel", None),
        ("2025-02-28", "ADP Payroll", "February payroll - all staff", 450000, "personnel", None),
        ("2025-03-31", "ADP Payroll", "March payroll - all staff", 450000, "personnel", None),
        ("2025-01-15", "Robert Half", "Temporary accounting staff", 22000, "personnel", None),

        # Deal-Specific
        ("2025-02-05", "Intralinks", "VDR for Project Atlas", 8500, "deal_expense", None),
        ("2025-02-20", "Houlihan Lokey", "Fairness opinion - CloudBridge add-on", 150000, "deal_expense", None),
        ("2025-03-10", "Duff & Phelps", "Valuation report - GreenPath", 45000, "deal_expense", None),

        # Fund Formation / Organizational
        ("2025-01-08", "Debevoise & Plimpton", "Fund III PPM drafting", 200000, "fund_formation", None),
        ("2025-01-25", "Ernst & Young", "Fund III tax structuring", 85000, "fund_formation", None),
        ("2025-02-12", "Seward & Kissel", "Fund III regulatory filings", 45000, "organizational", None),
        ("2025-03-20", "Blue River Partners", "Fund III placement agent fee", 350000, "fund_formation", None),

        # Broken Deal
        ("2025-03-15", "Wachtell Lipton", "Project Phoenix termination costs", 120000, "broken_deal", None),
    ]

    for row in expenses:
        date_str, vendor, description, amount, category, override_cat = row
        cat = ExpenseCategory(override_cat) if override_cat else ExpenseCategory(category)
        expense = Expense(
            date=datetime.strptime(date_str, "%Y-%m-%d"),
            vendor=vendor,
            description=description,
            amount=amount,
            currency="USD",
            expense_category=cat,
            source_entity_id=gp.entity_id,
            status=ExpenseStatus.PENDING,
        )
        session.add(expense)

    session.flush()
