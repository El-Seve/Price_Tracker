#!/usr/bin/env python3
"""
Junta dos versiones de data/precios.db que divergieron (típicamente: la que
generó el bot en GitHub Actions vs. la que quedó en tu compu después de correr
"py run.py --retailer X" a mano) en una sola, SIN perder ninguna fila de
ninguna de las dos.

Por qué esto es seguro y no un "quedarse con una versión al azar": la tabla
`capturas` tiene una restricción UNIQUE(fecha, retailer, modelo, vendedor,
precio_oferta) -- ver db.py. Sumar las dos bases con INSERT OR IGNORE
simplemente descarta los duplicados reales (misma fila exacta en ambas) y
conserva todo lo demás. Ninguna captura real se pierde, venga de donde venga.

Se necesitó esto después de descubrir (17-18/09/2026) que GitHub Actions no
puede traer datos de Falabella/PlazaVea/Promart/Oechsle (probablemente
bloquean la IP de nube del runner), mientras que corriendo el mismo código
desde una compu normal sí funciona. Antes de este script, subir-cambios.ps1
resolvía el choque de precios.db quedándose con la versión de GitHub -- lo
cual borraba en silencio justo los datos de Falabella (y con ellos, Sany) que
tu compu sí había logrado traer. Ahora se suman en vez de descartar.

Uso (lo llama subir-cambios.ps1 solo, no hace falta correrlo a mano):
    python merge_precios_db.py <db_base> <db_a_sumar> <db_salida>
"""
import shutil
import sqlite3
import sys
from pathlib import Path

import db as db_module  # reusa el mismo SCHEMA (misma restricción UNIQUE) que db.py


def merge(db_base: str, db_extra: str, db_salida: str) -> int:
    conn = sqlite3.connect(db_base)
    conn.executescript(db_module.SCHEMA)
    db_module._migrar_columnas_nuevas(conn)
    conn.execute("ATTACH DATABASE ? AS extra", (db_extra,))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS extra.capturas (
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
    """)
    # La base "extra" puede venir de antes del 18/09/2026 (sin precio_tarjeta
    # todavía) -- se migra igual que la base propia antes de leerla, si no
    # ALTER TABLE de abajo fallaría al no existir la columna en ninguna de
    # las dos, o el SELECT de precio_tarjeta fallaría si falta solo en extra.
    db_module._migrar_columnas_nuevas(conn, tabla="capturas", esquema="extra")
    cur = conn.execute("""
        INSERT OR IGNORE INTO capturas
            (fecha, retailer, categoria, marca, modelo, precio_regular,
             precio_oferta, precio_tarjeta, vendedor, vendedor_tercero, url)
        SELECT fecha, retailer, categoria, marca, modelo, precio_regular,
               precio_oferta, precio_tarjeta, vendedor, vendedor_tercero, url
        FROM extra.capturas
    """)
    sumadas = cur.rowcount
    conn.commit()
    conn.execute("DETACH DATABASE extra")
    conn.close()

    if str(Path(db_salida).resolve()) != str(Path(db_base).resolve()):
        Path(db_salida).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(db_base, db_salida)

    return sumadas


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Uso: python merge_precios_db.py <db_base> <db_a_sumar> <db_salida>", file=sys.stderr)
        sys.exit(1)
    n = merge(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Filas nuevas sumadas desde {sys.argv[2]}: {n}")
