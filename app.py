from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
import ssl
import threading
import time
from urllib.parse import unquote, urlparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

import bcrypt
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import BadRequest


ROOT = Path(__file__).resolve().parent
ADMIN_MATRICULA = "777"
ADMIN_PASSWORD_HASH = (
    "$2y$12$s.fXFDO7BPiOnsY5JmSiveHScrd2ZBnF5Ph3HCryM9AuHBTu0A1/O"
)
EXAMPLE_PRODUCTS = [
    ("Playera Pimpz Classic", "Pimpz", "Ropa", 299.00, 12, "PZ000000000001", "2 por $499"),
    ("Gorra Pimpz Logo", "Pimpz", "Gorras", 349.00, 8, "PZ000000000002", None),
    ("Tenis Street Pimpz", "Pimpz", "Tenis", 899.00, 6, "PZ000000000003", None),
    ("Sudadera Pimpz Urban", "Pimpz", "Ropa", 649.00, 5, "PZ000000000004", None),
    ("Perfume Pimpz Night", "Pimpz", "Perfumes", 499.00, 10, "PZ000000000005", "15% de descuento"),
    ("Cinturón Pimpz", "Pimpz", "Accesorios", 249.00, 9, "PZ000000000006", None),
    ("Mochila Pimpz Street", "Pimpz", "Accesorios", 579.00, 4, "PZ000000000007", None),
    ("Playera Pimpz Premium", "Pimpz", "Ropa", 399.00, 7, "PZ000000000008", None),
]

app = Flask(
    __name__,
    static_folder=str(ROOT / "assets"),
    static_url_path="/assets",
    template_folder=str(ROOT / "templates"),
)
app.secret_key = os.getenv("SECRET_KEY", "local-development-key-change-me")

# Base de datos:
# - DATABASE_URL que empieza con postgres:// -> PostgreSQL (Aiven PostgreSQL, gratis).
# - DATABASE_URL que empieza con mysql://    -> MySQL.
# - Sin DATABASE_URL                         -> SQLite local en data/pascual.sqlite3.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
USE_MYSQL = DATABASE_URL.startswith("mysql")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg2.IntegrityError)
elif USE_MYSQL:
    import pymysql
    import pymysql.cursors

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, pymysql.err.IntegrityError)
else:
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)

# Búsquedas sin distinguir mayúsculas (en PostgreSQL LIKE sí las distingue).
LIKE = "ILIKE" if USE_POSTGRES else "LIKE"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

_schema_lock = threading.Lock()
_schema_initialized = False

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre VARCHAR(100) NOT NULL,
        descripcion VARCHAR(255) NOT NULL,
        precio DECIMAL(10, 2) NOT NULL,
        existencia INT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS estudiantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        matricula VARCHAR(20) NOT NULL UNIQUE,
        nombre VARCHAR(80) NOT NULL,
        apellido VARCHAR(80) NOT NULL,
        carrera VARCHAR(120) NOT NULL,
        correo VARCHAR(120) NOT NULL,
        promedio DECIMAL(4, 2) NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS respuestas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre VARCHAR(120) NOT NULL,
        carrera VARCHAR(120) NOT NULL,
        factor VARCHAR(120) NOT NULL,
        instalaciones VARCHAR(60) NOT NULL,
        mejora TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visitante_id CHAR(36) NOT NULL,
        sesion_id CHAR(36) NOT NULL,
        usuario_id INT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('vista', 'clic', 'tiempo')),
        pagina VARCHAR(200) NOT NULL,
        elemento VARCHAR(100) NULL,
        segundos SMALLINT UNSIGNED NULL,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES estudiantes(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_eventos_visitante ON eventos(visitante_id)",
    "CREATE INDEX IF NOT EXISTS idx_eventos_sesion ON eventos(sesion_id)",
    """
    CREATE TABLE IF NOT EXISTS productos_tienda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre VARCHAR(120) NOT NULL,
        marca VARCHAR(80) NOT NULL,
        categoria VARCHAR(60) NOT NULL,
        precio DECIMAL(10, 2) NOT NULL,
        existencia INT NOT NULL,
        codigo_barras VARCHAR(20) NOT NULL UNIQUE,
        promocion VARCHAR(120) NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_mensajes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        autor_matricula VARCHAR(20) NOT NULL,
        autor_nombre VARCHAR(180) NOT NULL,
        mensaje VARCHAR(500) NOT NULL,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_creado ON chat_mensajes(creado_en)",
)

SCHEMA_MYSQL = (
    """
    CREATE TABLE IF NOT EXISTS productos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(100) NOT NULL,
        descripcion VARCHAR(255) NOT NULL,
        precio DECIMAL(10, 2) NOT NULL,
        existencia INT NOT NULL
    ) DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS estudiantes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        matricula VARCHAR(20) NOT NULL UNIQUE,
        nombre VARCHAR(80) NOT NULL,
        apellido VARCHAR(80) NOT NULL,
        carrera VARCHAR(120) NOT NULL,
        correo VARCHAR(120) NOT NULL,
        promedio DECIMAL(4, 2) NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    ) DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS respuestas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(120) NOT NULL,
        carrera VARCHAR(120) NOT NULL,
        factor VARCHAR(120) NOT NULL,
        instalaciones VARCHAR(60) NOT NULL,
        mejora TEXT NOT NULL
    ) DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        visitante_id CHAR(36) NOT NULL,
        sesion_id CHAR(36) NOT NULL,
        usuario_id INT NULL,
        tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('vista', 'clic', 'tiempo')),
        pagina VARCHAR(200) NOT NULL,
        elemento VARCHAR(100) NULL,
        segundos SMALLINT UNSIGNED NULL,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_eventos_visitante (visitante_id),
        INDEX idx_eventos_sesion (sesion_id),
        FOREIGN KEY (usuario_id) REFERENCES estudiantes(id) ON DELETE SET NULL
    ) DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS productos_tienda (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(120) NOT NULL,
        marca VARCHAR(80) NOT NULL,
        categoria VARCHAR(60) NOT NULL,
        precio DECIMAL(10, 2) NOT NULL,
        existencia INT NOT NULL,
        codigo_barras VARCHAR(20) NOT NULL UNIQUE,
        promocion VARCHAR(120) NULL
    ) DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_mensajes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        autor_matricula VARCHAR(20) NOT NULL,
        autor_nombre VARCHAR(180) NOT NULL,
        mensaje VARCHAR(500) NOT NULL,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_chat_creado (creado_en)
    ) DEFAULT CHARSET=utf8mb4
    """,
)

SCHEMA_POSTGRES = tuple(
    statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    .replace("SMALLINT UNSIGNED", "SMALLINT")
    for statement in SCHEMA
)


def date_format(column: str, pattern: str) -> str:
    """Formatea una fecha en SQL para SQLite, MySQL o PostgreSQL (pattern usa %d %m %H %M %S)."""
    if USE_POSTGRES:
        return "to_char({}, '{}')".format(
            column,
            pattern.replace("%d", "DD").replace("%m", "MM").replace("%H", "HH24")
            .replace("%M", "MI").replace("%S", "SS"),
        )
    if USE_MYSQL:
        # En MySQL los minutos son %i y el % se escribe %% por los parámetros de PyMySQL.
        return "DATE_FORMAT({}, '{}')".format(
            column, pattern.replace("%M", "%i").replace("%", "%%")
        )
    return "strftime('{}', {})".format(pattern, column)


def mysql_ssl_context():
    # Aiven exige conexión cifrada. Si pegas el certificado CA en DB_SSL_CA se
    # verifica; si no, la conexión va cifrada sin verificar el certificado.
    ca_text = os.getenv("DB_SSL_CA", "").strip()
    if ca_text:
        return ssl.create_default_context(cadata=ca_text)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def mysql_connection():
    url = urlparse(DATABASE_URL)
    return pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=unquote(url.username or ""),
        password=unquote(url.password or ""),
        database=(url.path or "/defaultdb").lstrip("/") or "defaultdb",
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
        init_command="SET time_zone = '-06:00'",
        ssl=mysql_ssl_context(),
        cursorclass=pymysql.cursors.DictCursor,
    )


def postgres_connection():
    connection = psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        options="-c timezone=America/Mexico_City",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    connection.autocommit = True
    return connection


def normalize_row(row) -> dict:
    # MySQL y PostgreSQL devuelven Decimal en DECIMAL y SUM(); se convierten como lo hace SQLite.
    result = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        result[key] = value
    return result


def get_db():
    if "db" not in g and USE_POSTGRES:
        g.db = postgres_connection()
    if "db" not in g and USE_MYSQL:
        g.db = mysql_connection()
    if "db" not in g:
        configured_path = os.getenv("DB_PATH")
        database_path = (
            Path(configured_path)
            if configured_path
            else ROOT / "data" / "pascual.sqlite3"
        )
        database_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path = ROOT / "data" / "awos.sqlite3"
        if not configured_path and not database_path.exists() and legacy_path.exists():
            shutil.copy2(legacy_path, database_path)
        g.db = sqlite3.connect(database_path, timeout=5, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def sqlite_parameters(params: tuple | list) -> tuple:
    return tuple(str(value) if isinstance(value, Decimal) else value for value in params)


def run_sql(sql: str, params: tuple | list = ()):
    if USE_POSTGRES or USE_MYSQL:
        cursor = get_db().cursor()
        cursor.execute(sql, sqlite_parameters(params))
        return cursor
    return get_db().execute(sql.replace("%s", "?"), sqlite_parameters(params))


def query_all(sql: str, params: tuple | list = ()) -> list[dict]:
    return [normalize_row(row) for row in run_sql(sql, params).fetchall()]


def query_one(sql: str, params: tuple | list = ()) -> dict | None:
    row = run_sql(sql, params).fetchone()
    return normalize_row(row) if row is not None else None


def query_value(sql: str, params: tuple | list = ()):
    row = query_one(sql, params)
    return next(iter(row.values())) if row else None


def execute(sql: str, params: tuple | list = ()) -> tuple[int, int]:
    if USE_POSTGRES and sql.lstrip().upper().startswith("INSERT"):
        # PostgreSQL no tiene lastrowid; se pide el id con RETURNING.
        cursor = run_sql(sql.rstrip() + " RETURNING id", params)
        row = cursor.fetchone()
        return cursor.rowcount, (row["id"] if row else None)
    cursor = run_sql(sql, params)
    return cursor.rowcount, cursor.lastrowid


@app.before_request
def initialize_database():
    global _schema_initialized
    if request.endpoint == "static":
        return
    if _schema_initialized:
        return
    with _schema_lock:
        if _schema_initialized:
            return
        schema = SCHEMA_POSTGRES if USE_POSTGRES else SCHEMA_MYSQL if USE_MYSQL else SCHEMA
        for statement in schema:
            run_sql(statement)
        _schema_initialized = True


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def page(template: str, title: str, **context):
    if template == "p4.html":
        context.setdefault("styles_p4", True)
        context.setdefault("scripts_p4", True)
    if template == "p8.html":
        context.setdefault("styles_p8", True)
    if template == "p9.html":
        context.setdefault("styles_p9", True)
        context.setdefault("scripts_p9_map", context.get("view") == "public")
        context.setdefault("scripts_p9_chat", context.get("view") == "chat")
    return render_template(template, title=title, **context)


def path_url(path: str) -> str:
    return url_for("dispatch", path=path)


def require_login():
    if not session.get("usuario"):
        flash("Inicia sesión para continuar.", "info")
        return redirect(path_url("p5/login"))
    return None


def password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    normalized_hash = stored_hash.replace("$2y$", "$2b$", 1)
    try:
        return bcrypt.checkpw(password.encode("utf-8"), normalized_hash.encode("ascii"))
    except ValueError:
        return False


def get_student() -> dict | None:
    matricula = session.get("usuario")
    if not matricula:
        return None
    student = query_one(
        "SELECT id, matricula, nombre, apellido FROM estudiantes WHERE matricula=%s",
        (matricula,),
    )
    if student is None:
        session.pop("usuario", None)
    return student


def product_form_data() -> dict:
    return {
        "nombre": request.form.get("nombre", "").strip(),
        "marca": request.form.get("marca", "").strip(),
        "categoria": request.form.get("categoria", "").strip(),
        "precio": request.form.get("precio", "").strip(),
        "existencia": request.form.get("existencia", "").strip(),
        "codigo_barras": request.form.get("codigo_barras", "").strip(),
        "promocion": request.form.get("promocion", "").strip(),
    }


def validate_store_product(data: dict) -> str:
    limits = (
        ("nombre", "El nombre del producto es obligatorio.", 120),
        ("marca", "La marca es obligatoria.", 80),
        ("categoria", "La categoría es obligatoria.", 60),
        ("codigo_barras", "El código de barras es obligatorio.", 20),
    )
    for field, message, limit in limits:
        if not data[field]:
            return message
        if len(data[field]) > limit:
            return f"El campo {field.replace('_', ' ')} no puede pasar de {limit} caracteres."
    try:
        price = Decimal(data["precio"])
        if not price.is_finite() or price < 0 or price > Decimal("99999999.99"):
            return "El precio debe ser un número entre 0 y 99,999,999.99."
    except InvalidOperation:
        return "El precio debe ser un número entre 0 y 99,999,999.99."
    try:
        stock = int(data["existencia"])
        if stock < 0 or str(stock) != data["existencia"]:
            return "La existencia debe ser un número entero mayor o igual a cero."
    except ValueError:
        return "La existencia debe ser un número entero mayor o igual a cero."
    if len(data["promocion"]) > 120:
        return "La promoción no puede pasar de 120 caracteres."
    return ""


def save_store_product(data: dict, product_id: int | None = None):
    values = (
        data["nombre"],
        data["marca"],
        data["categoria"],
        Decimal(data["precio"]),
        int(data["existencia"]),
        data["codigo_barras"],
        data["promocion"] or None,
    )
    if product_id is None:
        return execute(
            """
            INSERT INTO productos_tienda
                (nombre, marca, categoria, precio, existencia, codigo_barras, promocion)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    return execute(
        """
        UPDATE productos_tienda SET nombre=%s, marca=%s, categoria=%s, precio=%s,
            existencia=%s, codigo_barras=%s, promocion=%s WHERE id=%s
        """,
        (*values, product_id),
    )


def store_products(search: str = "", category: str = "") -> list[dict]:
    conditions = []
    params = []
    if search:
        conditions.append(
            f"(nombre {LIKE} %s OR marca {LIKE} %s OR categoria {LIKE} %s OR codigo_barras {LIKE} %s)"
        )
        params.extend([f"%{search}%"] * 4)
    if category:
        conditions.append("categoria=%s")
        params.append(category)
    sql = "SELECT * FROM productos_tienda"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY categoria, nombre"
    return query_all(sql, tuple(params))


def store_categories() -> list[str]:
    return [row["categoria"] for row in query_all(
        "SELECT DISTINCT categoria FROM productos_tienda ORDER BY categoria"
    )]


def store_summary() -> dict:
    summary = query_one(
        """
        SELECT COUNT(*) AS productos,
            COALESCE(SUM(existencia), 0) AS piezas,
            COALESCE(SUM(precio * existencia), 0) AS inventario,
            COALESCE(SUM(CASE WHEN existencia > 0 AND existencia < 10 THEN 1 ELSE 0 END), 0) AS pocas,
            COALESCE(SUM(CASE WHEN existencia = 0 THEN 1 ELSE 0 END), 0) AS agotados,
            COALESCE(SUM(CASE WHEN promocion IS NOT NULL AND promocion <> '' THEN 1 ELSE 0 END), 0) AS promociones
        FROM productos_tienda
        """
    )
    summary["inventario"] = float(summary["inventario"])
    return summary


def new_branches() -> list[dict]:
    return [
        {
            "nombre": "Pimpz · Sucursal principal",
            "direccion": "Av. Agricultura 258, Tultitlán, Estado de México",
            "horario": "Lunes a domingo de 10:00 a. m. a 7:00 p. m.",
            "lat": 19.645,
            "lng": -99.16944,
        },
    ]


def get_branches() -> list[dict]:
    if not session.get("sucursales_pimpz"):
        session["sucursales_pimpz"] = new_branches()
    return session["sucursales_pimpz"]


def chat_messages(since: int = 0, limit: int = 100) -> list[dict]:
    limit = max(1, min(200, limit))
    if since > 0:
        return query_all(
            """
            SELECT id, autor_matricula, autor_nombre, mensaje,
                """ + date_format("creado_en", "%d/%m %H:%M") + """ AS hora
            FROM chat_mensajes WHERE id > %s ORDER BY id ASC LIMIT %s
            """,
            (since, limit),
        )
    messages = query_all(
        """
        SELECT id, autor_matricula, autor_nombre, mensaje,
            """ + date_format("creado_en", "%d/%m %H:%M") + """ AS hora
        FROM chat_mensajes ORDER BY id DESC LIMIT %s
        """,
        (limit,),
    )
    return list(reversed(messages))


def admin_active() -> bool:
    return bool(session.get("admin_p9"))


def product_destination() -> str:
    return "p9/admin" if admin_active() else "p9"


def analytics_json():
    summary = query_one(
        """
        SELECT COUNT(DISTINCT visitante_id) AS visitantes,
            COUNT(DISTINCT sesion_id) AS sesiones,
            COUNT(DISTINCT usuario_id) AS usuarios,
            COALESCE(SUM(CASE WHEN tipo='vista' THEN 1 ELSE 0 END), 0) AS vistas,
            COALESCE(SUM(CASE WHEN tipo='clic' THEN 1 ELSE 0 END), 0) AS clics
        FROM eventos
        """
    )
    average = query_value(
        """
        SELECT COALESCE(ROUND(AVG(total)), 0) AS promedio
        FROM (SELECT SUM(segundos) AS total FROM eventos
              WHERE tipo='tiempo' GROUP BY sesion_id) AS t
        """
    )
    summary["tiempo_promedio"] = average
    pages = query_all(
        """
        SELECT pagina, SUM(CASE WHEN tipo='vista' THEN 1 ELSE 0 END) AS vistas, SUM(CASE WHEN tipo='clic' THEN 1 ELSE 0 END) AS clics,
            COALESCE(SUM(segundos), 0) AS segundos
        FROM eventos GROUP BY pagina ORDER BY vistas DESC LIMIT 10
        """
    )
    clicks = query_all(
        """
        SELECT elemento, pagina, COUNT(*) AS total FROM eventos
        WHERE tipo='clic' GROUP BY elemento, pagina ORDER BY total DESC LIMIT 10
        """
    )
    users = query_all(
        """
        SELECT COALESCE(u.nombre, '(anónimos)') AS nombre,
            COALESCE(u.carrera, '—') AS carrera,
            COUNT(DISTINCT e.sesion_id) AS sesiones,
            SUM(CASE WHEN e.tipo='vista' THEN 1 ELSE 0 END) AS vistas, SUM(CASE WHEN e.tipo='clic' THEN 1 ELSE 0 END) AS clics,
            COALESCE(SUM(e.segundos), 0) AS segundos, MAX(e.creado_en) AS ultima
        FROM eventos e LEFT JOIN estudiantes u ON u.id=e.usuario_id
        GROUP BY e.usuario_id, u.nombre, u.carrera ORDER BY ultima DESC
        """
    )
    careers = query_all(
        """
        SELECT u.carrera, COUNT(DISTINCT u.id) AS usuarios,
            SUM(CASE WHEN e.tipo='clic' THEN 1 ELSE 0 END) AS clics, COALESCE(SUM(e.segundos), 0) AS segundos
        FROM eventos e JOIN estudiantes u ON u.id=e.usuario_id
        GROUP BY u.carrera ORDER BY segundos DESC
        """
    )
    recent = query_all(
        """
        SELECT """ + date_format("e.creado_en", "%H:%M:%S") + """ AS hora,
            COALESCE(u.nombre, 'Anónimo') AS nombre, e.tipo, e.pagina,
            e.elemento, e.segundos
        FROM eventos e LEFT JOIN estudiantes u ON u.id=e.usuario_id
        ORDER BY e.id DESC LIMIT 15
        """
    )
    for row in users:
        if row["ultima"] is not None:
            row["ultima"] = str(row["ultima"])
    return {
        "resumen": summary,
        "paginas": pages,
        "clics": clicks,
        "usuarios": users,
        "carreras": careers,
        "recientes": recent,
    }


def handle_p3(parts: list[str]):
    view = parts[0] if parts else ""
    product_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    if view == "":
        return page(
            "p3.html",
            "Práctica 3 · CRUD de productos",
            products=query_all("SELECT * FROM productos ORDER BY nombre"),
        )
    if view == "crear":
        if request.method == "POST":
            price = request.form.get("precio", "")
            stock = request.form.get("existencia", "")
            try:
                parsed_price = Decimal(price)
                parsed_stock = int(stock)
                if parsed_price < 0 or parsed_stock < 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                flash("El precio y la existencia deben ser números válidos.", "error")
                return redirect(path_url("p3/crear"))
            execute(
                "INSERT INTO productos (nombre, descripcion, precio, existencia) "
                "VALUES (%s, %s, %s, %s)",
                (
                    request.form.get("nombre", "").strip(),
                    request.form.get("descripcion", "").strip(),
                    parsed_price,
                    parsed_stock,
                ),
            )
            flash("Producto agregado correctamente.", "exito")
            return redirect(path_url("p3"))
        return page("p3.html", "Agregar producto", mode="form", product=None)
    if view == "editar" and product_id is not None:
        product = query_one("SELECT * FROM productos WHERE id=%s", (product_id,))
        if product is None:
            flash("El producto que buscas no existe.", "error")
            return redirect(path_url("p3"))
        if request.method == "POST":
            try:
                price = Decimal(request.form.get("precio", ""))
                stock = int(request.form.get("existencia", ""))
                if price < 0 or stock < 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                flash("El precio y la existencia deben ser números válidos.", "error")
                return redirect(path_url(f"p3/editar/{product_id}"))
            execute(
                """
                UPDATE productos SET nombre=%s, descripcion=%s, precio=%s,
                    existencia=%s WHERE id=%s
                """,
                (
                    request.form.get("nombre", "").strip(),
                    request.form.get("descripcion", "").strip(),
                    price,
                    stock,
                    product_id,
                ),
            )
            flash("Producto modificado correctamente.", "exito")
            return redirect(path_url("p3"))
        return page("p3.html", "Editar producto", mode="form", product=product)
    if view == "eliminar" and product_id is not None and request.method == "POST":
        execute("DELETE FROM productos WHERE id=%s", (product_id,))
        flash("Producto eliminado correctamente.", "info")
        return redirect(path_url("p3"))
    return redirect(path_url("p3"))


def handle_p5(parts: list[str]):
    view = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    student_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if view == "login":
        if request.method == "POST":
            matricula = request.form.get("usuario", "").strip()
            student = query_one(
                "SELECT * FROM estudiantes WHERE matricula=%s", (matricula,)
            )
            if student and verify_password(
                request.form.get("contrasena", ""), student["password_hash"]
            ):
                session["usuario"] = student["matricula"]
                flash(f"¡Hola {student['nombre']}! Iniciaste sesión.", "exito")
                return redirect(path_url("p5"))
            flash("Matrícula o contraseña incorrectos.", "error")
        return page("p5.html", "Iniciar sesión", view="login")
    if view == "logout":
        session.pop("usuario", None)
        flash("Cerraste sesión correctamente.", "info")
        return redirect(path_url("p5/login"))
    if view == "registro":
        if request.method == "POST":
            password = request.form.get("contrasena", "")
            if len(password) < 8:
                flash("La contraseña debe tener al menos 8 caracteres.", "error")
                return redirect(path_url("p5/registro"))
            if password != request.form.get("repetir_contrasena", ""):
                flash("Las dos contraseñas no son iguales.", "error")
                return redirect(path_url("p5/registro"))
            try:
                execute(
                    """
                    INSERT INTO estudiantes
                        (matricula, nombre, apellido, carrera, correo, promedio, password_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.form.get("matricula", "").strip(),
                        request.form.get("nombre", "").strip(),
                        request.form.get("apellido", "").strip(),
                        request.form.get("carrera", "").strip(),
                        request.form.get("correo", "").strip(),
                        Decimal(request.form.get("promedio", "0")),
                        password_hash(password),
                    ),
                )
            except INTEGRITY_ERRORS:
                flash("Ya existe un estudiante con esa matrícula.", "error")
                return redirect(path_url("p5/registro"))
            flash("¡Cuenta creada! Ya puedes iniciar sesión.", "exito")
            return redirect(path_url("p5/login"))
        return page("p5.html", "Registrar estudiante", view="registro")

    login_redirect = require_login()
    if login_redirect:
        return login_redirect
    if view == "estudiantes" and action == "":
        return page(
            "p5.html",
            "Lista de estudiantes",
            view="lista",
            students=query_all(
                "SELECT id, matricula, nombre, apellido, carrera, correo, promedio "
                "FROM estudiantes ORDER BY apellido"
            ),
        )
    if view == "estudiantes" and action == "crear":
        if request.method == "POST":
            password = request.form.get("contrasena", "")
            if not password:
                flash("La contraseña no puede quedar vacía.", "error")
                return redirect(path_url("p5/estudiantes/crear"))
            try:
                execute(
                    """
                    INSERT INTO estudiantes
                        (matricula, nombre, apellido, carrera, correo, promedio, password_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.form.get("matricula", "").strip(),
                        request.form.get("nombre", "").strip(),
                        request.form.get("apellido", "").strip(),
                        request.form.get("carrera", "").strip(),
                        request.form.get("correo", "").strip(),
                        Decimal(request.form.get("promedio", "0")),
                        password_hash(password),
                    ),
                )
            except INTEGRITY_ERRORS:
                flash("Ya existe un estudiante con esa matrícula.", "error")
                return redirect(path_url("p5/estudiantes/crear"))
            flash("Estudiante agregado correctamente.", "exito")
            return redirect(path_url("p5/estudiantes"))
        return page("p5.html", "Agregar estudiante", view="student_form", student=None)
    if view == "estudiantes" and action == "editar" and student_id is not None:
        student = query_one(
            """
            SELECT id, matricula, nombre, apellido, carrera, correo, promedio
            FROM estudiantes WHERE id=%s
            """,
            (student_id,),
        )
        if student is None:
            flash("El estudiante que buscas no existe.", "error")
            return redirect(path_url("p5/estudiantes"))
        if request.method == "POST":
            try:
                execute(
                    """
                    UPDATE estudiantes SET matricula=%s, nombre=%s, apellido=%s,
                        carrera=%s, correo=%s, promedio=%s WHERE id=%s
                    """,
                    (
                        request.form.get("matricula", "").strip(),
                        request.form.get("nombre", "").strip(),
                        request.form.get("apellido", "").strip(),
                        request.form.get("carrera", "").strip(),
                        request.form.get("correo", "").strip(),
                        Decimal(request.form.get("promedio", "0")),
                        student_id,
                    ),
                )
                flash("Estudiante modificado correctamente.", "exito")
            except INTEGRITY_ERRORS:
                flash("Ya existe un estudiante con esa matrícula.", "error")
            return redirect(path_url("p5/estudiantes"))
        return page("p5.html", "Editar estudiante", view="student_form", student=student)
    if view == "estudiantes" and action == "eliminar" and student_id is not None:
        if request.method == "POST":
            execute("DELETE FROM estudiantes WHERE id=%s", (student_id,))
            flash("Estudiante eliminado correctamente.", "info")
        return redirect(path_url("p5/estudiantes"))
    return page("p5.html", "Práctica 5 · Gestión de estudiantes", view="home")


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def dispatch(path: str):
    parts = [part for part in path.split("/") if part]
    section = parts[0] if parts else ""
    remainder = parts[1:]
    if section == "p3":
        return handle_p3(remainder)
    if section == "p5":
        return handle_p5(remainder)
    if section == "p6":
        return handle_p6(remainder)
    if section == "p8":
        return handle_p8(remainder)
    if section == "p9":
        return handle_p9(remainder)
    if section == "p4":
        return page("p4.html", "Práctica 4 · Sitio personal", scripts_p4=True)
    if section == "p7":
        return handle_p7(remainder)
    cards = [
        ("Práctica 3", "CRUD completo: insertar, consultar, modificar y eliminar.", "p3"),
        ("Práctica 4", "Perfil, trayecto a Pimpz y mapas de Tultitlán.", "p4"),
        ("Práctica 5", "Sesiones, inicio de sesión y CRUD de estudiantes.", "p5"),
        ("Práctica 6", "Encuesta de satisfacción sobre la UPVM.", "p6"),
        ("Práctica 7", "Incrustación de un video en la página.", "p7"),
        ("Práctica 8", "Métricas de visitas, clics y tiempo en el sitio.", "p8"),
        ("Práctica 9", "Tienda Pimpz con ropa, accesorios, chat, video y sucursal.", "p9"),
    ]
    return page("index.html", "Pascual · Prácticas Web", cards=cards)


def handle_p6(parts: list[str]):
    view = parts[0] if parts else ""
    if view == "encuesta":
        if request.method == "POST":
            execute(
                """
                INSERT INTO respuestas (nombre, carrera, factor, instalaciones, mejora)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request.form.get("nombre", "").strip(),
                    request.form.get("carrera", ""),
                    request.form.get("factor", ""),
                    request.form.get("instalaciones", ""),
                    request.form.get("mejora", "").strip(),
                ),
            )
            return redirect(path_url("p6/regalo"))
        return page(
            "p6.html",
            "Formulario de encuesta",
            view="encuesta",
            total=query_value("SELECT COUNT(*) FROM respuestas"),
        )
    if view == "regalo":
        return page("p6.html", "¡Gracias por tu respuesta!", view="regalo")
    return page("p6.html", "Práctica 6 · Encuesta UPVM", view="home")


def handle_p7(parts: list[str]):
    view = parts[0] if parts else ""
    return page(
        "p7.html",
        "Video de Pimpz · Práctica 7" if view == "video" else "Práctica 7 · Incrustación de un video",
        video=view == "video",
    )


def handle_p8(parts: list[str]):
    view = parts[0] if parts else ""
    student = get_student()
    if student:
        visitor = request.cookies.get("pascual_visitante_id")
        if visitor:
            execute(
                "UPDATE eventos SET usuario_id=%s "
                "WHERE visitante_id=%s AND usuario_id IS NULL",
                (student["id"], visitor),
            )
    if view == "eventos":
        if request.method != "POST":
            return jsonify(error="Usa POST para registrar eventos."), 405, {"Allow": "POST"}
        try:
            data = request.get_json(force=True)
        except BadRequest:
            return jsonify(error="Evento inválido."), 400
        if not isinstance(data, dict):
            return jsonify(error="Evento inválido."), 400
        event_type = data.get("tipo", "")
        visitor_id = data.get("visitante_id", "")
        session_id = data.get("sesion_id", "")
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if (
            not isinstance(event_type, str)
            or event_type not in {"vista", "clic", "tiempo"}
            or not isinstance(visitor_id, str)
            or not uuid_pattern.fullmatch(visitor_id)
            or not isinstance(session_id, str)
            or not uuid_pattern.fullmatch(session_id)
        ):
            return jsonify(error="Evento inválido."), 400
        raw_page = data.get("pagina", "")
        page_name = "" if raw_page is None else str(raw_page)[:200]
        if not page_name:
            return jsonify(error="Falta la página del evento."), 400
        element = str(data.get("elemento", ""))[:100] if event_type == "clic" else None
        try:
            seconds = max(0, min(3600, int(data.get("segundos", 0)))) if event_type == "tiempo" else None
        except (TypeError, ValueError):
            seconds = 0
        execute(
            """
            INSERT INTO eventos
                (visitante_id, sesion_id, usuario_id, tipo, pagina, elemento, segundos)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                visitor_id,
                session_id,
                student["id"] if student else None,
                event_type,
                page_name,
                element,
                seconds,
            ),
        )
        return "", 204
    if view == "metricas":
        if request.method != "GET":
            return jsonify(error="Usa GET para consultar las métricas."), 405, {"Allow": "GET"}
        return jsonify(analytics_json())
    if view == "panel":
        return page("p8.html", "Práctica 8 · Panel de métricas", view="panel")
    return page("p8.html", "Práctica 8 · Métricas del sitio", view="home")


def handle_p9(parts: list[str]):
    view = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    product_id = int(action) if action.isdigit() else None
    if view == "ejemplo":
        if request.method != "POST":
            return redirect(path_url("p9"))
        added = 0
        for product in EXAMPLE_PRODUCTS:
            if USE_POSTGRES:
                insert_sql = """
                    INSERT INTO productos_tienda
                        (nombre, marca, categoria, precio, existencia, codigo_barras, promocion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (codigo_barras) DO NOTHING
                """
            else:
                insert_sql = ("INSERT IGNORE" if USE_MYSQL else "INSERT OR IGNORE") + """
                    INTO productos_tienda
                        (nombre, marca, categoria, precio, existencia, codigo_barras, promocion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
            added += execute(insert_sql, product)[0]
        if added:
            flash(f"Se cargaron {added} productos de ejemplo.", "exito")
        else:
            flash("Los productos de ejemplo ya estaban cargados.", "info")
        return redirect(path_url(product_destination()))
    if view == "admin":
        if action == "salir":
            session.pop("admin_p9", None)
            session.pop("admin_p9_matricula", None)
            flash("Cerraste la sesión de administrador.", "info")
            return redirect(path_url("p9/admin"))
        if request.method == "POST" and not admin_active():
            matricula = request.form.get("matricula", "").strip()
            password = request.form.get("contrasena", "")
            if matricula == ADMIN_MATRICULA and verify_password(password, ADMIN_PASSWORD_HASH):
                session["admin_p9"] = True
                session["admin_p9_matricula"] = ADMIN_MATRICULA
                flash("Bienvenido al panel de administración.", "exito")
                return redirect(path_url("p9/admin"))
            flash("Matrícula o contraseña de administrador incorrectas.", "error")
        if not admin_active():
            return page("p9.html", "Práctica 9 · Administración", view="admin_login")
        search = request.args.get("q", "").strip()
        category = request.args.get("categoria", "").strip()
        return page(
            "p9.html",
            "Práctica 9 · Administración de la tienda",
            view="admin",
            products=store_products(search, category),
            categories=store_categories(),
            summary=store_summary(),
            search=search,
            category=category,
        )
    if view == "chat":
        student = get_student()
        if action == "mensajes":
            if request.method != "GET":
                return jsonify(error="Usa GET para consultar los mensajes."), 405, {"Allow": "GET"}
            if student is None:
                return jsonify(error="Inicia sesión para ver el chat."), 401
            try:
                since = max(0, int(request.args.get("desde", "0")))
            except ValueError:
                since = 0
            messages = chat_messages(since)
            for message in messages:
                message["es_mio"] = message["autor_matricula"] == student["matricula"]
            latest = max([since, *(message["id"] for message in messages)])
            return jsonify(mensajes=messages, ultimo=latest)
        if action == "enviar":
            wants_json = "application/json" in request.headers.get("Accept", "")

            def reject(status: int, message: str):
                if wants_json:
                    return jsonify(error=message), status
                flash(message, "error")
                return redirect(path_url("p9/chat"))

            if request.method != "POST":
                return reject(405, "Usa POST para enviar mensajes.")
            if student is None:
                return reject(401, "Inicia sesión para escribir en el chat.")
            token = request.form.get("token", "")
            if not secrets.compare_digest(session.get("chat_token", ""), token):
                return reject(403, "La sesión expiró. Recarga la página e inténtalo de nuevo.")
            message_text = request.form.get("mensaje", "").strip()
            if not message_text:
                return reject(400, "Escribe un mensaje antes de enviarlo.")
            if len(message_text) > 500:
                return reject(400, "El mensaje no puede pasar de 500 caracteres.")
            now = int(time.time())
            if now - int(session.get("chat_ultimo", 0)) < 1:
                return reject(429, "Espera un segundo antes de enviar otro mensaje.")
            session["chat_ultimo"] = now
            _, new_id = execute(
                """
                INSERT INTO chat_mensajes (autor_matricula, autor_nombre, mensaje)
                VALUES (%s, %s, %s)
                """,
                (
                    student["matricula"],
                    f"{student['nombre']} {student['apellido']}".strip(),
                    message_text,
                ),
            )
            new_message = query_one(
                """
                SELECT id, autor_matricula, autor_nombre, mensaje,
                    """ + date_format("creado_en", "%d/%m %H:%M") + """ AS hora
                FROM chat_mensajes WHERE id=%s
                """,
                (new_id,),
            )
            new_message["es_mio"] = True
            if wants_json:
                return jsonify(ok=True, mensaje=new_message, ultimo=new_id)
            return redirect(path_url("p9/chat"))
        if student is None:
            return page("p9.html", "Práctica 9 · Chat de la tienda", view="chat_guest")
        if "chat_token" not in session:
            session["chat_token"] = secrets.token_hex(16)
        messages = chat_messages()
        return page(
            "p9.html",
            "Práctica 9 · Chat de la tienda",
            view="chat",
            student=student,
            messages=messages,
            latest=messages[-1]["id"] if messages else 0,
            chat_token=session["chat_token"],
        )
    if view == "":
        if request.args.get("nuevas_sucursales"):
            session.pop("sucursales_pimpz", None)
            return redirect(path_url("p9") + "#sucursales")
        search = request.args.get("q", "").strip()
        category = request.args.get("categoria", "").strip()
        return page(
            "p9.html",
            "Práctica 9 · Tienda Pimpz",
            view="public",
            products=store_products(search, category),
            categories=store_categories(),
            summary=store_summary(),
            search=search,
            category=category,
            branches=get_branches(),
            admin=admin_active(),
        )
    if view == "crear":
        if request.method == "POST":
            data = product_form_data()
            problem = validate_store_product(data)
            if problem:
                flash(problem, "error")
                return redirect(path_url("p9/crear"))
            try:
                save_store_product(data)
            except INTEGRITY_ERRORS:
                flash("Ya existe un producto con ese código de barras.", "error")
                return redirect(path_url("p9/crear"))
            flash("Producto agregado correctamente.", "exito")
            return redirect(path_url(product_destination()))
        return page("p9.html", "Práctica 9 · Agregar producto", view="product_form", product=None)
    if view == "editar" and product_id is not None:
        product = query_one("SELECT * FROM productos_tienda WHERE id=%s", (product_id,))
        if product is None:
            flash("El producto que buscas no existe.", "error")
            return redirect(path_url("p9"))
        if request.method == "POST":
            data = product_form_data()
            problem = validate_store_product(data)
            if problem:
                flash(problem, "error")
                return redirect(path_url(f"p9/editar/{product_id}"))
            try:
                save_store_product(data, product_id)
            except INTEGRITY_ERRORS:
                flash("Ya existe otro producto con ese código de barras.", "error")
                return redirect(path_url(f"p9/editar/{product_id}"))
            flash("Producto modificado correctamente.", "exito")
            return redirect(path_url(product_destination()))
        return page(
            "p9.html",
            "Práctica 9 · Editar producto",
            view="product_form",
            product=product,
        )
    if view == "eliminar" and product_id is not None:
        if request.method != "POST":
            return redirect(path_url("p9"))
        execute("DELETE FROM productos_tienda WHERE id=%s", (product_id,))
        flash("Producto eliminado correctamente.", "info")
        return redirect(path_url(product_destination()))
    return redirect(path_url("p9"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
