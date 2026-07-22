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


async def filtrar_con_ia(contactos: list[dict]) -> list[dict]:
    """Filtra contactos con Claude API. Devuelve solo los relevantes con puntaje."""
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

Analiza estos contactos y devuelve SOLO un JSON array con los que son prospectos potenciales
(personas que podrian comprar estos productos por su cargo/empresa). Para cada uno devuelve:
{{"idx": numero, "puntaje": 1-100, "razon": "por que es buen prospecto"}}

Solo incluye contactos con puntaje >= 50. Si ninguno califica, devuelve [].

Contactos:
{batch_text}

Responde SOLO el JSON array, sin explicacion."""

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
    """Filtro sin IA: por cargo relevante."""
    resultados = []
    for c in contactos:
        cargo = (c.get("cargo", "") or "").lower()
        puntaje = 0
        razon = ""
        for kw in CARGOS_RELEVANTES:
            if kw in cargo:
                puntaje = 60
                razon = f"Cargo relevante: {c.get('cargo', '')}"
                break
        if puntaje >= 50:
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
                c["fuente_prospeccion"] = "hunter"
                contactos_raw.append(c)
                resumen["hunter"] += 1
        except Exception:
            pass

    # 2. Mercado Publico — buscar licitaciones
    for kw in keywords:
        try:
            licitaciones = await scraper.buscar_mercadopublico(kw)
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

    # 5. Filtrar con IA
    calificados = await filtrar_con_ia(nuevos)
    resumen["calificados"] = len(calificados)

    # 6. Guardar en DB
    for c in calificados:
        dominio = c.get("dominio", "")
        empresa_id = None
        empresa_nombre = c.get("empresa", "")

        if dominio:
            empresa_id = db.empresa_existe_por_dominio(dominio)
        if not empresa_id and empresa_nombre:
            empresa_id = db.crear_empresa({
                "nombre": empresa_nombre,
                "sitio_web": f"https://{dominio}" if dominio else "",
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

        db.crear_prospecto(
            contacto_id=contacto_id,
            puntaje=c.get("puntaje_ia", 0),
            razon=c.get("razon_ia", ""),
        )

    db.log_scraping("prospeccion_auto", f"empresas:{len(empresas_target)} keywords:{len(keywords)}", resumen["calificados"])
    return resumen
