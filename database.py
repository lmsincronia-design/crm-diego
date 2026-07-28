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
    _migrar_columnas_nuevas()


def _migrar_columnas_nuevas():
    """ponytail: agrega columnas nuevas a tablas ya existentes en despliegues viejos.
    Cada ALTER va en su propia conexion para que un 'columna ya existe' no aborte
    las siguientes (Postgres invalida toda la transaccion tras un error)."""
    for col, coltype in [
        ("rubro", "TEXT DEFAULT ''"),
        ("producto_sugerido", "TEXT DEFAULT ''"),
        ("email_asunto", "TEXT DEFAULT ''"),
        ("email_cuerpo", "TEXT DEFAULT ''"),
    ]:
        try:
            with get_db() as conn:
                _exec(conn, f"ALTER TABLE prospectos ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    try:
        with get_db() as conn:
            _exec(conn, "ALTER TABLE config_prospeccion ADD COLUMN ultima_ejecucion TEXT")
    except Exception:
        pass
    for col in ("asunto", "cuerpo"):
        try:
            with get_db() as conn:
                _exec(conn, f"ALTER TABLE emails_enviados ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass


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
            estado TEXT DEFAULT 'pendiente', fecha_envio TIMESTAMP, error TEXT,
            asunto TEXT DEFAULT '', cuerpo TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS scraping_log (
            id SERIAL PRIMARY KEY, fuente TEXT NOT NULL, query TEXT DEFAULT '', resultados INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'completado', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS prospectos (
            id SERIAL PRIMARY KEY, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            puntaje_ia REAL DEFAULT 0, razon TEXT DEFAULT '', estado TEXT DEFAULT 'nuevo',
            rubro TEXT DEFAULT '', producto_sugerido TEXT DEFAULT '', email_asunto TEXT DEFAULT '', email_cuerpo TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS config_prospeccion (
            id SERIAL PRIMARY KEY, empresas_target TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
            intervalo_horas INTEGER DEFAULT 6, activo BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS evaluaciones_ia (
            id SERIAL PRIMARY KEY, nombre TEXT DEFAULT '', apellido TEXT DEFAULT '', cargo TEXT DEFAULT '',
            email TEXT DEFAULT '', empresa TEXT DEFAULT '', rubro TEXT DEFAULT '',
            puntaje_ia REAL DEFAULT 0, razon_ia TEXT DEFAULT '', calificado BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS plantillas_email (
            id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, categoria TEXT DEFAULT '',
            asunto TEXT NOT NULL, cuerpo TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS oportunidades (
            id SERIAL PRIMARY KEY, fuente TEXT NOT NULL, query TEXT DEFAULT '', nombre TEXT DEFAULT '',
            organismo TEXT DEFAULT '', region TEXT DEFAULT '', monto TEXT DEFAULT '', estado TEXT DEFAULT '',
            fecha TEXT DEFAULT '', url_ficha TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
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
            estado TEXT DEFAULT 'pendiente', fecha_envio TEXT, error TEXT,
            asunto TEXT DEFAULT '', cuerpo TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS scraping_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fuente TEXT NOT NULL, query TEXT DEFAULT '', resultados INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'completado', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS prospectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contacto_id INTEGER REFERENCES contactos(id) ON DELETE CASCADE,
            puntaje_ia REAL DEFAULT 0, razon TEXT DEFAULT '', estado TEXT DEFAULT 'nuevo',
            rubro TEXT DEFAULT '', producto_sugerido TEXT DEFAULT '', email_asunto TEXT DEFAULT '', email_cuerpo TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS config_prospeccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresas_target TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
            intervalo_horas INTEGER DEFAULT 6, activo INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS evaluaciones_ia (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '', apellido TEXT DEFAULT '', cargo TEXT DEFAULT '',
            email TEXT DEFAULT '', empresa TEXT DEFAULT '', rubro TEXT DEFAULT '',
            puntaje_ia REAL DEFAULT 0, razon_ia TEXT DEFAULT '', calificado INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS plantillas_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, categoria TEXT DEFAULT '',
            asunto TEXT NOT NULL, cuerpo TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS oportunidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fuente TEXT NOT NULL, query TEXT DEFAULT '', nombre TEXT DEFAULT '',
            organismo TEXT DEFAULT '', region TEXT DEFAULT '', monto TEXT DEFAULT '', estado TEXT DEFAULT '',
            fecha TEXT DEFAULT '', url_ficha TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')));
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


def listar_empresas(buscar: str = "", industria: str = "", fuente: str = "", limit: int = 100, offset: int = 0):
    like = "ILIKE" if USE_PG else "LIKE"
    ph = "%s" if USE_PG else "?"
    where, params = [], []
    if buscar:
        where.append(f"(nombre {like} {ph} OR rut {like} {ph} OR industria {like} {ph})")
        params += [f"%{buscar}%"] * 3
    if industria:
        where.append(f"industria = {ph}")
        params.append(industria)
    if fuente:
        where.append(f"fuente = {ph}")
        params.append(fuente)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db() as conn:
        q = f"SELECT * FROM empresas {where_sql} ORDER BY id DESC LIMIT {ph} OFFSET {ph}"
        return _fetchall(conn, q, (*params, limit, offset))


def fuentes_empresas() -> list[str]:
    with get_db() as conn:
        rows = _fetchall(conn, "SELECT DISTINCT fuente FROM empresas WHERE fuente != '' ORDER BY fuente")
        return [r["fuente"] for r in rows]


def industrias_empresas() -> list[str]:
    with get_db() as conn:
        rows = _fetchall(conn, "SELECT DISTINCT industria FROM empresas WHERE industria != '' ORDER BY industria")
        return [r["industria"] for r in rows]


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


def listar_contactos(buscar: str = "", empresa_id: int = None, fuente: str = "", calificado: str = "",
                      limit: int = 100, offset: int = 0):
    base = ("SELECT c.*, e.nombre as empresa_nombre, p.puntaje_ia FROM contactos c "
            "LEFT JOIN empresas e ON c.empresa_id = e.id LEFT JOIN prospectos p ON p.contacto_id = c.id ")
    like = "ILIKE" if USE_PG else "LIKE"
    ph = "%s" if USE_PG else "?"
    where, params = [], []
    if empresa_id:
        where.append(f"c.empresa_id = {ph}")
        params.append(empresa_id)
    if buscar:
        where.append(f"(c.nombre {like} {ph} OR c.apellido {like} {ph} OR c.email {like} {ph} OR c.cargo {like} {ph})")
        params += [f"%{buscar}%"] * 4
    if fuente:
        where.append(f"c.fuente = {ph}")
        params.append(fuente)
    if calificado == "si":
        where.append("p.puntaje_ia >= 50")
    elif calificado == "no":
        where.append("(p.puntaje_ia IS NULL OR p.puntaje_ia < 50)")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db() as conn:
        return _fetchall(conn, base + f"{where_sql} ORDER BY c.id DESC LIMIT {ph} OFFSET {ph}", (*params, limit, offset))


def fuentes_contactos() -> list[str]:
    with get_db() as conn:
        rows = _fetchall(conn, "SELECT DISTINCT fuente FROM contactos WHERE fuente != '' ORDER BY fuente")
        return [r["fuente"] for r in rows]


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


def marcar_email_enviado(id: int, estado: str, error: str = None, asunto: str = "", cuerpo: str = ""):
    now = "CURRENT_TIMESTAMP" if USE_PG else "datetime('now')"
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        _exec(conn, f"UPDATE emails_enviados SET estado = {ph}, fecha_envio = {now}, error = {ph}, "
                    f"asunto = {ph}, cuerpo = {ph} WHERE id = {ph}",
              (estado, error, asunto, cuerpo, id))


def listar_emails_por_contacto(contacto_id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn,
            f"SELECT ee.*, c.nombre as campana_nombre FROM emails_enviados ee "
            f"LEFT JOIN campanas c ON ee.campana_id = c.id "
            f"WHERE ee.contacto_id = {ph} ORDER BY ee.id DESC", (contacto_id,))


def obtener_deal_por_contacto(contacto_id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM pipeline WHERE contacto_id = {ph} ORDER BY id LIMIT 1", (contacto_id,))


def marcar_contacto_contactado(contacto_id: int, empresa_id: int = None):
    """Al enviar un correo exitosamente, refleja el avance en Pipeline: crea el deal
    si no existe, o lo sube de 'prospecto' a 'contactado'. No baja un deal que ya
    esta mas avanzado (propuesta/negociacion/cerrado)."""
    deal = obtener_deal_por_contacto(contacto_id)
    if not deal:
        crear_deal({"contacto_id": contacto_id, "empresa_id": empresa_id, "etapa": "contactado"})
    elif deal["etapa"] == "prospecto":
        actualizar_deal(deal["id"], {"etapa": "contactado"})


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


def eliminar_contactos_duplicados() -> dict:
    """Borra contactos con email repetido, quedandose con el mas antiguo (id menor) de
    cada email. Limpieza puntual para datos que quedaron duplicados antes del fix de
    deduplicacion en las importaciones manuales (Hunter/Apollo/CSV)."""
    with get_db() as conn:
        if USE_PG:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM contactos WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY email ORDER BY id) AS rn
                        FROM contactos WHERE email != ''
                    ) t WHERE t.rn > 1
                )
            """)
            borrados = cur.rowcount
        else:
            cur = conn.execute("""
                DELETE FROM contactos WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY email ORDER BY id) AS rn
                        FROM contactos WHERE email != ''
                    ) WHERE rn > 1
                )
            """)
            borrados = cur.rowcount
    return {"contactos_borrados": borrados}


def empresa_existe_por_dominio(dominio: str) -> int | None:
    like = "ILIKE" if USE_PG else "LIKE"
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT id FROM empresas WHERE sitio_web {like} {ph}", (f"%{dominio}%",))
        return row["id"] if row else None


# --- PLANTILLAS DE EMAIL ---

_plantilla_fields = ["nombre", "categoria", "asunto", "cuerpo"]

def crear_plantilla(data: dict) -> int:
    vals = {k: data.get(k, "") for k in _plantilla_fields}
    cols = ", ".join(_plantilla_fields)
    with get_db() as conn:
        if USE_PG:
            phs = ", ".join(f"%({k})s" for k in _plantilla_fields)
            cur = conn.cursor()
            cur.execute(f"INSERT INTO plantillas_email ({cols}) VALUES ({phs}) RETURNING id", vals)
            return cur.fetchone()["id"]
        else:
            phs = ", ".join(f":{k}" for k in _plantilla_fields)
            return conn.execute(f"INSERT INTO plantillas_email ({cols}) VALUES ({phs})", vals).lastrowid


def listar_plantillas():
    with get_db() as conn:
        return _fetchall(conn, "SELECT * FROM plantillas_email ORDER BY id DESC")


def obtener_plantilla(id: int):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM plantillas_email WHERE id = {ph}", (id,))


def actualizar_plantilla(id: int, data: dict):
    fields = {k: v for k, v in data.items() if k in _plantilla_fields}
    if not fields:
        return
    if USE_PG:
        set_c = ", ".join(f"{k} = %({k})s" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.cursor().execute(f"UPDATE plantillas_email SET {set_c} WHERE id = %(id)s", fields)
    else:
        set_c = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = id
        with get_db() as conn:
            conn.execute(f"UPDATE plantillas_email SET {set_c} WHERE id = :id", fields)


def eliminar_plantilla(id: int):
    with get_db() as conn:
        _exec(conn, "DELETE FROM plantillas_email WHERE id = %s" if USE_PG else "DELETE FROM plantillas_email WHERE id = ?", (id,))


# --- PROSPECTOS ---

def crear_prospecto(contacto_id: int, puntaje: float, razon: str, rubro: str = "",
                     producto_sugerido: str = "", email_asunto: str = "", email_cuerpo: str = "") -> int:
    ph = "%s" if USE_PG else "?"
    params = (puntaje, razon, rubro, producto_sugerido, email_asunto, email_cuerpo, contacto_id)
    with get_db() as conn:
        exists = _fetchone(conn, f"SELECT 1 as x FROM prospectos WHERE contacto_id = {ph}", (contacto_id,))
        if exists:
            _exec(conn, f"UPDATE prospectos SET puntaje_ia = {ph}, razon = {ph}, rubro = {ph}, "
                        f"producto_sugerido = {ph}, email_asunto = {ph}, email_cuerpo = {ph} WHERE contacto_id = {ph}",
                  params)
            return contacto_id
        cols = "contacto_id, puntaje_ia, razon, rubro, producto_sugerido, email_asunto, email_cuerpo"
        vals = (contacto_id, puntaje, razon, rubro, producto_sugerido, email_asunto, email_cuerpo)
        if USE_PG:
            cur = conn.cursor()
            cur.execute(f"INSERT INTO prospectos ({cols}) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph}) RETURNING id", vals)
            return cur.fetchone()["id"]
        else:
            return conn.execute(f"INSERT INTO prospectos ({cols}) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})", vals).lastrowid


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


# --- EVALUACIONES IA (log completo, califiquen o no) ---

def guardar_evaluaciones_ia(evaluados: list[dict]):
    """Registra TODOS los contactos que evaluo la IA en una corrida de prospeccion,
    califiquen o no. Es un log de auditoria, no se deduplica ni se mezcla con
    Empresas/Contactos -- eso permite revisar despues si el filtro estuvo bien."""
    if not evaluados:
        return
    ph = "%s" if USE_PG else "?"
    cols = "nombre, apellido, cargo, email, empresa, rubro, puntaje_ia, razon_ia, calificado"
    with get_db() as conn:
        for e in evaluados:
            calificado = e.get("calificado", False)
            vals = (e.get("nombre", ""), e.get("apellido", ""), e.get("cargo", ""), e.get("email", ""),
                    e.get("empresa", ""), e.get("rubro", ""), e.get("puntaje_ia", 0), e.get("razon_ia", ""),
                    calificado if USE_PG else int(calificado))
            _exec(conn, f"INSERT INTO evaluaciones_ia ({cols}) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", vals)


def listar_evaluaciones_ia(limit: int = 100000):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn, f"SELECT * FROM evaluaciones_ia ORDER BY id DESC LIMIT {ph}", (limit,))


# --- OPORTUNIDADES (log de cada busqueda de licitaciones/SEIA, sin filtrar) ---

def guardar_oportunidades(fuente: str, query: str, items: list[dict]):
    """Registra cada resultado de una busqueda de Mercado Publico o SEIA, tal cual
    aparecio, para que quede historial exportable a Sheets aunque no se importe al CRM."""
    if not items:
        return
    ph = "%s" if USE_PG else "?"
    cols = "fuente, query, nombre, organismo, region, monto, estado, fecha, url_ficha"
    with get_db() as conn:
        for it in items:
            vals = (fuente, query, it.get("nombre", ""), it.get("organismo", ""), it.get("region", ""),
                    str(it.get("monto", "")), it.get("estado", ""), it.get("fecha", ""), it.get("url_ficha", ""))
            _exec(conn, f"INSERT INTO oportunidades ({cols}) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})", vals)


def listar_oportunidades(limit: int = 100000):
    ph = "%s" if USE_PG else "?"
    with get_db() as conn:
        return _fetchall(conn, f"SELECT * FROM oportunidades ORDER BY id DESC LIMIT {ph}", (limit,))


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
            return {"empresas_target": [], "keywords": [], "intervalo_horas": 6, "activo": False, "ultima_ejecucion": None}
        return {
            "empresas_target": json.loads(row.get("empresas_target", "[]")),
            "keywords": json.loads(row.get("keywords", "[]")),
            "intervalo_horas": row.get("intervalo_horas", 6),
            "activo": bool(row.get("activo", False)),
            "ultima_ejecucion": row.get("ultima_ejecucion"),
        }


def marcar_ejecucion_prospeccion():
    now = "CURRENT_TIMESTAMP" if USE_PG else "datetime('now')"
    with get_db() as conn:
        _exec(conn, f"UPDATE config_prospeccion SET ultima_ejecucion = {now}")


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
