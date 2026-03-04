"""
SQLAlchemy models for Smart Goblin.

Defines the database schema for sets, cards, card ratings, users, and analyses.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    DECIMAL,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Set(Base):
    """MTG Set model."""

    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    release_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    cards: Mapped[list["Card"]] = relationship(
        "Card", back_populates="set", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="set"
    )

    def __repr__(self) -> str:
        return f"Set(id={self.id}, code={self.code!r}, name={self.name!r})"


class Card(Base):
    """MTG Card model."""

    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("name", "set_id", name="uq_cards_name_set_id"),
        Index("ix_cards_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scryfall_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    set_id: Mapped[int] = mapped_column(ForeignKey("sets.id", ondelete="CASCADE"))
    mana_cost: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cmc: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(3, 1), nullable=True)
    colors: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(10)), nullable=True
    )
    type_line: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rarity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    image_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    set: Mapped["Set"] = relationship("Set", back_populates="cards")
    ratings: Mapped[list["CardRating"]] = relationship(
        "CardRating", back_populates="card", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Card(id={self.id}, name={self.name!r}, set_id={self.set_id})"


class CardRating(Base):
    """Card rating from external sources like 17lands."""

    __tablename__ = "card_ratings"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "source", "format", name="uq_card_ratings_card_source_format"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    rating: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(2, 1), nullable=True)
    win_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True)
    games_played: Mapped[Optional[int]] = mapped_column(nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    card: Mapped["Card"] = relationship("Card", back_populates="ratings")

    def __repr__(self) -> str:
        return f"CardRating(id={self.id}, card_id={self.card_id}, source={self.source!r})"


class User(Base):
    """Telegram user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="uk")
    active_set_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"User(id={self.id}, telegram_id={self.telegram_id})"


class Analysis(Base):
    """Deck analysis result model."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    set_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sets.id", ondelete="SET NULL"), nullable=True
    )
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    main_deck: Mapped[list] = mapped_column(JSONB, nullable=False)
    sideboard: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(4, 2), nullable=True)
    estimated_win_rate: Mapped[Optional[Decimal]] = mapped_column(
        DECIMAL(5, 2), nullable=True
    )
    advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="analyses")
    set: Mapped[Optional["Set"]] = relationship("Set", back_populates="analyses")

    def __repr__(self) -> str:
        return f"Analysis(id={self.id}, user_id={self.user_id}, set_id={self.set_id})"
