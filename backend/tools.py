"""
Tool functions the Claude agent can call.

Every function:
  - Takes a SQLAlchemy session + session_db_id + validated params
  - Returns a JSON-serializable dict
  - NEVER trusts the LLM for amounts or order IDs — those come from the DB/Razorpay

ASSUMPTION: Amounts are always in paise (₹1 = 100 paise), matching Razorpay's
convention. The LLM never fabricates prices — it reads them from the catalog.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from backend.models import CartItem, Coupon, Order, PaymentLink, Product, Session

# ---------------------------------------------------------------------------
# Guardrail constants (can also be set via .env, but defaults are fine for demo)
# ---------------------------------------------------------------------------

MAX_SINGLE_ORDER_PAISE = int(os.getenv("MAX_SINGLE_ORDER_PAISE", "10000000"))      # ₹1,00,000
MAX_SESSION_TOTAL_PAISE = int(os.getenv("MAX_SESSION_TOTAL_PAISE", "50000000"))   # ₹5,00,000
MAX_QUANTITY_PER_ITEM = int(os.getenv("MAX_QUANTITY_PER_ITEM", "5"))
CONFIRMATION_THRESHOLD_PAISE = int(os.getenv("CONFIRMATION_THRESHOLD_PAISE", "50000"))  # ₹500
MAX_DISCOUNT_PERCENT = int(os.getenv("MAX_DISCOUNT_PERCENT", "25"))


# ---------------------------------------------------------------------------
# Helper: find or create session
# ---------------------------------------------------------------------------

def get_or_create_session(db: DBSession, session_id: str) -> Session:
    """Return the DB session row, creating one if it doesn't exist."""
    row = db.query(Session).filter(Session.session_id == session_id).first()
    if row is None:
        row = Session(session_id=session_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Tool: search_catalog
# ---------------------------------------------------------------------------

def search_catalog(db: DBSession, session_db_id: int, query: str = "", category: str = "") -> dict:
    """Search the product catalog by keyword and/or category.

    Returns matching products with their details. The agent uses this to
    help customers discover products.
    """
    q = db.query(Product).filter(Product.is_active == True)

    if query:
        # Simple case-insensitive LIKE search across name + description
        pattern = f"%{query}%"
        q = q.filter(
            or_(
                Product.name.ilike(pattern),
                Product.description.ilike(pattern),
                Product.category.ilike(pattern),
            )
        )
    if category:
        q = q.filter(Product.category.ilike(f"%{category}%"))

    products = q.order_by(Product.price_paise.asc()).limit(20).all()

    return {
        "results": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price_paise": p.price_paise,
                "price_display": f"₹{p.price_paise // 100}",
                "category": p.category,
                "stock_count": p.stock_count,
                "in_stock": p.stock_count > 0,
            }
            for p in products
        ],
        "count": len(products),
        "query": query,
        "category": category,
    }


# ---------------------------------------------------------------------------
# Tool: view_catalog  (list everything)
# ---------------------------------------------------------------------------

def view_catalog(db: DBSession, session_db_id: int) -> dict:
    """Return the full active product catalog."""
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.category, Product.name).all()
    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price_paise": p.price_paise,
                "price_display": f"₹{p.price_paise // 100}",
                "category": p.category,
                "stock_count": p.stock_count,
            }
            for p in products
        ],
        "count": len(products),
    }


# ---------------------------------------------------------------------------
# Tool: add_to_cart
# ---------------------------------------------------------------------------

def add_to_cart(db: DBSession, session_db_id: int, product_id: int, quantity: int = 1) -> dict:
    """Add a product to the session's cart. Validates stock and guardrails."""
    # Validate quantity
    if quantity < 1:
        return {"error": "Quantity must be at least 1.", "blocked": True}
    if quantity > MAX_QUANTITY_PER_ITEM:
        return {
            "error": f"Maximum quantity per item is {MAX_QUANTITY_PER_ITEM}.",
            "blocked": True,
            "guardrail": "max_quantity",
        }

    # Check product exists and is in stock
    product = db.query(Product).get(product_id)
    if not product or not product.is_active:
        return {"error": "Product not found.", "blocked": True}
    if product.stock_count < quantity:
        return {
            "error": f"Only {product.stock_count} units of {product.name} in stock.",
            "blocked": True,
            "guardrail": "insufficient_stock",
        }

    # Check if already in cart — update quantity instead
    existing = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_db_id, CartItem.product_id == product_id)
        .first()
    )
    new_qty = quantity if not existing else existing.quantity + quantity
    if new_qty > MAX_QUANTITY_PER_ITEM:
        return {
            "error": f"Cart already has {existing.quantity} of {product.name}. "
                     f"Max allowed is {MAX_QUANTITY_PER_ITEM}.",
            "blocked": True,
            "guardrail": "max_quantity",
        }

    # Check session spending limit
    cart_total = _cart_total_paise(db, session_db_id)
    added_value = product.price_paise * quantity
    if cart_total + added_value > MAX_SESSION_TOTAL_PAISE:
        return {
            "error": f"Adding this would exceed the session spending limit of ₹{MAX_SESSION_TOTAL_PAISE // 100}.",
            "blocked": True,
            "guardrail": "session_spending_limit",
        }

    if existing:
        existing.quantity = new_qty
    else:
        db.add(CartItem(session_id=session_db_id, product_id=product_id, quantity=quantity))
    db.commit()

    return {
        "product_id": product_id,
        "product_name": product.name,
        "quantity": new_qty,
        "unit_price_paise": product.price_paise,
        "line_total_paise": product.price_paise * new_qty,
        "cart_total_paise": _cart_total_paise(db, session_db_id),
    }


# ---------------------------------------------------------------------------
# Tool: remove_from_cart
# ---------------------------------------------------------------------------

def remove_from_cart(db: DBSession, session_db_id: int, product_id: int) -> dict:
    """Remove a product from the cart entirely."""
    item = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_db_id, CartItem.product_id == product_id)
        .first()
    )
    if not item:
        return {"error": "That item is not in your cart.", "blocked": True}

    product = db.query(Product).get(product_id)
    product_name = product.name if product else f"Product #{product_id}"

    db.delete(item)
    db.commit()

    return {
        "product_id": product_id,
        "product_name": product_name,
        "cart_total_paise": _cart_total_paise(db, session_db_id),
    }


# ---------------------------------------------------------------------------
# Tool: get_cart
# ---------------------------------------------------------------------------

def get_cart(db: DBSession, session_db_id: int) -> dict:
    """Return current cart contents and total (with coupon discount if applied)."""
    items = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_db_id)
        .all()
    )
    cart_items = []
    total = 0
    for item in items:
        product = db.query(Product).get(item.product_id)
        if product:
            line_total = product.price_paise * item.quantity
            total += line_total
            cart_items.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": item.quantity,
                "unit_price_paise": product.price_paise,
                "unit_price_display": f"₹{product.price_paise // 100}",
                "line_total_paise": line_total,
                "line_total_display": f"₹{line_total // 100}",
            })

    # Check for applied coupon and calculate discount
    discount_paise = 0
    discount_percent = 0
    coupon_code = ""
    db_session = db.query(Session).filter(Session.id == session_db_id).first()
    if db_session and db_session.applied_coupon:
        coupon = db.query(Coupon).filter(Coupon.code == db_session.applied_coupon).first()
        if coupon and coupon.is_active:
            discount_percent = coupon.discount_percent
            discount_paise = int(total * discount_percent / 100)
            coupon_code = coupon.code

    final_total = total - discount_paise

    return {
        "items": cart_items,
        "item_count": len(cart_items),
        "total_paise": total,
        "total_display": f"₹{total // 100}",
        "discount_paise": discount_paise,
        "discount_display": f"₹{discount_paise // 100}" if discount_paise else "",
        "discount_percent": discount_percent,
        "coupon_code": coupon_code,
        "final_total_paise": final_total,
        "final_total_display": f"₹{final_total // 100}",
    }


# ---------------------------------------------------------------------------
# Tool: apply_coupon
# ---------------------------------------------------------------------------

def apply_coupon(db: DBSession, session_db_id: int, code: str) -> dict:
    """Apply a discount coupon to the session. Validates the coupon exists,
    is active, hasn't exceeded max uses, and discount doesn't exceed the cap.
    """
    coupon = db.query(Coupon).filter(Coupon.code == code.upper(), Coupon.is_active == True).first()
    if not coupon:
        return {"error": f"Coupon '{code}' is invalid or expired.", "blocked": True}

    if coupon.uses_count >= coupon.max_uses:
        return {"error": f"Coupon '{code}' has been fully redeemed.", "blocked": True}

    if coupon.discount_percent > MAX_DISCOUNT_PERCENT:
        return {
            "error": f"Discount of {coupon.discount_percent}% exceeds the maximum allowed ({MAX_DISCOUNT_PERCENT}%).",
            "blocked": True,
            "guardrail": "max_discount",
        }

    coupon.uses_count += 1

    # Store applied coupon on the session
    db_session = db.query(Session).filter(Session.id == session_db_id).first()
    if db_session:
        db_session.applied_coupon = coupon.code
    db.commit()

    return {
        "code": coupon.code,
        "discount_percent": coupon.discount_percent,
        "message": f"Coupon '{coupon.code}' applied — {coupon.discount_percent}% off.",
    }


# ---------------------------------------------------------------------------
# Tool: create_razorpay_order
# ---------------------------------------------------------------------------

def create_razorpay_order(db: DBSession, session_db_id: int) -> dict:
    """Create a Razorpay test-mode order from the current cart.

    Guardrails enforced:
      - Cart cannot be empty
      - Single order cannot exceed MAX_SINGLE_ORDER_PAISE
      - Session total cannot exceed MAX_SESSION_TOTAL_PAISE

    Returns the Razorpay order details + internal order ID.
    """
    import asyncio
    from backend.razorpay_client import create_order, RazorpayError

    cart = get_cart(db, session_db_id)
    if not cart["items"]:
        return {"error": "Cart is empty. Add items before checkout.", "blocked": True, "requires_confirmation": False}

    total = cart["final_total_paise"]
    if total > MAX_SINGLE_ORDER_PAISE:
        return {
            "error": f"Order total ₹{total // 100} exceeds the single order limit of ₹{MAX_SINGLE_ORDER_PAISE // 100}.",
            "blocked": True,
            "guardrail": "single_order_limit",
            "requires_confirmation": False,
        }

    # Build receipt string
    receipt = f"rcpt_{session_db_id}_{uuid.uuid4().hex[:8]}"

    # Direct checkout — no confirmation gate
    return _execute_create_order(db, session_db_id, total, receipt, cart)


def confirm_order(db: DBSession, session_db_id: int) -> dict:
    """Called after the user confirms a high-value order."""
    from backend.razorpay_client import RazorpayError

    cart = get_cart(db, session_db_id)
    if not cart["items"]:
        return {"error": "Cart is empty.", "blocked": True}

    total = cart["final_total_paise"]
    receipt = f"rcpt_{session_db_id}_{uuid.uuid4().hex[:8]}"
    return _execute_create_order(db, session_db_id, total, receipt, cart)


def _execute_create_order(db: DBSession, session_db_id: int, total_paise: int, receipt: str, cart: dict) -> dict:
    """Actually create the Razorpay order (with retry + fallback)."""
    import asyncio
    from backend.razorpay_client import create_order, create_payment_link, RazorpayError

    # Store the order in our DB first
    order = Order(
        session_id=session_db_id,
        amount_paise=total_paise,
        receipt=receipt,
        status="creating",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Attempt order creation (with one retry)
    for attempt in range(2):
        try:
            rp_order = asyncio.run(create_order(total_paise, receipt))

            order.razorpay_order_id = rp_order["id"]
            order.status = "created"
            db.commit()

            return {
                "razorpay_order_id": rp_order["id"],
                "amount_paise": total_paise,
                "amount_display": f"₹{total_paise // 100}",
                "receipt": receipt,
                "status": "created",
                "order_db_id": order.id,
            }
        except RazorpayError as exc:
            if attempt == 0:
                continue  # retry once
            # Fallback: create a payment link instead
            try:
                link = asyncio.run(
                    create_payment_link(total_paise, f"Order {receipt}", receipt)
                )
                order.status = "fallback_payment_link"
                order.failure_reason = str(exc)
                db.commit()

                pl = PaymentLink(
                    order_id=order.id,
                    razorpay_link_id=link.get("id"),
                    short_url=link.get("short_url"),
                    amount_paise=total_paise,
                    status="created",
                )
                db.add(pl)
                db.commit()

                return {
                    "fallback": True,
                    "short_url": link.get("short_url"),
                    "razorpay_link_id": link.get("id"),
                    "amount_display": f"₹{total_paise // 100}",
                    "message": "Order creation had an issue, but I've generated a payment link you can use.",
                }
            except Exception:
                order.status = "failed"
                order.failure_reason = str(exc)
                db.commit()
                return {
                    "error": "Unable to process payment right now. Please try again later.",
                    "blocked": True,
                }


# ---------------------------------------------------------------------------
# Tool: initiate_payment  (generate payment link for an existing order)
# ---------------------------------------------------------------------------

def initiate_payment(db: DBSession, session_db_id: int, order_db_id: int) -> dict:
    """Generate a Razorpay payment link for a confirmed order."""
    from backend.razorpay_client import create_payment_link, RazorpayError

    order = db.query(Order).filter(
        Order.id == order_db_id, Order.session_id == session_db_id
    ).first()
    if not order:
        return {"error": "Order not found.", "blocked": True}

    try:
        import asyncio
        link = asyncio.run(
            create_payment_link(order.amount_paise, f"Order {order.receipt}", order.receipt)
        )
        pl = PaymentLink(
            order_id=order.id,
            razorpay_link_id=link.get("id"),
            short_url=link.get("short_url"),
            amount_paise=order.amount_paise,
            status="created",
        )
        db.add(pl)
        db.commit()

        return {
            "short_url": link.get("short_url"),
            "razorpay_link_id": link.get("id"),
            "amount_display": f"₹{order.amount_paise // 100}",
        }
    except RazorpayError as exc:
        return {"error": f"Failed to generate payment link: {exc}", "blocked": True}


# ---------------------------------------------------------------------------
# Tool: get_recommendations  (simple upsell logic)
# ---------------------------------------------------------------------------

def get_recommendations(db: DBSession, session_db_id: int) -> dict:
    """Suggest complementary products based on cart contents.

    Simple rule-based approach: find products in different categories that
    are similar in price range. This is clearly separable and doesn't block
    the core demo if not finished.
    """
    cart_items = db.query(CartItem).filter(CartItem.session_id == session_db_id).all()
    if not cart_items:
        return {"recommendations": [], "message": "Your cart is empty — add some items first!"}

    cart_product_ids = {item.product_id for item in cart_items}
    cart_categories = set()
    cart_prices = []
    for item in cart_items:
        product = db.query(Product).get(item.product_id)
        if product:
            cart_categories.add(product.category)
            cart_prices.append(product.price_paise)

    avg_price = sum(cart_prices) // len(cart_prices) if cart_prices else 0
    price_min = int(avg_price * 0.5)
    price_max = int(avg_price * 2.0)

    # Find products NOT in the cart, in different categories, similar price
    candidates = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.stock_count > 0,
            ~Product.id.in_(cart_product_ids),
        )
        .all()
    )

    recommendations = []
    for p in candidates:
        in_different_category = p.category not in cart_categories
        in_price_range = price_min <= p.price_paise <= price_max
        if in_different_category or in_price_range:
            recommendations.append({
                "id": p.id,
                "name": p.name,
                "price_paise": p.price_paise,
                "price_display": f"₹{p.price_paise // 100}",
                "category": p.category,
                "reason": f"Goes well with items in your cart ({p.category})",
            })

    # Sort by price proximity to average cart price
    recommendations.sort(key=lambda r: abs(r["price_paise"] - avg_price))
    recommendations = recommendations[:3]

    return {
        "recommendations": recommendations,
        "count": len(recommendations),
    }


# ---------------------------------------------------------------------------
# Tool: search_online_prices (async version for agent)
# ---------------------------------------------------------------------------

async def search_online_prices_async(session_db_id: int, query: str, max_results: int = 8) -> dict:
    """Async version — called by the agent when running inside FastAPI's event loop."""
    from backend.search_providers import search_all_products

    try:
        results = await search_all_products(query, max_results=max_results)
    except Exception as exc:
        return {"error": f"Search failed: {exc}", "blocked": True, "results": []}

    if not results:
        return {
            "query": query,
            "results": [],
            "total_found": 0,
            "message": f"No results found for '{query}'. Try a different search term.",
        }

    formatted = []
    for r in results:
        formatted.append({
            "title": r.title,
            "price": r.price,
            "price_display": r.price_display,
            "source": r.source,
            "url": r.url,
            "rating": r.rating,
            "thumbnail": r.thumbnail,
            "delivery": r.delivery,
        })

    cheapest_source = results[0].source if results else ""

    return {
        "query": query,
        "results": formatted,
        "total_found": len(formatted),
        "cheapest_source": cheapest_source,
        "cheapest_price": results[0].price_display if results else "",
    }


# ---------------------------------------------------------------------------
# Tool: search_online_prices (sync version for direct calls)
# ---------------------------------------------------------------------------

def search_online_prices(session_db_id: int, query: str, max_results: int = 8) -> dict:
    """Search for products across Amazon, Flipkart, and Google Shopping.

    Returns the cheapest options from multiple e-commerce platforms with
    prices, ratings, and direct links to buy.
    """
    import asyncio
    from backend.search_providers import search_all_products

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an async context (FastAPI) — use nest_asyncio or thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, search_all_products(query, max_results=max_results))
                results = future.result(timeout=15)
        else:
            results = loop.run_until_complete(search_all_products(query, max_results=max_results))
    except Exception as exc:
        return {"error": f"Search failed: {exc}", "blocked": True, "results": []}

    if not results:
        return {
            "query": query,
            "results": [],
            "total_found": 0,
            "message": f"No results found for '{query}'. Try a different search term.",
        }

    formatted = []
    for r in results:
        formatted.append({
            "title": r.title,
            "price": r.price,
            "price_display": r.price_display,
            "source": r.source,
            "url": r.url,
            "rating": r.rating,
            "thumbnail": r.thumbnail,
            "delivery": r.delivery,
        })

    cheapest_source = results[0].source if results else ""

    return {
        "query": query,
        "results": formatted,
        "total_found": len(formatted),
        "cheapest_source": cheapest_source,
        "cheapest_price": results[0].price_display if results else "",
    }


# ---------------------------------------------------------------------------
# Tool: add_online_product_to_cart
# ---------------------------------------------------------------------------

def add_online_product_to_cart(
    db: DBSession,
    session_db_id: int,
    title: str,
    price: float,
    source: str = "",
    url: str = "",
    rating: float = None,
    quantity: int = 1,
) -> dict:
    """Add an online product (from search_online_prices results) to the cart.

    Creates a temporary Product entry in the DB so the existing cart and
    Razorpay checkout flow works seamlessly.
    """
    if price <= 0:
        return {"error": "Invalid price.", "blocked": True}

    # Create a product entry for this online item
    price_paise = int(price * 100)
    product = Product(
        name=title[:200],
        description=f"From {source}: {title}",
        price_paise=price_paise,
        currency="INR",
        category="online",
        stock_count=999,
        image_url=url if url else None,
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    # Add to cart
    existing = (
        db.query(CartItem)
        .filter(CartItem.session_id == session_db_id, CartItem.product_id == product.id)
        .first()
    )
    if existing:
        existing.quantity += quantity
    else:
        db.add(CartItem(session_id=session_db_id, product_id=product.id, quantity=quantity))
    db.commit()

    return {
        "product_id": product.id,
        "product_name": product.name,
        "source": source,
        "url": url,
        "quantity": quantity,
        "unit_price_paise": price_paise,
        "line_total_paise": price_paise * quantity,
        "cart_total_paise": _cart_total_paise(db, session_db_id),
        "cart_total_display": f"\u20b9{_cart_total_paise(db, session_db_id) // 100}",
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _cart_total_paise(db: DBSession, session_db_id: int) -> int:
    """Calculate the current cart total in paise."""
    items = db.query(CartItem).filter(CartItem.session_id == session_db_id).all()
    total = 0
    for item in items:
        product = db.query(Product).get(item.product_id)
        if product:
            total += product.price_paise * item.quantity
    return total
