"""Entity Allocation CLI - PE Multi-Entity Expense Allocation Tool."""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ceviche.db.database import get_session, init_db
from ceviche.models.entities import Entity, EntityType, EntityStatus
from ceviche.models.expenses import Expense, ExpenseCategory, ExpenseStatus
from ceviche.models.policies import AllocationPolicy, AllocationMethod
from ceviche.models.allocations import Allocation, AllocationOverride
from ceviche.engine.allocator import AllocationEngine, AllocationError
from ceviche.engine.categorizer import categorize_heuristic, categorize_with_ai
from ceviche.engine.compliance import ComplianceEngine
from ceviche.engine.journal_entries import JournalEntryGenerator
from ceviche.importers.csv_importer import import_expenses_csv
from ceviche.reports.summary import (
    monthly_summary, entity_report, category_report, variance_report,
)

console = Console()
app = typer.Typer(name="entity-allocation", help="PE Multi-Entity Expense Allocation Tool")

# Sub-command groups
entities_app = typer.Typer(help="Manage legal entities")
policies_app = typer.Typer(help="Manage allocation policies")
expenses_app = typer.Typer(help="Manage and import expenses")
report_app = typer.Typer(help="Generate reports")

app.add_typer(entities_app, name="entities")
app.add_typer(policies_app, name="policies")
app.add_typer(expenses_app, name="expenses")
app.add_typer(report_app, name="report")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    return {}


def get_db():
    config = load_config()
    db_path = os.path.expanduser(config.get("database", {}).get("path", "~/.ceviche/ceviche.db"))
    os.environ.setdefault("CEVICHE_DB", db_path)
    return get_session(db_path)


# ─── Init ───────────────────────────────────────────────────────────────────────

@app.command()
def init():
    """Initialize the database and create tables."""
    config = load_config()
    db_path = os.path.expanduser(config.get("database", {}).get("path", "~/.ceviche/ceviche.db"))
    os.environ.setdefault("CEVICHE_DB", db_path)
    init_db(db_path)
    console.print(f"[green]Database initialized at {db_path}[/green]")


# ─── Entities ───────────────────────────────────────────────────────────────────

@entities_app.command("list")
def entities_list():
    """List all entities."""
    session = get_db()
    entities = session.query(Entity).order_by(Entity.entity_type, Entity.entity_name).all()

    table = Table(title="Entities", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Committed Capital", justify="right")
    table.add_column("Invested Capital", justify="right")
    table.add_column("AUM", justify="right")
    table.add_column("Headcount", justify="right")

    for e in entities:
        status_style = "green" if e.status == EntityStatus.ACTIVE else "red"
        table.add_row(
            str(e.entity_id),
            e.entity_name,
            e.entity_type.value if e.entity_type else "",
            f"[{status_style}]{e.status.value}[/{status_style}]",
            f"${e.committed_capital:,.0f}" if e.committed_capital else "-",
            f"${e.invested_capital:,.0f}" if e.invested_capital else "-",
            f"${e.aum:,.0f}" if e.aum else "-",
            f"{e.headcount:.1f}" if e.headcount else "-",
        )

    console.print(table)
    session.close()


@entities_app.command("add")
def entities_add(
    name: str = typer.Option(..., "--name", help="Entity name"),
    type: str = typer.Option(..., "--type", help="Entity type: GP, Fund, PortCo, SPV"),
    committed_capital: float = typer.Option(0, "--committed-capital", help="Committed capital"),
    invested_capital: float = typer.Option(0, "--invested-capital", help="Invested capital"),
    aum: float = typer.Option(0, "--aum", help="Assets under management"),
    headcount: float = typer.Option(0, "--headcount", help="Headcount / FTE"),
    parent_id: Optional[int] = typer.Option(None, "--parent-id", help="Parent entity ID"),
    vintage: Optional[int] = typer.Option(None, "--vintage", help="Vintage year"),
):
    """Add a new entity."""
    session = get_db()
    try:
        entity_type = EntityType(type)
    except ValueError:
        console.print(f"[red]Invalid entity type '{type}'. Use: GP, Fund, PortCo, SPV[/red]")
        raise typer.Exit(1)

    entity = Entity(
        entity_name=name,
        entity_type=entity_type,
        status=EntityStatus.ACTIVE,
        committed_capital=committed_capital,
        invested_capital=invested_capital,
        aum=aum,
        headcount=headcount,
        parent_entity_id=parent_id,
        vintage_year=vintage,
    )
    session.add(entity)
    session.commit()
    console.print(f"[green]Entity '{name}' added with ID {entity.entity_id}[/green]")
    session.close()


@entities_app.command("update")
def entities_update(
    entity_id: int = typer.Argument(..., help="Entity ID to update"),
    name: Optional[str] = typer.Option(None, "--name"),
    committed_capital: Optional[float] = typer.Option(None, "--committed-capital"),
    invested_capital: Optional[float] = typer.Option(None, "--invested-capital"),
    aum: Optional[float] = typer.Option(None, "--aum"),
    headcount: Optional[float] = typer.Option(None, "--headcount"),
    status: Optional[str] = typer.Option(None, "--status", help="active, inactive, liquidated"),
):
    """Update an entity's metrics."""
    session = get_db()
    entity = session.query(Entity).get(entity_id)
    if not entity:
        console.print(f"[red]Entity {entity_id} not found[/red]")
        raise typer.Exit(1)

    if name is not None:
        entity.entity_name = name
    if committed_capital is not None:
        entity.committed_capital = committed_capital
    if invested_capital is not None:
        entity.invested_capital = invested_capital
    if aum is not None:
        entity.aum = aum
    if headcount is not None:
        entity.headcount = headcount
    if status is not None:
        try:
            entity.status = EntityStatus(status)
        except ValueError:
            console.print(f"[red]Invalid status '{status}'[/red]")
            raise typer.Exit(1)

    session.commit()
    console.print(f"[green]Entity '{entity.entity_name}' updated[/green]")
    session.close()


@entities_app.command("show")
def entities_show(entity_id: int = typer.Argument(..., help="Entity ID")):
    """Show detailed entity information."""
    session = get_db()
    entity = session.query(Entity).get(entity_id)
    if not entity:
        console.print(f"[red]Entity {entity_id} not found[/red]")
        raise typer.Exit(1)

    data = entity.to_dict()
    panel_content = "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in data.items())
    console.print(Panel(panel_content, title=entity.entity_name, box=box.ROUNDED))

    # Show children
    children = session.query(Entity).filter(Entity.parent_entity_id == entity_id).all()
    if children:
        console.print("\n[bold]Child Entities:[/bold]")
        for c in children:
            console.print(f"  - {c.entity_name} ({c.entity_type.value})")

    session.close()


# ─── Policies ───────────────────────────────────────────────────────────────────

@policies_app.command("list")
def policies_list():
    """List all allocation policies."""
    session = get_db()
    policies = session.query(AllocationPolicy).all()

    table = Table(title="Allocation Policies", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Methodology")
    table.add_column("Categories")
    table.add_column("Effective Date")

    for p in policies:
        categories = ", ".join(p.get_categories()[:3])
        if len(p.get_categories()) > 3:
            categories += f" (+{len(p.get_categories()) - 3})"
        table.add_row(
            str(p.policy_id),
            p.policy_name,
            p.methodology.value if p.methodology else "",
            categories,
            p.effective_date.strftime("%Y-%m-%d") if p.effective_date else "",
        )

    console.print(table)
    session.close()


@policies_app.command("add")
def policies_add(
    name: str = typer.Option(..., "--name", help="Policy name"),
    method: str = typer.Option(..., "--method", help="Allocation method"),
    categories: str = typer.Option("", "--categories", help="Comma-separated expense categories"),
    splits: str = typer.Option("", "--splits", help="JSON custom splits, e.g. '{\"1\": 0.5, \"2\": 0.5}'"),
    target_entity: Optional[int] = typer.Option(None, "--target-entity", help="Target entity ID for direct/deal"),
    lpa_ref: Optional[str] = typer.Option(None, "--lpa-ref", help="LPA reference text"),
):
    """Add a new allocation policy."""
    session = get_db()
    try:
        alloc_method = AllocationMethod(method)
    except ValueError:
        methods = ", ".join(m.value for m in AllocationMethod)
        console.print(f"[red]Invalid method '{method}'. Use: {methods}[/red]")
        raise typer.Exit(1)

    policy = AllocationPolicy(
        policy_name=name,
        methodology=alloc_method,
        target_entity_id=target_entity,
        lpa_reference=lpa_ref,
    )

    if categories:
        policy.set_categories([c.strip() for c in categories.split(",")])

    if splits:
        try:
            policy.set_splits(json.loads(splits))
        except json.JSONDecodeError:
            console.print("[red]Invalid JSON for --splits[/red]")
            raise typer.Exit(1)

    session.add(policy)
    session.commit()
    console.print(f"[green]Policy '{name}' added with ID {policy.policy_id}[/green]")
    session.close()


@policies_app.command("show")
def policies_show(policy_id: int = typer.Argument(..., help="Policy ID")):
    """Show detailed policy information."""
    session = get_db()
    policy = session.query(AllocationPolicy).get(policy_id)
    if not policy:
        console.print(f"[red]Policy {policy_id} not found[/red]")
        raise typer.Exit(1)

    data = policy.to_dict()
    panel_content = "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in data.items())
    console.print(Panel(panel_content, title=policy.policy_name, box=box.ROUNDED))
    session.close()


# ─── Expenses ───────────────────────────────────────────────────────────────────

@expenses_app.command("list")
def expenses_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
    month: Optional[str] = typer.Option(None, "--month", help="Filter by month (YYYY-MM)"),
    category: Optional[str] = typer.Option(None, "--category", help="Filter by category"),
    limit: int = typer.Option(50, "--limit", help="Max rows to display"),
):
    """List expenses with optional filters."""
    session = get_db()
    query = session.query(Expense)

    if status:
        try:
            query = query.filter(Expense.status == ExpenseStatus(status))
        except ValueError:
            console.print(f"[red]Invalid status '{status}'[/red]")
            raise typer.Exit(1)

    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
            start = datetime(year, mon, 1)
            end = datetime(year, mon + 1, 1) if mon < 12 else datetime(year + 1, 1, 1)
            query = query.filter(Expense.date >= start, Expense.date < end)
        except ValueError:
            console.print("[red]Invalid month format. Use YYYY-MM[/red]")
            raise typer.Exit(1)

    if category:
        try:
            query = query.filter(Expense.expense_category == ExpenseCategory(category))
        except ValueError:
            console.print(f"[red]Invalid category '{category}'[/red]")
            raise typer.Exit(1)

    expenses = query.order_by(Expense.date.desc()).limit(limit).all()

    table = Table(title="Expenses", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Date")
    table.add_column("Vendor", style="bold")
    table.add_column("Amount", justify="right")
    table.add_column("Category")
    table.add_column("Status")
    table.add_column("Description", max_width=30)

    for e in expenses:
        status_colors = {
            ExpenseStatus.PENDING: "yellow",
            ExpenseStatus.ALLOCATED: "green",
            ExpenseStatus.REVIEWED: "blue",
            ExpenseStatus.POSTED: "dim",
        }
        color = status_colors.get(e.status, "white")
        table.add_row(
            str(e.expense_id),
            e.date.strftime("%Y-%m-%d") if e.date else "",
            e.vendor,
            f"${e.amount:,.2f}",
            e.expense_category.value if e.expense_category else "-",
            f"[{color}]{e.status.value}[/{color}]",
            (e.description or "")[:30],
        )

    console.print(table)
    console.print(f"[dim]Showing {len(expenses)} expenses[/dim]")
    session.close()


@expenses_app.command("add")
def expenses_add(
    date: str = typer.Option(..., "--date", help="Expense date (YYYY-MM-DD)"),
    vendor: str = typer.Option(..., "--vendor", help="Vendor name"),
    amount: float = typer.Option(..., "--amount", help="Expense amount"),
    category: str = typer.Option("other", "--category", help="Expense category"),
    description: str = typer.Option("", "--description", help="Description"),
    entity: Optional[str] = typer.Option(None, "--entity", help="Source entity name"),
    gl_account: Optional[str] = typer.Option(None, "--gl-account", help="GL account code"),
    currency: str = typer.Option("USD", "--currency"),
):
    """Add a single expense."""
    session = get_db()

    try:
        exp_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    try:
        cat = ExpenseCategory(category)
    except ValueError:
        cats = ", ".join(c.value for c in ExpenseCategory)
        console.print(f"[red]Invalid category '{category}'. Use: {cats}[/red]")
        raise typer.Exit(1)

    source_entity_id = None
    if entity:
        ent = session.query(Entity).filter(Entity.entity_name == entity).first()
        if ent:
            source_entity_id = ent.entity_id
        else:
            console.print(f"[yellow]Warning: Entity '{entity}' not found[/yellow]")

    expense = Expense(
        date=exp_date,
        vendor=vendor,
        description=description,
        amount=amount,
        currency=currency,
        expense_category=cat,
        source_entity_id=source_entity_id,
        status=ExpenseStatus.PENDING,
        gl_account_code=gl_account,
    )
    session.add(expense)
    session.commit()
    console.print(f"[green]Expense added with ID {expense.expense_id}[/green]")
    session.close()


@expenses_app.command("import")
def expenses_import(
    file: str = typer.Option(..., "--file", help="Path to CSV file"),
):
    """Import expenses from a CSV file."""
    session = get_db()

    if not os.path.exists(file):
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]Importing from {file}...[/blue]")
    result = import_expenses_csv(session, file)

    console.print(f"[green]Imported: {result.imported}[/green]")
    if result.skipped:
        console.print(f"[yellow]Skipped: {result.skipped}[/yellow]")
    if result.duplicates:
        console.print("[yellow]Duplicates:[/yellow]")
        for d in result.duplicates:
            console.print(f"  - {d}")
    if result.errors:
        console.print("[red]Errors:[/red]")
        for e in result.errors:
            console.print(f"  - {e}")

    session.close()


@expenses_app.command("categorize")
def expenses_categorize():
    """Auto-categorize uncategorized expenses using AI/heuristics."""
    session = get_db()
    uncategorized = (
        session.query(Expense)
        .filter(Expense.expense_category.is_(None))
        .all()
    )

    if not uncategorized:
        console.print("[green]No uncategorized expenses found[/green]")
        return

    console.print(f"[blue]Categorizing {len(uncategorized)} expenses...[/blue]")

    categorized = 0
    for expense in uncategorized:
        result = categorize_with_ai(expense.vendor, expense.description or "", expense.amount)
        if result:
            try:
                expense.expense_category = ExpenseCategory(result["category"])
                categorized += 1
                console.print(
                    f"  {expense.vendor}: {result['category']} "
                    f"(confidence: {result.get('confidence', 0):.0%})"
                )
            except ValueError:
                pass

    session.commit()
    console.print(f"[green]Categorized {categorized}/{len(uncategorized)} expenses[/green]")
    session.close()


# ─── Allocate ───────────────────────────────────────────────────────────────────

@app.command()
def allocate(
    expense_id: Optional[int] = typer.Option(None, "--expense-id", help="Allocate a single expense"),
    month: Optional[str] = typer.Option(None, "--month", help="Allocate all pending for month (YYYY-MM)"),
    preview: bool = typer.Option(False, "--preview", help="Dry run / preview mode"),
    recalculate: bool = typer.Option(False, "--recalculate", help="Recalculate existing allocations"),
):
    """Run the allocation engine."""
    session = get_db()
    engine = AllocationEngine(session)

    if expense_id:
        expense = session.query(Expense).get(expense_id)
        if not expense:
            console.print(f"[red]Expense {expense_id} not found[/red]")
            raise typer.Exit(1)

        try:
            splits = engine.allocate_expense(expense, preview=preview)
            _display_allocation_result(expense, splits, preview)
        except AllocationError as e:
            console.print(f"[red]Allocation error: {e}[/red]")
            raise typer.Exit(1)

    elif month:
        try:
            dt = datetime.strptime(month, "%Y-%m")
        except ValueError:
            console.print("[red]Invalid month format. Use YYYY-MM[/red]")
            raise typer.Exit(1)

        mode = "PREVIEW" if preview else "ALLOCATING"
        console.print(f"[blue]{mode} expenses for {month}...[/blue]")

        results = engine.allocate_month(dt.year, dt.month, preview=preview, recalculate=recalculate)

        for item in results["allocated"]:
            console.print(
                f"  [green]#{item['expense_id']}[/green] {item['vendor']} "
                f"(${item['amount']:,.2f}) → {len(item['allocations'])} entities"
            )

        if results["errors"]:
            console.print("\n[red]Errors:[/red]")
            for err in results["errors"]:
                console.print(f"  #{err['expense_id']} {err['vendor']}: {err['error']}")

        console.print(
            f"\n[bold]Total: {len(results['allocated'])} allocated, "
            f"{len(results['errors'])} errors[/bold]"
        )
    else:
        console.print("[red]Specify --expense-id or --month[/red]")
        raise typer.Exit(1)

    session.close()


def _display_allocation_result(expense: Expense, splits: list, preview: bool):
    """Display allocation result in a formatted table."""
    mode = "PREVIEW" if preview else "ALLOCATED"
    table = Table(title=f"{mode}: {expense.vendor} (${expense.amount:,.2f})", box=box.ROUNDED)
    table.add_column("Entity", style="bold")
    table.add_column("Amount", justify="right")
    table.add_column("Percentage", justify="right")

    for s in splits:
        table.add_row(
            s["entity_name"],
            f"${s['amount']:,.2f}",
            f"{s['percentage']:.1f}%",
        )

    console.print(table)


# ─── Override ───────────────────────────────────────────────────────────────────

@app.command()
def override(
    expense_id: int = typer.Argument(..., help="Expense ID to override"),
    new_splits: str = typer.Option(..., "--new-splits", help="JSON splits: {\"entity_id\": pct, ...}"),
    reason: str = typer.Option(..., "--reason", help="Reason for override"),
):
    """Override an existing allocation with new splits."""
    session = get_db()

    expense = session.query(Expense).get(expense_id)
    if not expense:
        console.print(f"[red]Expense {expense_id} not found[/red]")
        raise typer.Exit(1)

    try:
        splits = json.loads(new_splits)
    except json.JSONDecodeError:
        console.print("[red]Invalid JSON for --new-splits[/red]")
        raise typer.Exit(1)

    # Validate splits sum to ~1.0
    total = sum(splits.values())
    if abs(total - 1.0) > 0.001:
        console.print(f"[red]Splits must sum to 1.0 (got {total})[/red]")
        raise typer.Exit(1)

    # Save original allocations
    existing = session.query(Allocation).filter(Allocation.expense_id == expense_id).all()
    original = {str(a.target_entity_id): a.allocation_percentage for a in existing}

    # Create override record
    ovr = AllocationOverride(
        expense_id=expense_id,
        reason=reason,
        original_allocation=json.dumps(original),
        new_allocation=json.dumps(splits),
        approval_status="approved",
    )
    session.add(ovr)

    # Delete old allocations
    for a in existing:
        session.delete(a)

    # Create new allocations
    for entity_id_str, pct in splits.items():
        entity_id = int(entity_id_str)
        entity = session.query(Entity).get(entity_id)
        if not entity:
            console.print(f"[red]Entity {entity_id} not found[/red]")
            raise typer.Exit(1)

        alloc = Allocation(
            expense_id=expense_id,
            target_entity_id=entity_id,
            allocated_amount=round(expense.amount * pct, 2),
            allocation_percentage=pct * 100,
            methodology_used="manual_override",
            journal_entry_reference=f"OVERRIDE-{expense_id}",
        )
        session.add(alloc)

    session.commit()
    console.print(f"[green]Allocation override applied for expense #{expense_id}[/green]")
    session.close()


# ─── Audit Trail ────────────────────────────────────────────────────────────────

@app.command("audit-trail")
def audit_trail(
    expense_id: Optional[int] = typer.Option(None, "--expense-id", help="Expense ID"),
    month: Optional[str] = typer.Option(None, "--month", help="Month (YYYY-MM)"),
):
    """View audit trail for allocations."""
    session = get_db()

    if expense_id:
        expense = session.query(Expense).get(expense_id)
        if not expense:
            console.print(f"[red]Expense {expense_id} not found[/red]")
            raise typer.Exit(1)

        console.print(Panel(
            f"Vendor: {expense.vendor}\n"
            f"Date: {expense.date.strftime('%Y-%m-%d')}\n"
            f"Amount: ${expense.amount:,.2f}\n"
            f"Category: {expense.expense_category.value if expense.expense_category else 'N/A'}\n"
            f"Status: {expense.status.value}",
            title=f"Expense #{expense_id}",
        ))

        allocations = session.query(Allocation).filter(Allocation.expense_id == expense_id).all()
        if allocations:
            table = Table(title="Allocations", box=box.SIMPLE)
            table.add_column("Entity")
            table.add_column("Amount", justify="right")
            table.add_column("Percentage", justify="right")
            table.add_column("Method")
            table.add_column("Date")
            table.add_column("JE Ref")

            for a in allocations:
                entity = session.query(Entity).get(a.target_entity_id)
                table.add_row(
                    entity.entity_name if entity else str(a.target_entity_id),
                    f"${a.allocated_amount:,.2f}",
                    f"{a.allocation_percentage:.1f}%",
                    a.methodology_used,
                    a.allocation_date.strftime("%Y-%m-%d %H:%M") if a.allocation_date else "",
                    a.journal_entry_reference or "",
                )
            console.print(table)

        # Show overrides
        overrides = session.query(AllocationOverride).filter(
            AllocationOverride.expense_id == expense_id
        ).all()
        if overrides:
            console.print("\n[bold]Override History:[/bold]")
            for o in overrides:
                console.print(
                    f"  [{o.created_at.strftime('%Y-%m-%d')}] {o.reason} "
                    f"(status: {o.approval_status})"
                )

    elif month:
        try:
            dt = datetime.strptime(month, "%Y-%m")
        except ValueError:
            console.print("[red]Invalid month format[/red]")
            raise typer.Exit(1)

        start = datetime(dt.year, dt.month, 1)
        end = datetime(dt.year, dt.month + 1, 1) if dt.month < 12 else datetime(dt.year + 1, 1, 1)

        allocations = (
            session.query(Allocation)
            .filter(Allocation.allocation_date >= start, Allocation.allocation_date < end)
            .order_by(Allocation.allocation_date)
            .all()
        )

        console.print(f"[bold]{len(allocations)} allocations in {month}[/bold]")
        for a in allocations[:50]:
            expense = session.query(Expense).get(a.expense_id)
            entity = session.query(Entity).get(a.target_entity_id)
            console.print(
                f"  [{a.allocation_date.strftime('%m/%d')}] "
                f"{expense.vendor if expense else '?'} → "
                f"{entity.entity_name if entity else '?'}: "
                f"${a.allocated_amount:,.2f} ({a.methodology_used})"
            )
    else:
        console.print("[red]Specify --expense-id or --month[/red]")

    session.close()


# ─── Reports ────────────────────────────────────────────────────────────────────

@report_app.command("summary")
def report_summary(
    month: str = typer.Option(..., "--month", help="Month (YYYY-MM)"),
):
    """Monthly allocation summary."""
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
    except ValueError:
        console.print("[red]Invalid month format[/red]")
        raise typer.Exit(1)

    data = monthly_summary(session, dt.year, dt.month)

    console.print(Panel(
        f"Total Expenses: {data['total_expense_count']}\n"
        f"Total Amount: ${data['total_expense_amount']:,.2f}",
        title=f"Monthly Summary - {month}",
    ))

    # Status breakdown
    if data["status_breakdown"]:
        table = Table(title="By Status", box=box.SIMPLE)
        table.add_column("Status")
        table.add_column("Count", justify="right")
        table.add_column("Amount", justify="right")
        for s in data["status_breakdown"]:
            table.add_row(s["status"], str(s["count"]), f"${s['amount']:,.2f}")
        console.print(table)

    # By entity
    if data["by_entity"]:
        table = Table(title="By Entity", box=box.SIMPLE)
        table.add_column("Entity")
        table.add_column("Type")
        table.add_column("Allocated", justify="right")
        table.add_column("# Allocations", justify="right")
        for e in sorted(data["by_entity"], key=lambda x: -x["allocated_amount"]):
            table.add_row(
                e["entity"], e["type"],
                f"${e['allocated_amount']:,.2f}", str(e["allocation_count"]),
            )
        console.print(table)

    # By category
    if data["by_category"]:
        table = Table(title="By Category", box=box.SIMPLE)
        table.add_column("Category")
        table.add_column("Count", justify="right")
        table.add_column("Amount", justify="right")
        for c in sorted(data["by_category"], key=lambda x: -x["amount"]):
            table.add_row(c["category"], str(c["count"]), f"${c['amount']:,.2f}")
        console.print(table)

    session.close()


@report_app.command("by-entity")
def report_by_entity(
    entity: str = typer.Option(..., "--entity", help="Entity name"),
    quarter: Optional[str] = typer.Option(None, "--quarter", help="Quarter (Q1-2025)"),
    year: Optional[int] = typer.Option(None, "--year", help="Year"),
):
    """Report for a specific entity."""
    session = get_db()

    q = None
    y = year or datetime.utcnow().year
    if quarter:
        parts = quarter.split("-")
        q = int(parts[0].replace("Q", "").replace("q", ""))
        if len(parts) > 1:
            y = int(parts[1])

    data = entity_report(session, entity, y, q)
    if "error" in data:
        console.print(f"[red]{data['error']}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"Entity: {data['entity']} ({data['entity_type']})\n"
        f"Period: {data['period']}\n"
        f"Total Allocated: ${data['total_allocated']:,.2f}\n"
        f"Expense Count: {data['expense_count']}",
        title=f"Entity Report - {entity}",
    ))

    if data["by_category"]:
        table = Table(title="By Category", box=box.SIMPLE)
        table.add_column("Category")
        table.add_column("Amount", justify="right")
        for cat, amt in sorted(data["by_category"].items(), key=lambda x: -x[1]):
            table.add_row(cat, f"${amt:,.2f}")
        console.print(table)

    if data["top_vendors"]:
        table = Table(title="Top Vendors", box=box.SIMPLE)
        table.add_column("Vendor")
        table.add_column("Amount", justify="right")
        for vendor, amt in list(data["top_vendors"].items())[:10]:
            table.add_row(vendor, f"${amt:,.2f}")
        console.print(table)

    session.close()


@report_app.command("by-category")
def report_by_category(
    category: str = typer.Option(..., "--category", help="Expense category"),
    year: int = typer.Option(None, "--year", help="Year"),
):
    """Report by expense category across all entities."""
    session = get_db()
    y = year or datetime.utcnow().year
    data = category_report(session, category, y)

    if "error" in data:
        console.print(f"[red]{data['error']}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"Category: {data['category']}\nYear: {data['year']}\nTotal: ${data['total']:,.2f}",
        title=f"Category Report - {category}",
    ))

    if data["by_entity"]:
        table = Table(title="By Entity", box=box.SIMPLE)
        table.add_column("Entity")
        table.add_column("Amount", justify="right")
        for ent, amt in sorted(data["by_entity"].items(), key=lambda x: -x[1]):
            table.add_row(ent, f"${amt:,.2f}")
        console.print(table)

    if data["by_month"]:
        table = Table(title="By Month", box=box.SIMPLE)
        table.add_column("Month")
        table.add_column("Amount", justify="right")
        for mo, amt in data["by_month"].items():
            table.add_row(mo, f"${amt:,.2f}")
        console.print(table)

    session.close()


@report_app.command("variance")
def report_variance(
    month: str = typer.Option(..., "--month", help="Month (YYYY-MM)"),
):
    """Compare allocations to prior period."""
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
    except ValueError:
        console.print("[red]Invalid month format[/red]")
        raise typer.Exit(1)

    data = variance_report(session, dt.year, dt.month)

    console.print(Panel(
        f"Current Period: {data['current_period']} (${data['total_current']:,.2f})\n"
        f"Prior Period: {data['prior_period']} (${data['total_prior']:,.2f})\n"
        f"Change: ${data['total_change']:,.2f}",
        title="Variance Report",
    ))

    if data["by_entity"]:
        table = Table(title="Entity Variance", box=box.SIMPLE)
        table.add_column("Entity")
        table.add_column("Current", justify="right")
        table.add_column("Prior", justify="right")
        table.add_column("Change", justify="right")
        table.add_column("% Change", justify="right")

        for e in data["by_entity"]:
            change_style = "green" if e["change"] <= 0 else "red"
            table.add_row(
                e["entity"],
                f"${e['current']:,.2f}",
                f"${e['prior']:,.2f}",
                f"[{change_style}]${e['change']:,.2f}[/{change_style}]",
                f"[{change_style}]{e['pct_change']:+.1f}%[/{change_style}]",
            )
        console.print(table)

    session.close()


@report_app.command("lpa-compliance")
def report_lpa_compliance(
    fund: str = typer.Option(..., "--fund", help="Fund name"),
    year: Optional[int] = typer.Option(None, "--year"),
):
    """Check LPA compliance for a fund."""
    session = get_db()
    config = load_config()
    y = year or datetime.utcnow().year

    engine = ComplianceEngine(session, config)
    violations = engine.check_fund_compliance(fund, y)

    if not violations:
        console.print(f"[green]Fund '{fund}' is fully compliant for {y}[/green]")
    else:
        console.print(f"[red]{len(violations)} compliance issue(s) found for '{fund}':[/red]")
        for v in violations:
            severity_color = "red" if v.severity == "critical" else "yellow"
            console.print(Panel(
                f"[{severity_color}]{v.description}[/{severity_color}]\n"
                f"Limit: ${v.limit:,.2f}\n"
                f"Actual: ${v.actual:,.2f}\n"
                f"Excess: ${v.excess:,.2f}",
                title=f"[{severity_color}]{v.rule_name} ({v.severity.upper()})[/{severity_color}]",
            ))

    session.close()


@report_app.command("export")
def report_export(
    format: str = typer.Option("csv", "--format", help="Export format: csv"),
    month: str = typer.Option(..., "--month", help="Month (YYYY-MM)"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Export report data to CSV."""
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
    except ValueError:
        console.print("[red]Invalid month format[/red]")
        raise typer.Exit(1)

    data = monthly_summary(session, dt.year, dt.month)
    output_path = output or f"ceviche_report_{month}.csv"

    # Flatten entity data for export
    from ceviche.reports.summary import export_report_csv
    if data["by_entity"]:
        export_report_csv(data["by_entity"], output_path)
        console.print(f"[green]Report exported to {output_path}[/green]")
    else:
        console.print("[yellow]No allocation data to export[/yellow]")

    session.close()


@report_app.command("journal-entries")
def report_journal_entries(
    month: str = typer.Option(..., "--month", help="Month (YYYY-MM)"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Generate journal entries for NetSuite/QBO export."""
    session = get_db()
    try:
        dt = datetime.strptime(month, "%Y-%m")
    except ValueError:
        console.print("[red]Invalid month format[/red]")
        raise typer.Exit(1)

    generator = JournalEntryGenerator(session)
    entries = generator.generate_for_month(dt.year, dt.month)

    if not entries:
        console.print("[yellow]No journal entries to generate[/yellow]")
        return

    output_path = output or f"journal_entries_{month}.csv"
    generator.export_csv(entries, output_path)
    console.print(f"[green]Generated {len(entries)} journal entry lines to {output_path}[/green]")

    # Preview first few
    table = Table(title=f"Journal Entries Preview ({month})", box=box.SIMPLE)
    table.add_column("Date")
    table.add_column("JE ID")
    table.add_column("Entity")
    table.add_column("Account")
    table.add_column("Debit", justify="right")
    table.add_column("Credit", justify="right")
    table.add_column("Memo", max_width=30)

    for entry in entries[:20]:
        table.add_row(
            entry["date"],
            entry["journal_entry_id"],
            entry["entity"],
            f"{entry['account_code']} - {entry['account_name']}",
            f"${entry['debit']:,.2f}" if entry["debit"] else "",
            f"${entry['credit']:,.2f}" if entry["credit"] else "",
            entry["memo"][:30],
        )

    console.print(table)
    if len(entries) > 20:
        console.print(f"[dim]... and {len(entries) - 20} more lines[/dim]")

    session.close()


# ─── Seed Data ──────────────────────────────────────────────────────────────────

@app.command()
def seed():
    """Load sample seed data for testing."""
    from ceviche.tests.fixtures.sample_data import load_seed_data
    session = get_db()
    init_db()
    load_seed_data(session)
    console.print("[green]Seed data loaded successfully[/green]")
    session.close()


# ─── Query ──────────────────────────────────────────────────────────────────────

@app.command()
def query(
    question: str = typer.Argument(..., help="Natural language question"),
):
    """Ask a natural language question about allocations."""
    from ceviche.ai.query_handler import handle_natural_query

    session = get_db()
    answer = handle_natural_query(session, question)
    console.print(f"\n{answer}\n")
    session.close()


def main():
    app()


if __name__ == "__main__":
    main()
