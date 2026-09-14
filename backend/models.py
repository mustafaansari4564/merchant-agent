"""
SQLite schema and Pydantic models for the Conversational Checkout Agent.

Tables:
  - products:          merchant catalog
  - sessions:          chat sessions (UUID keyed)
  - messages:          chat history per session
  - cart_items:        shopping cart per session
  - orders:            Razorpay orders
  - payment_links:     Razorpay payment links
  - coupons:           available discount coupons
  - audit_log:         every agent action with full trace
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session


# ---------------------------------------------------------------------------
# SQLAlchemy ORM
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    price_paise = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    category = Column(String(50), nullable=False, default="general")
    stock_count = Column(Integer, nullable=False, default=100)
    image_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    customer_name = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    applied_coupon = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    cart_items = relationship("CartItem", back_populates="session", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="session", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" | "assistant" | "tool_use" | "tool_result"
    content = Column(Text, nullable=False)
    tool_name = Column(String(100), nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("Session", back_populates="messages")


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    added_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("Session", back_populates="cart_items")
    product = relationship("Product")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    razorpay_order_id = Column(String(100), nullable=True, unique=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    receipt = Column(String(200), nullable=False)
    status = Column(String(30), nullable=False, default="created")
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("Session", back_populates="orders")
    payment_links = relationship("PaymentLink", back_populates="order", cascade="all, delete-orphan")


class PaymentLink(Base):
    __tablename__ = "payment_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    razorpay_link_id = Column(String(100), nullable=True, unique=True)
    short_url = Column(String(500), nullable=True)
    amount_paise = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="created")
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    order = relationship("Order", back_populates="payment_links")


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True)
    discount_percent = Column(Integer, nullable=False)
    max_uses = Column(Integer, nullable=False, default=100)
    uses_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    action = Column(String(100), nullable=False)
    tool_name = Column(String(100), nullable=True)
    arguments = Column(Text, nullable=True)       # JSON string
    result = Column(Text, nullable=True)           # JSON string
    status = Column(String(20), nullable=False, default="success")  # success | blocked | failed
    guardrail = Column(String(200), nullable=True)
    explanation = Column(Text, nullable=True)      # human-readable explanation
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("Session", back_populates="audit_entries")


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def init_db(db_url: str = "sqlite:///./merchant_agent.db"):
    """Create engine and tables. Returns the engine."""
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


# ---------------------------------------------------------------------------
# Pydantic schemas (for API request/response)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_actions: list[dict] = []
    cart: list[dict] = []
    awaiting_confirmation: bool = False


class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    price_paise: int
    currency: str
    category: str
    stock_count: int
    is_active: bool

    class Config:
        from_attributes = True


class AuditEntryOut(BaseModel):
    id: int
    action: str
    tool_name: Optional[str] = None
    arguments: Optional[str] = None
    result: Optional[str] = None
    status: str
    guardrail: Optional[str] = None
    explanation: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    razorpay_order_id: Optional[str] = None
    amount_paise: int
    status: str
    receipt: str
    created_at: datetime

    class Config:
        from_attributes = True
