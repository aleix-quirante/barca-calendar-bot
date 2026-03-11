# ⚽ Barça Calendar Bot

Un bot automatizado en Python que descarga el calendario oficial de partidos del FC Barcelona y lo sincroniza con tu Google Calendar. Además, se ejecuta diariamente mediante GitHub Actions, manteniendo un registro de actividad y sumando contribuciones ("commits verdes") en tu perfil de GitHub.

## 🌟 Características

- **Sincronización Automática:** Descarga el archivo `.ics` oficial del FC Barcelona y añade/actualiza los eventos en Google Calendar.
- **Automatización Diaria:** Utiliza GitHub Actions para ejecutarse todos los días a las 09:00 AM (UTC) sin intervención manual.
- **Contribuciones en GitHub:** Genera un commit automático en el archivo `log_partidos.md` tras cada ejecución exitosa, manteniendo activa tu gráfica de contribuciones.
- **Fácil Despliegue:** Preparado para funcionar directamente en GitHub Actions usando Secrets.

## 🚀 Requisitos

- Python 3.9 o superior (para ejecución local).
- Una cuenta de Google Cloud Platform (GCP) con la API de Google Calendar habilitada.
- Credenciales OAuth 2.0 de Google (`credentials.json`).

## ⚙️ Configuración y Uso Local

1. **Clonar el repositorio y preparar el entorno:**
   ```bash
   git clone <tu-repositorio>
   cd barca-calendar-bot
   python -m venv .venv
   source .venv/bin/activate  # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Obtener las credenciales de Google API:**
   - Ve a la [Consola de Google Cloud](https://console.cloud.google.com/).
   - Crea un nuevo proyecto y habilita la **Google Calendar API**.
   - Configura la Pantalla de Consentimiento de OAuth (añade tu correo como usuario de prueba).
   - Crea credenciales de tipo **ID de cliente de OAuth** (Aplicación de escritorio).
   - Descarga el archivo JSON de credenciales y guárdalo en la raíz del proyecto con el nombre `credentials.json`.

3. **Generar el Token de Acceso:**
   Ejecuta el script para generar el token inicial. Se abrirá una ventana en tu navegador para que autorices a la aplicación:
   ```bash
   python generar_token.py
   ```
   Esto creará un archivo `token.json` que contiene tu token de acceso y de refresco.

4. **Ejecutar el Bot:**
   ```bash
   python bot_barca.py
   ```
   El script descargará el calendario, sincronizará los eventos con tu Google Calendar y añadirá una línea al archivo `log_partidos.md`.

## ☁️ Configuración en GitHub Actions

Para que el bot se ejecute automáticamente todos los días en la nube:

1. Asegúrate de haber generado el archivo `token.json` localmente (ver paso anterior).
2. Abre el archivo `token.json` y copia todo su contenido.
3. Ve a tu repositorio en GitHub > **Settings** > **Secrets and variables** > **Actions**.
4. Crea un nuevo secreto llamado `GOOGLE_TOKEN_JSON` y pega el contenido de `token.json` como valor.
5. ¡Listo! El bot se ejecutará automáticamente según el cronograma definido en `.github/workflows/run_bot.yml` (todos los días a las 09:00 UTC). También puedes ejecutarlo manualmente desde la pestaña **Actions** usando el botón "Run workflow".

## 📁 Estructura del Proyecto

- `bot_barca.py`: Script principal que hace el fetching del `.ics` y la sincronización con Google Calendar.
- `generar_token.py`: Script auxiliar para realizar la primera autenticación OAuth y obtener el `token.json`.
- `requirements.txt`: Dependencias de Python necesarias.
- `.github/workflows/run_bot.yml`: Configuración del workflow de GitHub Actions.
- `log_partidos.md`: Archivo de registro que se actualiza automáticamente con cada ejecución.

## 📝 Notas Adicionales

- Si cambias la cuenta de Google o los permisos expiran, es posible que necesites borrar el `token.json`, generar uno nuevo localmente y actualizar el secreto en GitHub.
- El ID del calendario de destino por defecto es `primary` (tu calendario principal). Puedes modificar la variable `calendar_id` en `bot_barca.py` si deseas usar un calendario específico.

---
*Força Barça! 🔴🔵*
