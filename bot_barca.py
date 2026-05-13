#!/usr/bin/env python3
"""
Barça Calendar Bot - Script de entrada principal.

Este script ejecuta la sincronización del calendario del FC Barcelona con Google Calendar,
añadiendo probabilidades de victoria y resúmenes automáticos.

Ejecución:
    python bot_barca.py

Variables de entorno (prefijo BARCA_):
    - GOOGLE_TOKEN_JSON: Token de Google en formato JSON (para GitHub Actions)
    - OLLAMA_BASE_URL: URL del servicio LLM para resúmenes
    - Y más... ver src/shared/config.py
"""

import os
import sys

# Asegurar que la raíz del proyecto esté en PYTHONPATH para imports de 'src'
os.environ.setdefault("PYTHONPATH", ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api.routes import (
    obtener_eventos_ics,
    obtener_probabilidades_barca,
    obtener_servicio_google,
    sincronizar_eventos,
    registrar_ejecucion,
)
from src.shared.config import settings
from src.sports_summary_agent import create_agent, ENABLED as SUMMARY_ENABLED


def main():
    """
    Punto de entrada principal del bot.

    Ejecuta el flujo completo:
    1. Obtener eventos del ICS del Barça
    2. Obtener probabilidades de ClubElo
    3. Conectar a Google Calendar
    4. Sincronizar eventos
    5. Generar análisis pre-partido (si está activado)
    6. Registrar ejecución
    """
    print("⚽ Iniciando Barça Bot...")

    try:
        # 1. Obtener eventos de FC Barcelona
        eventos = obtener_eventos_ics()

        if not eventos:
            print("⚠️ No se encontraron partidos futuros en el calendario ICS.")
            registrar_ejecucion()
            return

        # 2. Obtener probabilidades
        probabilidades = obtener_probabilidades_barca()

        # 3. Conectar a Google
        servicio = obtener_servicio_google()

        # 4. Sincronizar
        if eventos and servicio:
            sincronizar_eventos(servicio, eventos, probabilidades)

        # 5. Generar análisis pre-partido (si está activado).
        # El agente persiste el análisis directamente en el evento del calendario
        # (idempotente gracias al marcador PREVIA_MARKER).
        if SUMMARY_ENABLED and settings.is_summary_enabled and servicio:
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
                        "ℹ️ No se encontró próximo partido sin previa para generar análisis."
                    )
            except Exception as e:
                print(f"⚠️ Error generando análisis pre-partido: {e}")
        else:
            print("ℹ️ Módulo de resúmenes desactivado o sin configuración.")

        # 6. Actualizar log (mantiene el verde)
        registrar_ejecucion()

    except Exception as e:
        print(f"❌ Error durante el proceso: {e}")
        import traceback

        traceback.print_exc()
        # Registrar error en el log para mantener el workflow activo
        try:
            registrar_ejecucion()
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
