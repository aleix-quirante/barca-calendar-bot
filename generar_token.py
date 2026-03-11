import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Permisos necesarios: poder leer y escribir eventos en Google Calendar
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main():
    """Genera el token.json a partir de credentials.json"""
    creds = None

    # El archivo token.json almacena los tokens de acceso y actualización del usuario.
    # Se crea automáticamente cuando el flujo de autorización se completa por primera vez.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # Si no hay credenciales (válidas) disponibles, pide al usuario iniciar sesión.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                print("❌ ERROR: No se encontró 'credentials.json'.")
                print("Descárgalo desde Google Cloud Console y ponlo en esta carpeta.")
                return

            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Guarda las credenciales para la próxima vez
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            print("\n✅ 'token.json' generado correctamente. ¡No lo subas a GitHub!")


if __name__ == "__main__":
    main()
