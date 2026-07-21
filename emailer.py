import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import database as db


def _render_template(template: str, contacto: dict) -> str:
    replacements = {
        "nombre": contacto.get("nombre", ""),
        "apellido": contacto.get("apellido", ""),
        "cargo": contacto.get("cargo", ""),
        "empresa": contacto.get("empresa_nombre", ""),
        "email": contacto.get("email", ""),
    }
    result = template
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


def enviar_email(destinatario: str, asunto: str, cuerpo_html: str) -> tuple[bool, str]:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_name = os.environ.get("SMTP_FROM_NAME", "Diego Ostertag")
    from_email = os.environ.get("SMTP_FROM_EMAIL", user)

    if not host or not user:
        return False, "SMTP no configurado. Agrega las variables de entorno SMTP_*"

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = destinatario
    msg["Subject"] = asunto

    text_body = re.sub(r"<[^>]+>", "", cuerpo_html)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)


def enviar_campana(campana_id: int) -> dict:
    campana = db.obtener_campana(campana_id)
    if not campana:
        return {"error": "Campana no encontrada"}

    destinatarios = db.listar_destinatarios(campana_id)
    pendientes = [d for d in destinatarios if d["estado"] == "pendiente"]

    enviados = 0
    errores = 0

    for dest in pendientes:
        contacto = db.obtener_contacto(dest["contacto_id"])
        if not contacto or not contacto.get("email"):
            db.marcar_email_enviado(dest["id"], "error", "Sin email")
            errores += 1
            continue

        asunto = _render_template(campana["asunto"], contacto)
        cuerpo = _render_template(campana["cuerpo"], contacto)

        ok, error = enviar_email(contacto["email"], asunto, cuerpo)
        if ok:
            db.marcar_email_enviado(dest["id"], "enviado")
            enviados += 1
        else:
            db.marcar_email_enviado(dest["id"], "error", error)
            errores += 1

    return {"enviados": enviados, "errores": errores, "total": len(pendientes)}
