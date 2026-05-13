"""
Sports Summary Agent – Módulo para generar análisis pre-partido (Previa).

Utiliza la API OpenAI‑compatible (Ollama/LocalAI) configurada en `src.shared.config`.
"""

import logging
from typing import Optional

from src.shared.config import settings

logger = logging.getLogger(__name__)

# Re‑exportar la configuración para conveniencia
config = settings

# Determinar si el módulo está activo
ENABLED = settings.is_summary_enabled

# Cliente OpenAI (se importa bajo demanda para evitar dependencia obligatoria)
_openai_client = None


def get_openai_client():
    """
    Devuelve un cliente OpenAI configurado con la URL base y API key de Ollama/LocalAI.

    Returns:
        openai.OpenAI: Cliente listo para usar.

    Raises:
        ImportError: Si la librería `openai` no está instalada.
        RuntimeError: Si la URL base no está configurada o el módulo está desactivado.
    """
    global _openai_client
    if not ENABLED:
        raise RuntimeError(
            "El módulo SportsSummaryAgent está desactivado (SUMMARY_ENABLED=False)."
        )

    if _openai_client is None:
        try:
            from openai import OpenAI
        except ImportError as e:
            logger.error(
                "La librería 'openai' no está instalada. "
                "Añádala a las dependencias (openai>=1.0)."
            )
            raise ImportError(
                "openai>=1.0 es requerido para SportsSummaryAgent. "
                "Instálelo con 'pip install openai'."
            ) from e

        base_url = settings.ollama_base_url.strip()
        api_key = settings.ollama_api_key.strip() or "ollama"

        if not base_url:
            raise RuntimeError(
                "OLLAMA_BASE_URL no está configurada. "
                "Establezca la variable de entorno BARCA_OLLAMA_BASE_URL."
            )

        logger.debug(
            "Creando cliente OpenAI‑compatible con base_url=%s",
            base_url,
        )
        _openai_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=settings.summary_timeout,
        )

    return _openai_client


def create_agent(cache_enabled: bool = True, calendar_service=None):
    """
    Crea una instancia de SportsSummaryAgent configurada con los ajustes actuales.

    Args:
        cache_enabled: Habilitar caché de análisis.
        calendar_service: Servicio de Google Calendar para buscar próximos partidos.

    Returns:
        SportsSummaryAgent: Agente listo para usar.

    Raises:
        RuntimeError: Si el módulo está desactivado o falta configuración.
    """
    if not ENABLED:
        raise RuntimeError(
            "El módulo SportsSummaryAgent está desactivado (SUMMARY_ENABLED=False)."
        )

    # Importar aquí para evitar dependencias circulares
    from src.sports_summary_agent.agent import SportsSummaryAgent
    from src.sports_summary_agent.feed_client import FeedClient
    from src.sports_summary_agent.llm_client import LLMClient

    feed_url = str(settings.rss_feed_url)
    feed_client = FeedClient(
        feed_url=feed_url,
        timeout=settings.summary_timeout,
        max_retries=3,
        retry_delay=1.0,
        ssl_verify=settings.ollama_ssl_verify,
        max_items=10,
    )

    llm_client = LLMClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.summary_model,
        timeout=settings.summary_timeout,
        max_tokens=settings.summary_max_tokens,
        temperature=settings.summary_temperature,
        dry_run=False,  # Puede ser configurable en el futuro
        ssl_verify=settings.ollama_ssl_verify,
    )

    return SportsSummaryAgent(
        feed_client=feed_client,
        llm_client=llm_client,
        calendar_service=calendar_service,
        calendar_id=settings.google_calendar_id,
        cache_enabled=cache_enabled,
    )


# Marcador estable para detectar eventos que ya tienen previa.
# Se utiliza tanto al insertar como al filtrar duplicados, garantizando
# que la detección sea robusta ante cambios en el texto del análisis.
PREVIA_MARKER = "🔮 **PREVIA DEL PARTIDO**"


def has_prematch_analysis(description: str | None) -> bool:
    """
    Determina si una descripción de evento ya contiene una previa generada.

    Args:
        description: Texto de la descripción del evento.

    Returns:
        True si la descripción contiene el marcador de previa.
    """
    if not description:
        return False
    return PREVIA_MARKER in description


def update_event_with_prematch_analysis(
    calendar_service, event_id: str, analysis_text: str, force: bool = False
) -> bool:
    """
    Actualiza la descripción de un evento de Google Calendar con el análisis pre-partido.

    Preserva la descripción existente (incluyendo la línea de probabilidad de
    victoria del Barça) y antepone el bloque de previa con marcador estable.
    Es idempotente: si la descripción ya contiene una previa, no la duplica.

    Args:
        calendar_service: Servicio de Google Calendar autenticado.
        event_id: ID del evento a actualizar.
        analysis_text: Texto del análisis a insertar.
        force: Si True, ignora la detección de previa existente y fuerza la actualización.

    Returns:
        bool: True si la actualización fue exitosa (o ya estaba aplicada).
    """
    try:
        event = (
            calendar_service.events()
            .get(calendarId=settings.google_calendar_id, eventId=event_id)
            .execute()
        )

        current_description = event.get("description", "") or ""

        # Idempotencia: si ya existe una previa, no la duplicamos (a menos que force=True).
        if not force and has_prematch_analysis(current_description):
            logger.info(
                "Evento %s ya contiene una previa; se omite la actualización.",
                event_id,
            )
            return True

        # Validar que el análisis no esté vacío
        if not analysis_text or analysis_text.strip() == "":
            logger.warning(
                "El texto del análisis está vacío para el evento %s; no se actualiza.",
                event_id,
            )
            return False

        # Anteponer la previa al inicio de la descripción, preservando
        # la información existente (probabilidad de victoria, etc.).
        new_description = (
            f"{PREVIA_MARKER}\n\n{analysis_text}\n\n---\n\n{current_description}"
        ).rstrip()

        # Log para depuración: mostrar los primeros 200 caracteres de la nueva descripción
        logger.debug(
            "Actualizando evento %s con nueva descripción (primeros 200 chars): %s",
            event_id,
            new_description[:200],
        )

        event["description"] = new_description

        calendar_service.events().update(
            calendarId=settings.google_calendar_id, eventId=event_id, body=event
        ).execute()

        logger.info("Evento %s actualizado con análisis pre-partido", event_id)
        return True
    except Exception as e:
        logger.error(f"Error actualizando evento con análisis: {e}", exc_info=True)
        return False


# Exportar símbolos públicos
__all__ = [
    "config",
    "ENABLED",
    "PREVIA_MARKER",
    "get_openai_client",
    "create_agent",
    "has_prematch_analysis",
    "update_event_with_prematch_analysis",
]
