"""Motor de prospeccion automatica para CRM Diego.
Busca contactos en multiples fuentes, deduplica, y filtra con IA.
"""
import os
import asyncio
import httpx
import json
import database as db
import scraper


PRODUCTOS_DIEGO = """Repuestos industriales y forestales: rodamientos, sellos mecanicos,
correas industriales, filtros, acoplamientos, cadenas, sprockets, piñones,
mangueras hidraulicas, bombas, motores electricos, reductores de velocidad."""

CARGOS_RELEVANTES = [
    "compras", "adquisiciones", "abastecimiento", "procurement", "purchasing",
    "mantenimiento", "maintenance", "operaciones", "operations",
    "supply chain", "logistica", "logistics", "planta", "plant",
    "gerente", "jefe", "director", "manager", "head", "chief",
]

# ponytail: seed de grandes empresas industriales chilenas por rubro, para
# precargar "Empresas Target" con un clic. Dominios a validar/corregir por
# Diego (si un dominio esta mal, Hunter simplemente devuelve 0 contactos).
EMPRESAS_CHILE = {
    "Forestal": [
        ("Arauco", "arauco.cl"),
        ("CMPC", "cmpc.cl"),
        ("Masisa", "masisa.com"),
        ("Forestal Mininco", "mininco.cl"),
        ("Volterra", "volterra.cl"),
    ],
    "Mineria": [
        ("Codelco", "codelco.cl"),
        ("SQM", "sqm.com"),
        ("Antofagasta Minerals", "aminerals.cl"),
        ("Collahuasi", "collahuasi.cl"),
        ("Anglo American Chile", "angloamerican.cl"),
        ("CAP Mineria", "cap.cl"),
        ("Minera Los Pelambres", "aminerals.cl"),
        ("BHP Escondida", "bhp.com"),
        ("Kinross Chile", "kinross.com"),
        ("Teck Resources Chile", "teck.com"),
        ("Albemarle Chile", "albemarle.com"),
    ],
    "Energia": [
        ("ENAP", "enap.cl"),
        ("Enel Chile", "enel.cl"),
        ("Colbun", "colbun.cl"),
        ("AES Andes", "aesandes.com"),
        ("Engie Chile", "engie-energia.cl"),
        ("Transelec", "transelec.cl"),
        ("Grupo Saesa", "saesa.cl"),
        ("Statkraft Chile", "statkraft.cl"),
    ],
    "Pesca y Acuicultura": [
        ("Camanchaca", "camanchaca.cl"),
        ("Multiexport Foods", "multiexportfoods.com"),
        ("Blumar", "blumar.com"),
        ("Salmones Austral", "salmonesaustral.cl"),
        ("Cermaq Chile", "cermaq.com"),
        ("Australis Seafoods", "australisseafoods.com"),
    ],
    "Alimentos y Bebidas": [
        ("Carozzi", "carozzi.cl"),
        ("CCU", "ccu.cl"),
        ("Embotelladora Andina", "koandina.com"),
        ("Watts", "watts.cl"),
        ("Agrosuper", "agrosuper.com"),
        ("Nestle Chile", "nestle.cl"),
        ("Ariztia", "ariztia.com"),
        ("Iansa", "iansa.cl"),
    ],
    "Transporte y Logistica": [
        ("SAAM", "saam.com"),
        ("Ultramar", "ultramar.com"),
        ("Agunsa", "agunsa.com"),
        ("CCNI", "ccni.cl"),
        ("Puerto Ventanas", "puertoventanas.cl"),
    ],
    "Construccion e Industrial": [
        ("Melon", "melon.cl"),
        ("Sigdo Koppers", "sigdokoppers.cl"),
        ("Cementos Bio Bio", "cbb.cl"),
        ("Besalco", "besalco.cl"),
        ("Echeverria Izquierdo", "echeverriaizquierdo.cl"),
    ],
}


def listar_rubros() -> list[dict]:
    return [{"rubro": r, "total": len(v)} for r, v in EMPRESAS_CHILE.items()]


def empresas_por_rubro(rubros: list[str]) -> list[dict]:
    resultado = []
    for r in rubros:
        for nombre, dominio in EMPRESAS_CHILE.get(r, []):
            resultado.append({"nombre": nombre, "dominio": dominio, "rubro": r})
    return resultado


# ponytail: sin ANTHROPIC_API_KEY no hay como generar un match producto/email
# realmente inteligente, asi que esto es una plantilla por rubro. Funciona hoy,
# sin depender de ninguna API paga. Si despues se agrega la key, se puede pedirle
# a filtrar_con_ia que genere esto mismo pero personalizado con mas contexto.
RUBRO_PRODUCTOS = {
    "Forestal": "correas transportadoras, rodamientos y mangueras hidraulicas para cosechadoras y equipos forestales",
    "Mineria": "rodamientos, sellos mecanicos y reductores de velocidad para chancadores y correas transportadoras",
    "Energia": "acoplamientos, bombas y motores electricos para plantas de generacion",
    "Pesca y Acuicultura": "bombas, sellos mecanicos y motores electricos para plantas de proceso",
    "Transporte y Logistica": "rodamientos, correas industriales y reductores de velocidad para equipos de manejo de materiales",
    "Construccion e Industrial": "cadenas, piñones y rodamientos para maquinaria pesada",
    "Alimentos y Bebidas": "correas transportadoras, bombas, motores electricos y sellos mecanicos para lineas de proceso y envasado",
}
PRODUCTOS_DEFAULT = "rodamientos, sellos mecanicos, correas industriales y repuestos para mantenimiento industrial"


def sugerir_producto(rubro: str) -> str:
    return RUBRO_PRODUCTOS.get(rubro, PRODUCTOS_DEFAULT)


def armar_email_sugerido(contacto: dict, rubro: str) -> dict:
    """Arma un borrador de correo para que Diego lo revise, edite y envie el mismo."""
    nombre = contacto.get("nombre", "")
    empresa = contacto.get("empresa", "")
    productos = sugerir_producto(rubro)
    asunto = f"Repuestos industriales para {empresa}" if empresa else "Repuestos industriales para su operacion"
    saludo = f"Estimado/a {nombre}," if nombre else "Estimado/a,"
    rubro_txt = rubro.lower() if rubro else "industrial"
    cuerpo = (
        f"{saludo}\n\n"
        f"Mi nombre es Diego Ostertag. Importamos y distribuimos repuestos industriales "
        f"({productos}) para empresas del rubro {rubro_txt} en Chile.\n\n"
        f"Nos gustaria conversar sobre como podemos apoyar el abastecimiento de repuestos en "
        f"{empresa or 'su empresa'}.\n\n"
        f"Quedo atento a su respuesta.\n\nSaludos,\nDiego Ostertag"
    )
    return {"asunto": asunto, "cuerpo": cuerpo}


async def filtrar_con_ia(contactos: list[dict]) -> list[dict]:
    """Puntua TODOS los contactos con Claude API (no descarta ninguno).
    El llamador decide el corte (>=50) para saber quien califica."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # ponytail: sin API key, filtro basico por cargo
        return _filtro_basico(contactos)

    batch_size = 20
    resultados = []
    for i in range(0, len(contactos), batch_size):
        batch = contactos[i:i + batch_size]
        batch_text = "\n".join(
            f"{j+1}. {c.get('nombre','')} {c.get('apellido','')} - {c.get('cargo','')} en {c.get('empresa','')} ({c.get('email','')})"
            for j, c in enumerate(batch)
        )

        prompt = f"""Eres un asistente de ventas B2B. Diego vende repuestos industriales y forestales en Chile:
{PRODUCTOS_DIEGO}

Analiza estos contactos y devuelve un JSON array con TODOS ellos, sin excepcion (no descartes
ninguno). Para cada uno, evalua si por su cargo/empresa podria comprar estos productos y devuelve:
{{"idx": numero, "puntaje": 1-100, "razon": "explicacion breve, sea alto o bajo el puntaje"}}

Contactos:
{batch_text}

Responde SOLO el JSON array con los {len(batch)} contactos, sin explicacion."""

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code != 200:
                    return _filtro_basico(contactos)

                text = resp.json()["content"][0]["text"].strip()
                # ponytail: extraer JSON del response
                if "```" in text:
                    text = text.split("```")[1].replace("json", "", 1).strip()
                calificados = json.loads(text)

                for cal in calificados:
                    idx = cal.get("idx", 0) - 1
                    if 0 <= idx < len(batch):
                        c = batch[idx].copy()
                        c["puntaje_ia"] = cal.get("puntaje", 0)
                        c["razon_ia"] = cal.get("razon", "")
                        resultados.append(c)
            except Exception:
                resultados.extend(_filtro_basico(batch))

    return resultados


def _filtro_basico(contactos: list[dict]) -> list[dict]:
    """Filtro sin IA: por cargo relevante. Puntua TODOS, no descarta ninguno."""
    resultados = []
    for c in contactos:
        cargo = (c.get("cargo", "") or "").lower()
        puntaje = 0
        razon = "Cargo no coincide con palabras clave de compras/mantenimiento"
        for kw in CARGOS_RELEVANTES:
            if kw in cargo:
                puntaje = 60
                razon = f"Cargo relevante: {c.get('cargo', '')}"
                break
        c["puntaje_ia"] = puntaje
        c["razon_ia"] = razon
        resultados.append(c)
    return resultados


async def ejecutar_prospeccion() -> dict:
    """Ejecuta un ciclo completo de prospeccion."""
    config = db.obtener_config_prospeccion()
    empresas_target = config.get("empresas_target", [])
    keywords = config.get("keywords", [])

    if not empresas_target and not keywords:
        return {"error": "Configura empresas y keywords primero", "nuevos": 0}

    contactos_raw = []
    resumen = {"hunter": 0, "mercadopublico": 0, "web": 0, "total_raw": 0, "nuevos": 0, "calificados": 0}

    # 1. Hunter.io — buscar por dominio
    for emp in empresas_target:
        dominio = emp.get("dominio", "")
        if not dominio:
            continue
        try:
            data = await scraper.buscar_hunter(dominio)
            for c in data.get("contacts", []):
                c["empresa"] = data.get("empresa", emp.get("nombre", dominio))
                c["dominio"] = dominio
                c["rubro"] = emp.get("rubro", "")
                c["fuente_prospeccion"] = "hunter"
                contactos_raw.append(c)
                resumen["hunter"] += 1
        except Exception:
            pass

    # 2. Mercado Publico — buscar licitaciones
    for kw in keywords:
        try:
            licitaciones = (await scraper.buscar_mercadopublico(kw)).get("resultados", [])
            for lic in licitaciones:
                contactos_raw.append({
                    "nombre": lic.get("organismo", ""),
                    "apellido": "",
                    "cargo": "Licitacion",
                    "email": "",
                    "empresa": lic.get("organismo", ""),
                    "fuente_prospeccion": "mercadopublico",
                    "licitacion": lic.get("nombre", ""),
                    "codigo_licitacion": lic.get("codigo", ""),
                    "monto": lic.get("monto", 0),
                })
                resumen["mercadopublico"] += 1
        except Exception:
            pass

    # 3. Scraping web de empresas target
    for emp in empresas_target:
        url = emp.get("sitio_web", "")
        if not url:
            url = f"https://{emp.get('dominio', '')}"
        if not url or url == "https://":
            continue
        try:
            info = await scraper.scrape_sitio_empresa(url)
            for email in info.get("emails", []):
                parts = email.split("@")
                contactos_raw.append({
                    "nombre": parts[0] if parts else "",
                    "apellido": "",
                    "cargo": "",
                    "email": email,
                    "empresa": emp.get("nombre", ""),
                    "dominio": emp.get("dominio", ""),
                    "rubro": emp.get("rubro", ""),
                    "fuente_prospeccion": "web",
                })
                resumen["web"] += 1
        except Exception:
            pass

    resumen["total_raw"] = len(contactos_raw)

    # 4. Deduplicar contra DB existente
    nuevos = []
    for c in contactos_raw:
        email = c.get("email", "").strip()
        if not email and not c.get("nombre"):
            continue
        if email and db.contacto_existe(email=email):
            continue
        nuevos.append(c)

    resumen["nuevos"] = len(nuevos)

    if not nuevos:
        db.log_scraping("prospeccion_auto", f"empresas:{len(empresas_target)} keywords:{len(keywords)}", 0)
        return resumen

    # 5. Filtrar con IA (puntua a todos, el corte de calificacion se aplica aca)
    evaluados = await filtrar_con_ia(nuevos)
    calificados = [c for c in evaluados if c.get("puntaje_ia", 0) >= 50]
    resumen["calificados"] = len(calificados)
    # ponytail: se manda la lista completa (calificados y descartados) para que
    # se pueda auditar el filtro en el frontend/exportar a CSV, no solo confiar
    # ciegamente en el corte de la IA.
    resumen["evaluados"] = [
        {"nombre": c.get("nombre", ""), "apellido": c.get("apellido", ""), "cargo": c.get("cargo", ""),
         "email": c.get("email", ""), "empresa": c.get("empresa", ""), "rubro": c.get("rubro", ""),
         "puntaje_ia": c.get("puntaje_ia", 0), "razon_ia": c.get("razon_ia", ""),
         "calificado": c.get("puntaje_ia", 0) >= 50}
        for c in evaluados
    ]

    # 6. Guardar en DB
    for c in calificados:
        dominio = c.get("dominio", "")
        empresa_id = None
        empresa_nombre = c.get("empresa", "")

        rubro = c.get("rubro", "")

        if dominio:
            empresa_id = db.empresa_existe_por_dominio(dominio)
        if not empresa_id and empresa_nombre:
            empresa_id = db.crear_empresa({
                "nombre": empresa_nombre,
                "sitio_web": f"https://{dominio}" if dominio else "",
                "industria": rubro,
                "fuente": c.get("fuente_prospeccion", "prospeccion"),
            })

        contacto_id = db.crear_contacto({
            "empresa_id": empresa_id,
            "nombre": c.get("nombre", ""),
            "apellido": c.get("apellido", ""),
            "cargo": c.get("cargo", ""),
            "email": c.get("email", ""),
            "telefono": c.get("telefono", ""),
            "linkedin_url": c.get("linkedin_url", ""),
            "fuente": c.get("fuente_prospeccion", "prospeccion"),
        })

        email_draft = armar_email_sugerido(c, rubro)
        db.crear_prospecto(
            contacto_id=contacto_id,
            puntaje=c.get("puntaje_ia", 0),
            razon=c.get("razon_ia", ""),
            rubro=rubro,
            producto_sugerido=sugerir_producto(rubro),
            email_asunto=email_draft["asunto"],
            email_cuerpo=email_draft["cuerpo"],
        )

    db.log_scraping("prospeccion_auto", f"empresas:{len(empresas_target)} keywords:{len(keywords)}", resumen["calificados"])

    # ponytail: si Google Sheets no esta configurado o falla, no debe romper
    # la prospeccion -- es un extra, no el flujo principal.
    try:
        import sheets_sync
        sheets_sync.sincronizar()
    except Exception:
        pass

    return resumen
