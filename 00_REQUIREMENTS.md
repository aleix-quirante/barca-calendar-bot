# Capa 3 - Requisitos Técnicos de Módulos

**Proyecto:** FC Barcelona Calendar Bot  
**Versión:** 3.1.0  
**Fecha:** 2026-04-04  
**Arquitecto:** Roo (Perfil ARQUITECTO)

---

## 1. CONTEXTO Y OBJETIVOS

Este documento define los requisitos técnicos para la refactorización del bot de calendario del FC Barcelona, elevando la calidad del código, la resiliencia del sistema y la capacidad de mantenimiento. Se establecen tres módulos principales que deben implementarse con **Python 3.12** y **Pydantic v2.10+**, aprovechando las últimas características del lenguaje y las mejores prácticas de validación de datos.

**Objetivos principales:**
- **Optimización de rendimiento:** Reducir la carga en Google Calendar mediante purgado inteligente de eventos pasados.
- **Resiliencia operativa:** Implementar degradación elegante en la obtención de probabilidades de victoria.
- **Valor añadido:** Generar resúmenes automáticos post‑partido usando inferencia local gratuita (nodo Edge Mac Mini) mediante API OpenAI‑compatible.

---

## 2. ESPECIFICACIONES TÉCNICAS GLOBALES

### 2.1 Entorno de Ejecución
- **Python:** Versión 3.12 (mínimo)
- **Gestor de dependencias:** `pip` (compatible con `pyproject.toml`)
- **Entorno virtual:** `venv` o `uv` (recomendado)

### 2.2 Dependencias Principales
```toml
# pyproject.toml (sección [project.dependencies])
python = "^3.12"
pydantic = "^2.10"
requests = "^2.32"
google-api-python-client = "^2.130"
google-auth-oauthlib = "^1.2"
icalendar = "^5.0"
httpx = "^0.27"  # Para clientes HTTP asíncronos opcionales
pydantic-settings = "^2.5"  # Para gestión de configuración
openai = "^1.0"  # Cliente oficial para APIs OpenAI‑compatible (Ollama/LocalAI)
```

### 2.3 Estructura de Módulos
```
src/
├── calendar_cleaner/          # Módulo CalendarCleaner
│   ├── __init__.py
│   ├── cleaner.py
│   ├── models.py
│   └── config.py
├── win_probability_fix/       # Módulo WinProbabilityFix
│   ├── __init__.py
│   ├── clubelo_client.py
│   ├── models.py
│   ├── fallback.py
│   └── gracefull_degradation.py
├── sports_summary_agent/      # Módulo SportsSummaryAgent
│   ├── __init__.py
│   ├── openai_client.py       # Cliente OpenAI‑compatible (configurable via OLLAMA_BASE_URL)
│   ├── summarizer.py
│   ├── models.py
│   └── cost_optimizer.py
└── shared/
    ├── __init__.py
    ├── google_calendar.py
    ├── ics_parser.py
    └── logging_config.py
```

---

## 3. MÓDULO 1: CALENDAR CLEANER

### 3.1 Propósito
Eliminar automáticamente eventos pasados del calendario de Google para mantenerlo optimizado y evitar la acumulación de partidos ya finalizados.

### 3.2 Requisitos Funcionales
- **RF‑CC‑01:** Purgar eventos cuyo `end` sea anterior a la fecha actual menos un umbral configurable (por defecto 7 días).
- **RF‑CC‑02:** Identificar eventos creados por el bot mediante una marca en la descripción (`"Barça Bot"`).
- **RF‑CC‑03:** Soporte para borrado por lotes (batch) para reducir llamadas a la API.
- **RF‑CC‑04:** Log detallado de eventos eliminados (sin exponer datos sensibles).
- **RF‑CC‑05:** Configuración mediante variables de entorno o archivo `.env` (usando `pydantic-settings`).

### 3.3 Requisitos No Funcionales
- **RNF‑CC‑01:** Tiempo máximo de ejecución < 30 segundos para calendarios con hasta 500 eventos.
- **RNF‑CC‑02:** Tolerancia a fallos: si un evento no puede eliminarse, el proceso continúa con los restantes.
- **RNF‑CC‑03:** Uso de tipos fuertes con Pydantic para validar respuestas de la API de Google Calendar.

### 3.4 Modelos de Datos (Pydantic v2)
```python
from pydantic import BaseModel, Field
from datetime import datetime

class CalendarCleanerConfig(BaseModel):
    retention_days: int = Field(default=7, ge=0, le=365)
    batch_size: int = Field(default=50, ge=1, le=250)
    dry_run: bool = Field(default=False)

class GoogleEvent(BaseModel):
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
```

---

## 4. MÓDULO 2: WIN PROBABILITY FIX

### 4.1 Propósito
Refactorizar la obtención de probabilidades de victoria desde ClubElo con degradación elegante (graceful degradation) y manejo robusto de errores.

### 4.2 Requisitos Funcionales
- **RF‑WP‑01:** Consultar la API de ClubElo (`http://api.clubelo.com/Fixtures`) y parsear el CSV.
- **RF‑WP‑02:** Validar que las columnas esperadas (`GD=1`, `GD=-1`, etc.) existen en el CSV; si no, usar columnas alternativas o valores por defecto.
- **RF‑WP‑03:** Calcular la probabilidad de victoria del Barça para cada partido futuro.
- **RF‑WP‑04:** Implementar un sistema de caché en memoria (TTL configurable) para reducir llamadas a la API.
- **RF‑WP‑05:** Degradación elegante: si la API de ClubElo falla, usar la última respuesta cachead; si no hay caché, devolver un diccionario vacío sin romper el flujo principal.
- **RF‑WP‑06:** Reintentos exponenciales con backoff en caso de errores transitorios (HTTP 5xx, timeout).

### 4.3 Requisitos No Funcionales
- **RNF‑WP‑01:** Latencia máxima de consulta: 5 segundos (incluyendo reintentos).
- **RNF‑WP‑02:** Consumo de memoria: < 50 MB para el caché de una temporada completa.
- **RNF‑WP‑03:** Validación estricta de fechas y números mediante Pydantic.

### 4.4 Modelos de Datos (Pydantic v2)
```python
from pydantic import BaseModel, Field, validator
from datetime import date

class ClubEloMatch(BaseModel):
    date: date
    home: str
    away: str
    gd_columns: dict[str, float] = Field(default_factory=dict)

    @validator("gd_columns")
    def validate_probabilities(cls, v):
        total = sum(v.values())
        if total > 1.0:
            raise ValueError("Suma de probabilidades no puede exceder 1.0")
        return v

class WinProbabilityResponse(BaseModel):
    match_date: date
    probability_percent: float = Field(ge=0.0, le=100.0)
    source: Literal["clubelo", "cache", "fallback"]
    cached_until: datetime | None = None
```

---

## 5. MÓDULO 3: SPORTS SUMMARY AGENT

### 5.1 Propósito
Generar automáticamente 3 bullet points de resumen post‑partido utilizando inferencia local gratuita (nodo Edge Mac Mini con Ollama/LocalAI) mediante la librería oficial de OpenAI, añadiendo valor a los eventos del calendario con coste cero.

### 5.2 Requisitos Funcionales
- **RF‑SS‑01:** Detectar partidos que hayan finalizado (fecha de fin anterior a la actual).
- **RF‑SS‑02:** Obtener el resultado del partido desde una fuente confiable (por ejemplo, API de Football‑Data.org o scraping de ESPN).
- **RF‑SS‑03:** Utilizar la librería oficial `openai` con `base_url` extraído de la variable de entorno `OLLAMA_BASE_URL` para apuntar a localhost (desarrollo) o a un túnel de Cloudflare (producción).
- **RF‑SS‑04:** Enviar el resultado a la API OpenAI‑compatible (endpoint `/v1/chat/completions`) con un prompt optimizado para generar **exactamente 3 bullet points** en español, incluyendo contexto del campeonato.
- **RF‑SS‑05:** Almacenar el resumen generado en la descripción del evento de Google Calendar (actualización incremental).
- **RF‑SS‑06:** Implementar un sistema de caché permanente: una vez generado un resumen, no se vuelve a llamar a la API para el mismo partido.
- **RF‑SS‑07:** Soporte para modo "dry‑run" donde se simula la llamada a la API para validar el prompt sin realizar inferencia real.

### 5.3 Requisitos No Funcionales
- **RNF‑SS‑01:** Coste por partido: $0.00 (inferencia local gratuita en nodo Edge).
- **RNF‑SS‑02:** Tiempo de generación: < 15 segundos (incluyendo llamada a la API local/remota).
- **RNF‑SS‑03:** Los bullet points deben ser concisos (máximo 20 palabras cada uno), objetivos y centrados en aspectos tácticos, jugadores destacados y consecuencias en la clasificación.
- **RNF‑SS‑04:** Resiliencia de conexión: el agente debe funcionar tanto con `localhost:11434` (Ollama local) como con un túnel Cloudflare remoto, configurable mediante variable de entorno.

### 5.4 Modelos de Datos (Pydantic v2)
```python
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Literal

class MatchResult(BaseModel):
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    match_date: date
    competition: str = Field(default="La Liga", description="Nombre del campeonato/torneo")

class MatchSummary(BaseModel):
    """Resumen de partido generado por IA con exactamente 3 bullet points y contexto del campeonato."""
    match_id: str
    bullet_points: list[str] = Field(
        min_items=3,
        max_items=3,
        description="Tres puntos clave del partido, cada uno como string separado"
    )
    championship_context: str = Field(
        description="Contexto del campeonato: posición en la tabla, implicaciones, etc."
    )
    generated_at: datetime
    model_used: str = Field(description="Modelo de lenguaje utilizado para la generación")
    inference_source: Literal["local_ollama", "cloudflare_tunnel", "dry_run"]
```

---

## 6. INTEGRACIÓN Y FLUJO DE TRABAJO

### 6.1 Secuencia de Ejecución
1. **CalendarCleaner** se ejecuta primero, eliminando eventos antiguos.
2. **WinProbabilityFix** obtiene probabilidades actualizadas (con fallback a caché si es necesario).
3. El flujo principal descarga los partidos futuros desde el ICS y los sincroniza con Google Calendar, añadiendo las probabilidades.
4. **SportsSummaryAgent** se ejecuta en un segundo plano (por ejemplo, cada 6 horas) para detectar partidos finalizados y añadir resúmenes.

### 6.2 Configuración Unificada
Todos los módulos compartirán una configuración centralizada mediante `pydantic-settings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class BotSettings(BaseSettings):
    google_calendar_id: str = "primary"
    clubelo_timeout: int = 10
    ollama_base_url: str = "http://localhost:11434/v1"  # Para inferencia local
    ollama_api_key: str = "ollama"  # Clave por defecto para Ollama (no requerida realmente)
    summary_enabled: bool = True
    summary_model: str = "llama3.2:3b"  # Modelo por defecto para Ollama/LocalAI

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

---

## 7. CRITERIOS DE ACEPTACIÓN

- [ ] Los tres módulos se implementan como paquetes Python independientes dentro de `src/`.
- [ ] Todas las entradas y salidas de funciones públicas están validadas con modelos Pydantic v2.10+.
- [ ] El bot funciona correctamente con Python 3.12 (verificado con `python -m pytest`).
- [ ] El flujo de degradación elegante en WinProbabilityFix permite que el bot continúe aunque ClubElo esté caído.
- [ ] SportsSummaryAgent genera resúmenes con coste cero utilizando el nodo Edge Mac Mini.
- [ ] CalendarCleaner reduce el número de eventos en el calendario a solo los futuros + los de los últimos 7 días.

---

## 8. NOTAS DE IMPLEMENTACIÓN

- **Migración progresiva:** Los nuevos módulos pueden coexistir con el código legacy mientras se prueba su funcionamiento.
- **Logging estructurado:** Usar `structlog` o `logging` con formato JSON para facilitar el monitoreo en GitHub Actions.
- **Tests:** Cada módulo debe incluir tests unitarios (cobertura >80%) y tests de integración con las APIs reales (modo "dry‑run").
- **Infraestructura Edge:** El nodo Mac Mini ejecutará Ollama/LocalAI expuesto via `localhost:11434` en desarrollo y via túnel Cloudflare en producción. La variable `OLLAMA_BASE_URL` permitirá cambiar entre ambos entornos sin modificar código.

---

*Documento aprobado por el arquitecto para su implementación en la Capa 3.*