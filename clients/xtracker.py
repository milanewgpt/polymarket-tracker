"""
Xtracker adapter — fetches the current tweet count from the Xtracker API.

Discovered API:
  GET /api/users/{handle}             → user info + all trackings
  GET /api/trackings/{id}?includeStats=true → tracking stats (stats.total = tweet count)
  GET /api/users/{handle}/posts?startDate=...&endDate=... → raw posts (fallback)

Each tracking has a `marketLink` that matches a Polymarket event URL.
The flow:
  1. On /add: call find_tracking_for_event() to get the tracking ID
  2. On each monitoring tick: call get_tweet_count(tracking_id) for the count
  3. Fallback: count posts in date range if no tracking is found
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class XtrackerError(Exception):
    pass


@dataclass
class TrackingInfo:
    tracking_id: str
    title: str
    start_date: str
    end_date: str
    market_link: Optional[str]
    is_active: bool


class XtrackerClient:
    def __init__(
        self,
        base_url: str = "https://xtracker.polymarket.com",
        handle: str = "elonmusk",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.handle = handle
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PolymarketTracker/1.0)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    # ── Primary: tweet count by tracking ID ─────────────────────────

    async def get_tweet_count(self, tracking_id: str) -> int:
        """Fetch cumulative tweet count from tracking stats."""
        url = f"{self.base_url}/api/trackings/{tracking_id}"
        resp = await self.client.get(url, params={"includeStats": "true"})
        resp.raise_for_status()

        data = resp.json()
        if not data.get("success"):
            raise XtrackerError(f"API returned success=false for tracking {tracking_id}")

        stats = data.get("data", {}).get("stats", {})
        total = stats.get("total")
        if total is None:
            raise XtrackerError(f"No stats.total in tracking {tracking_id}")

        logger.info("Tweet count from tracking %s: %d", tracking_id, total)
        return int(total)

    # ── Fallback: count posts in date range ─────────────────────────

    async def get_tweet_count_by_dates(
        self, start_date: datetime, end_date: datetime
    ) -> int:
        """Count posts between two UTC datetimes (fallback if no tracking)."""
        url = f"{self.base_url}/api/users/{self.handle}/posts"
        resp = await self.client.get(
            url,
            params={
                "startDate": self._to_utc_z(start_date),
                "endDate": self._to_utc_z(end_date),
            },
        )
        resp.raise_for_status()

        data = resp.json()
        posts = data.get("data", [])
        count = len(posts)
        logger.info("Tweet count by date range: %d posts", count)
        return count

    # ── Discovery: find tracking for a Polymarket event ─────────────

    async def find_tracking_for_event(
        self,
        event_url: str,
        event_end_date: Optional[datetime] = None,
    ) -> Optional[TrackingInfo]:
        """Match a Polymarket event URL to an Xtracker tracking.

        First tries exact slug match via marketLink.
        Falls back to closest end-date match when no marketLink is set.
        """
        url = f"{self.base_url}/api/users/{self.handle}"
        resp = await self.client.get(url)
        resp.raise_for_status()

        data = resp.json()
        trackings = data.get("data", {}).get("trackings", [])

        event_slug = self._extract_slug(event_url)

        # 1. Exact slug match via marketLink
        for t in trackings:
            market_link = t.get("marketLink") or ""
            tracking_slug = self._extract_slug(market_link)
            if event_slug and tracking_slug and event_slug == tracking_slug:
                info = TrackingInfo(
                    tracking_id=t["id"],
                    title=t.get("title", ""),
                    start_date=t.get("startDate", ""),
                    end_date=t.get("endDate", ""),
                    market_link=market_link,
                    is_active=t.get("isActive", False),
                )
                logger.info(
                    "Found tracking %s by slug for event %s", info.tracking_id, event_slug
                )
                return info

        # 2. Fallback: match by closest end date (within 12 hours)
        if event_end_date:
            if event_end_date.tzinfo is None:
                event_end_date = event_end_date.replace(tzinfo=timezone.utc)
            best: Optional[dict] = None
            best_diff = float("inf")
            for t in trackings:
                raw_end = t.get("endDate", "")
                if not raw_end:
                    continue
                try:
                    t_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                    diff = abs((t_end - event_end_date).total_seconds())
                    if diff < best_diff:
                        best_diff = diff
                        best = t
                except (ValueError, AttributeError):
                    continue
            if best is not None and best_diff <= 43200:  # 12 hours
                info = TrackingInfo(
                    tracking_id=best["id"],
                    title=best.get("title", ""),
                    start_date=best.get("startDate", ""),
                    end_date=best.get("endDate", ""),
                    market_link=best.get("marketLink"),
                    is_active=best.get("isActive", False),
                )
                logger.info(
                    "Found tracking %s by date proximity (%.0fs) for event %s",
                    info.tracking_id,
                    best_diff,
                    event_slug,
                )
                return info

        logger.warning("No tracking found for event URL: %s", event_url)
        return None

    async def get_all_trackings(self) -> list[TrackingInfo]:
        """Return all trackings for the user."""
        url = f"{self.base_url}/api/users/{self.handle}"
        resp = await self.client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return [
            TrackingInfo(
                tracking_id=t["id"],
                title=t.get("title", ""),
                start_date=t.get("startDate", ""),
                end_date=t.get("endDate", ""),
                market_link=t.get("marketLink"),
                is_active=t.get("isActive", False),
            )
            for t in data.get("data", {}).get("trackings", [])
        ]

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_slug(url: str) -> Optional[str]:
        if not url:
            return None
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "event":
            return parts[1].lower()
        return path.lower() if path else None

    @staticmethod
    def _to_utc_z(dt: datetime) -> str:
        """Format datetime as ISO 8601 with Z suffix (required by xtracker API)."""
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    async def close(self) -> None:
        await self.client.aclose()
