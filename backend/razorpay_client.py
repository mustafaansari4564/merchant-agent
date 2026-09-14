"""
Razorpay SDK wrapper.

All payment operations go through this module so we have one place to
handle errors, retries, and fallbacks.

ASSUMPTION: Razorpay test-mode keys are provided via .env. The SDK handles
auth internally. In test mode no real money is moved — use Razorpay's test
card numbers (4111 1111 1111 1111, CVV any 3 digits, future expiry) to
simulate successful payments, or the "failure" test card to simulate
declines.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import razorpay
from razorpay.errors import BadRequestError, ServerError

logger = logging.getLogger(__name__)

_client: Optional[razorpay.Client] = None


def get_client() -> razorpay.Client:
    """Return a singleton Razorpay client, initialised from env vars."""
    global _client
    if _client is None:
        key_id = os.getenv("RAZORPAY_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise RuntimeError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env"
            )
        _client = razorpay.Client(auth=(key_id, key_secret))
        _client.set_app_details({"title": "MerchantAgent", "version": "1.0.0"})
    return _client


class RazorpayError(Exception):
    """Raised when a Razorpay API call fails."""
    def __init__(self, message: str, status_code: int = 500, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


async def create_order(amount_paise: int, receipt: str, notes: dict | None = None) -> dict:
    """Create a Razorpay order. Returns the full order dict from Razorpay.

    Args:
        amount_paise: Amount in paise (e.g. 99900 for ₹999).
        receipt: Internal receipt string for your reference.
        notes: Optional key-value metadata.
    """
    try:
        client = get_client()
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
        }
        if notes:
            payload["notes"] = notes
        # SDK call is synchronous — run in a thread to not block the event loop
        import asyncio
        order = await asyncio.to_thread(client.order.create, payload)
        logger.info("Razorpay order created: %s (₹%d)", order["id"], amount_paise // 100)
        return order
    except BadRequestError as exc:
        logger.error("Razorpay bad request: %s", exc)
        raise RazorpayError(str(exc), 400, str(exc)) from exc
    except ServerError as exc:
        logger.error("Razorpay server error: %s", exc)
        raise RazorpayError(str(exc), 502, str(exc)) from exc
    except Exception as exc:
        logger.error("Razorpay unexpected error: %s", exc)
        raise RazorpayError(str(exc)) from exc


async def create_payment_link(
    amount_paise: int,
    description: str,
    receipt: str | None = None,
) -> dict:
    """Create a Razorpay Payment Link. Returns the full link dict.

    The `short_url` field in the response is the shareable checkout link.
    """
    try:
        client = get_client()
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "description": description,
            "accept_partial": False,
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        if receipt:
            payload["reference_id"] = receipt
        import asyncio
        link = await asyncio.to_thread(client.payment_link.create, payload)
        logger.info("Razorpay payment link created: %s", link.get("id"))
        return link
    except BadRequestError as exc:
        logger.error("Razorpay payment link bad request: %s", exc)
        raise RazorpayError(str(exc), 400, str(exc)) from exc
    except ServerError as exc:
        logger.error("Razorpay payment link server error: %s", exc)
        raise RazorpayError(str(exc), 502, str(exc)) from exc
    except Exception as exc:
        logger.error("Razorpay payment link unexpected error: %s", exc)
        raise RazorpayError(str(exc)) from exc


async def fetch_order(order_id: str) -> dict:
    """Fetch order details by Razorpay order ID."""
    try:
        client = get_client()
        import asyncio
        return await asyncio.to_thread(client.order.fetch, order_id)
    except Exception as exc:
        raise RazorpayError(str(exc)) from exc


async def fetch_payment(payment_id: str) -> dict:
    """Fetch payment details by Razorpay payment ID."""
    try:
        client = get_client()
        import asyncio
        return await asyncio.to_thread(client.payment.fetch, payment_id)
    except Exception as exc:
        raise RazorpayError(str(exc)) from exc
