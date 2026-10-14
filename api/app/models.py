"""Lendly data model.

All money is integer cents. All timestamps are tz-aware UTC. Calendar fields
(loan start date, payment date) are plain dates in the lender's local sense.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db

INTEREST_TYPES = ("compound", "simple", "fixed")
SCHEDULES = ("weekly", "biweekly", "monthly")
LOAN_STATUSES = ("active", "paid", "cancelled")
ROLES = ("admin", "borrower")
PAYMENT_METHODS = ("cash", "zelle", "venmo", "cashapp", "bank", "check", "other")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class User(db.Model):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    apple_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Tenant(db.Model):
    """One tenant per lender ("workspace")."""
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    receipt_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Membership(db.Model):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    borrower_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("borrowers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship()
    borrower: Mapped["Borrower | None"] = relationship()


class Borrower(db.Model):
    """Profile the admin creates for the person taking a loan."""
    __tablename__ = "borrowers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    loans: Mapped[list["Loan"]] = relationship(back_populates="borrower")
    user: Mapped[User | None] = relationship()


class Invite(db.Model):
    __tablename__ = "invites"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    borrower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("borrowers.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    borrower: Mapped[Borrower] = relationship()
    tenant: Mapped[Tenant] = relationship()


class Loan(db.Model):
    __tablename__ = "loans"
    __table_args__ = (Index("ix_loans_tenant_status", "tenant_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    borrower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("borrowers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    principal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interest_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # compound: rate per period, in basis points. simple: flat % of principal, in basis points.
    rate_bps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # fixed: dollar fee in cents, charged once or every period.
    fixed_fee_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    fixed_fee_per_period: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule: Mapped[str] = mapped_column(String(16), nullable=False)
    term_periods: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    borrower: Mapped[Borrower] = relationship(back_populates="loans")
    payments: Mapped[list["Payment"]] = relationship(back_populates="loan", order_by="Payment.paid_on, Payment.created_at")


class Payment(db.Model):
    """A payment recorded by the admin. Every payment is also its receipt."""
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_number", name="uq_payment_receipt_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payment_idempotency"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(16), default="cash", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    receipt_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Client-generated key so a retried POST can't record the same payment twice.
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    loan: Mapped[Loan] = relationship(back_populates="payments")


class OtpCode(db.Model):
    __tablename__ = "otp_codes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
