"""
RSS feed client for fetching news articles.
"""

import time
from datetime import date

import feedparser
import httpx

from src.sports_summary_agent.models import NewsItem


class FeedClientError(Exception):
    """Base exception for feed client errors."""

    pass


class FeedClient:
    """Client for fetching and parsing news articles from an RSS feed."""

    def __init__(
        self,
        feed_url: str,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        ssl_verify: bool = True,
        max_items: int = 10,
    ):
        """
        Initialize the feed client.

        Args:
            feed_url: URL of the RSS feed.
            timeout: HTTP timeout in seconds.
            max_retries: Maximum number of retries for transient failures.
            retry_delay: Delay between retries in seconds (will be increased exponentially).
            ssl_verify: Whether to verify SSL certificates (set False for self‑signed or tunnel endpoints).
            max_items: Maximum number of news items to fetch (default: 10).
        """
        self.feed_url = feed_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.ssl_verify = ssl_verify
        self.max_items = max_items
        self._http_client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            verify=self.ssl_verify,
        )

    def fetch_news(self) -> list[NewsItem]:
        """
        Fetch and parse the RSS feed, returning a list of NewsItem objects.

        Returns:
            List of NewsItem objects (up to max_items).

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

    def _parse_feed(self, raw_feed: str) -> list[NewsItem]:
        """
        Parse the raw RSS feed into NewsItem objects.

        Args:
            raw_feed: Raw XML content of the feed.

        Returns:
            List of NewsItem objects (up to max_items).
        """
        parsed = feedparser.parse(raw_feed)
        news_items = []

        for entry in parsed.entries[: self.max_items]:
            news_item = self._parse_entry(entry)
            if news_item:
                news_items.append(news_item)

        return news_items

    def _parse_entry(self, entry) -> NewsItem | None:
        """
        Parse a single feed entry into a NewsItem.

        Args:
            entry: A feedparser entry object.

        Returns:
            NewsItem if parsing succeeds, None otherwise.
        """
        # Extract title
        title = getattr(entry, "title", "")
        if not title:
            return None

        # Extract publication date
        pub_date = getattr(entry, "published_parsed", None)
        if pub_date:
            published_date = date(pub_date.tm_year, pub_date.tm_mon, pub_date.tm_mday)
        else:
            # Fallback to today if no date
            published_date = date.today()

        # Extract description (summary)
        description = getattr(entry, "summary", "") or getattr(entry, "description", "")

        # Extract link
        link = getattr(entry, "link", "")

        return NewsItem(
            title=title,
            published_date=published_date,
            description=description,
            link=link,
        )

    def close(self):
        """Close the HTTP client."""
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
