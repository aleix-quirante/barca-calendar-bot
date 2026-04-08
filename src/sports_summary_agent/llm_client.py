"""
LLM client for generating pre-match analysis using an OpenAI‑compatible API.
"""

import json
import logging
import httpx

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from src.sports_summary_agent.models import NewsItem, UpcomingMatch, PreMatchAnalysis

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""

    pass


class LLMClient:
    """Client for interacting with an OpenAI‑compatible API (Ollama/LocalAI)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 30,
        max_tokens: int = 500,
        temperature: float = 0.7,
        dry_run: bool = False,
        ssl_verify: bool = True,
    ):
        """
        Initialize the LLM client.

        Args:
            base_url: Base URL of the OpenAI‑compatible API (e.g., 'http://localhost:11434/v1').
            api_key: API key (can be a dummy for local inference).
            model: Model name to use (e.g., 'qwen2.5:3b').
            timeout: Request timeout in seconds.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0–1.0).
            dry_run: If True, no actual API call is made; a dummy analysis is returned.
            ssl_verify: Whether to verify SSL certificates (set False for self‑signed or tunnel endpoints).
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.dry_run = dry_run
        self.ssl_verify = ssl_verify
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        """Lazy initialization of the OpenAI client."""
        if self._client is None:
            http_client = httpx.Client(verify=self.ssl_verify, timeout=self.timeout)
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                http_client=http_client,
            )
        return self._client

    def generate_prematch_analysis(
        self, upcoming_match: UpcomingMatch, news_items: list[NewsItem]
    ) -> PreMatchAnalysis:
        """
        Generate a pre-match analysis for an upcoming match.

        Args:
            upcoming_match: The upcoming match to analyze.
            news_items: Recent news articles for context.

        Returns:
            A PreMatchAnalysis object.

        Raises:
            LLMClientError: If the API call fails or the response cannot be parsed.
        """
        if self.dry_run:
            logger.info("Dry‑run mode: generating dummy pre-match analysis")
            return self._generate_dry_run_analysis(upcoming_match)

        prompt = self._build_prematch_prompt(upcoming_match, news_items)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
        except OpenAIError as e:
            raise LLMClientError(f"OpenAI API error: {e}") from e

        content = response.choices[0].message.content
        if not content:
            raise LLMClientError("Empty response from LLM")

        return self._parse_prematch_response(content, upcoming_match.match_id)

    def _build_prematch_prompt(
        self, upcoming_match: UpcomingMatch, news_items: list[NewsItem]
    ) -> str:
        """Build the pre-match analysis prompt for the LLM."""
        # Format news context
        news_context = "\n".join(
            [
                f"- {item.title} ({item.published_date}): {item.description[:200]}"
                for item in news_items[:5]
            ]
        )

        return f"""
You are a football analyst specializing in FC Barcelona. Write a pre-match analysis (Previa) for the upcoming game.

UPCOMING MATCH:
{upcoming_match.home_team} vs {upcoming_match.away_team}
Date: {upcoming_match.match_date.strftime('%Y-%m-%d %H:%M')}
Competition: {upcoming_match.competition}
Venue: {upcoming_match.location}

RECENT NEWS CONTEXT:
{news_context if news_context else "No recent news available."}

Based on the recent news and the upcoming opponent, provide a JSON object with exactly the following structure:
{{
  "analysis_points": [
    "First key point about team form, injuries, or recent performance (max 25 words)",
    "Second point about the opponent's strengths/weaknesses or tactical matchup (max 25 words)",
    "Third point about what to watch for or match importance (max 25 words)"
  ],
  "tactical_preview": "A brief tactical preview of what to expect from this match, including key battles and potential strategies (2-3 sentences, max 60 words)"
}}

Write in Spanish. Be insightful and use the news context to inform your analysis. Ensure analysis_points are exactly three items.
"""

    def _parse_prematch_response(self, content: str, match_id: str) -> PreMatchAnalysis:
        """Parse the LLM response into a PreMatchAnalysis."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMClientError(f"Failed to parse LLM response as JSON: {e}") from e

        # Ensure required fields are present
        analysis_points = data.get("analysis_points", [])
        tactical_preview = data.get("tactical_preview", "")

        try:
            return PreMatchAnalysis(
                match_id=match_id,
                analysis_points=analysis_points,
                tactical_preview=tactical_preview,
                model_used=self.model,
                inference_source=self._inference_source(),
            )
        except ValidationError as e:
            raise LLMClientError(f"LLM response validation failed: {e}") from e

    def _generate_dry_run_analysis(
        self, upcoming_match: UpcomingMatch
    ) -> PreMatchAnalysis:
        """Generate a dummy pre-match analysis for dry‑run mode."""
        analysis_points = [
            f"[DRY‑RUN] El Barça llega en buena forma al enfrentamiento contra {upcoming_match.away_team}.",
            "[DRY‑RUN] El rival presenta debilidades defensivas que pueden ser explotadas.",
            "[DRY‑RUN] Partido clave para mantener el liderato en la competición.",
        ]
        return PreMatchAnalysis(
            match_id=upcoming_match.match_id,
            analysis_points=analysis_points,
            tactical_preview="[DRY‑RUN] Se espera un partido intenso con dominio del Barça en posesión. Las claves estarán en la presión alta y aprovechar los espacios.",
            model_used=self.model,
            inference_source="dry_run",
        )

    def _inference_source(self) -> str:
        """Determine the inference source based on base URL."""
        if self.dry_run:
            return "dry_run"
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            return "local_ollama"
        return "cloudflare_tunnel"

    def close(self):
        """Close the underlying client."""
        if self._client is not None:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
