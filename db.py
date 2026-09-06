"""
Histórico de precios en SQLite. Un archivo simple (`data/precios.db`) en vez de
sobreescribir un Excel cada día -- así cada corrida SUMA una fila con su fecha,
en vez de reemplazar la anterior, y se puede armar una serie de tiempo real por
producto (¿bajó, subió, cuánto tiempo estuvo en oferta?).
"""
import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).parent / "data" / "precios.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS capturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    retailer TEXT NOT NULL,
    categoria TEXT NOT NULL,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    precio_regular REAL,
    precio_oferta REAL,
    vendedor TEXT,
    vendedor_tercero INTEGER,
    url TEXT,
    UNIQUE(fecha, retailer, modelo, vendedor, precio_oferta)
);
CREATE INDEX IF NOT EXISTS idx_capturas_marca_fecha ON capturas(marca, fecha);
CREATE INDEX IF NOT EXISTS idx_capturas_retailer_fecha ON capturas(retailer, fecha);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def insert_rows(conn, rows: list[dict], fecha: str | None = None):
    fecha = fecha or date.today().isoformat()
    cur = conn.cursor()
    inserted = 0
    for r in rows:
        try:
            cur.execute(
                """INSERT OR IGNORE INTO capturas
                   (fecha, retailer, categoria, marca, modelo, precio_regular,
                    precio_oferta, vendedor, vendedor_tercero, url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (fecha, r["retailer"], r["categoria"], r["marca"], r["modelo"],
                 r.get("precio_regular"), r.get("precio_oferta"), r.get("vendedor"),
                 int(bool(r.get("vendedor_tercero"))), r.get("url")),
            )
            inserted += cur.rowcount
        except sqlite3.Error:
            continue
    conn.commit()
    return inserted


def price_changes_since_last_run(conn, marca: str = "HONOR"):
    """
    Compara la captura de hoy contra la más reciente anterior, por (retailer, modelo,
    vendedor), y devuelve los productos cuyo precio de oferta cambió. Útil para que
    el aviso diario diga solo lo que cambió, no las 200 filas completas.
    """
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT fecha FROM capturas WHERE marca = ? ORDER BY fecha DESC LIMIT 2", (marca,))
    fechas = [row[0] for row in cur.fetchall()]
    if len(fechas) < 2:
        return []
    hoy, ayer = fechas[0], fechas[1]
    cur.execute("""
        SELECT h.retailer, h.modelo, h.vendedor, a.precio_oferta AS antes, h.precio_oferta AS ahora
        FROM capturas h
        JOIN capturas a
          ON a.retailer = h.retailer AND a.modelo = h.modelo AND a.vendedor = h.vendedor
         AND a.fecha = ? AND h.fecha = ? AND a.marca = ?
        WHERE h.precio_oferta != a.precio_oferta
    """, (ayer, hoy, marca))
    return cur.fetchall()
