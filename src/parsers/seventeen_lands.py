"""
17lands.com parser for Smart Goblin.

Fetches card ratings and win rates from 17lands.com API.
17lands provides draft statistics based on user-submitted game data.
"""

import asyncio
import logging
import re
import statistics
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

# Minimum cards in a color group to compute reliable color statistics
MIN_CARDS_FOR_COLOR_STATS = 5

# Letter grade to numeric rating mapping (0-5 scale)
# Based on 17lands grading system
GRADE_TO_RATING: dict[str, Decimal] = {
    "A+": Decimal("5.0"),
    "A": Decimal("4.5"),
    "A-": Decimal("4.0"),
    "B+": Decimal("3.5"),
    "B": Decimal("3.0"),
    "B-": Decimal("2.5"),
    "C+": Decimal("2.0"),
    "C": Decimal("1.5"),
    "C-": Decimal("1.0"),
    "D+": Decimal("0.75"),
    "D": Decimal("0.5"),
    "D-": Decimal("0.25"),
    "F": Decimal("0.0"),
}

# Z-score thresholds matching 17lands per-color grading methodology.
# Source: MTGA_Draft_17Lands GRADE_DEVIATION_DICT
# z_score = (card_gih_wr - color_mean_gih_wr) / color_population_std
Z_SCORE_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (2.00, "A+"),
    (1.67, "A"),
    (1.33, "A-"),
    (1.00, "B+"),
    (0.67, "B"),
    (0.33, "B-"),
    (0.00, "C+"),
    (-0.33, "C"),
    (-0.67, "C-"),
    (-1.00, "D+"),
    (-1.33, "D"),
    (-1.67, "D-"),
]

# Absolute GIH WR thresholds used only when color group is too small for z-scores
_FALLBACK_WIN_RATE_THRESHOLDS: list[tuple[float, str]] = [
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


def z_score_to_grade(z_score: float) -> str:
    """
    Convert a per-color z-score to a letter grade, matching 17lands methodology.

    Args:
        z_score: Standard deviations from the color mean GIH win rate.

    Returns:
        Letter grade string (A+ through F).
    """
    for threshold, grade in Z_SCORE_GRADE_THRESHOLDS:
        if z_score >= threshold:
            return grade
    return "F"


def win_rate_to_grade(win_rate_pct: float) -> str:
    """
    Absolute-threshold fallback grade from GIH win rate.

    Used when a color group is too small for z-score calculation, or as a
    display fallback in reports when no stored grade is available.
    """
    for threshold, grade in _FALLBACK_WIN_RATE_THRESHOLDS:
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
        card_name = card_data.get("name", "Unknown")
        color = card_data.get("color", "")

        win_rate_raw = card_data.get("ever_drawn_win_rate")
        win_rate = None
        if win_rate_raw is not None:
            # Keep 6 decimal places for accurate per-color z-score calculation.
            # The DB column (DECIMAL 5,2) rounds to 2dp on storage — precision
            # only matters here, in the in-memory RatingData used by _apply_color_grades.
            win_rate = Decimal(str(round(float(win_rate_raw) * 100, 6)))

        games_played = card_data.get("game_count") or card_data.get(
            "ever_drawn_game_count"
        )
        if games_played is not None:
            games_played = int(games_played)

        # 17lands API does not return color_grade; grade is assigned later
        # in _apply_color_grades() using per-color z-scores.
        grade = card_data.get("color_grade")
        rating = grade_to_rating(grade)

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
            color=color,
        )

    def _apply_color_grades(
        self,
        ratings: list[RatingData],
        main_set_card_names: Optional[set[str]] = None,
    ) -> None:
        """
        Assign grades to all ratings using per-color z-scores.

        Replicates 17lands methodology: each card's GIH WR is compared to the
        mean and population std of cards of the same color in the set.
        Cards with grades already set by the API are left unchanged.

        17lands' card_ratings endpoint mixes bonus-sheet/reprint cards with
        main-set cards. These reprints inflate the per-color std and shift
        grades on borderline cards. Pass ``main_set_card_names`` to restrict
        the stats sample to true main-set cards (e.g. those returned by
        Scryfall for this set code). Grades are still assigned to every
        rating, including bonus-sheet cards.
        """
        color_groups: dict[str, list[RatingData]] = {}
        for r in ratings:
            if r.win_rate is not None:
                key = r.color or "colorless"
                color_groups.setdefault(key, []).append(r)

        for color, group in color_groups.items():
            if main_set_card_names is not None:
                stats_sample = [
                    r for r in group if r.card_name in main_set_card_names
                ]
            else:
                stats_sample = group

            sample_wrs = [float(r.win_rate) for r in stats_sample]

            if len(sample_wrs) < MIN_CARDS_FOR_COLOR_STATS:
                for r in group:
                    if r.grade is None:
                        r.grade = win_rate_to_grade(float(r.win_rate))
                        r.rating = grade_to_rating(r.grade)
                continue

            mean_wr = statistics.mean(sample_wrs)
            std_wr = statistics.pstdev(sample_wrs)

            if std_wr == 0:
                continue

            for r in group:
                if r.grade is None:
                    z = (float(r.win_rate) - mean_wr) / std_wr
                    r.grade = z_score_to_grade(z)
                    r.rating = grade_to_rating(r.grade)

    async def fetch_ratings(
        self,
        set_code: str,
        format_name: str = "PremierDraft",
        main_set_card_names: Optional[set[str]] = None,
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

        self._apply_color_grades(ratings, main_set_card_names)

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
