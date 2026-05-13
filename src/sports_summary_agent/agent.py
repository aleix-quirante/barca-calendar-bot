"""
SportsSummaryAgent orchestrates the generation of pre-match analysis.
"""

import logging
from datetime import datetime, timedelta, UTC

from src.sports_summary_agent.feed_client import FeedClient, FeedClientError
from src.sports_summary_agent.llm_client import LLMClient, LLMClientError
from src.sports_summary_agent.models import (
    PreMatchAnalysis,
    UpcomingMatch,
    PreMatchContext,
)

logger = logging.getLogger(__name__)


class SportsSummaryAgent:
    """
    Agent that finds upcoming matches and generates pre-match analysis using an LLM.

    Attributes:
        feed_client: Client for fetching news articles.
        llm_client: Client for generating pre-match analysis.
        calendar_service: Google Calendar service for fetching upcoming matches.
        calendar_id: Google Calendar ID to query.
        cache_enabled: Whether to cache analysis to avoid duplicate generation.
        _cache: In‑memory cache of generated analysis (match_id → PreMatchAnalysis).
    """

    def __init__(
        self,
        feed_client: FeedClient,
        llm_client: LLMClient,
        calendar_service=None,
        calendar_id: str = "primary",
        cache_enabled: bool = True,
    ):
        """
        Initialize the agent.

        Args:
            feed_client: FeedClient instance.
            llm_client: LLMClient instance.
            calendar_service: Google Calendar API service (from googleapiclient.discovery.build).
            calendar_id: Google Calendar ID to query for upcoming matches.
            cache_enabled: Enable caching of analysis.
        """
        self.feed_client = feed_client
        self.llm_client = llm_client
        self.calendar_service = calendar_service
        self.calendar_id = calendar_id
        self.cache_enabled = cache_enabled
        self._cache: dict[str, PreMatchAnalysis] = {}

    def run(self, force: bool = False) -> list[PreMatchAnalysis]:
        """
        Run the agent: find next match, fetch news, generate pre-match analysis,
        and persist the analysis into the matching Google Calendar event.

        Args:
            force: If True, force update even if the event already contains a previa.

        Returns:
            List of PreMatchAnalysis objects (only newly generated ones).
        """
        # Fetch recent news for context
        try:
            news_items = self.feed_client.fetch_news()
        except FeedClientError:
            logger.error("Failed to fetch news", exc_info=True)
            news_items = []

        if not news_items:
            logger.warning("No news items found for context")

        # Find the next upcoming match
        upcoming_match = self._find_next_match()
        if not upcoming_match:
            logger.info("No upcoming match found in the next 7 days")
            return []

        match_id = upcoming_match.match_id

        # Check cache
        if self.cache_enabled and match_id in self._cache:
            logger.debug("Analysis for match %s already cached, skipping", match_id)
            return []

        # Build deterministic context
        context = self._build_prematch_context(upcoming_match)

        # Generate pre-match analysis
        try:
            analysis = self.llm_client.generate_prematch_analysis(
                upcoming_match, news_items, context
            )
        except LLMClientError:
            logger.error("Failed to generate pre-match analysis", exc_info=True)
            return []

        # Persist analysis to the calendar event (idempotente: el helper
        # detecta el marcador y evita duplicados). Si el servicio de
        # calendario no está disponible, omitimos la persistencia pero
        # devolvemos el análisis igualmente.
        if self.calendar_service and upcoming_match.event_id:
            try:
                # Import perezoso para evitar dependencias circulares
                from src.sports_summary_agent import (
                    update_event_with_prematch_analysis,
                )

                analysis_text = self._format_analysis_text(analysis)
                persisted = update_event_with_prematch_analysis(
                    calendar_service=self.calendar_service,
                    event_id=upcoming_match.event_id,
                    analysis_text=analysis_text,
                    force=force,
                )
                if persisted:
                    logger.info(
                        "Análisis pre-partido persistido en evento %s",
                        upcoming_match.event_id,
                    )
                else:
                    logger.warning(
                        "No se pudo persistir el análisis para el evento %s",
                        upcoming_match.event_id,
                    )
            except Exception:
                logger.error(
                    "Error inesperado persistiendo el análisis pre-partido",
                    exc_info=True,
                )
        else:
            logger.warning(
                "No hay calendar_service o event_id; el análisis no se persistirá."
            )

        if self.cache_enabled:
            self._cache[match_id] = analysis

        logger.info("Generated pre-match analysis for %s", match_id)
        return [analysis]

    @staticmethod
    def _format_analysis_text(analysis: PreMatchAnalysis) -> str:
        """
        Formatea un PreMatchAnalysis a texto plano para insertar en el evento.

        Estructura:
            • Punto 1
            • Punto 2
            • Punto 3

            🎯 Previa táctica: <tactical_preview>

        Args:
            analysis: Objeto PreMatchAnalysis ya validado.

        Returns:
            Texto formateado listo para insertar en la descripción del evento.
        """
        bullet_points = "\n".join(
            f"• {point.strip()}" for point in analysis.analysis_points
        )
        tactical = analysis.tactical_preview.strip()
        return f"{bullet_points}\n\n🎯 Previa táctica: {tactical}"

    def _build_prematch_context(self, upcoming_match: UpcomingMatch) -> PreMatchContext:
        """
        Build deterministic context for pre-match analysis.

        Determines rival name, home/away condition, and ClubElo probability (if available).
        Gracefully handles missing ClubElo data.
        """
        # Determine if Barça is home or away
        barca_keywords = ["barcelona", "barça", "fc barcelona"]
        home_lower = upcoming_match.home_team.lower()
        away_lower = upcoming_match.away_team.lower()
        is_barca_home = any(kw in home_lower for kw in barca_keywords)
        is_barca_away = any(kw in away_lower for kw in barca_keywords)

        if is_barca_home and is_barca_away:
            # Ambiguous, default to home
            is_barca_home = True
            is_barca_away = False

        rival_name = (
            upcoming_match.away_team if is_barca_home else upcoming_match.home_team
        )
        is_home = is_barca_home

        # Try to fetch ClubElo probability
        clubelo_prob = None
        try:
            from src.win_probability_fix.clubelo_client import ClubEloClient

            client = ClubEloClient()
            probabilities = client.get_probabilities()
            match_date_str = upcoming_match.match_date.date().isoformat()
            clubelo_prob = probabilities.get(match_date_str)
        except Exception as e:
            logger.debug("Could not fetch ClubElo probability: %s", e)

        return PreMatchContext(
            rival_name=rival_name,
            is_home=is_home,
            clubelo_probability=clubelo_prob,
        )

    def _find_next_match(self) -> UpcomingMatch | None:
        """
        Find the next upcoming match in the calendar (within 7 days) that
        doesn't already contain a generated previa (detected via stable marker).

        Returns:
            UpcomingMatch object or None if no match found.
        """
        if not self.calendar_service:
            logger.warning(
                "No calendar service provided, cannot fetch upcoming matches"
            )
            return None

        try:
            # Import perezoso para evitar dependencias circulares
            from src.sports_summary_agent import has_prematch_analysis

            now = datetime.now(UTC)
            time_max = now + timedelta(days=7)

            events_result = (
                self.calendar_service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])

            for event in events:
                # Saltar eventos que ya tienen una previa (marcador estable)
                description = event.get("description", "") or ""
                if has_prematch_analysis(description):
                    continue

                # Parse event details
                summary = event.get("summary", "")
                start = event.get("start", {})
                start_datetime_str = start.get("dateTime") or start.get("date")

                if not start_datetime_str:
                    continue

                # Parse datetime
                try:
                    if "T" in start_datetime_str:
                        match_date = datetime.fromisoformat(
                            start_datetime_str.replace("Z", "+00:00")
                        )
                    else:
                        # Date only, skip
                        continue
                except ValueError:
                    continue

                # Extract teams from summary (assuming format like "⚽ FC Barcelona vs Real Madrid")
                summary_clean = summary.replace("⚽", "").strip()
                teams = summary_clean.split(" vs ")
                if len(teams) != 2:
                    teams = summary_clean.split(" - ")
                if len(teams) != 2:
                    continue

                home_team = teams[0].strip()
                away_team = teams[1].strip()

                return UpcomingMatch(
                    home_team=home_team,
                    away_team=away_team,
                    match_date=match_date,
                    competition="La Liga",  # Could be extracted from description
                    location=event.get("location", ""),
                    event_id=event.get("id", ""),
                    description=description,
                )

        except Exception as e:
            logger.error("Error fetching upcoming matches from calendar", exc_info=True)
            return None

        return None

    def clear_cache(self):
        """Clear the internal cache."""
        self._cache.clear()

    def get_cache_size(self) -> int:
        """Return the number of cached analyses."""
        return len(self._cache)
