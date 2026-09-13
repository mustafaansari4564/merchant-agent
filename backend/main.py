"""
FastAPI application -- the entry point.

Endpoints:
  POST /api/chat           -- send a message, get agent reply + tool actions
  GET  /api/products       -- list products
  GET  /api/audit/{sid}    -- audit trail for a session
  GET  /api/orders/{sid}   -- orders for a session
  POST /webhook/razorpay   -- Razorpay webhook receiver
  GET  /health             -- liveness probe
  GET  /                   -- serves the frontend
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Ensure the project root is on sys.path so `backend.` imports work
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.agent import CheckoutAgent
from backend.audit import get_audit_trail, get_all_audit_entries
from backend.models import Order, PaymentLink, Product, Session, init_db
from backend.seed import seed_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Global state
engine = None
agent = CheckoutAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB + seed demo products. Shutdown: nothing special."""
    global engine
    db_url = os.getenv("DATABASE_URL", "sqlite:///./merchant_agent.db")
    engine = init_db(db_url)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    logger.info("Database initialised and seeded.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="MerchantAgent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db():
    """Dependency: yield a SQLAlchemy session."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Send a message to the checkout agent. Returns the agent's reply,
    any tool actions taken, and the current cart state."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        result = await agent.chat(db, req.session_id, req.message)
        return JSONResponse(content={
            "session_id": req.session_id,
            "reply": result["reply"],
            "tool_actions": result["tool_actions"],
            "cart": result["cart"],
            "awaiting_confirmation": result["awaiting_confirmation"],
        })
    except Exception as exc:
        logger.exception("Chat error")
        return JSONResponse(
            status_code=500,
            content={"error": f"Agent error: {exc}"},
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Product endpoints
# ---------------------------------------------------------------------------

@app.get("/api/products")
def list_products(category: Optional[str] = None):
    """List all active products, optionally filtered by category."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        q = db.query(Product).filter(Product.is_active == True)
        if category:
            q = q.filter(Product.category == category)
        products = q.order_by(Product.name).all()
        return {
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "price_paise": p.price_paise,
                    "price_display": f"\u20b9{p.price_paise // 100}",
                    "category": p.category,
                    "stock_count": p.stock_count,
                }
                for p in products
            ]
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Audit trail endpoint
# ---------------------------------------------------------------------------

@app.get("/api/audit/{session_id}")
def get_audit(session_id: str, limit: int = 100):
    """Return the full audit trail for a session -- every tool call with
    timestamp, arguments, result, status, guardrail, and explanation."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            return {"entries": []}
        entries = get_audit_trail(db, db_session.id, limit)
        return {
            "entries": [
                {
                    "id": e.id,
                    "action": e.action,
                    "tool_name": e.tool_name,
                    "arguments": json.loads(e.arguments) if e.arguments else None,
                    "result": json.loads(e.result) if e.result else None,
                    "status": e.status,
                    "guardrail": e.guardrail,
                    "explanation": e.explanation,
                    "created_at": e.created_at.isoformat(),
                }
                for e in entries
            ]
        }
    finally:
        db.close()


@app.get("/api/audit")
def get_all_audit():
    """Return all audit entries (for the admin view)."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        entries = get_all_audit_entries(db)
        return {
            "entries": [
                {
                    "id": e.id,
                    "session_id": e.session_id,
                    "action": e.action,
                    "tool_name": e.tool_name,
                    "arguments": json.loads(e.arguments) if e.arguments else None,
                    "result": json.loads(e.result) if e.result else None,
                    "status": e.status,
                    "guardrail": e.guardrail,
                    "explanation": e.explanation,
                    "created_at": e.created_at.isoformat(),
                }
                for e in entries
            ]
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Orders endpoint
# ---------------------------------------------------------------------------

@app.get("/api/orders/{session_id}")
def get_orders(session_id: str):
    """Return orders for a session."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            return {"orders": []}
        orders = db.query(Order).filter(Order.session_id == db_session.id).all()
        return {
            "orders": [
                {
                    "id": o.id,
                    "razorpay_order_id": o.razorpay_order_id,
                    "amount_paise": o.amount_paise,
                    "amount_display": f"\u20b9{o.amount_paise // 100}",
                    "status": o.status,
                    "receipt": o.receipt,
                    "created_at": o.created_at.isoformat(),
                }
                for o in orders
            ]
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Razorpay webhook
# ---------------------------------------------------------------------------

@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request, x_razorpay_signature: Optional[str] = Header(None)):
    """Handle Razorpay webhook events.

    ASSUMPTION: Razorpay signs the webhook payload with HMAC-SHA256 using
    your webhook secret. If RAZORPAY_WEBHOOK_SECRET is not set, signature
    verification is skipped (fine for demo/test mode). In production, always
    verify the signature.
    """
    body = await request.body()
    payload = json.loads(body)
    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})

    logger.info("Razorpay webhook: event=%s", event)

    # Optional: verify signature
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if webhook_secret and x_razorpay_signature:
        expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_razorpay_signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    # Process event
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        if event == "payment.captured":
            order_id = entity.get("order_id")
            if order_id:
                order = db.query(Order).filter(Order.razorpay_order_id == order_id).first()
                if order:
                    order.status = "paid"
                    db.commit()
                    logger.info("Order %s marked as paid", order_id)

        elif event == "payment.failed":
            order_id = entity.get("order_id")
            if order_id:
                order = db.query(Order).filter(Order.razorpay_order_id == order_id).first()
                if order:
                    error = entity.get("error_description", "Payment failed")
                    order.status = "failed"
                    order.failure_reason = error
                    db.commit()
                    logger.info("Order %s marked as failed: %s", order_id, error)
    finally:
        db.close()

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "merchant-agent"}


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    @app.get("/", response_class=HTMLResponse)
    def serve_frontend():
        index_html = frontend_dir / "index.html"
        return HTMLResponse(content=index_html.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI: run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("APP_PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
