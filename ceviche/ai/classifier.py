"""Claude API integration for intelligent expense classification and queries."""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_client():
    """Get Anthropic client, or None if API key not set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.warning("anthropic package not installed")
        return None


def detect_anomalies(expenses: list[dict], historical: list[dict] = None) -> list[dict]:
    """
    Flag expenses that are unusually large or don't match typical patterns.

    Uses Claude API if available, otherwise uses simple statistical detection.
    """
    anomalies = []

    if not expenses:
        return anomalies

    # Simple statistical anomaly detection (always available)
    amounts = [e["amount"] for e in expenses if e.get("amount")]
    if len(amounts) >= 5:
        mean = sum(amounts) / len(amounts)
        variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
        std_dev = variance ** 0.5

        for expense in expenses:
            amt = expense.get("amount", 0)
            if std_dev > 0 and (amt - mean) / std_dev > 2.5:
                anomalies.append({
                    "expense_id": expense.get("expense_id"),
                    "vendor": expense.get("vendor"),
                    "amount": amt,
                    "reason": f"Amount ${amt:,.2f} is {(amt-mean)/std_dev:.1f} std devs above mean ${mean:,.2f}",
                    "severity": "high" if (amt - mean) / std_dev > 3 else "medium",
                })

    # Vendor-category mismatch detection
    client = get_client()
    if client and expenses:
        try:
            expense_summary = json.dumps(expenses[:20], default=str)
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Review these PE fund expenses for anomalies. Flag any that seem "
                        f"unusual in amount, categorization, or vendor-category mismatch. "
                        f"Respond with a JSON array of objects with keys: expense_id, reason, severity.\n\n"
                        f"{expense_summary}"
                    ),
                }],
            )
            response_text = message.content[0].text
            if "[" in response_text:
                json_str = response_text[response_text.index("["):response_text.rindex("]") + 1]
                ai_anomalies = json.loads(json_str)
                for a in ai_anomalies:
                    if a not in anomalies:
                        anomalies.append(a)
        except Exception as e:
            logger.warning(f"AI anomaly detection failed: {e}")

    return anomalies
