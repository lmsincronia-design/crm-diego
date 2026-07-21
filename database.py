import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager


def _get_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", "")


@contextmanager
def get_db():
    conn = psycopg2.connect(_get_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                rut TEXT DEFAULT '',
                industria TEXT DEFAULT '',
                tamano TEXT DEFAULT '',
                sitio_web TEXT DEFAULT '',
                direccion TEXT DEFAULT '',
                ciudad TEXT DEFAULT '',
                fuente TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS contactos (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL,
                nombre TEXT NOT NULL,
                apellido TEXT DEFAULT '',
                cargo TEXT DEFAULT '',
                email TEXT DEFAULT '',
                telefono TEXT DEFAULT '',
                linkedin_url TEXT DEFAULT '',
                fuente TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pipeline (
                id SERIAL PRIMARY KEY,
                contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
                empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL,
                etapa TEXT DEFAULT 'prospecto',
                valor_estimado REAL DEFAULT 0,
                producto TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS campanas (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                asunto TEXT NOT NULL,
                cuerpo TEXT NOT NULL,
                estado TEXT DEFAULT 'borrador',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS emails_enviados (
                id SERIAL PRIMARY KEY,
                campana_id INTEGER REFERENCES campanas(id) ON DELETE CASCADE,
                contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
                email_destino TEXT DEFAULT '',
                estado TEXT DEFAULT 'pendiente',
                fecha_envio TIMESTAMP,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS scraping_log (
                id SERIAL PRIMARY KEY,
                fuente TEXT NOT NULL,
                query TEXT DEFAULT '',
                resultados INTEGER DEFAULT 0,
                estado TEXT DEFAULT 'completado',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# --- EMPRESAS ---

def crear_empresa(data: dict) -> int:
    fields = ["nombre", "rut", "industria", "tamano", "sitio_web", "direccion", "ciudad", "fuente", "notas"]
    vals = {k: data.get(k, "") for k in fields}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO empresas (nombre, rut, industria, tamano, sitio_web, direccion, ciudad, fuente, notas) "
            "VALUES (%(nombre)s, %(rut)s, %(industria)s, %(tamano)s, %(sitio_web)s, %(direccion)s, %(ciudad)s, %(fuente)s, %(notas)s) "
            "RETURNING id", vals,
        )
        return cur.fetchone()["id"]


def listar_empresas(buscar: str = "", limit: int = 100, offset: int = 0):
    with get_db() as conn:
        cur = conn.cursor()
        if buscar:
            cur.execute(
                "SELECT * FROM empresas WHERE nombre ILIKE %s OR rut ILIKE %s OR industria ILIKE %s ORDER BY id DESC LIMIT %s OFFSET %s",
                (f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", limit, offset),
            )
        else:
            cur.execute("SELECT * FROM empresas ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset))
        return [dict(r) for r in cur.fetchall()]


def obtener_empresa(id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM empresas WHERE id = %s", (id,))
        row = cur.fetchone()
        return dict(row) if row else None


def actualizar_empresa(id: int, data: dict):
    allowed = ["nombre", "rut", "industria", "tamano", "sitio_web", "direccion", "ciudad", "fuente", "notas"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    fields["id"] = id
    with get_db() as conn:
        conn.cursor().execute(f"UPDATE empresas SET {set_clause} WHERE id = %(id)s", fields)


def eliminar_empresa(id: int):
    with get_db() as conn:
        conn.cursor().execute("DELETE FROM empresas WHERE id = %s", (id,))


# --- CONTACTOS ---

def crear_contacto(data: dict) -> int:
    fields = ["empresa_id", "nombre", "apellido", "cargo", "email", "telefono", "linkedin_url", "fuente", "notas"]
    vals = {k: data.get(k) or "" for k in fields}
    vals["empresa_id"] = data.get("empresa_id") or None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO contactos (empresa_id, nombre, apellido, cargo, email, telefono, linkedin_url, fuente, notas) "
            "VALUES (%(empresa_id)s, %(nombre)s, %(apellido)s, %(cargo)s, %(email)s, %(telefono)s, %(linkedin_url)s, %(fuente)s, %(notas)s) "
            "RETURNING id", vals,
        )
        return cur.fetchone()["id"]


def listar_contactos(buscar: str = "", empresa_id: int = None, limit: int = 100, offset: int = 0):
    base = ("SELECT c.*, e.nombre as empresa_nombre FROM contactos c "
            "LEFT JOIN empresas e ON c.empresa_id = e.id ")
    with get_db() as conn:
        cur = conn.cursor()
        if empresa_id:
            cur.execute(base + "WHERE c.empresa_id = %s ORDER BY c.id DESC LIMIT %s OFFSET %s",
                        (empresa_id, limit, offset))
        elif buscar:
            cur.execute(base + "WHERE c.nombre ILIKE %s OR c.apellido ILIKE %s OR c.email ILIKE %s OR c.cargo ILIKE %s "
                        "ORDER BY c.id DESC LIMIT %s OFFSET %s",
                        (f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", limit, offset))
        else:
            cur.execute(base + "ORDER BY c.id DESC LIMIT %s OFFSET %s", (limit, offset))
        return [dict(r) for r in cur.fetchall()]


def obtener_contacto(id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.*, e.nombre as empresa_nombre FROM contactos c "
            "LEFT JOIN empresas e ON c.empresa_id = e.id WHERE c.id = %s", (id,))
        row = cur.fetchone()
        return dict(row) if row else None


def actualizar_contacto(id: int, data: dict):
    allowed = ["empresa_id", "nombre", "apellido", "cargo", "email", "telefono", "linkedin_url", "fuente", "notas"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    fields["id"] = id
    with get_db() as conn:
        conn.cursor().execute(f"UPDATE contactos SET {set_clause} WHERE id = %(id)s", fields)


def eliminar_contacto(id: int):
    with get_db() as conn:
        conn.cursor().execute("DELETE FROM contactos WHERE id = %s", (id,))


# --- PIPELINE ---

def crear_deal(data: dict) -> int:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pipeline (contacto_id, empresa_id, etapa, valor_estimado, producto, notas) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (data.get("contacto_id"), data.get("empresa_id"), data.get("etapa", "prospecto"),
             data.get("valor_estimado", 0), data.get("producto", ""), data.get("notas", "")),
        )
        return cur.fetchone()["id"]


def listar_pipeline(etapa: str = None):
    base = ("SELECT p.*, c.nombre as contacto_nombre, c.apellido as contacto_apellido, e.nombre as empresa_nombre "
            "FROM pipeline p LEFT JOIN contactos c ON p.contacto_id = c.id "
            "LEFT JOIN empresas e ON p.empresa_id = e.id ")
    with get_db() as conn:
        cur = conn.cursor()
        if etapa:
            cur.execute(base + "WHERE p.etapa = %s ORDER BY p.updated_at DESC", (etapa,))
        else:
            cur.execute(base + "ORDER BY p.updated_at DESC")
        return [dict(r) for r in cur.fetchall()]


def actualizar_deal(id: int, data: dict):
    allowed = ["etapa", "valor_estimado", "producto", "notas"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    fields["id"] = id
    with get_db() as conn:
        conn.cursor().execute(f"UPDATE pipeline SET {set_clause} WHERE id = %(id)s", fields)


def eliminar_deal(id: int):
    with get_db() as conn:
        conn.cursor().execute("DELETE FROM pipeline WHERE id = %s", (id,))


def stats_pipeline():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT etapa, COUNT(*) as cantidad, COALESCE(SUM(valor_estimado), 0) as valor_total "
            "FROM pipeline GROUP BY etapa"
        )
        return [dict(r) for r in cur.fetchall()]


# --- CAMPANAS ---

def crear_campana(data: dict) -> int:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO campanas (nombre, asunto, cuerpo) VALUES (%s, %s, %s) RETURNING id",
            (data.get("nombre", ""), data.get("asunto", ""), data.get("cuerpo", "")),
        )
        return cur.fetchone()["id"]


def listar_campanas():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM emails_enviados e WHERE e.campana_id = c.id) as total_emails, "
            "(SELECT COUNT(*) FROM emails_enviados e WHERE e.campana_id = c.id AND e.estado = 'enviado') as enviados "
            "FROM campanas c ORDER BY c.id DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def obtener_campana(id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas WHERE id = %s", (id,))
        row = cur.fetchone()
        return dict(row) if row else None


def agregar_destinatarios(campana_id: int, contacto_ids: list[int]):
    with get_db() as conn:
        cur = conn.cursor()
        for cid in contacto_ids:
            cur.execute("SELECT email FROM contactos WHERE id = %s", (cid,))
            contacto = cur.fetchone()
            if contacto and contacto["email"]:
                cur.execute("SELECT 1 FROM emails_enviados WHERE campana_id = %s AND contacto_id = %s",
                            (campana_id, cid))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO emails_enviados (campana_id, contacto_id, email_destino) VALUES (%s, %s, %s)",
                        (campana_id, cid, contacto["email"]),
                    )


def listar_destinatarios(campana_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ee.*, c.nombre, c.apellido, c.cargo FROM emails_enviados ee "
            "JOIN contactos c ON ee.contacto_id = c.id WHERE ee.campana_id = %s ORDER BY ee.id",
            (campana_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def marcar_email_enviado(id: int, estado: str, error: str = None):
    with get_db() as conn:
        conn.cursor().execute(
            "UPDATE emails_enviados SET estado = %s, fecha_envio = CURRENT_TIMESTAMP, error = %s WHERE id = %s",
            (estado, error, id),
        )


# --- SCRAPING LOG ---

def log_scraping(fuente: str, query: str, resultados: int):
    with get_db() as conn:
        conn.cursor().execute(
            "INSERT INTO scraping_log (fuente, query, resultados) VALUES (%s, %s, %s)",
            (fuente, query, resultados),
        )


def listar_scraping_log(limit: int = 50):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scraping_log ORDER BY id DESC LIMIT %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


# --- DASHBOARD ---

def dashboard_stats():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM empresas")
        empresas = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM contactos")
        contactos = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM pipeline")
        deals = cur.fetchone()["c"]
        cur.execute("SELECT COALESCE(SUM(valor_estimado), 0) as v FROM pipeline")
        valor_total = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as c FROM emails_enviados WHERE estado = 'enviado'")
        emails_env = cur.fetchone()["c"]

        cur.execute(
            "SELECT etapa, COUNT(*) as cantidad, COALESCE(SUM(valor_estimado), 0) as valor "
            "FROM pipeline GROUP BY etapa"
        )
        pipeline_stats = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT c.nombre, c.apellido, c.cargo, e.nombre as empresa_nombre, c.created_at "
            "FROM contactos c LEFT JOIN empresas e ON c.empresa_id = e.id ORDER BY c.id DESC LIMIT 10"
        )
        recientes = [dict(r) for r in cur.fetchall()]

        return {
            "empresas": empresas,
            "contactos": contactos,
            "deals": deals,
            "valor_total": float(valor_total or 0),
            "emails_enviados": emails_env,
            "pipeline": pipeline_stats,
            "contactos_recientes": recientes,
        }
