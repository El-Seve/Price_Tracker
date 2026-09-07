"""
Normalización de nombre de modelo -> "familia" comparable entre retailers.

Cada retailer nombra el mismo producto distinto (mayúsculas, orden de
palabras, bundles con regalo incluido, typos). Para poder comparar el mismo
modelo Honor entre retailers ("dispersión de precio del mismo SKU") hace
falta reducir el nombre a una clave estable: familia de línea + capacidad.

v1 pragmático: en vez de adivinar con regex genérico (que confunde, por
ejemplo, "Earbuds X7L" de regalo con el modelo "X7 Lite"), usa una lista de
familias Honor conocidas, ordenada de más a menos específica, y busca la
primera que aparezca en el texto. Cubre las líneas activas en Perú al
momento de escribir esto (sept. 2026) -- agregar una línea nueva es sumar
una entrada a FAMILIAS_HONOR.
"""
import re
import unicodedata

# Orden importa: de más específico a menos específico, para no matchear
# "600" cuando en realidad es "600 Pro" o "600e".
FAMILIAS_HONOR = [
    "MAGIC 8 PRO", "MAGIC 8 LITE", "MAGIC8 LITE", "MAGIC 8",
    "MAGIC 7 PRO", "MAGIC 7 LITE", "MAGIC7 LITE", "MAGIC 7",
    # Tablets (PAD ...) van ANTES que sus códigos "X" equivalentes: si no,
    # "Tablet Honor PAD X7 128GB" matchea el patrón de teléfono "X7" primero
    # (substring) y termina mezclado en el mismo bucket que el celular X7 --
    # comparar precio de tablet contra celular sería un sinsentido.
    "PAD X9A", "PAD X8B", "PAD X7", "PAD 10",
    "600 SMART", "600 PRO", "600E", "600",
    "400 PRO", "400 LITE", "400",
    "200 PRO", "200",
    "90",
    "X9D", "X9A",
    "X8D", "X8C", "X8B",
    "X7E PLUS", "X7E", "X7D", "X7C", "X7",
    "X6D", "X6E", "X6C", "X6S", "X6",
    "X5D", "X5C PLUS", "X5C",
    "PLAY 10A", "PLAY 10",
]

# Marcas que, si aparecen en el nombre, casi seguro indican un error de
# etiquetado del retailer (venía como "marca": "HONOR" pero el producto real
# es de otra marca -- típico en bundles/gift-with-purchase mal armados).
_OTRAS_MARCAS = ["SAMSUNG", "XIAOMI", "OPPO", "APPLE", "IPHONE", "MOTOROLA", "REDMI", "POCO", "VIVO", "ZTE"]

# Accesorios/no-telefonos que no deben entrar a la comparación de precio de
# equipos (audífonos, watch, cases, etc. -- aunque la categoría ya debería
# filtrarlos, esto es una segunda barrera si el nombre los delata).
_ACCESORIO_KEYWORDS = ["AUDIFONO", "AURICULAR", "EARBUD", "WATCH", "SMARTWATCH", "CASE ", "FUNDA",
                       "CARGADOR", "CABLE", "MICA", "PROTECTOR", "BATERIA", "POWER BANK", "PARLANTE"]

_GB_RE = re.compile(r"(\d{2,4})\s*GB")


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def es_accesorio_por_nombre(texto_upper_sin_acentos: str) -> bool:
    """Señal genérica (no depende de marca): el nombre empieza nombrando un
    accesorio, no un equipo. Reutilizable tanto para filas Honor como para
    filas de competencia -- un smartwatch o power bank Xiaomi/Samsung no
    debe colarse en la comparación de precio de celulares por segmento."""
    primeras_palabras = " ".join(texto_upper_sin_acentos.split()[:4])
    return any(k in primeras_palabras for k in _ACCESORIO_KEYWORDS)


def es_producto_valido(modelo: str) -> bool:
    """False si el nombre sugiere error de marca o que es un accesorio, no
    un equipo -- para no meter ruido en la comparación de precios de equipos.

    OJO: revisar "tiene alguna familia conocida en el texto" NO alcanza para
    detectar accesorios, porque un código de familia puede aparecer como
    substring dentro del propio nombre del accesorio (p.ej. "Audífonos
    Bluetooth Honor Choice X7 Lite" contiene "X7"). En cambio, un bundle real
    de equipo + regalo casi siempre nombra el equipo primero y el accesorio
    después ("600 Smart 5G ... + Earbuds X7L + Liberado"). Por eso la señal
    de accesorio se busca solo en las primeras palabras del nombre."""
    if not modelo:
        return False
    texto = _sin_acentos(modelo.upper())
    if any(m in texto for m in _OTRAS_MARCAS):
        return False
    if es_accesorio_por_nombre(texto):
        return False
    return True


def modelo_a_familia(modelo: str) -> str:
    """'Celular Honor X5d 4GB + 128GB Meteor Silver' -> 'X5D 128GB'.
    Si no reconoce ninguna familia conocida, devuelve 'OTRO: <texto corto>'
    en vez de una clave falsa -- mejor visible como pendiente de mapear que
    silenciosamente mal agrupado."""
    if not modelo:
        return "DESCONOCIDO"
    texto = modelo.upper()

    familia = None
    for fam in FAMILIAS_HONOR:
        if fam in texto:
            familia = fam
            break

    gbs = [int(g) for g in _GB_RE.findall(texto)]
    almacenamiento = max(gbs) if gbs else None

    if not familia:
        primeras = " ".join(texto.split()[:3])
        return f"OTRO: {primeras}"

    if almacenamiento:
        return f"{familia} {almacenamiento}GB"
    return familia


_BARCODE_RE = re.compile(r"^\d{8,}$")


def es_texto_barcode(texto: str) -> bool:
    """True si el 'modelo' es solo un código de barras (EAN/UPC) -- pasa en
    varios retailers cuando el feed no trae nombre de producto. No es
    exclusivo de Honor: hace falta también al filtrar competencia (ver
    build_dashboard_data._filas_competencia_hoy), donde un accesorio barato
    mal etiquetado con marca "SAMSUNG"/"XIAOMI" puede distorsionar la
    comparación de precio por segmento si no se descarta."""
    if not texto:
        return False
    return bool(_BARCODE_RE.match(texto.strip()))


# Un celular real en el mercado peruano no baja de este precio -- por debajo
# de esto, un producto "marca":"SAMSUNG"/"XIAOMI"/etc. casi siempre es un
# accesorio (case, cargador, mica) mal etiquetado por el propio retailer.
PRECIO_MINIMO_CELULAR = 150.0


def segmento_de_precio(precio: float) -> str:
    """Bucket de precio para comparar 'Honor vs el competidor más barato del
    mismo segmento' cuando no se puede hacer match exacto de modelo entre
    marcas distintas."""
    bandas = [
        (0, 600, "Hasta S/600"),
        (600, 1000, "S/600 - S/1,000"),
        (1000, 1500, "S/1,000 - S/1,500"),
        (1500, 2500, "S/1,500 - S/2,500"),
        (2500, 4000, "S/2,500 - S/4,000"),
        (4000, float("inf"), "Más de S/4,000"),
    ]
    for lo, hi, etiqueta in bandas:
        if lo <= precio < hi:
            return etiqueta
    return "Sin clasificar"
