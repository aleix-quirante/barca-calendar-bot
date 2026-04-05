"""
Sports Summary Agent – Módulo para generar resúmenes automáticos post‑partido.

Utiliza la API OpenAI‑compatible (Ollama/LocalAI) configurada en `src.shared.config`.
"""

from typing import Optional
import logging

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


def generate_summary(
    match_result: dict,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Genera un resumen de 3 bullet points para un partido dado.

    Args:
        match_result: Diccionario con los datos del partido (equipos, resultado, etc.)
        model: Modelo a usar (por defecto settings.summary_model)
        temperature: Temperatura de generación (por defecto settings.summary_temperature)
        max_tokens: Máximo de tokens (por defecto settings.summary_max_tokens)

    Returns:
        str: Resumen formateado en markdown.

    Raises:
        RuntimeError: Si el módulo está desactivado o la API falla.
    """
    if not ENABLED:
        raise RuntimeError("SportsSummaryAgent está desactivado.")

    # Esta es una implementación de ejemplo que debe ser completada
    # con la lógica real de llamada a la API.
    # Por ahora devuelve un placeholder.
    logger.warning(
        "generate_summary no está implementado completamente; "
        "devuelve un resumen de ejemplo."
    )
    return (
        "⚽ **Resumen generado automáticamente**\n"
        "• El Barça demostró un buen control del balón en la primera mitad.\n"
        "• La defensa mantuvo la solidez ante los contraataques rivales.\n"
        "• Con esta victoria, el equipo se afianza en la parte alta de la tabla."
    )


def update_event_with_summary(
    calendar_service, event_id: str, summary_text: str
) -> bool:
    """
    Actualiza la descripción de un evento de Google Calendar con el resumen generado.

    Args:
        calendar_service: Servicio de Google Calendar autenticado.
        event_id: ID del evento a actualizar.
        summary_text: Texto del resumen a insertar.

    Returns:
        bool: True si la actualización fue exitosa.
    """
    # Implementación pendiente (se integrará con google_calendar.py)
    logger.warning("update_event_with_summary no implementado aún.")
    return False


# Exportar símbolos públicos
__all__ = [
    "config",
    "ENABLED",
    "get_openai_client",
    "generate_summary",
    "update_event_with_summary",
]
