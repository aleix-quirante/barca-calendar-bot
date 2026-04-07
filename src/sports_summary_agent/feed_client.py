"""
RSS feed client for fetching match results.
"""

import re
import time
from datetime import date

import feedparser
import httpx

from src.sports_summary_agent.models import MatchResult


class FeedClientError(Exception):
    """Base exception for feed client errors."""

    pass


class FeedClient:
    """Client for fetching and parsing match results from an RSS feed."""

    def __init__(
        self,
        feed_url: str,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        ssl_verify: bool = True,
    ):
        """
        Initialize the feed client.

        Args:
            feed_url: URL of the RSS feed.
            timeout: HTTP timeout in seconds.
            max_retries: Maximum number of retries for transient failures.
            retry_delay: Delay between retries in seconds (will be increased exponentially).
            ssl_verify: Whether to verify SSL certificates (set False for self‑signed or tunnel endpoints).
        """
        self.feed_url = feed_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.ssl_verify = ssl_verify
        self._http_client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=self.ssl_verify,
        )

    def fetch_match_results(self) -> list[MatchResult]:
        """
        Fetch and parse the RSS feed, returning a list of MatchResult objects.

        Returns:
            List of MatchResult objects.

        Raises:
            FeedClientError: If the feed cannot be fetched or parsed after all retries.
        """
        raw_feed = self._fetch_feed_with_retry()
        return self._parse_feed(raw_feed)

    def _fetch_feed_with_retry(self) -> str:
        """Fetch the raw feed content with retry logic."""
        last_exception: Exception | None = None
        delay = self.retry_delay

        for attempt in range(self.max_retries):
            try:
                response = self._http_client.get(self.feed_url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code < 500:
                    # Client errors (4xx) are not retried
                    raise FeedClientError(f"HTTP error {e.response.status_code}") from e
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                # Transient error, will retry
                pass

            if attempt < self.max_retries - 1:
                time.sleep(delay)
                delay *= 2  # Exponential backoff

        # All retries exhausted
        raise FeedClientError(
            f"Failed to fetch feed after {self.max_retries} attempts"
        ) from last_exception

    def _parse_feed(self, raw_feed: str) -> list[MatchResult]:
        """
        Parse the raw RSS feed into MatchResult objects.

        Args:
            raw_feed: Raw XML content of the feed.

        Returns:
            List of MatchResult objects. Items that cannot be parsed are silently skipped.
        """
        parsed = feedparser.parse(raw_feed)
        results = []

        for entry in parsed.entries:
            match_result = self._parse_entry(entry)
            if match_result:
                results.append(match_result)

        return results

    def _parse_entry(self, entry) -> MatchResult | None:
        """
        Parse a single feed entry into a MatchResult.

        Args:
            entry: A feedparser entry object.

        Returns:
            MatchResult if parsing succeeds, None otherwise.
        """
        # Extract title and publication date
        title = getattr(entry, "title", "")
        pub_date = getattr(entry, "published_parsed", None)
        if pub_date:
            match_date = date(pub_date.tm_year, pub_date.tm_mon, pub_date.tm_mday)
        else:
            # Fallback to today if no date
            match_date = date.today()

        # Try to parse score from title using a simple regex
        # Example: "FC Barcelona 3 - 1 Real Madrid"
        pattern = r"([A-Za-z\s]+)\s+(\d+)\s*[-–]\s*(\d+)\s+([A-Za-z\s]+)"
        match = re.search(pattern, title)
        if not match:
            return None

        home_team = match.group(1).strip()
        home_score = int(match.group(2))
        away_score = int(match.group(3))
        away_team = match.group(4).strip()

        # Determine competition from description or default
        description = getattr(entry, "description", "")
        competition = "La Liga"
        if "Champions League" in description:
            competition = "UEFA Champions League"
        elif "Copa del Rey" in description:
            competition = "Copa del Rey"

        return MatchResult(
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            match_date=match_date,
            competition=competition,
        )

    def close(self):
        """Close the HTTP client."""
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
