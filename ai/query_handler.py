"""Natural language query handler using Claude API."""
import json
import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from ceviche.models.entities import Entity
from ceviche.models.expenses import Expense, ExpenseCategory
from ceviche.models.allocations import Allocation

logger = logging.getLogger(__name__)


def handle_natural_query(session: Session, question: str) -> str:
    """
    Handle a natural language question about allocations.

    Falls back to keyword parsing if Claude API is not available.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        return _handle_with_ai(session, question, api_key)
    else:
        return _handle_with_keywords(session, question)


def _handle_with_ai(session: Session, question: str, api_key: str) -> str:
    """Use Claude to interpret the question and generate a SQL-like query."""
    try:
        import anthropic

        # Gather schema context
        entities = session.query(Entity).all()
        entity_names = [e.entity_name for e in entities]
        categories = [c.value for c in ExpenseCategory]

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a PE fund accounting assistant. Answer this question about "
                    f"expense allocations.\n\n"
                    f"Available entities: {entity_names}\n"
                    f"Available categories: {categories}\n\n"
                    f"Question: {question}\n\n"
                    f"Respond with a JSON object specifying the query parameters:\n"
                    f'{{"action": "sum"|"list"|"count", '
                    f'"entity": "<entity name or null>", '
                    f'"category": "<category or null>", '
                    f'"year": <year or null>, '
                    f'"quarter": <quarter 1-4 or null>, '
                    f'"month": <month 1-12 or null>}}'
                ),
            }],
        )

        response_text = message.content[0].text
        if "{" in response_text:
            json_str = response_text[response_text.index("{"):response_text.rindex("}") + 1]
            params = json.loads(json_str)
            return _execute_query(session, params, question)

    except Exception as e:
        logger.warning(f"AI query handling failed: {e}")

    return _handle_with_keywords(session, question)


def _handle_with_keywords(session: Session, question: str) -> str:
    """Parse question using simple keyword matching."""
    q = question.lower()

    # Extract entity name
    entities = session.query(Entity).all()
    target_entity = None
    for e in entities:
        if e.entity_name.lower() in q:
            target_entity = e.entity_name
            break

    # Extract category
    target_category = None
    for cat in ExpenseCategory:
        if cat.value.replace("_", " ") in q:
            target_category = cat.value
            break

    # Extract year
    year = None
    for y in range(2020, 2030):
        if str(y) in q:
            year = y
            break

    # Extract quarter
    quarter = None
    for i in range(1, 5):
        if f"q{i}" in q:
            quarter = i
            break

    params = {
        "action": "sum" if any(w in q for w in ["how much", "total", "sum"]) else "list",
        "entity": target_entity,
        "category": target_category,
        "year": year or datetime.utcnow().year,
        "quarter": quarter,
    }

    return _execute_query(session, params, question)


def _execute_query(session: Session, params: dict, original_question: str) -> str:
    """Execute the parsed query and format results."""
    action = params.get("action", "sum")
    entity_name = params.get("entity")
    category = params.get("category")
    year = params.get("year") or datetime.utcnow().year
    quarter = params.get("quarter")
    month = params.get("month")

    query = (
        session.query(
            func.sum(Allocation.allocated_amount).label("total"),
            func.count(Allocation.allocation_id).label("count"),
        )
        .join(Expense, Allocation.expense_id == Expense.expense_id)
        .filter(extract("year", Expense.date) == year)
    )

    if entity_name:
        entity = session.query(Entity).filter(Entity.entity_name == entity_name).first()
        if entity:
            query = query.filter(Allocation.target_entity_id == entity.entity_id)

    if category:
        try:
            cat_enum = ExpenseCategory(category)
            query = query.filter(Expense.expense_category == cat_enum)
        except ValueError:
            pass

    if quarter:
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 3
        query = query.filter(
            extract("month", Expense.date) >= start_month,
            extract("month", Expense.date) < end_month,
        )
    elif month:
        query = query.filter(extract("month", Expense.date) == month)

    result = query.first()
    total = float(result.total or 0)
    count = int(result.count or 0)

    # Format response
    parts = []
    if entity_name:
        parts.append(f"for {entity_name}")
    if category:
        parts.append(f"in category '{category}'")

    period = str(year)
    if quarter:
        period = f"Q{quarter} {year}"
    elif month:
        period = f"{year}-{month:02d}"
    parts.append(f"during {period}")

    context = " ".join(parts)

    return (
        f"Total allocated {context}: ${total:,.2f} "
        f"across {count} allocation(s)"
    )
