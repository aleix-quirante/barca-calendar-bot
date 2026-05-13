URL_CALENDARIO = "https://ics.fixtur.es/v2/fc-barcelona.ics"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

from fastapi import APIRouter
import csv
import json
import os
from datetime import UTC, datetime
from io import StringIO
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from icalendar import Calendar
from src.calendar_cleaner.cleaner import create_cleaner
from src.calendar_cleaner.models import CalendarCleanerConfig
from src.shared.config import settings
from src.sports_summary_agent import create_agent

router = APIRouter()


def obtener_eventos_ics():
    """Descarga y parsea el archivo ICS del Barça"""
    print(f"Descargando calendario desde {URL_CALENDARIO}..")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(URL_CALENDARIO, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error descargando ICS: {e}")
        return []

    if response.status_code != 200:
        print(f"Error al descargar ICS: {response.status_code}")
        return []

    cal = Calendar.from_ical(response.content)
    eventos = []

    for component in cal.walk():
        if component.name == "VEVENT":
            # Extraer detalles del evento
            summary = str(component.get("summary"))
            dtstart_prop = component.get("dtstart")
            if not dtstart_prop:
                continue

            dtstart = dtstart_prop.dt

            # Omitir eventos con horario no confirmado (todo el día o 'TBC'/'TBD')
            if (
                type(dtstart) is not datetime
                or "TBC" in summary.upper()
                or "TBD" in summary.upper()
            ):
                continue

            dtend = component.get("dtend").dt if component.get("dtend") else None
            location = str(component.get("location", "Por definir"))
            uid = str(component.get("uid"))

            # Añadir emoji de pelota si no lo tiene
            if not summary.startswith("⚽"):
                summary = "⚽ " + summary.strip()

            # Solo guardamos eventos futuros
            now_utc = datetime.now(UTC)
            if hasattr(dtstart, "tzinfo") and dtstart.tzinfo is not None:
                diff = dtstart - now_utc
            else:
                # Si es naive, asumimos UTC
                diff = dtstart.replace(tzinfo=UTC) - now_utc

            # Guardamos solo eventos futuros (que no hayan empezado)
            if diff.total_seconds() > 0:
                eventos.append(
                    {
                        "summary": summary,
                        "start": dtstart,
                        "end": dtend,
                        "location": location,
                        "uid": uid,
                    }
                )

    print(f"Se encontraron {len(eventos)} partidos confirmados en el ICS.")
    return eventos


def obtener_probabilidades_barca():
    """Obtiene las probabilidades de victoria del Barça para los próximos partidos usando ClubElo (Sin API Key)"""
    print("Consultando probabilidades en ClubElo...")
    url = "http://api.clubelo.com/Fixtures"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error descargando ClubElo: {e}")
        return {}

    probabilidades = {}
    csv_reader = csv.DictReader(StringIO(response.text))

    for row in csv_reader:
        home = row.get("Home", "")
        away = row.get("Away", "")
        date = row.get("Date", "")

        if home == "Barcelona" or away == "Barcelona":
            try:
                prob_home_win = sum(
                    float(row[col])
                    for col in ["GD=1", "GD=2", "GD=3", "GD=4", "GD=5", "GD>5"]
                )
                prob_away_win = sum(
                    float(row[col])
                    for col in ["GD=-1", "GD=-2", "GD=-3", "GD=-4", "GD=-5", "GD<-5"]
                )

                if home == "Barcelona":
                    prob_barca = prob_home_win
                else:
                    prob_barca = prob_away_win

                probabilidades[date] = round(prob_barca * 100, 1)
            except Exception:
                continue

    return probabilidades


def obtener_servicio_google():
    """Autentica y devuelve el servicio de Google Calendar"""
    creds = None

    # En GitHub Actions, usaremos una variable de entorno para el token.
    # Localmente, usaremos el archivo token.json.
    if "GOOGLE_TOKEN_JSON" in os.environ:
        token_info = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception(
                "No hay credenciales válidas de Google. Ejecuta generar_token.py localmente o configura el secreto en GitHub."
            )

    return build("calendar", "v3", credentials=creds)


def limpiar_eventos_viejos(servicio, calendar_id):
    """Busca y elimina eventos del bot que ya hayan finalizado para mantener el calendario limpio."""
    print("Buscando eventos antiguos para eliminar...")
    try:
        # Configuración del cleaner basada en settings globales
        config = CalendarCleanerConfig(
            retention_days=settings.retention_days,
            batch_size=settings.cleanup_batch_size,
            dry_run=settings.cleanup_dry_run,
            filter_description="Barça Bot",
        )
        cleaner = create_cleaner(servicio, calendar_id=calendar_id, config=config)
        stats = cleaner.run()
        print(
            f"✅ Limpieza de eventos antiguos completada. "
            f"Escaneados: {stats.total_scanned}, "
            f"elegibles: {stats.eligible_for_deletion}, "
            f"eliminados: {stats.deleted}, "
            f"errores: {stats.errors}"
        )
    except Exception as e:
        print(f"Error al limpiar eventos viejos: {e}")


def _merge_description(current_desc: str, probability: float | None) -> str:
    """
    Fusiona la descripción actual con la probabilidad de victoria.

    Preserva cualquier bloque de previa (🔮 **PREVIA DEL PARTIDO**) al inicio
    y actualiza/inserta la línea de probabilidad después del bloque de previa
    pero antes del resto del contenido.

    Args:
        current_desc: Descripción actual del evento.
        probability: Probabilidad de victoria (0-100) o None si no hay datos.

    Returns:
        Nueva descripción fusionada.
    """
    if not current_desc:
        current_desc = ""

    # Separar el bloque de previa si existe
    previa_marker = "🔮 **PREVIA DEL PARTIDO**"
    probability_marker = "📈 Probabilidad de victoria del Barça:"

    # Buscar el marcador de previa
    previa_index = current_desc.find(previa_marker)
    has_previa = previa_index != -1

    if has_previa:
        # Encontrar el final del bloque de previa (buscar "---" después del marcador)
        # Asumimos que el bloque de previa termina con "---" en una línea separada
        rest_start = current_desc.find("\n---\n", previa_index)
        if rest_start == -1:
            # Si no hay separador claro, tomamos todo después del marcador como resto
            previa_block = current_desc[previa_index:]
            rest = ""
        else:
            previa_block = current_desc[previa_index:rest_start]
            rest = current_desc[rest_start + 5 :]  # +5 para saltar "\n---\n"
    else:
        previa_block = ""
        rest = current_desc

    # Eliminar cualquier línea de probabilidad existente en el resto
    # (para evitar duplicados)
    lines = rest.split("\n")
    filtered_lines = []
    for line in lines:
        if probability_marker not in line:
            filtered_lines.append(line)
    rest = "\n".join(filtered_lines).strip()

    # Construir la nueva descripción
    parts = []
    if has_previa:
        parts.append(previa_block)
        parts.append("")  # línea vacía

    # Añadir probabilidad si está disponible
    if probability is not None:
        parts.append(
            f"📈 Probabilidad de victoria del Barça: {probability}% (según ClubElo)"
        )

    # Añadir el resto del contenido
    if rest:
        if parts:  # Si ya hay contenido, añadir separador
            parts.append("---")
            parts.append("")
        parts.append(rest)

    # Si no hay nada, mantener el texto base
    if not parts:
        parts.append("Sincronizado automáticamente (Barça Bot)")

    return "\n".join(parts).strip()


def sincronizar_eventos(servicio, eventos, probabilidades):
    """Sincroniza los eventos extraídos a Google Calendar"""
    calendar_id = "primary"  # O puedes poner el ID de un calendario específico

    # Primero limpiamos los eventos que tienen más de dos semanas
    limpiar_eventos_viejos(servicio, calendar_id)

    print("Sincronizando con Google Calendar...")
    for partido in eventos:
        # Formatear la fecha para Google API
        # asumiendo que el datetime viene en un formato correcto o necesita .isoformat()
        try:
            # Los dtstart de icalendar pueden ser 'date' o 'datetime'
            start_date_obj = partido["start"]
            start_iso = start_date_obj.isoformat()
            if type(start_date_obj) is not datetime:
                start_iso = start_date_obj.isoformat()  # Si es tipo date

            # Obtener el día del partido en formato YYYY-MM-DD para buscar la probabilidad
            fecha_str = (
                start_date_obj.strftime("%Y-%m-%d")
                if hasattr(start_date_obj, "strftime")
                else str(start_date_obj)[:10]
            )

            end_iso = partido["end"].isoformat() if partido["end"] else start_iso

            # Formato requerido por Google
            start_body = (
                {"dateTime": start_iso} if "T" in start_iso else {"date": start_iso}
            )
            end_body = {"dateTime": end_iso} if "T" in end_iso else {"date": end_iso}

            # Obtener probabilidad para esta fecha
            probability = (
                probabilidades.get(fecha_str) if fecha_str in probabilidades else None
            )

            # Usar 'list' con iCalUID para ver si ya existe y actualizar en lugar de solo importar
            busqueda = (
                servicio.events()
                .list(calendarId=calendar_id, iCalUID=partido["uid"])
                .execute()
            )
            existentes = busqueda.get("items", [])

            if existentes:
                # Si existe, obtenemos la descripción actual para fusionar
                event_id = existentes[0]["id"]
                current_event = (
                    servicio.events()
                    .get(calendarId=calendar_id, eventId=event_id)
                    .execute()
                )
                current_description = current_event.get("description", "") or ""

                # Fusionar descripción preservando previa
                new_description = _merge_description(current_description, probability)

                print(f"Actualizando evento existente: {partido['summary']}")

                # Crear cuerpo de actualización
                update_body = {
                    "summary": partido["summary"],
                    "location": partido["location"],
                    "description": new_description,
                    "start": start_body,
                    "end": end_body,
                }

                try:
                    servicio.events().update(
                        calendarId=calendar_id, eventId=event_id, body=update_body
                    ).execute()
                except HttpError as e:
                    # Si el error es de secuencia, borramos y recreamos
                    if "Invalid sequence" in str(e) or "sequence" in str(e).lower():
                        print(
                            f"Error de secuencia detectado, recreando evento: {partido['summary']}"
                        )
                        servicio.events().delete(
                            calendarId=calendar_id, eventId=event_id
                        ).execute()
                        # Para recrear, usamos descripción base con probabilidad
                        base_desc = "Sincronizado automáticamente (Barça Bot)"
                        if probability is not None:
                            base_desc += f"\n\n📈 Probabilidad de victoria del Barça: {probability}% (según ClubElo)"

                        evento_cuerpo = {
                            "summary": partido["summary"],
                            "location": partido["location"],
                            "description": base_desc,
                            "start": start_body,
                            "end": end_body,
                            "iCalUID": partido["uid"],
                            "sequence": int(datetime.now().timestamp() % 1000000),
                            "updated": datetime.now(UTC)
                            .isoformat()
                            .replace("+00:00", "Z"),
                        }
                        servicio.events().insert(
                            calendarId=calendar_id, body=evento_cuerpo
                        ).execute()
                        print(f"Evento recreado: {partido['summary']}")
                    else:
                        raise
            else:
                # Si no existe, lo insertamos con descripción base
                print(f"Insertando nuevo evento: {partido['summary']}")
                base_desc = "Sincronizado automáticamente (Barça Bot)"
                if probability is not None:
                    base_desc += f"\n\n📈 Probabilidad de victoria del Barça: {probability}% (según ClubElo)"

                evento_cuerpo = {
                    "summary": partido["summary"],
                    "location": partido["location"],
                    "description": base_desc,
                    "start": start_body,
                    "end": end_body,
                    "iCalUID": partido["uid"],
                    "sequence": int(datetime.now().timestamp() % 1000000),
                    "updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
                servicio.events().insert(
                    calendarId=calendar_id, body=evento_cuerpo
                ).execute()

        except Exception as e:
            print(f"Error sincronizando {partido['summary']}: {e}")

    print("✅ Sincronización completada.")


def registrar_ejecucion():
    """Mantiene el registro verde en GitHub (Fase 1)"""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("log_partidos.md", "a") as f:
        f.write(f"\n- ✅ Actualizado el {ahora}: Calendario sincronizado con Google.")
    print("¡Registro de Markdown actualizado!")


@router.post("/api/v1/calendar/sync")
async def sync_calendar():
    print("⚽ Iniciando Barça Bot...")
    try:
        # 1. Obtener eventos de FC Barcelona
        eventos = obtener_eventos_ics()
        # 2. Obtener probabilidades
        probabilidades = obtener_probabilidades_barca()
        # 3. Conectar a Google
        servicio = obtener_servicio_google()
        # 4. Sincronizar
        if eventos and servicio:
            sincronizar_eventos(servicio, eventos, probabilidades)
        # 5. Generar análisis pre-partido (si está activado).
        # El agente persiste el análisis directamente en el evento del calendario.
        if settings.is_summary_enabled and servicio:
            print("🔮 Generando análisis pre-partido del próximo partido...")
            try:
                agent = create_agent(cache_enabled=True, calendar_service=servicio)
                analyses = agent.run()
                if analyses:
                    print(
                        f"✅ Generado y persistido análisis pre-partido para "
                        f"{len(analyses)} partido(s)."
                    )
                else:
                    print(
                        "ℹ️  No se encontró próximo partido sin previa para generar análisis."
                    )
            except Exception as e:
                print(f"⚠️  Error generando análisis pre-partido: {e}")
        # 6. Actualizar log (mantiene el verde)
        registrar_ejecucion()
    except Exception as e:
        print(f"❌ Error durante el proceso: {e}")
    finally:
        # 6. Actualizar log (mantiene el verde)
        registrar_ejecucion()
    return {"status": "success"}
