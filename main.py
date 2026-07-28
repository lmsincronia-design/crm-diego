from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import database as db
import scraper
import emailer
import prospector
import sheets_sync
from auth import AuthMiddleware

app = FastAPI(title="CRM Diego - Repuestos Industriales")
app.add_middleware(AuthMiddleware)

PUBLIC_DIR = Path(__file__).parent / "public"


@app.on_event("startup")
def startup():
    db.init_db()
    try:
        PUBLIC_DIR.mkdir(exist_ok=True)
    except OSError:
        pass  # ponytail: read-only filesystem on Vercel, public/ is served as a separate static build there


# --- DASHBOARD ---

@app.get("/api/dashboard")
def get_dashboard():
    return db.dashboard_stats()


# --- EMPRESAS ---

@app.get("/api/empresas")
def list_empresas(buscar: str = "", industria: str = "", fuente: str = "", limit: int = 100, offset: int = 0):
    return db.listar_empresas(buscar, industria, fuente, limit, offset)

@app.get("/api/empresas/fuentes")
def get_fuentes_empresas():
    return db.fuentes_empresas()

@app.get("/api/empresas/industrias")
def get_industrias_empresas():
    return db.industrias_empresas()

@app.post("/api/empresas")
def create_empresa(data: dict):
    return {"id": db.crear_empresa(data)}

@app.get("/api/empresas/{id}")
def get_empresa(id: int):
    return db.obtener_empresa(id) or {"error": "No encontrada"}

@app.put("/api/empresas/{id}")
def update_empresa(id: int, data: dict):
    db.actualizar_empresa(id, data)
    return {"ok": True}

@app.delete("/api/empresas/{id}")
def delete_empresa(id: int):
    db.eliminar_empresa(id)
    return {"ok": True}


# --- CONTACTOS ---

@app.get("/api/contactos")
def list_contactos(buscar: str = "", empresa_id: int = None, fuente: str = "", limit: int = 100, offset: int = 0):
    return db.listar_contactos(buscar, empresa_id, fuente, limit, offset)

@app.get("/api/contactos/fuentes")
def get_fuentes_contactos():
    return db.fuentes_contactos()

@app.post("/api/contactos")
def create_contacto(data: dict):
    return {"id": db.crear_contacto(data)}

@app.get("/api/contactos/{id}")
def get_contacto(id: int):
    return db.obtener_contacto(id) or {"error": "No encontrado"}

@app.put("/api/contactos/{id}")
def update_contacto(id: int, data: dict):
    db.actualizar_contacto(id, data)
    return {"ok": True}

@app.delete("/api/contactos/{id}")
def delete_contacto(id: int):
    db.eliminar_contacto(id)
    return {"ok": True}

@app.post("/api/contactos/limpiar-duplicados")
def limpiar_contactos_duplicados():
    return db.eliminar_contactos_duplicados()


# --- PIPELINE ---

@app.get("/api/pipeline")
def list_pipeline(etapa: str = None):
    return db.listar_pipeline(etapa)

@app.get("/api/pipeline/stats")
def pipeline_stats():
    return db.stats_pipeline()

@app.post("/api/pipeline")
def create_deal(data: dict):
    return {"id": db.crear_deal(data)}

@app.put("/api/pipeline/{id}")
def update_deal(id: int, data: dict):
    db.actualizar_deal(id, data)
    return {"ok": True}

@app.delete("/api/pipeline/{id}")
def delete_deal(id: int):
    db.eliminar_deal(id)
    return {"ok": True}


# --- CAMPANAS EMAIL ---

@app.get("/api/campanas")
def list_campanas():
    return db.listar_campanas()

@app.post("/api/campanas")
def create_campana(data: dict):
    return {"id": db.crear_campana(data)}

@app.get("/api/campanas/{id}")
def get_campana(id: int):
    campana = db.obtener_campana(id)
    if not campana:
        return {"error": "No encontrada"}
    campana["destinatarios"] = db.listar_destinatarios(id)
    return campana

@app.post("/api/campanas/{id}/destinatarios")
def add_destinatarios(id: int, data: dict):
    db.agregar_destinatarios(id, data.get("contacto_ids", []))
    return {"ok": True}

@app.post("/api/campanas/{id}/enviar")
def send_campana(id: int):
    return emailer.enviar_campana(id)


# --- PLANTILLAS DE EMAIL ---

@app.get("/api/plantillas")
def list_plantillas():
    return db.listar_plantillas()

@app.post("/api/plantillas")
def create_plantilla(data: dict):
    return {"id": db.crear_plantilla(data)}

@app.get("/api/plantillas/{id}")
def get_plantilla(id: int):
    return db.obtener_plantilla(id) or {"error": "No encontrada"}

@app.put("/api/plantillas/{id}")
def update_plantilla(id: int, data: dict):
    db.actualizar_plantilla(id, data)
    return {"ok": True}

@app.delete("/api/plantillas/{id}")
def delete_plantilla(id: int):
    db.eliminar_plantilla(id)
    return {"ok": True}

@app.post("/api/plantillas/{id}/enviar")
def enviar_plantilla(id: int, data: dict):
    plantilla = db.obtener_plantilla(id)
    if not plantilla:
        return {"error": "Plantilla no encontrada"}
    contacto_ids = data.get("contacto_ids", [])
    if not contacto_ids:
        return {"error": "Selecciona al menos un contacto"}
    campana_id = db.crear_campana({
        "nombre": f"{plantilla['nombre']} ({len(contacto_ids)} destinatarios)",
        "asunto": plantilla["asunto"],
        "cuerpo": plantilla["cuerpo"],
    })
    db.agregar_destinatarios(campana_id, contacto_ids)
    return emailer.enviar_campana(campana_id)


# --- APOLLO.IO ---

@app.post("/api/apollo/buscar")
async def apollo_search(data: dict):
    return await scraper.buscar_apollo(
        empresa=data.get("empresa", ""),
        cargo=data.get("cargo", ""),
        ubicacion=data.get("ubicacion", "Chile"),
        page=data.get("page", 1),
        per_page=data.get("per_page", 25),
    )

@app.post("/api/apollo/importar")
async def apollo_import(data: dict):
    contactos = data.get("contactos", [])
    return await scraper.importar_apollo_al_crm(contactos)


# --- HUNTER.IO ---

@app.post("/api/hunter/buscar")
async def hunter_search(data: dict):
    dominio = data.get("dominio", "")
    if not dominio:
        return {"error": "Falta dominio (ej: cmpc.cl)"}
    return await scraper.buscar_hunter(dominio)

@app.post("/api/hunter/email")
async def hunter_find_email(data: dict):
    return await scraper.buscar_hunter_email(
        data.get("nombre", ""), data.get("apellido", ""), data.get("dominio", ""))

@app.post("/api/hunter/importar")
async def hunter_import(data: dict):
    return await scraper.importar_hunter_al_crm(
        data.get("contactos", []), data.get("empresa", ""), data.get("dominio", ""))


# --- PROSPECCION AUTOMATICA ---

@app.get("/api/prospeccion/config")
def get_prospeccion_config():
    return db.obtener_config_prospeccion()

@app.get("/api/prospeccion/rubros")
def get_rubros():
    return prospector.listar_rubros()

@app.post("/api/prospeccion/empresas-por-rubro")
def get_empresas_por_rubro(data: dict):
    return {"empresas": prospector.empresas_por_rubro(data.get("rubros", []))}

@app.post("/api/prospeccion/config")
def save_prospeccion_config(data: dict):
    db.guardar_config_prospeccion(data)
    return {"ok": True}

@app.post("/api/prospeccion/ejecutar")
async def run_prospeccion():
    return await prospector.ejecutar_prospeccion()

@app.get("/api/prospeccion/prospectos")
def list_prospectos(min_puntaje: float = 0, limit: int = 100):
    return db.listar_prospectos(min_puntaje, limit)

@app.put("/api/prospeccion/prospectos/{id}")
def update_prospecto(id: int, data: dict):
    db.actualizar_prospecto_estado(id, data.get("estado", "nuevo"))
    return {"ok": True}


@app.get("/api/prospeccion/cron")
async def cron_prospeccion():
    """Disparado por un GitHub Action cada hora (ver .github/workflows/prospeccion-cron.yml).
    Solo ejecuta prospeccion real si esta activa y ya paso el intervalo configurado -- asi
    un solo cron horario sirve para las opciones de 1/3/6/12/24 horas."""
    config = db.obtener_config_prospeccion()
    if not config.get("activo"):
        return {"ejecutado": False, "razon": "prospeccion en modo manual"}

    ultima = config.get("ultima_ejecucion")
    if ultima:
        from datetime import datetime, timedelta
        try:
            desde = datetime.fromisoformat(str(ultima).split(".")[0].replace("Z", ""))
            if datetime.utcnow() - desde < timedelta(hours=config.get("intervalo_horas", 6)):
                return {"ejecutado": False, "razon": "aun no toca segun el intervalo configurado"}
        except ValueError:
            pass

    resultado = await prospector.ejecutar_prospeccion()
    db.marcar_ejecucion_prospeccion()
    return {"ejecutado": True, **resultado}


# --- SCRAPING ---

@app.post("/api/scraping/mercadopublico")
async def scrape_mercadopublico(data: dict):
    keyword = data.get("keyword", "")
    if not keyword:
        return {"error": "Falta keyword"}
    resultado = await scraper.buscar_mercadopublico(keyword)
    if "error" in resultado:
        return resultado
    return {"resultados": resultado["resultados"], "total": len(resultado["resultados"])}

@app.post("/api/scraping/sitio")
async def scrape_sitio(data: dict):
    url = data.get("url", "")
    if not url:
        return {"error": "Falta URL"}
    if not url.startswith("http"):
        url = "https://" + url
    return await scraper.scrape_sitio_empresa(url)

@app.post("/api/importar/csv")
async def importar_csv(file: UploadFile = File(...)):
    contenido = await file.read()
    if file.filename and file.filename.endswith((".xlsx", ".xls")):
        return scraper.importar_excel(contenido, f"excel:{file.filename}")
    return scraper.importar_csv(contenido, f"csv:{file.filename}")

@app.get("/api/scraping/log")
def scraping_log():
    return db.listar_scraping_log()

@app.post("/api/sheets/sincronizar")
def sincronizar_sheets():
    return sheets_sync.sincronizar()

@app.post("/api/scraping/seia")
async def scrape_seia(data: dict):
    rubro = data.get("rubro", "")
    if not rubro:
        return {"error": "Falta rubro"}
    return await scraper.buscar_seia(rubro)

@app.post("/api/scraping/seia/contacto")
async def scrape_seia_contacto(data: dict):
    url_ficha = data.get("url_ficha", "")
    if not url_ficha:
        return {"error": "Falta url_ficha"}
    return await scraper.obtener_contacto_seia(url_ficha)


# --- STATIC FILES ---

if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")

@app.get("/")
def root():
    return FileResponse(str(PUBLIC_DIR / "index.html"), headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
