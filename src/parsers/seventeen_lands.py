"""
17lands.com parser for Smart Goblin.

Fetches card ratings and win rates from 17lands.com API.
17lands provides draft statistics based on user-submitted game data.
"""

import asyncio
import logging
import re
import unicodedata
from decimal import Decimal
from typing import Any, Optional

import httpx

from src.config import get_settings
from src.parsers.base import (
    NetworkError,
    NotFoundError,
    ParserError,
    RateLimitError,
    RatingData,
)

logger = logging.getLogger(__name__)

# Minimum games threshold for high confidence ratings
MIN_GAMES_FOR_CONFIDENCE = 200

# Letter grade to numeric rating mapping (0-5 scale)
# Based on 17lands grading system
GRADE_TO_RATING: dict[str, Decimal] = {
    "A+": Decimal("5.0"),   # Bomb, first pick
    "A": Decimal("4.5"),    # Excellent card
    "A-": Decimal("4.0"),   # Very strong
    "B+": Decimal("3.5"),   # Strong card
    "B": Decimal("3.0"),    # Solid playable
    "B-": Decimal("2.5"),   # Good playable
    "C+": Decimal("2.0"),   # Average playable
    "C": Decimal("1.5"),    # Filler
    "C-": Decimal("1.0"),   # Weak filler
    "D+": Decimal("0.75"),  # Below average
    "D": Decimal("0.5"),    # Weak card
    "D-": Decimal("0.25"),  # Very weak
    "F": Decimal("0.0"),    # Unplayable
}

# Win rate (GIH WR %) to letter grade thresholds.
# Calibrated against actual 17lands grades (which use per-color z-scores).
# These absolute thresholds approximate the 17lands grading across sets
# where the average GIH WR is ~56-57%.
# Thresholds are (min_win_rate_pct, grade_label), checked top-down.
WIN_RATE_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (64.0, "A+"),
    (62.5, "A"),
    (61.0, "A-"),
    (59.5, "B+"),
    (58.5, "B"),
    (57.0, "B-"),
    (55.5, "C+"),
    (54.5, "C"),
    (53.0, "C-"),
    (52.0, "D+"),
    (51.0, "D"),
    (49.5, "D-"),
]

# Grades that indicate insufficient data (should be excluded from calculations)
UNRATED_GRADES = {"-", "SB"}  # No data / sideboard-only


def win_rate_to_grade(win_rate_pct: float) -> str:
    """
    Calculate letter grade from GIH win rate percentage.

    Used as a fallback when 17lands API does not return ``color_grade``.

    Args:
        win_rate_pct: Win rate as a percentage (e.g. 55.0 for 55%).

    Returns:
        Letter grade string (A+ through F).
    """
    for threshold, grade in WIN_RATE_GRADE_THRESHOLDS:
        if win_rate_pct >= threshold:
            return grade
    return "F"


def grade_to_rating(grade: Optional[str]) -> Optional[Decimal]:
    """
    Convert letter grade to numeric rating.

    Args:
        grade: Letter grade from 17lands (A+, A, B, etc.).

    Returns:
        Numeric rating on 0-5 scale, or None if card is unrated/insufficient data.
        Cards with None rating should be excluded from deck calculations.
    """
    if grade is None:
        return None
    if grade in UNRATED_GRADES:
        return None
    return GRADE_TO_RATING.get(grade.upper())


def normalize_card_name(name: str) -> str:
    """
    Normalize card name for case-insensitive comparison.

    Removes special characters, converts to lowercase, and normalizes unicode.
    This allows matching cards like "Jötun Grunt" with "Jotun Grunt".

    Args:
        name: Original card name.

    Returns:
        Normalized card name for comparison.
    """
    # Normalize unicode characters (e.g., ö -> o)
    normalized = unicodedata.normalize("NFKD", name)
    # Remove combining characters (accents, etc.)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    # Convert to lowercase
    normalized = normalized.lower()
    # Remove special characters except spaces and alphanumeric
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    # Collapse multiple spaces to single space and strip
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class SeventeenLandsParser:
    """
    Parser for 17lands.com card ratings API.

    Fetches card statistics including win rates and game counts.
    Supports multiple draft formats (PremierDraft, QuickDraft, etc.).
    """

    SOURCE_NAME = "17lands"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize 17lands parser.

        Args:
            base_url: 17lands base URL. Defaults to config value.
            timeout: HTTP request timeout in seconds.
        """
        settings = get_settings()
        self.base_url = (base_url or settings.parser.seventeenlands_base).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._request_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "User-Agent": "SmartGoblin/1.0 (MTG Draft Analyzer Bot)",
                    "Accept": "application/json",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, url: str) -> Any:
        """
        Make a request to 17lands API.

        Args:
            url: Full URL to request.

        Returns:
            JSON response (list or dict).

        Raises:
            RateLimitError: If rate limited.
            NotFoundError: If resource not found.
            NetworkError: If network request fails.
        """
        async with self._request_lock:
            client = await self._get_client()
            try:
                logger.debug(f"Requesting: {url}")
                response = await client.get(url)

                if response.status_code == 429:
                    raise RateLimitError("17lands rate limit exceeded")
                elif response.status_code == 404:
                    raise NotFoundError(f"Resource not found: {url}")
                elif response.status_code >= 400:
                    raise ParserError(
                        f"17lands API error: {response.status_code} - {response.text}"
                    )

                return response.json()

            except httpx.TimeoutException as e:
                raise NetworkError(f"Request timeout: {url}") from e
            except httpx.RequestError as e:
                raise NetworkError(f"Network error: {e}") from e

    def _parse_rating(
        self, card_data: dict[str, Any], format_name: str
    ) -> RatingData:
        """
        Parse 17lands card data into RatingData.

        Args:
            card_data: Raw card data from 17lands API.
            format_name: Draft format name (e.g., "PremierDraft").

        Returns:
            RatingData object with extracted fields.
        """
        # Extract card name
        card_name = card_data.get("name", "Unknown")

        # Extract win rate - 17lands provides "ever_drawn_win_rate" as the primary metric
        # This represents the game win rate when the card is drawn at any point
        win_rate_raw = card_data.get("ever_drawn_win_rate")
        win_rate = None
        if win_rate_raw is not None:
            # Convert from decimal (0.55) to percentage (55.0)
            win_rate = Decimal(str(round(float(win_rate_raw) * 100, 2)))

        # Extract games played - use "game_count" or "ever_drawn_game_count"
        games_played = card_data.get("game_count") or card_data.get(
            "ever_drawn_game_count"
        )
        if games_played is not None:
            games_played = int(games_played)

        # Extract letter grade from 17lands (A+, A, A-, B+, B, etc.)
        grade = card_data.get("color_grade")

        # If grade is missing but win rate exists, compute grade from win rate
        if grade is None and win_rate is not None:
            grade = win_rate_to_grade(float(win_rate))

        # Convert letter grade to numeric rating (0-5 scale)
        rating = grade_to_rating(grade)

        # Determine confidence level
        low_confidence = (games_played or 0) < MIN_GAMES_FOR_CONFIDENCE

        return RatingData(
            card_name=card_name,
            source=self.SOURCE_NAME,
            rating=rating,
            win_rate=win_rate,
            games_played=games_played,
            format=format_name,
            low_confidence=low_confidence,
            grade=grade,
        )

    async def fetch_ratings(
        self, set_code: str, format_name: str = "PremierDraft"
    ) -> list[RatingData]:
        """
        Fetch card ratings for a given set and format.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").
            format_name: Draft format (e.g., "PremierDraft", "QuickDraft").

        Returns:
            List of RatingData objects for all cards with available data.

        Raises:
            NotFoundError: If set/format combination not found.
            ParserError: If fetching fails.
        """
        # Build URL for 17lands card ratings API
        url = (
            f"{self.base_url}/card_ratings/data"
            f"?expansion={set_code.upper()}"
            f"&format={format_name}"
        )

        logger.info(f"Fetching 17lands ratings for {set_code} ({format_name})...")

        try:
            data = await self._request(url)
        except NotFoundError:
            logger.warning(f"No 17lands data found for {set_code} ({format_name})")
            raise

        # Handle both list and dict responses
        cards_data = data if isinstance(data, list) else data.get("data", [])

        if not cards_data:
            logger.warning(f"Empty response from 17lands for {set_code} ({format_name})")
            return []

        ratings = []
        for card_data in cards_data:
            rating = self._parse_rating(card_data, format_name)
            ratings.append(rating)

        logger.info(
            f"Fetched {len(ratings)} ratings for {set_code} ({format_name}), "
            f"{sum(1 for r in ratings if r.low_confidence)} with low confidence"
        )

        return ratings

    async def fetch_ratings_for_formats(
        self,
        set_code: str,
        formats: Optional[list[str]] = None,
    ) -> dict[str, list[RatingData]]:
        """
        Fetch ratings for multiple formats at once.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").
            formats: List of formats to fetch. Defaults to common draft formats.

        Returns:
            Dictionary mapping format name to list of RatingData.
        """
        if formats is None:
            formats = ["PremierDraft", "QuickDraft"]

        results = {}
        for format_name in formats:
            try:
                ratings = await self.fetch_ratings(set_code, format_name)
                results[format_name] = ratings
            except NotFoundError:
                logger.warning(f"Format {format_name} not available for {set_code}")
                results[format_name] = []
            except ParserError as e:
                logger.error(f"Error fetching {format_name} for {set_code}: {e}")
                results[format_name] = []

        return results

    def match_card_names(
        self,
        rating_name: str,
        card_names: list[str],
    ) -> Optional[str]:
        """
        Find the best matching card name from a list.

        Uses normalized comparison for case-insensitive matching
        that ignores special characters.

        Args:
            rating_name: Card name from 17lands rating.
            card_names: List of card names to match against.

        Returns:
            Matched card name from the list, or None if no match.
        """
        normalized_rating = normalize_card_name(rating_name)

        for card_name in card_names:
            if normalize_card_name(card_name) == normalized_rating:
                return card_name

        return None

    def create_name_mapping(
        self, card_names: list[str]
    ) -> dict[str, str]:
        """
        Create a mapping from normalized names to original names.

        Useful for efficiently matching multiple ratings to card names.

        Args:
            card_names: List of original card names.

        Returns:
            Dictionary mapping normalized name to original name.
        """
        return {normalize_card_name(name): name for name in card_names}
