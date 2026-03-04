"""
Scryfall API parser for Smart Goblin.

Fetches card metadata from Scryfall API with rate limiting and pagination support.
Scryfall API docs: https://scryfall.com/docs/api
"""

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import httpx

from src.config import get_settings
from src.parsers.base import (
    BaseParser,
    CardData,
    NetworkError,
    NotFoundError,
    ParserError,
    RateLimitError,
    SetData,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for API requests.

    Ensures no more than max_requests requests are made per second.
    """

    def __init__(self, max_requests_per_second: int = 10):
        self.max_requests = max_requests_per_second
        self.min_interval = 1.0 / max_requests_per_second
        self._last_request_time: float = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request can be made within rate limit."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            time_since_last = now - self._last_request_time
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)
            self._last_request_time = asyncio.get_event_loop().time()


class ScryfallParser(BaseParser):
    """
    Parser for Scryfall API.

    Fetches card and set metadata with proper rate limiting (max 10 req/sec)
    and pagination support for large sets.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        max_requests_per_second: int = 10,
        timeout: float = 30.0,
    ):
        """
        Initialize Scryfall parser.

        Args:
            base_url: Scryfall API base URL. Defaults to config value.
            max_requests_per_second: Rate limit for API requests. Scryfall allows 10/sec.
            timeout: HTTP request timeout in seconds.
        """
        settings = get_settings()
        self.base_url = (base_url or settings.parser.scryfall_api_base).rstrip("/")
        self.rate_limiter = RateLimiter(max_requests_per_second)
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "User-Agent": "SmartGoblin/1.0 (MTG Draft Analyzer Bot)",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, url: str) -> dict[str, Any]:
        """
        Make a rate-limited request to Scryfall API.

        Args:
            url: Full URL to request.

        Returns:
            JSON response as dictionary.

        Raises:
            RateLimitError: If rate limited by Scryfall.
            NotFoundError: If resource not found.
            NetworkError: If network request fails.
        """
        await self.rate_limiter.acquire()

        client = await self._get_client()
        try:
            logger.debug(f"Requesting: {url}")
            response = await client.get(url)

            if response.status_code == 429:
                raise RateLimitError("Scryfall rate limit exceeded")
            elif response.status_code == 404:
                raise NotFoundError(f"Resource not found: {url}")
            elif response.status_code >= 400:
                raise ParserError(
                    f"Scryfall API error: {response.status_code} - {response.text}"
                )

            return response.json()

        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timeout: {url}") from e
        except httpx.RequestError as e:
            raise NetworkError(f"Network error: {e}") from e

    def _parse_card(self, card_data: dict[str, Any]) -> CardData:
        """
        Parse Scryfall card JSON into CardData.

        Args:
            card_data: Raw card data from Scryfall API.

        Returns:
            CardData object with extracted fields.
        """
        # Extract scryfall_id
        scryfall_id = None
        if "id" in card_data:
            try:
                scryfall_id = UUID(card_data["id"])
            except ValueError:
                pass

        # Extract CMC
        cmc = None
        if "cmc" in card_data and card_data["cmc"] is not None:
            cmc = Decimal(str(card_data["cmc"]))

        # Get image URI - prefer normal size, fall back to others
        image_uri = None
        if "image_uris" in card_data:
            image_uris = card_data["image_uris"]
            image_uri = (
                image_uris.get("normal")
                or image_uris.get("large")
                or image_uris.get("small")
            )
        elif "card_faces" in card_data and card_data["card_faces"]:
            # Double-faced cards have images in card_faces
            first_face = card_data["card_faces"][0]
            if "image_uris" in first_face:
                image_uri = (
                    first_face["image_uris"].get("normal")
                    or first_face["image_uris"].get("large")
                    or first_face["image_uris"].get("small")
                )

        return CardData(
            name=card_data.get("name", "Unknown"),
            scryfall_id=scryfall_id,
            mana_cost=card_data.get("mana_cost"),
            cmc=cmc,
            colors=card_data.get("colors"),
            type_line=card_data.get("type_line"),
            rarity=card_data.get("rarity"),
            image_uri=image_uri,
        )

    async def fetch_set_cards(self, set_code: str) -> list[CardData]:
        """
        Fetch all cards for a given set with pagination support.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").

        Returns:
            List of CardData objects for all cards in the set.

        Raises:
            NotFoundError: If set not found.
            ParserError: If fetching fails.
        """
        cards: list[CardData] = []
        url = f"{self.base_url}/cards/search?q=set:{set_code.lower()}&unique=cards"

        page_count = 0
        while url:
            page_count += 1
            logger.info(f"Fetching {set_code} cards, page {page_count}...")

            try:
                data = await self._request(url)
            except NotFoundError:
                if page_count == 1:
                    # No cards found for this set
                    raise NotFoundError(f"No cards found for set: {set_code}")
                break

            # Parse cards from this page
            for card_data in data.get("data", []):
                card = self._parse_card(card_data)
                cards.append(card)

            # Check for more pages
            if data.get("has_more") and data.get("next_page"):
                url = data["next_page"]
            else:
                url = None

        logger.info(f"Fetched {len(cards)} cards for set {set_code}")
        return cards

    async def fetch_set_info(self, set_code: str) -> Optional[SetData]:
        """
        Fetch metadata for a given set.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").

        Returns:
            SetData object with set metadata, or None if not found.

        Raises:
            ParserError: If fetching fails (except 404).
        """
        url = f"{self.base_url}/sets/{set_code.lower()}"

        try:
            data = await self._request(url)
        except NotFoundError:
            return None

        # Parse release date
        release_date = None
        if "released_at" in data and data["released_at"]:
            try:
                release_date = datetime.strptime(
                    data["released_at"], "%Y-%m-%d"
                ).date()
            except ValueError:
                pass

        return SetData(
            code=data.get("code", set_code).upper(),
            name=data.get("name", "Unknown"),
            release_date=release_date,
        )

    async def fetch_card_by_name(
        self, card_name: str, set_code: Optional[str] = None
    ) -> Optional[CardData]:
        """
        Fetch a single card by exact name.

        Args:
            card_name: Exact card name.
            set_code: Optional set code to narrow search.

        Returns:
            CardData object or None if not found.
        """
        query = f'!"{card_name}"'
        if set_code:
            query += f" set:{set_code.lower()}"

        url = f"{self.base_url}/cards/named?exact={httpx.QueryParams({'': card_name})['']}"
        if set_code:
            url += f"&set={set_code.lower()}"

        try:
            data = await self._request(url)
            return self._parse_card(data)
        except NotFoundError:
            return None

    async def search_cards(
        self, query: str, limit: int = 20
    ) -> list[CardData]:
        """
        Search cards by name (fuzzy match).

        Args:
            query: Search query.
            limit: Maximum number of results.

        Returns:
            List of matching CardData objects.
        """
        url = f"{self.base_url}/cards/search?q={query}"

        try:
            data = await self._request(url)
        except NotFoundError:
            return []

        cards = []
        for card_data in data.get("data", [])[:limit]:
            cards.append(self._parse_card(card_data))

        return cards
