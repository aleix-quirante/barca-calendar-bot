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


def update_event_with_prematch_analysis(
    calendar_service, event_id: str, analysis_text: str
) -> bool:
    """
    Actualiza la descripción de un evento de Google Calendar con el análisis pre-partido.

    Args:
        calendar_service: Servicio de Google Calendar autenticado.
        event_id: ID del evento a actualizar.
        analysis_text: Texto del análisis a insertar.

    Returns:
        bool: True si la actualización fue exitosa.
    """
    try:
        event = (
            calendar_service.events()
            .get(calendarId=settings.google_calendar_id, eventId=event_id)
            .execute()
        )

        current_description = event.get("description", "")

        # Agregar la previa al inicio de la descripción
        new_description = f"🔮 **PREVIA DEL PARTIDO**\n\n{analysis_text}\n\n---\n\n{current_description}"

        event["description"] = new_description

        calendar_service.events().update(
            calendarId=settings.google_calendar_id, eventId=event_id, body=event
        ).execute()

        logger.info(f"Evento {event_id} actualizado con análisis pre-partido")
        return True
    except Exception as e:
        logger.error(f"Error actualizando evento con análisis: {e}", exc_info=True)
        return False


# Exportar símbolos públicos
__all__ = [
    "config",
    "ENABLED",
    "get_openai_client",
    "create_agent",
    "update_event_with_prematch_analysis",
]
