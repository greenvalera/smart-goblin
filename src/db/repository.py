"""
Repository layer for Smart Goblin.

Provides CRUD operations for cards, users, and analyses.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.db.models import Analysis, Card, CardRating, Set, User


@dataclass
class CardData:
    """Data transfer object for card creation/update."""

    name: str
    set_code: str
    scryfall_id: Optional[UUID] = None
    mana_cost: Optional[str] = None
    cmc: Optional[Decimal] = None
    colors: Optional[list[str]] = None
    type_line: Optional[str] = None
    rarity: Optional[str] = None
    image_uri: Optional[str] = None


@dataclass
class RatingData:
    """Data transfer object for card rating creation/update."""

    card_name: str
    set_code: str
    source: str
    rating: Optional[Decimal] = None
    win_rate: Optional[Decimal] = None
    games_played: Optional[int] = None
    format: Optional[str] = None


class SetRepository:
    """Repository for Set operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_code(self, code: str) -> Optional[Set]:
        """Get set by code."""
        result = await self.session.execute(
            select(Set).where(Set.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, code: str, name: Optional[str] = None
    ) -> tuple[Set, bool]:
        """
        Get existing set or create a new one.

        Returns:
            Tuple of (Set, created) where created is True if new set was created.
        """
        code = code.upper()
        existing = await self.get_by_code(code)
        if existing:
            return existing, False

        new_set = Set(code=code, name=name or code)
        self.session.add(new_set)
        await self.session.flush()
        return new_set, True


class CardRepository:
    """Repository for Card operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_name(self, name: str, set_code: str) -> Optional[Card]:
        """
        Get card by exact name and set code.

        Searches the requested set first; if not found, falls back to any
        bonus-sheet child sets (where ``sets.parent_set_code == set_code``).
        Lookup by a child code does NOT include the parent.
        """
        set_code_upper = set_code.upper()
        priority = case((Set.code == set_code_upper, 0), else_=1)
        result = await self.session.execute(
            select(Card)
            .join(Set)
            .where(
                and_(
                    Card.name == name,
                    or_(
                        Set.code == set_code_upper,
                        Set.parent_set_code == set_code_upper,
                    ),
                )
            )
            .options(selectinload(Card.ratings), joinedload(Card.set))
            .order_by(priority)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_set(self, set_code: str) -> list[Card]:
        """Get all cards in a set."""
        result = await self.session.execute(
            select(Card)
            .join(Set)
            .where(Set.code == set_code.upper())
            .options(selectinload(Card.ratings))
        )
        return list(result.scalars().all())

    async def get_card_names_by_set(self, set_code: str) -> list[str]:
        """
        Get all card names for a set (lightweight query for fuzzy matching).

        Includes cards from any bonus-sheet child sets (where
        ``sets.parent_set_code == set_code``). Lookup by a child code does
        NOT include the parent.

        Args:
            set_code: Set code (e.g., "ECL").

        Returns:
            List of card name strings (parent + children, may contain
            duplicates if the same name exists in both).
        """
        set_code_upper = set_code.upper()
        result = await self.session.execute(
            select(Card.name)
            .join(Set)
            .where(
                or_(
                    Set.code == set_code_upper,
                    Set.parent_set_code == set_code_upper,
                )
            )
        )
        return list(result.scalars().all())

    async def search_by_name(self, name_pattern: str, limit: int = 20) -> list[Card]:
        """
        Search cards by partial name match (case-insensitive).

        Args:
            name_pattern: Pattern to search for (e.g., "Lightning")
            limit: Maximum number of results

        Returns:
            List of cards matching the pattern.
        """
        result = await self.session.execute(
            select(Card)
            .where(Card.name.ilike(f"%{name_pattern}%"))
            .options(selectinload(Card.ratings), joinedload(Card.set))
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_cards_with_ratings(
        self, card_names: list[str], set_code: str
    ) -> list[Card]:
        """
        Get cards with their ratings by card names and set code.

        Includes cards from any bonus-sheet child sets (where
        ``sets.parent_set_code == set_code``). When the same name exists in
        both the parent and a child, the parent's card wins.

        Args:
            card_names: List of card names to fetch
            set_code: Set code (e.g., "MKM")

        Returns:
            List of cards with loaded ratings relationship.
        """
        if not card_names:
            return []

        set_code_upper = set_code.upper()
        priority = case((Set.code == set_code_upper, 0), else_=1)
        result = await self.session.execute(
            select(Card)
            .join(Set)
            .where(
                and_(
                    Card.name.in_(card_names),
                    or_(
                        Set.code == set_code_upper,
                        Set.parent_set_code == set_code_upper,
                    ),
                )
            )
            .options(selectinload(Card.ratings), joinedload(Card.set))
            .order_by(Card.name, priority)
        )
        cards = list(result.scalars().unique().all())

        # Dedup by name, keeping the first occurrence (parent wins per ORDER BY).
        seen: set[str] = set()
        deduped: list[Card] = []
        for card in cards:
            if card.name in seen:
                continue
            seen.add(card.name)
            deduped.append(card)
        return deduped

    async def upsert_cards(self, cards: list[CardData]) -> int:
        """
        Insert or update cards (upsert).

        Uses PostgreSQL ON CONFLICT to update existing cards.

        Args:
            cards: List of card data to upsert

        Returns:
            Number of cards processed.
        """
        if not cards:
            return 0

        # Group cards by set code to ensure sets exist
        set_codes = set(c.set_code.upper() for c in cards)
        set_repo = SetRepository(self.session)

        # Ensure all sets exist
        set_id_map = {}
        for code in set_codes:
            set_obj, _ = await set_repo.get_or_create(code)
            set_id_map[code] = set_obj.id

        # Prepare data for upsert
        values = [
            {
                "name": c.name,
                "set_id": set_id_map[c.set_code.upper()],
                "scryfall_id": c.scryfall_id,
                "mana_cost": c.mana_cost,
                "cmc": c.cmc,
                "colors": c.colors,
                "type_line": c.type_line,
                "rarity": c.rarity,
                "image_uri": c.image_uri,
            }
            for c in cards
        ]

        # PostgreSQL upsert using ON CONFLICT
        stmt = insert(Card).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_cards_name_set_id",
            set_={
                "scryfall_id": stmt.excluded.scryfall_id,
                "mana_cost": stmt.excluded.mana_cost,
                "cmc": stmt.excluded.cmc,
                "colors": stmt.excluded.colors,
                "type_line": stmt.excluded.type_line,
                "rarity": stmt.excluded.rarity,
                "image_uri": stmt.excluded.image_uri,
            },
        )

        await self.session.execute(stmt)
        return len(cards)

    async def upsert_ratings(self, ratings: list[RatingData]) -> int:
        """
        Insert or update card ratings (upsert).

        Args:
            ratings: List of rating data to upsert

        Returns:
            Number of ratings processed.
        """
        if not ratings:
            return 0

        processed = 0
        for r in ratings:
            # Find the card
            card = await self.get_by_name(r.card_name, r.set_code)
            if not card:
                continue

            # Upsert rating
            stmt = insert(CardRating).values(
                card_id=card.id,
                source=r.source,
                rating=r.rating,
                win_rate=r.win_rate,
                games_played=r.games_played,
                format=r.format,
                fetched_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_card_ratings_card_source_format",
                set_={
                    "rating": stmt.excluded.rating,
                    "win_rate": stmt.excluded.win_rate,
                    "games_played": stmt.excluded.games_played,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await self.session.execute(stmt)
            processed += 1

        return processed


class UserRepository:
    """Repository for User operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by internal ID."""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self, telegram_id: int, username: Optional[str] = None
    ) -> tuple[User, bool]:
        """
        Get existing user or create a new one.

        Args:
            telegram_id: Telegram user ID
            username: Telegram username (optional)

        Returns:
            Tuple of (User, created) where created is True if new user was created.
        """
        existing = await self.get_by_telegram_id(telegram_id)
        if existing:
            return existing, False

        new_user = User(telegram_id=telegram_id, username=username, language="uk")
        self.session.add(new_user)
        await self.session.flush()
        return new_user, True

    async def update(
        self, telegram_id: int, username: Optional[str] = None, language: Optional[str] = None
    ) -> Optional[User]:
        """
        Update user fields.

        Args:
            telegram_id: Telegram user ID
            username: New username (optional)
            language: New language (optional)

        Returns:
            Updated user or None if not found.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return None

        if username is not None:
            user.username = username
        if language is not None:
            user.language = language

        await self.session.flush()
        return user

    async def update_active_set(
        self, telegram_id: int, set_code: Optional[str]
    ) -> Optional[User]:
        """
        Update user's active set code.

        Args:
            telegram_id: Telegram user ID
            set_code: Set code to set as active (e.g., "MKM"), or None to clear.

        Returns:
            Updated user or None if not found.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return None

        user.active_set_code = set_code
        await self.session.flush()
        return user


class AnalysisRepository:
    """Repository for Analysis operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, analysis_id: int) -> Optional[Analysis]:
        """Get analysis by ID with loaded relationships."""
        result = await self.session.execute(
            select(Analysis)
            .where(Analysis.id == analysis_id)
            .options(joinedload(Analysis.set), joinedload(Analysis.user))
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: int, limit: int = 10, offset: int = 0
    ) -> list[Analysis]:
        """
        Get analyses for a user, sorted by date descending.

        Args:
            user_id: Internal user ID
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of analyses sorted by created_at DESC.
        """
        result = await self.session.execute(
            select(Analysis)
            .where(Analysis.user_id == user_id)
            .order_by(Analysis.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(joinedload(Analysis.set))
        )
        return list(result.scalars().all())

    async def get_user_analyses(
        self, user_id: int, limit: int = 10
    ) -> list[Analysis]:
        """
        Get user's analyses sorted by date descending.

        Alias for get_by_user for convenience.

        Args:
            user_id: Internal user ID
            limit: Maximum number of results

        Returns:
            List of analyses sorted by created_at DESC.
        """
        return await self.get_by_user(user_id, limit=limit)

    async def create(
        self,
        user_id: int,
        main_deck: list,
        sideboard: Optional[list] = None,
        set_code: Optional[str] = None,
        image_url: Optional[str] = None,
        total_score: Optional[Decimal] = None,
        estimated_win_rate: Optional[Decimal] = None,
        advice: Optional[str] = None,
    ) -> Analysis:
        """
        Create a new analysis.

        Args:
            user_id: Internal user ID
            main_deck: List of main deck cards
            sideboard: List of sideboard cards (optional)
            set_code: Set code (optional)
            image_url: URL to stored image (optional)
            total_score: Calculated deck score (optional)
            estimated_win_rate: Estimated win rate (optional)
            advice: LLM-generated advice (optional)

        Returns:
            Created Analysis object.
        """
        set_id = None
        if set_code:
            set_repo = SetRepository(self.session)
            set_obj = await set_repo.get_by_code(set_code)
            if set_obj:
                set_id = set_obj.id

        analysis = Analysis(
            user_id=user_id,
            set_id=set_id,
            image_url=image_url,
            main_deck=main_deck,
            sideboard=sideboard or [],
            total_score=total_score,
            estimated_win_rate=estimated_win_rate,
            advice=advice,
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def delete(self, analysis_id: int) -> bool:
        """
        Delete an analysis by ID.

        Returns:
            True if deleted, False if not found.
        """
        result = await self.session.execute(
            delete(Analysis).where(Analysis.id == analysis_id)
        )
        return result.rowcount > 0

    async def count_by_user(self, user_id: int) -> int:
        """Get total number of analyses for a user."""
        result = await self.session.execute(
            select(func.count(Analysis.id)).where(Analysis.user_id == user_id)
        )
        return result.scalar_one()
