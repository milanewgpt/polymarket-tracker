"""
Polymarket event parser.

Primary strategy: use the Gamma API (JSON).
The gamma endpoint may change — keep base URL configurable via settings.
"""

import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx

from domain.range_utils import extract_range_from_text, parse_range_label

logger = logging.getLogger(__name__)


class PolymarketParseError(Exception):
    pass


class PolymarketClient:
    def __init__(self, gamma_api_url: str = "https://gamma-api.polymarket.com") -> None:
        self.gamma_api_url = gamma_api_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    # ── URL helpers ─────────────────────────────────────────────────

    @staticmethod
    def extract_slug(url: str) -> str:
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "event":
            return parts[1]
        raise PolymarketParseError(f"Cannot extract event slug from URL: {url}")

    @staticmethod
    def validate_url(url: str) -> bool:
        return bool(re.match(r"https?://polymarket\.com/event/.+", url))

    # ── Fetching ────────────────────────────────────────────────────

    async def fetch_event_data(self, slug: str) -> dict:
        url = f"{self.gamma_api_url}/events"
        params = {"slug": slug}
        logger.info("Fetching Polymarket event: %s", slug)

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            if not data:
                raise PolymarketParseError(f"No event found for slug: {slug}")
            return data[0]
        if isinstance(data, dict):
            if "id" in data:
                return data
            # Some API versions wrap in {"data": [...]}
            inner = data.get("data") or data.get("events")
            if isinstance(inner, list) and inner:
                return inner[0]
        raise PolymarketParseError(f"Unexpected API response shape for slug: {slug}")

    # ── Parsing ─────────────────────────────────────────────────────

    def parse_event(
        self, event_data: dict
    ) -> tuple[str, list[tuple[str, int, int]], Optional[datetime], Optional[datetime]]:
        """Return (title, sorted_ranges, end_date_or_None, start_time_or_None).

        start_time is when tweet counting begins (startTime field), which differs
        from the market creation date. E.g. for a 48h market "June 4-6", startTime
        is June 4 16:00 UTC even though the market opened for trading earlier.
        """

        title = event_data.get("title") or event_data.get("question") or "Unknown Event"

        end_date = self._parse_end_date(event_data)
        start_time = self._parse_start_time(event_data)

        markets = event_data.get("markets") or event_data.get("outcomes") or []
        if not markets:
            raise PolymarketParseError("No markets found in event data")

        ranges: list[tuple[str, int, int]] = []
        for market in markets:
            label = self._extract_market_range_label(market)
            if label is None:
                continue
            try:
                min_val, max_val = parse_range_label(label)
                ranges.append((label, min_val, max_val))
            except ValueError:
                logger.warning("Skipping unparseable label: %s", label)

        if not ranges:
            raise PolymarketParseError("No valid numeric ranges found in event markets")

        ranges.sort(key=lambda x: x[1])
        return title, ranges, end_date, start_time

    # ── Private helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_market_range_label(market: dict) -> Optional[str]:
        for field in ("groupItemTitle", "title", "question", "outcome"):
            value = market.get(field, "")
            if not value:
                continue
            extracted = extract_range_from_text(value)
            if extracted:
                return extracted
        return None

    @staticmethod
    def _parse_end_date(event_data: dict) -> Optional[datetime]:
        for key in ("endDate", "end_date_iso", "endDateIso", "end_date"):
            raw = event_data.get(key)
            if raw:
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
        # Try from nested markets — use the latest market end date
        markets = event_data.get("markets", [])
        dates: list[datetime] = []
        for m in markets:
            for key in ("endDate", "end_date_iso"):
                raw = m.get(key)
                if raw:
                    try:
                        dates.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
                    except (ValueError, AttributeError):
                        continue
        return max(dates) if dates else None

    @staticmethod
    def _parse_start_time(event_data: dict) -> Optional[datetime]:
        """Parse the tweet-counting start time (startTime field)."""
        for key in ("startTime", "start_time"):
            raw = event_data.get(key)
            if raw:
                try:
                    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
        return None

    async def close(self) -> None:
        await self.client.aclose()
