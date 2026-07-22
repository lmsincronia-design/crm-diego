import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# ponytail: dual-mode DB — SQLite local, PostgreSQL en producción (Vercel)
USE_PG = bool(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"))
DB_PATH = Path(__file__).parent / "crm.db"

if USE_PG:
    import psycopg2
    from psycopg2.extras import RealDictCursor


def _ph(n):
    """Placeholder: %s para PostgreSQL, ? para SQLite."""
    return ", ".join(["%s"] * n) if USE_PG else ", ".join(["?"] * n)


def _p(name):
    """Named placeholder: %(name)s para PG, :name para SQLite."""
    return f"%({name})s" if USE_PG else f":{name}"


def _dict(row):
    return dict(row) if row else None


def _dicts(rows):
    return [dict(r) for r in rows]


@contextmanager
def get_db():
    if USE_PG:
        url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", "")
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _exec(conn, sql, params=None):
    """Execute adaptando sintaxis PG vs SQLite."""
    if USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    else:
        if params and isinstance(params, dict):
            return conn.execute(sql, params)
        return conn.execute(sql, params or ())


def _fetchone(conn, sql, params=None):
    if USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    else:
        row = conn.execute(sql, params or ()).fetchone()
        return dict(row) if row else None


def _fetchall(conn, sql, params=None):
    if USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    else:
        return [dict(r) for r in conn.execute(sql, params or ()).fetchall()]


def _insert_returning(conn, sql_pg, sql_lite, params):
    """Insert con RETURNING id (PG) o lastrowid (SQLite)."""
    if USE_PG:
        cur = conn.cursor()
        cur.execute(sql_pg, params)
        return cur.fetchone()["id"]
    else:
        cur = conn.execute(sql_lite, params)
        return cur.lastrowid


# --- INIT ---

def init_db():
    with get_db() as conn:
        if USE_PG:
            conn.cursor().execute(_schema_pg())
        else:
            conn.executescript(_schema_sqlite())


def _schema_pg():
    return """
        CREATE TABLE IF NOT EXISTS empresas (
            id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, rut TEXT DEFAULT '', industria TEXT DEFAULT '',
            tamano TEXT DEFAULT '', sitio_web TEXT DEFAULT '', direccion TEXT DEFAULT '', ciudad TEXT DEFAULT '',
            fuente TEXT DEFAULT '', notas TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS contactos (
            id SERIAL PRIMARY KEY, empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL,
            nombre TEXT NOT NULL, apellido TEXT DEFAULT '', cargo TEXT DEFAULT '', email TEXT DEFAULT '',
            telefono TEXT DEFAULT '', linkedin_url TEXT DEFAULT '', fuente TEXT DEFAULT '', notas TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS pipeline (
            id SERIAL PRIMARY KEY, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL, etapa TEXT DEFAULT 'prospecto',
            valor_estimado REAL DEFAULT 0, producto TEXT DEFAULT '', notas TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS campanas (
            id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, asunto TEXT NOT NULL, cuerpo TEXT NOT NULL,
            estado TEXT DEFAULT 'borrador', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS emails_enviados (
            id SERIAL PRIMARY KEY, campana_id INTEGER REFERENCES campanas(id) ON DELETE CASCADE,
            contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE, email_destino TEXT DEFAULT '',
            estado TEXT DEFAULT 'pendiente', fecha_envio TIMESTAMP, error TEXT);
        CREATE TABLE IF NOT EXISTS scraping_log (
            id SERIAL PRIMARY KEY, fuente TEXT NOT NULL, query TEXT DEFAULT '', resultados INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'completado', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS prospectos (
            id SERIAL PRIMARY KEY, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            puntaje_ia REAL DEFAULT 0, razon TEXT DEFAULT '', estado TEXT DEFAULT 'nuevo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS config_prospeccion (
            id SERIAL PRIMARY KEY, empresas_target TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
            intervalo_horas INTEGER DEFAULT 6, activo BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """


def _schema_sqlite():
    return """
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, rut TEXT DEFAULT '', industria TEXT DEFAULT '',
            tamano TEXT DEFAULT '', sitio_web TEXT DEFAULT '', direccion TEXT DEFAULT '', ciudad TEXT DEFAULT '',
            fuente TEXT DEFAULT '', notas TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS contactos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL,
            nombre TEXT NOT NULL, apellido TEXT DEFAULT '', cargo TEXT DEFAULT '', email TEXT DEFAULT '',
            telefono TEXT DEFAULT '', linkedin_url TEXT DEFAULT '', fuente TEXT DEFAULT '', notas TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS pipeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            empresa_id INTEGER REFERENCES empresas(id) ON DELETE SET NULL, etapa TEXT DEFAULT 'prospecto',
            valor_estimado REAL DEFAULT 0, producto TEXT DEFAULT '', notas TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS campanas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, asunto TEXT NOT NULL, cuerpo TEXT NOT NULL,
            estado TEXT DEFAULT 'borrador', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS emails_enviados (
            id INTEGER PRIMARY KEY AUTOINCREMENT, campana_id INTEGER REFERENCES campanas(id) ON DELETE CASCADE,
            contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE, email_destino TEXT DEFAULT '',
            estado TEXT DEFAULT 'pendiente', fecha_envio TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS scraping_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fuente TEXT NOT NULL, query TEXT DEFAULT '', resultados INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'completado', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS prospectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            puntaje_ia REAL DEFAULT 0, razon TEXT DEFAULT '', estado TEXT DEFAULT 'nuevo',
            created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS config_prospeccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresas_target TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
            intervalo_horas INTEGER DEFAULT 6, activo INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')));
    """


# --- EMPRESAS ---

_emp_fields = ["nombre", "rut", "industria", "tamano", "sitio_web", "direccion", "ciudad", "fuente", "notas"]

def crear_empresa(data: dict) -> int:
    vals = {k: data.get(k, "") for k in _emp_fields}
    cols = ", ".join(_emp_fields)
    with get_db() as conn:
        if USE_PG:
            phs = ", ".join(f"%({k})s" for k in _emp_fields)
            cur = conn.cursor()
            cur.execute(f"INSERT INTO empresas ({cols}) VALUES ({phs}) RETURNING id", vals)
            return cur.fetchone()["id"]
        else:
            phs = ", ".join(f":{k}" for k in _emp_fields)
            return conn.execute(f"INSERT INTO empresas ({cols}) VALUES ({phs})", vals).lastrowid


def listar_empresas(buscar: str = "", limit: int = 100, offset: int = 0):
    like = "ILIKE" if USE_PG else "LIKE"
    with get_db() as conn:
        if buscar:
            q = f"SELECT * FROM empresas WHERE nombre {like} %s OR rut {like} %s OR industria {like} %s ORDER BY id DESC LIMIT %s OFFSET %s" if USE_PG else \
                f"SELECT * FROM empresas WHERE nombre {like} ? OR rut {like} ? OR industria {like} ? ORDER BY id DESC LIMIT ? OFFSET ?"
            return _fetchall(conn, q, (f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", limit, offset))
        q = "SELECT * FROM empresas ORDER BY id DESC LIMIT %s OFFSET %s" if USE_PG else \
            "SELECT * FROM empresas ORDER BY id DESC LIMIT ? OFFSET ?"
        return _fetchall(conn, q, (limit, offset))


def obtener_empresa(id: int):
    with get_db() as conn:
        q = "SELECT * FROM empresas WHERE id = %s" if USE_PG else "SELECT * FROM empresas WHERE id = ?"
        return _fetchone(conn, q, (id,))


def actualizar_empresa(id: int, data: dict):
    fields = {k: v for k, v in data.items() if k in _emp_fields}
    if not fields:
        return
    if USE_PG:
        set_c = ", ".join(f"{k} = %({k})s" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.cursor().execute(f"UPDATE empresas SET {set_c} WHERE id = %(id)s", fields)
    else:
        set_c = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.execute(f"UPDATE empresas SET {set_c} WHERE id = :id", fields)


def eliminar_empresa(id: int):
    with get_db() as conn:
        _exec(conn, "DELETE FROM empresas WHERE id = %s" if USE_PG else "DELETE FROM empresas WHERE id = ?", (id,))


# --- CONTACTOS ---

_con_fields = ["empresa_id", "nombre", "apellido", "cargo", "email", "telefono", "linkedin_url", "fuente", "notas"]

def crear_contacto(data: dict) -> int:
    vals = {k: data.get(k) or "" for k in _con_fields}
    vals["empresa_id"] = data.get("empresa_id") or None
    cols = ", ".join(_con_fields)
    with get_db() as conn:
        if USE_PG:
            phs = ", ".join(f"%({k})s" for k in _con_fields)
            cur = conn.cursor()
            cur.execute(f"INSERT INTO contactos ({cols}) VALUES ({phs}) RETURNING id", vals)
            return cur.fetchone()["id"]
        else:
            phs = ", ".join(f":{k}" for k in _con_fields)
            return conn.execute(f"INSERT INTO contactos ({cols}) VALUES ({phs})", vals).lastrowid


def listar_contactos(buscar: str = "", empresa_id: int = None, limit: int = 100, offset: int = 0):
    base = "SELECT c.*, e.nombre as empresa_nombre FROM contactos c LEFT JOIN empresas e ON c.empresa_id = e.id "
    like = "ILIKE" if USE_PG else "LIKE"
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        if empresa_id:
            return _fetchall(conn, base + f"WHERE c.empresa_id = {ph} ORDER BY c.id DESC LIMIT {ph} OFFSET {ph}",
                             (empresa_id, limit, offset))
        if buscar:
            return _fetchall(conn, base + f"WHERE c.nombre {like} {ph} OR c.apellido {like} {ph} OR c.email {like} {ph} OR c.cargo {like} {ph} ORDER BY c.id DESC LIMIT {ph} OFFSET {ph}",
                             (f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", limit, offset))
        return _fetchall(conn, base + f"ORDER BY c.id DESC LIMIT {ph} OFFSET {ph}", (limit, offset))


def obtener_contacto(id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchone(conn,
            f"SELECT c.*, e.nombre as empresa_nombre FROM contactos c LEFT JOIN empresas e ON c.empresa_id = e.id WHERE c.id = {ph}", (id,))


def actualizar_contacto(id: int, data: dict):
    fields = {k: v for k, v in data.items() if k in _con_fields}
    if not fields:
        return
    if USE_PG:
        set_c = ", ".join(f"{k} = %({k})s" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.cursor().execute(f"UPDATE contactos SET {set_c} WHERE id = %(id)s", fields)
    else:
        set_c = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.execute(f"UPDATE contactos SET {set_c} WHERE id = :id", fields)


def eliminar_contacto(id: int):
    with get_db() as conn:
        _exec(conn, "DELETE FROM contactos WHERE id = %s" if USE_PG else "DELETE FROM contactos WHERE id = ?", (id,))


# --- PIPELINE ---

def crear_deal(data: dict) -> int:
    with get_db() as conn:
        params = (data.get("contacto_id"), data.get("empresa_id"), data.get("etapa", "prospecto"),
                  data.get("valor_estimado", 0), data.get("producto", ""), data.get("notas", ""))
        if USE_PG:
            cur = conn.cursor()
            cur.execute("INSERT INTO pipeline (contacto_id, empresa_id, etapa, valor_estimado, producto, notas) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", params)
            return cur.fetchone()["id"]
        else:
            return conn.execute("INSERT INTO pipeline (contacto_id, empresa_id, etapa, valor_estimado, producto, notas) VALUES (?,?,?,?,?,?)", params).lastrowid


def listar_pipeline(etapa: str = None):
    base = ("SELECT p.*, c.nombre as contacto_nombre, c.apellido as contacto_apellido, e.nombre as empresa_nombre "
            "FROM pipeline p LEFT JOIN contactos c ON p.contacto_id = c.id LEFT JOIN empresas e ON p.empresa_id = e.id ")
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        if etapa:
            return _fetchall(conn, base + f"WHERE p.etapa = {ph} ORDER BY p.updated_at DESC", (etapa,))
        return _fetchall(conn, base + "ORDER BY p.updated_at DESC")


def actualizar_deal(id: int, data: dict):
    allowed = ["etapa", "valor_estimado", "producto", "notas"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    now = "CURRENT_TIMESTAMP" if USE_PG else "datetime('now')"
    if USE_PG:
        set_c = ", ".join(f"{k} = %({k})s" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.cursor().execute(f"UPDATE pipeline SET {set_c}, updated_at = {now} WHERE id = %(id)s", fields)
    else:
        set_c = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.execute(f"UPDATE pipeline SET {set_c}, updated_at = {now} WHERE id = :id", fields)


def eliminar_deal(id: int):
    with get_db() as conn:
        _exec(conn, "DELETE FROM pipeline WHERE id = %s" if USE_PG else "DELETE FROM pipeline WHERE id = ?", (id,))


def stats_pipeline():
    with get_db() as conn:
        return _fetchall(conn, "SELECT etapa, COUNT(*) as cantidad, COALESCE(SUM(valor_estimado), 0) as valor_total FROM pipeline GROUP BY etapa")


# --- CAMPANAS ---

def crear_campana(data: dict) -> int:
    params = (data.get("nombre", ""), data.get("asunto", ""), data.get("cuerpo", ""))
    with get_db() as conn:
        if USE_PG:
            cur = conn.cursor()
            cur.execute("INSERT INTO campanas (nombre, asunto, cuerpo) VALUES (%s,%s,%s) RETURNING id", params)
            return cur.fetchone()["id"]
        else:
            return conn.execute("INSERT INTO campanas (nombre, asunto, cuerpo) VALUES (?,?,?)", params).lastrowid


def listar_campanas():
    with get_db() as conn:
        return _fetchall(conn,
            "SELECT c.*, (SELECT COUNT(*) FROM emails_enviados e WHERE e.campana_id = c.id) as total_emails, "
            "(SELECT COUNT(*) FROM emails_enviados e WHERE e.campana_id = c.id AND e.estado = 'enviado') as enviados "
            "FROM campanas c ORDER BY c.id DESC")


def obtener_campana(id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM campanas WHERE id = {ph}", (id,))


def agregar_destinatarios(campana_id: int, contacto_ids: list[int]):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        for cid in contacto_ids:
            contacto = _fetchone(conn, f"SELECT email FROM contactos WHERE id = {ph}", (cid,))
            if contacto and contacto["email"]:
                exists = _fetchone(conn, f"SELECT 1 as x FROM emails_enviados WHERE campana_id = {ph} AND contacto_id = {ph}", (campana_id, cid))
                if not exists:
                    _exec(conn, f"INSERT INTO emails_enviados (campana_id, contacto_id, email_destino) VALUES ({ph},{ph},{ph})",
                          (campana_id, cid, contacto["email"]))


def listar_destinatarios(campana_id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn,
            f"SELECT ee.*, c.nombre, c.apellido, c.cargo FROM emails_enviados ee "
            f"JOIN contactos c ON ee.contacto_id = c.id WHERE ee.campana_id = {ph} ORDER BY ee.id", (campana_id,))


def marcar_email_enviado(id: int, estado: str, error: str = None):
    now = "CURRENT_TIMESTAMP" if USE_PG else "datetime('now')"
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        _exec(conn, f"UPDATE emails_enviados SET estado = {ph}, fecha_envio = {now}, error = {ph} WHERE id = {ph}",
              (estado, error, id))


# --- SCRAPING LOG ---

def log_scraping(fuente: str, query: str, resultados: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        _exec(conn, f"INSERT INTO scraping_log (fuente, query, resultados) VALUES ({ph},{ph},{ph})",
              (fuente, query, resultados))


def listar_scraping_log(limit: int = 50):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn, f"SELECT * FROM scraping_log ORDER BY id DESC LIMIT {ph}", (limit,))


# --- DEDUPLICACION ---

def contacto_existe(email: str = "", nombre: str = "", apellido: str = "", empresa_id: int = None) -> bool:
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        if email and email.strip():
            row = _fetchone(conn, f"SELECT 1 as x FROM contactos WHERE email = {ph}", (email.strip(),))
            if row:
                return True
        if nombre and apellido and empresa_id:
            row = _fetchone(conn, f"SELECT 1 as x FROM contactos WHERE nombre = {ph} AND apellido = {ph} AND empresa_id = {ph}",
                            (nombre, apellido, empresa_id))
            if row:
                return True
    return False


def empresa_existe_por_dominio(dominio: str) -> int | None:
    like = "ILIKE" if USE_PG else "LIKE"
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT id FROM empresas WHERE sitio_web {like} {ph}", (f"%{dominio}%",))
        return row["id"] if row else None


# --- PROSPECTOS ---

def crear_prospecto(contacto_id: int, puntaje: float, razon: str) -> int:
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        exists = _fetchone(conn, f"SELECT 1 as x FROM prospectos WHERE contacto_id = {ph}", (contacto_id,))
        if exists:
            _exec(conn, f"UPDATE prospectos SET puntaje_ia = {ph}, razon = {ph} WHERE contacto_id = {ph}",
                  (puntaje, razon, contacto_id))
            return contacto_id
        if USE_PG:
            cur = conn.cursor()
            cur.execute(f"INSERT INTO prospectos (contacto_id, puntaje_ia, razon) VALUES ({ph},{ph},{ph}) RETURNING id",
                        (contacto_id, puntaje, razon))
            return cur.fetchone()["id"]
        else:
            return conn.execute(f"INSERT INTO prospectos (contacto_id, puntaje_ia, razon) VALUES ({ph},{ph},{ph})",
                                (contacto_id, puntaje, razon)).lastrowid


def listar_prospectos(min_puntaje: float = 0, limit: int = 100):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn,
            f"SELECT p.*, c.nombre, c.apellido, c.cargo, c.email, c.telefono, c.linkedin_url, e.nombre as empresa_nombre "
            f"FROM prospectos p JOIN contactos c ON p.contacto_id = c.id LEFT JOIN empresas e ON c.empresa_id = e.id "
            f"WHERE p.puntaje_ia >= {ph} ORDER BY p.puntaje_ia DESC LIMIT {ph}", (min_puntaje, limit))


def actualizar_prospecto_estado(id: int, estado: str):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        _exec(conn, f"UPDATE prospectos SET estado = {ph} WHERE id = {ph}", (estado, id))


# --- CONFIG PROSPECCION ---

def guardar_config_prospeccion(data: dict):
    import json
    with get_db() as conn:
        existing = _fetchone(conn, "SELECT id FROM config_prospeccion LIMIT 1")
        empresas = json.dumps(data.get("empresas_target", []))
        keywords = json.dumps(data.get("keywords", []))
        intervalo = data.get("intervalo_horas", 6)
        activo = data.get("activo", False)
        ph = "%s" if USE_PG else "?"
        if existing:
            now = "CURRENT_TIMESTAMP" if USE_PG else "datetime('now')"
            _exec(conn, f"UPDATE config_prospeccion SET empresas_target={ph}, keywords={ph}, intervalo_horas={ph}, activo={ph}, updated_at={now} WHERE id={ph}",
                  (empresas, keywords, intervalo, activo if USE_PG else int(activo), existing["id"]))
        else:
            _exec(conn, f"INSERT INTO config_prospeccion (empresas_target, keywords, intervalo_horas, activo) VALUES ({ph},{ph},{ph},{ph})",
                  (empresas, keywords, intervalo, activo if USE_PG else int(activo)))


def obtener_config_prospeccion() -> dict:
    import json
    with get_db() as conn:
        row = _fetchone(conn, "SELECT * FROM config_prospeccion LIMIT 1")
        if not row:
            return {"empresas_target": [], "keywords": [], "intervalo_horas": 6, "activo": False}
        return {
            "empresas_target": json.loads(row.get("empresas_target", "[]")),
            "keywords": json.loads(row.get("keywords", "[]")),
            "intervalo_horas": row.get("intervalo_horas", 6),
            "activo": bool(row.get("activo", False)),
        }


# --- DASHBOARD ---

def dashboard_stats():
    with get_db() as conn:
        empresas = _fetchone(conn, "SELECT COUNT(*) as c FROM empresas")["c"]
        contactos = _fetchone(conn, "SELECT COUNT(*) as c FROM contactos")["c"]
        deals = _fetchone(conn, "SELECT COUNT(*) as c FROM pipeline")["c"]
        valor = _fetchone(conn, "SELECT COALESCE(SUM(valor_estimado), 0) as v FROM pipeline")["v"]
        emails_env = _fetchone(conn, "SELECT COUNT(*) as c FROM emails_enviados WHERE estado = 'enviado'")["c"]

        pipeline_stats = _fetchall(conn,
            "SELECT etapa, COUNT(*) as cantidad, COALESCE(SUM(valor_estimado), 0) as valor FROM pipeline GROUP BY etapa")

        recientes = _fetchall(conn,
            "SELECT c.nombre, c.apellido, c.cargo, e.nombre as empresa_nombre, c.created_at "
            "FROM contactos c LEFT JOIN empresas e ON c.empresa_id = e.id ORDER BY c.id DESC LIMIT 10")

        return {
            "empresas": empresas, "contactos": contactos, "deals": deals,
            "valor_total": float(valor or 0), "emails_enviados": emails_env,
            "pipeline": pipeline_stats, "contactos_recientes": recientes,
        }
