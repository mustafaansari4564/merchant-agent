"""
Audit trail: every agent action is logged with timestamp, tool name,
input params, result, status, guardrail info, and a human-readable explanation.

Expose via /audit/{session_id} so judges can see WHY the agent did what it did.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from backend.models import AuditEntry

logger = logging.getLogger(__name__)


def log_action(
    db: DBSession,
    *,
    session_id: Optional[int],
    action: str,
    tool_name: Optional[str] = None,
    arguments: Optional[dict] = None,
    result: Optional[dict] = None,
    status: str = "success",
    guardrail: Optional[str] = None,
    explanation: Optional[str] = None,
) -> AuditEntry:
    """Write one audit entry and return it."""
    entry = AuditEntry(
        session_id=session_id,
        action=action,
        tool_name=tool_name,
        arguments=json.dumps(arguments, ensure_ascii=False) if arguments else None,
        result=json.dumps(result, ensure_ascii=False) if result else None,
        status=status,
        guardrail=guardrail,
        explanation=explanation or _auto_explanation(action, tool_name, arguments, result, status),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(
        "AUDIT [%s] %s tool=%s status=%s guardrail=%s",
        action, explanation or "", tool_name, status, guardrail,
    )
    return entry


def _auto_explanation(
    action: str,
    tool_name: Optional[str],
    arguments: Optional[dict],
    result: Optional[dict],
    status: str,
) -> str:
    """Generate a human-readable explanation string when none is provided."""
    if status == "blocked":
        reason = (result or {}).get("reason", "Guardrail check failed")
        return f"Blocked: {reason}"

    if status == "failed":
        error = (result or {}).get("error", "Unknown error")
        return f"Failed: {error}"

    if tool_name == "search_catalog":
        query = (arguments or {}).get("query", "")
        count = len((result or {}).get("results", []))
        return f"Searched catalog for '{query}', found {count} product(s)."

    if tool_name == "add_to_cart":
        name = (result or {}).get("product_name", "item")
        qty = (arguments or {}).get("quantity", 1)
        return f"Added {qty}x {name} to cart."

    if tool_name == "remove_from_cart":
        name = (result or {}).get("product_name", "item")
        return f"Removed {name} from cart."

    if tool_name == "apply_coupon":
        code = (arguments or {}).get("code", "")
        discount = (result or {}).get("discount_percent", 0)
        return f"Applied coupon '{code}' — {discount}% discount."

    if tool_name == "create_razorpay_order":
        order_id = (result or {}).get("razorpay_order_id", "")
        amount = (result or {}).get("amount_paise", 0)
        return f"Created Razorpay order {order_id} for ₹{amount // 100}."

    if tool_name == "initiate_payment":
        url = (result or {}).get("short_url", "")
        return f"Generated payment link: {url}"

    if tool_name == "get_cart":
        items = (result or {}).get("items", [])
        return f"Retrieved cart with {len(items)} item(s)."

    if tool_name == "view_catalog":
        count = len((result or {}).get("products", []))
        return f"Listed {count} product(s) from catalog."

    if tool_name == "get_recommendations":
        count = len((result or {}).get("recommendations", []))
        return f"Generated {count} upsell recommendation(s)."

    return f"Executed {tool_name or action} successfully."


def get_audit_trail(db: DBSession, session_id: int, limit: int = 100) -> list[AuditEntry]:
    """Return audit entries for a session, newest last."""
    return (
        db.query(AuditEntry)
        .filter(AuditEntry.session_id == session_id)
        .order_by(AuditEntry.id.asc())
        .limit(limit)
        .all()
    )


def get_all_audit_entries(db: DBSession, limit: int = 200) -> list[AuditEntry]:
    """Return all audit entries, newest last."""
    return (
        db.query(AuditEntry)
        .order_by(AuditEntry.id.asc())
        .limit(limit)
        .all()
    )
