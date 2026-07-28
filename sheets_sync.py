"""Sincroniza Empresas y Contactos del CRM hacia un Google Sheet.

Requiere dos variables de entorno:
  GOOGLE_SERVICE_ACCOUNT_JSON - contenido completo del JSON de la cuenta de servicio
  GOOGLE_SHEET_ID             - el ID de la hoja (de la URL de Google Sheets)

La hoja debe estar compartida (permiso Editor) con el email de la cuenta de
servicio (termina en @...iam.gserviceaccount.com, esta dentro del JSON).
"""
import os
import json
import gspread
from google.oauth2.service_account import Credentials
import database as db

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

EMPRESAS_HEADERS = ["id", "nombre", "rut", "industria", "tamano", "sitio_web",
                     "direccion", "ciudad", "fuente", "notas", "created_at"]
CONTACTOS_HEADERS = ["id", "empresa_nombre", "nombre", "apellido", "cargo", "email",
                      "telefono", "linkedin_url", "fuente", "puntaje_ia", "razon_ia", "notas", "created_at"]
EVALUACIONES_HEADERS = ["id", "empresa", "rubro", "nombre", "apellido", "cargo", "email",
                         "puntaje_ia", "razon_ia", "calificado", "created_at"]
OPORTUNIDADES_HEADERS = ["id", "fuente", "query", "nombre", "organismo", "region", "monto",
                          "estado", "fecha", "url_ficha", "created_at"]


def _cliente():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not raw or not sheet_id:
        return None, None
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds), sheet_id


def sincronizar() -> dict:
    """Sobreescribe las hojas 'Empresas', 'Contactos' (solo lo que califico) y
    'Todos_Evaluados' (log completo, califique o no) con el estado actual del CRM.

    ponytail: reescribe todo en vez de hacer upsert incremental fila por fila.
    A la escala de este CRM (cientos/miles de filas, no millones) es mas simple
    y no hay riesgo de filas duplicadas o desincronizadas. El deduplicado real
    ya ocurre en la base de datos (por email), aca solo se refleja.
    """
    try:
        gc, sheet_id = _cliente()
        if not gc:
            return {"error": "GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_SHEET_ID no configurados"}

        sh = gc.open_by_key(sheet_id)
        empresas = db.listar_empresas(limit=100000)
        contactos = db.listar_contactos(limit=100000)
        evaluaciones = db.listar_evaluaciones_ia(limit=100000)
        oportunidades = db.listar_oportunidades(limit=100000)
        _escribir_hoja(sh, "Empresas", EMPRESAS_HEADERS, empresas)
        _escribir_hoja(sh, "Contactos", CONTACTOS_HEADERS, contactos)
        _escribir_hoja(sh, "Todos_Evaluados", EVALUACIONES_HEADERS, evaluaciones)
        _escribir_hoja(sh, "Oportunidades", OPORTUNIDADES_HEADERS, oportunidades)
    except Exception as e:
        return {"error": f"Error sincronizando con Google Sheets: {e}"}

    return {"empresas": len(empresas), "contactos": len(contactos), "evaluados": len(evaluaciones),
            "oportunidades": len(oportunidades)}


def _escribir_hoja(sh, nombre, headers, filas):
    try:
        ws = sh.worksheet(nombre)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=nombre, rows=max(len(filas) + 1, 100), cols=len(headers))

    valores = [headers] + [[str(f.get(h, "") if f.get(h) is not None else "") for h in headers] for f in filas]
    ws.update(valores)
