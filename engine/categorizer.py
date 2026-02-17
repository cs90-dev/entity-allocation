"""AI-assisted expense categorization using Claude API."""
import json
import logging
import os
from typing import Optional

from ceviche.models.expenses import ExpenseCategory

logger = logging.getLogger(__name__)

# Heuristic-based categorization rules (used as fallback or when API key not available)
VENDOR_CATEGORY_HINTS = {
    # Legal firms
    "kirkland": ExpenseCategory.LEGAL,
    "latham": ExpenseCategory.LEGAL,
    "simpson thacher": ExpenseCategory.LEGAL,
    "skadden": ExpenseCategory.LEGAL,
    "wachtell": ExpenseCategory.LEGAL,
    "davis polk": ExpenseCategory.LEGAL,
    "sullivan & cromwell": ExpenseCategory.LEGAL,
    "ropes & gray": ExpenseCategory.LEGAL,
    "goodwin": ExpenseCategory.LEGAL,
    "debevoise": ExpenseCategory.LEGAL,
    # Accounting
    "pwc": ExpenseCategory.ACCOUNTING,
    "pricewaterhousecoopers": ExpenseCategory.ACCOUNTING,
    "deloitte": ExpenseCategory.ACCOUNTING,
    "kpmg": ExpenseCategory.ACCOUNTING,
    "ernst & young": ExpenseCategory.ACCOUNTING,
    "ey ": ExpenseCategory.ACCOUNTING,
    "grant thornton": ExpenseCategory.ACCOUNTING,
    "bdo": ExpenseCategory.ACCOUNTING,
    # Technology
    "bloomberg": ExpenseCategory.TECHNOLOGY,
    "pitchbook": ExpenseCategory.TECHNOLOGY,
    "datasite": ExpenseCategory.TECHNOLOGY,
    "intralinks": ExpenseCategory.TECHNOLOGY,
    "microsoft": ExpenseCategory.TECHNOLOGY,
    "salesforce": ExpenseCategory.TECHNOLOGY,
    "aws": ExpenseCategory.TECHNOLOGY,
    "google cloud": ExpenseCategory.TECHNOLOGY,
    # Insurance
    "marsh": ExpenseCategory.INSURANCE,
    "aon": ExpenseCategory.INSURANCE,
    "willis": ExpenseCategory.INSURANCE,
    "chubb": ExpenseCategory.INSURANCE,
    # Travel
    "american express travel": ExpenseCategory.TRAVEL,
    "delta": ExpenseCategory.TRAVEL,
    "united airlines": ExpenseCategory.TRAVEL,
    "marriott": ExpenseCategory.TRAVEL,
    "hilton": ExpenseCategory.TRAVEL,
    # Compliance
    "sec filing": ExpenseCategory.COMPLIANCE,
    "compliance solutions": ExpenseCategory.COMPLIANCE,
    "aml": ExpenseCategory.COMPLIANCE,
    # Consulting
    "mckinsey": ExpenseCategory.CONSULTING,
    "bain": ExpenseCategory.CONSULTING,
    "bcg": ExpenseCategory.CONSULTING,
}

DESCRIPTION_KEYWORDS = {
    "formation": ExpenseCategory.FUND_FORMATION,
    "fund formation": ExpenseCategory.FUND_FORMATION,
    "organization": ExpenseCategory.ORGANIZATIONAL,
    "organizational": ExpenseCategory.ORGANIZATIONAL,
    "due diligence": ExpenseCategory.DUE_DILIGENCE,
    "diligence": ExpenseCategory.DUE_DILIGENCE,
    "broken deal": ExpenseCategory.BROKEN_DEAL,
    "dead deal": ExpenseCategory.BROKEN_DEAL,
    "terminated deal": ExpenseCategory.BROKEN_DEAL,
    "deal expense": ExpenseCategory.DEAL_EXPENSE,
    "transaction": ExpenseCategory.DEAL_EXPENSE,
    "acquisition": ExpenseCategory.DEAL_EXPENSE,
    "rent": ExpenseCategory.RENT,
    "office lease": ExpenseCategory.RENT,
    "sublease": ExpenseCategory.RENT,
    "insurance": ExpenseCategory.INSURANCE,
    "d&o": ExpenseCategory.INSURANCE,
    "e&o": ExpenseCategory.INSURANCE,
    "salary": ExpenseCategory.PERSONNEL,
    "bonus": ExpenseCategory.PERSONNEL,
    "compensation": ExpenseCategory.PERSONNEL,
    "payroll": ExpenseCategory.PERSONNEL,
    "travel": ExpenseCategory.TRAVEL,
    "flight": ExpenseCategory.TRAVEL,
    "hotel": ExpenseCategory.TRAVEL,
    "compliance": ExpenseCategory.COMPLIANCE,
    "regulatory": ExpenseCategory.COMPLIANCE,
    "audit": ExpenseCategory.ACCOUNTING,
    "tax return": ExpenseCategory.ACCOUNTING,
    "k-1": ExpenseCategory.ACCOUNTING,
    "software": ExpenseCategory.TECHNOLOGY,
    "license": ExpenseCategory.TECHNOLOGY,
    "subscription": ExpenseCategory.TECHNOLOGY,
}


def categorize_heuristic(vendor: str, description: str = "") -> Optional[ExpenseCategory]:
    """Categorize an expense using heuristic vendor/description matching."""
    vendor_lower = vendor.lower()
    desc_lower = (description or "").lower()

    # Check vendor hints
    for hint, category in VENDOR_CATEGORY_HINTS.items():
        if hint in vendor_lower:
            return category

    # Check description keywords
    for keyword, category in DESCRIPTION_KEYWORDS.items():
        if keyword in desc_lower:
            return category

    return None


def categorize_with_ai(
    vendor: str, description: str = "", amount: float = 0.0
) -> Optional[dict]:
    """
    Categorize an expense using Claude API.

    Returns dict with:
        - category: ExpenseCategory value
        - confidence: float 0-1
        - reasoning: str
        - suggested_policy: str (allocation method suggestion)
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to heuristic categorization")
        cat = categorize_heuristic(vendor, description)
        if cat:
            return {
                "category": cat.value,
                "confidence": 0.7,
                "reasoning": "Heuristic match based on vendor/description",
                "suggested_policy": None,
            }
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        categories = [c.value for c in ExpenseCategory]

        prompt = f"""You are a private equity fund accountant. Categorize this expense:

Vendor: {vendor}
Description: {description}
Amount: ${amount:,.2f}

Available categories: {', '.join(categories)}

Allocation methods: pro_rata_aum, pro_rata_committed, pro_rata_invested, direct, headcount, custom_split, deal_specific

Respond in JSON format:
{{
    "category": "<category>",
    "confidence": <0.0-1.0>,
    "reasoning": "<brief explanation>",
    "suggested_policy": "<allocation method>"
}}"""

        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text
        # Extract JSON from response
        if "{" in response_text:
            json_str = response_text[response_text.index("{"):response_text.rindex("}") + 1]
            result = json.loads(json_str)
            # Validate category
            if result.get("category") not in categories:
                result["category"] = "other"
            return result

    except Exception as e:
        logger.error(f"AI categorization failed: {e}")

    # Fallback to heuristic
    cat = categorize_heuristic(vendor, description)
    if cat:
        return {
            "category": cat.value,
            "confidence": 0.6,
            "reasoning": "Heuristic fallback",
            "suggested_policy": None,
        }
    return None
