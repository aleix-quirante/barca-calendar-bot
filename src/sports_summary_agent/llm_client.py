"""
LLM client for generating pre-match analysis using a local Ollama API (OpenAI‑compatible).
"""

import json
import logging
from typing import Optional

import httpx
from pydantic import ValidationError

from src.sports_summary_agent.models import (
    NewsItem,
    UpcomingMatch,
    PreMatchAnalysis,
    PreMatchContext,
)

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""

    pass


class LLMClient:
    """Client for interacting with a local Ollama API (OpenAI‑compatible)."""

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
            model: Model name to use (e.g., 'qwen3.5:9b').
            timeout: Request timeout in seconds.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0–1.0).
            dry_run: If True, no actual API call is made; a dummy analysis is returned.
            ssl_verify: Whether to verify SSL certificates (set False for self‑signed or tunnel endpoints).
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.dry_run = dry_run
        self.ssl_verify = ssl_verify
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy initialization of the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                verify=self.ssl_verify,
                timeout=self.timeout,
                headers=(
                    {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                ),
            )
        return self._client

    def generate_prematch_analysis(
        self,
        upcoming_match: UpcomingMatch,
        news_items: list[NewsItem],
        context: Optional[PreMatchContext] = None,
    ) -> PreMatchAnalysis:
        """
        Generate a pre-match analysis for an upcoming match.

        Args:
            upcoming_match: The upcoming match to analyze.
            news_items: Recent news articles for context.
            context: Deterministic context (rival name, home/away, ClubElo probability).
                If None, a minimal context will be derived from the match.

        Returns:
            A PreMatchAnalysis object.

        Raises:
            LLMClientError: If the API call fails or the response cannot be parsed.
        """
        if self.dry_run:
            logger.info("Dry‑run mode: generating dummy pre-match analysis")
            return self._generate_dry_run_analysis(upcoming_match)

        # Pre‑flight health check
        if not self._check_health():
            logger.error("🛑 Nodo Local inalcanzable en M4 Pro")
            # Return a safe empty analysis to allow ClubElo to keep operating
            return self._generate_fallback_analysis(upcoming_match)

        prompt = self._build_prematch_prompt(upcoming_match, news_items, context)
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise LLMClientError(f"HTTP error calling Ollama API: {e}") from e
        except json.JSONDecodeError as e:
            raise LLMClientError(f"Invalid JSON response from Ollama API: {e}") from e

        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            raise LLMClientError("Empty response from LLM")

        return self._parse_prematch_response(content, upcoming_match.match_id)

    def _check_health(self) -> bool:
        """
        Perform a quick health check of the local Ollama endpoint.

        Returns:
            True if the endpoint is reachable and responds with a valid models list.
        """
        try:
            resp = self.client.get(f"{self.base_url}/models", timeout=5)
            resp.raise_for_status()
            # Expect a JSON response with a "models" key (Ollama v1 API)
            data = resp.json()
            if isinstance(data, dict) and "models" in data:
                logger.debug("Health check passed: Ollama endpoint reachable")
                return True
            else:
                logger.warning("Health check: unexpected response format")
                return False
        except Exception as e:
            logger.debug("Health check failed: %s", e)
            return False

    def _build_prematch_prompt(
        self,
        upcoming_match: UpcomingMatch,
        news_items: list[NewsItem],
        context: Optional[PreMatchContext] = None,
    ) -> str:
        """Build the pre-match analysis prompt for the LLM."""
        # Format news context
        news_context = "\n".join(
            [
                f"- {item.title} ({item.published_date}): {item.description[:200]}"
                for item in news_items[:5]
            ]
        )

        # Determine rival and home/away condition
        if context is None:
            # Derive from match (assuming Barça is always home_team? Not safe)
            # We'll assume Barça is the home team if "Barcelona" in home_team
            is_barca_home = "barcelona" in upcoming_match.home_team.lower()
            rival_name = (
                upcoming_match.away_team if is_barca_home else upcoming_match.home_team
            )
            is_home = is_barca_home
            clubelo_prob = None
        else:
            rival_name = context.rival_name
            is_home = context.is_home
            clubelo_prob = context.clubelo_probability

        venue = "local" if is_home else "visitante"
        probability_text = (
            f"{clubelo_prob:.1f}%" if clubelo_prob is not None else "no disponible"
        )

        # System prompt reinforcement
        system_instruction = (
            "Basa tu análisis táctico en tu conocimiento previo sobre el rival indicado. "
            "NO inventes datos de lesiones actuales. "
            "Céntrate en estilos de juego históricos, formaciones típicas y cómo contrarrestarlos."
        )

        return f"""
You are a football analyst specializing in FC Barcelona. Write a pre-match analysis (Previa) for the upcoming game.

{system_instruction}

UPCOMING MATCH:
{upcoming_match.home_team} vs {upcoming_match.away_team}
Date: {upcoming_match.match_date.strftime('%Y-%m-%d %H:%M')}
Competition: {upcoming_match.competition}
Venue: {upcoming_match.location}

CONTEXT INJECTION (deterministic):
- Rival: {rival_name}
- Condición: El Barça juega como {venue}
- Probabilidad de victoria (ClubElo): {probability_text}

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

    def _generate_fallback_analysis(
        self, upcoming_match: UpcomingMatch
    ) -> PreMatchAnalysis:
        """Generate a fallback analysis when the local node is unreachable."""
        analysis_points = [
            "⚠️ El nodo local de Ollama no está disponible. No se pudo generar análisis táctico.",
            "⚠️ Se recomienda verificar la conexión con el servidor local (M4 Pro).",
            "⚠️ El partido se jugará según lo programado; se mantiene la probabilidad de ClubElo.",
        ]
        return PreMatchAnalysis(
            match_id=upcoming_match.match_id,
            analysis_points=analysis_points,
            tactical_preview="Análisis no disponible debido a indisponibilidad del nodo local. ClubElo continúa operando normalmente.",
            model_used=self.model,
            inference_source="local_ollama",  # Still marked as local_ollama but with fallback
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
