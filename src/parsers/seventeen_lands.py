"""
17lands.com parser for Smart Goblin.

Fetches card ratings and win rates from 17lands.com API and assigns
letter grades using the same z-score formula as 17lands' own grade UI.

Grading methodology mirrors the 17lands site default:

- Statistics (mean, population std) are computed over a single global pool
  of cards with a GIH win rate, not per-color. Bonus-sheet reprints can be
  excluded from the pool by passing ``main_set_card_names``.
- Grade is determined by ``floor(3 * (z + 11/6))`` indexed into the grade
  list ``["F","D-","D","D+","C-","C","C+","B-","B","B+","A-","A","A+"]``.
  Source: 17lands frontend bundle (Routes.*.bundle.js, ``iS`` /
  ``numStdDevsFromMean``). C is centered at z=0 with bands of 0.33 std-devs.
- ``start_date`` is forwarded to the API to mirror the site's default of
  filtering by the format release date.
"""

import asyncio
import logging
import math
import re
import statistics
import unicodedata
from datetime import date
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

# Minimum cards in the global pool to compute stats. Matches 17lands' own
# threshold (`o >= 15` in the bundle's UD function).
MIN_CARDS_FOR_STATS = 15

# Letter grade to numeric rating mapping (0-5 scale)
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

# Grade list indexed in the same order as 17lands' frontend `uS` array.
# index = floor(3 * (z + _GRADE_OFFSET)) → this list.
_GRADES_BY_INDEX: list[str] = [
    "F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+",
]
_GRADE_OFFSET = 11 / 6  # 17lands' dS = 2 - 1/6

# Grades that indicate insufficient data (excluded from numeric rating)
UNRATED_GRADES = {"-", "SB"}


def z_score_to_grade(z_score: float) -> str:
    """
    Convert a z-score to a letter grade matching 17lands' frontend.

    Replicates the formula extracted from 17lands' Routes bundle::

        index = floor(3 * (z + 11/6))
        grade = uS[index]      if 0 <= index < len(uS)
                "F"            if index < 0
                "A+"           if index >= len(uS)
    """
    idx = math.floor(3 * (z_score + _GRADE_OFFSET))
    if idx < 0:
        return "F"
    if idx >= len(_GRADES_BY_INDEX):
        return "A+"
    return _GRADES_BY_INDEX[idx]


def grade_to_rating(grade: Optional[str]) -> Optional[Decimal]:
    """
    Convert letter grade to numeric rating.

    Returns None for cards that are unrated or have insufficient data so
    callers can exclude them from deck calculations.
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
    Allows matching cards like "Jötun Grunt" with "Jotun Grunt".
    """
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class SeventeenLandsParser:
    """
    Parser for 17lands.com card ratings API.

    Fetches card statistics including win rates and game counts,
    then assigns letter grades using the global z-score formula
    that matches 17lands' own grade column.
    """

    SOURCE_NAME = "17lands"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
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
        Parse a 17lands card record into RatingData.

        ``rating`` and ``grade`` are left None — they're assigned later by
        ``_apply_grades`` which needs the full sample to compute z-scores.
        """
        card_name = card_data.get("name", "Unknown")

        win_rate_raw = card_data.get("ever_drawn_win_rate")
        win_rate = None
        if win_rate_raw is not None:
            # Keep 6 decimal places for accurate z-score calculation.
            # The DB column (DECIMAL 5,2) rounds to 2dp on storage — extra
            # precision only matters here, in the in-memory pool used by
            # _apply_grades.
            win_rate = Decimal(str(round(float(win_rate_raw) * 100, 6)))

        games_played = card_data.get("game_count") or card_data.get(
            "ever_drawn_game_count"
        )
        if games_played is not None:
            games_played = int(games_played)

        low_confidence = (games_played or 0) < MIN_GAMES_FOR_CONFIDENCE

        return RatingData(
            card_name=card_name,
            source=self.SOURCE_NAME,
            rating=None,
            win_rate=win_rate,
            games_played=games_played,
            format=format_name,
            low_confidence=low_confidence,
            grade=None,
            url=card_data.get("url"),
        )

    def _apply_grades(
        self,
        ratings: list[RatingData],
        main_set_card_names: Optional[set[str]] = None,
    ) -> None:
        """
        Assign grades to every rating from a single global stats pool.

        Mean and population std are computed over all cards with a GIH win
        rate. When ``main_set_card_names`` is provided, the stats pool is
        restricted to those names — this keeps bonus-sheet reprints (which
        17lands mixes into the same feed) out of mean/std without preventing
        the reprints themselves from receiving grades.

        Each card is graded by its z-score against this single pool, using
        the 17lands frontend formula (see ``z_score_to_grade``).
        """
        if main_set_card_names is not None:
            stats_pool = [
                r
                for r in ratings
                if r.win_rate is not None and r.card_name in main_set_card_names
            ]
        else:
            stats_pool = [r for r in ratings if r.win_rate is not None]

        sample_wrs = [float(r.win_rate) for r in stats_pool]

        if len(sample_wrs) < MIN_CARDS_FOR_STATS:
            logger.warning(
                "Stats pool has only %d card(s) with a GIH win rate "
                "(need >= %d) — leaving grades unset.",
                len(sample_wrs),
                MIN_CARDS_FOR_STATS,
            )
            return

        mean_wr = statistics.mean(sample_wrs)
        std_wr = statistics.pstdev(sample_wrs)

        if std_wr == 0:
            logger.warning("Population std is zero — cannot grade.")
            return

        for r in ratings:
            if r.win_rate is None:
                continue
            z = (float(r.win_rate) - mean_wr) / std_wr
            r.grade = z_score_to_grade(z)
            r.rating = grade_to_rating(r.grade)

    async def fetch_ratings(
        self,
        set_code: str,
        format_name: str = "PremierDraft",
        main_set_card_names: Optional[set[str]] = None,
        start_date: Optional[date] = None,
    ) -> list[RatingData]:
        """
        Fetch card ratings for a given set and format.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").
            format_name: Draft format (e.g., "PremierDraft", "QuickDraft").
            main_set_card_names: Names of the set's main-set cards. When
                provided, bonus-sheet reprints are excluded from the stats
                pool used to compute mean/std.
            start_date: Forwarded to the 17lands API as ``start_date`` to
                mirror the site's default of filtering by format release.
                When omitted, the API returns all-time data.

        Raises:
            NotFoundError: If set/format combination not found.
            ParserError: If fetching fails.
        """
        params = [
            f"expansion={set_code.upper()}",
            f"format={format_name}",
        ]
        if start_date is not None:
            params.append(f"start_date={start_date.isoformat()}")

        url = f"{self.base_url}/card_ratings/data?" + "&".join(params)

        logger.info(
            "Fetching 17lands ratings for %s (%s, start_date=%s)...",
            set_code,
            format_name,
            start_date,
        )

        try:
            data = await self._request(url)
        except NotFoundError:
            logger.warning(f"No 17lands data found for {set_code} ({format_name})")
            raise

        cards_data = data if isinstance(data, list) else data.get("data", [])

        if not cards_data:
            logger.warning(
                f"Empty response from 17lands for {set_code} ({format_name})"
            )
            return []

        ratings = [self._parse_rating(card_data, format_name) for card_data in cards_data]
        self._apply_grades(ratings, main_set_card_names)
        self._canonicalize_dfc_names(ratings, main_set_card_names)

        logger.info(
            f"Fetched {len(ratings)} ratings for {set_code} ({format_name}), "
            f"{sum(1 for r in ratings if r.low_confidence)} with low confidence"
        )

        return ratings

    def _canonicalize_dfc_names(
        self,
        ratings: list[RatingData],
        main_set_card_names: Optional[set[str]] = None,
    ) -> None:
        """
        Rewrite front-face-only DFC ratings into Scryfall's full ``Front // Back``
        form so they match how cards are stored in the DB.

        17lands returns DFC ratings under the front face name only
        (``"Adventurous Eater"``), but Scryfall stores the card as
        ``"Adventurous Eater // Have a Bite"``. Without rewriting,
        ``CardRepository.upsert_ratings`` cannot find the card by exact name
        and silently drops the rating.
        """
        if not main_set_card_names:
            return

        front_to_full: dict[str, str] = {}
        for full_name in main_set_card_names:
            if " // " not in full_name:
                continue
            front_face = full_name.split(" // ", 1)[0]
            front_to_full[normalize_card_name(front_face)] = full_name

        if not front_to_full:
            return

        for r in ratings:
            if " // " in r.card_name:
                continue
            full = front_to_full.get(normalize_card_name(r.card_name))
            if full is not None:
                r.card_name = full

    def match_card_names(
        self,
        rating_name: str,
        card_names: list[str],
    ) -> Optional[str]:
        """
        Find the best matching card name from a list using normalized comparison.
        """
        normalized_rating = normalize_card_name(rating_name)
        for card_name in card_names:
            if normalize_card_name(card_name) == normalized_rating:
                return card_name
        return None

    def create_name_mapping(
        self, card_names: list[str]
    ) -> dict[str, str]:
        """Create a mapping from normalized names to original names."""
        return {normalize_card_name(name): name for name in card_names}
