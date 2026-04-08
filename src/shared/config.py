"""
Configuración centralizada del Barça Calendar Bot usando pydantic-settings.

Todas las variables de entorno se cargan automáticamente y se validan con Pydantic v2.
"""

from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """
    Configuración principal del bot.

    Las variables de entorno deben prefijarse con 'BARCA_'.
    Ejemplo: BARCA_GOOGLE_CALENDAR_ID='primary'
    """

    model_config = SettingsConfigDict(
        env_prefix="BARCA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Calendar
    google_calendar_id: str = Field(
        default="primary",
        description="ID del calendario de Google (por defecto 'primary' para el calendario principal).",
    )
    google_token_json: str | None = Field(
        default=None,
        description="Contenido del token.json como string (para GitHub Actions). Si es None, se busca token.json en el filesystem.",
    )

    # Fuente de partidos (ICS)
    ics_url: HttpUrl = Field(
        default="https://ics.fixtur.es/v2/fc-barcelona.ics",
        description="URL del calendario ICS del FC Barcelona.",
    )

    # RSS feed for match results (SportsSummaryAgent)
    rss_feed_url: HttpUrl = Field(
        default="https://www.mundodeportivo.com/mvc/feed/rss/futbol/fc-barcelona",
        description="URL del feed RSS con los resultados de partidos del FC Barcelona.",
    )

    # ClubElo API
    clubelo_timeout: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Timeout en segundos para las peticiones a ClubElo.",
    )
    clubelo_cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="TTL en segundos para la caché de probabilidades de ClubElo.",
    )
    clubelo_graceful_degradation: bool = Field(
        default=True,
        description="Si es True, el bot continuará aunque ClubElo falle (usando caché o valores por defecto).",
    )

    # Ollama/LocalAI API (resúmenes automáticos - OpenAI‑compatible)
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="URL base para la API OpenAI‑compatible (Ollama/LocalAI). Ejemplos: 'http://localhost:11434/v1' para local, 'https://your-tunnel.cloudflare.com/v1' para producción.",
    )
    ollama_api_key: str = Field(
        default="ollama",
        description="API Key para Ollama/LocalAI (por defecto 'ollama', puede dejarse vacía para local).",
    )
    ollama_ssl_verify: bool = Field(
        default=True,
        description="Verificar certificados SSL para la conexión a Ollama/LocalAI. Desactivar para túneles Cloudflare con certificados autofirmados.",
    )
    summary_model: str = Field(
        default="qwen3:14b",
        description="Modelo de lenguaje a utilizar para generación de resúmenes.",
    )
    summary_max_tokens: int = Field(
        default=300,
        ge=50,
        le=1000,
        description="Máximo de tokens para la generación de resúmenes.",
    )
    summary_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Temperatura para la generación de resúmenes.",
    )
    summary_enabled: bool = Field(
        default=True,
        description="Activar/desactivar la generación de resúmenes post‑partido.",
    )
    summary_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout en segundos para las peticiones a la API de inferencia.",
    )

    # CalendarCleaner
    retention_days: int = Field(
        default=7,
        ge=0,
        le=365,
        description="Número de días que se conservan los eventos pasados antes de eliminarlos.",
    )
    cleanup_batch_size: int = Field(
        default=50,
        ge=1,
        le=250,
        description="Tamaño del lote para borrado de eventos antiguos.",
    )
    cleanup_dry_run: bool = Field(
        default=False,
        description="Si es True, no se eliminan eventos, solo se muestran en log.",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Nivel de logging.",
    )
    json_logs: bool = Field(
        default=False,
        description="Si es True, los logs se emiten en formato JSON (útil para producción).",
    )

    # Ejecución
    run_frequency_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Frecuencia de ejecución en minutos (usado solo para logging).",
    )

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, v: str) -> str:
        """Asegura que la URL base termine con /v1 si es necesario."""
        v = v.strip()
        if v and not v.endswith("/v1"):
            # Añadir /v1 si no está presente (compatibilidad con OpenAI)
            if v.endswith("/"):
                v = v + "v1"
            else:
                v = v + "/v1"
        return v

    @field_validator("ollama_ssl_verify", mode="before")
    @classmethod
    def parse_empty_ssl(cls, v):
        if v == "" or v is None:
            return False
        return v

    @property
    def is_summary_enabled(self) -> bool:
        """Determina si el módulo de resúmenes está activo."""
        return self.summary_enabled and bool(self.ollama_base_url)


# Instancia global de configuración
settings = BotSettings()


def get_settings() -> BotSettings:
    """
    Devuelve la instancia de configuración (singleton).

    Returns:
        BotSettings: Configuración actual.
    """
    return settings


if __name__ == "__main__":
    # Si se ejecuta este módulo directamente, muestra la configuración cargada.
    import json

    print(json.dumps(settings.model_dump(), indent=2, default=str))
