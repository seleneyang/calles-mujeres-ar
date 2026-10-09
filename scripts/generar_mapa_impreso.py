#!/usr/bin/env python3
"""
Genera el mapa impreso (plotter 320 × 320 cm): pines con el logo de Geochicas y un QR circular
adentro, con la punta sobre cada calle.

    .venv/bin/python scripts/generar_mapa_impreso.py \
        --url-base https://seleneyang.github.io/calles-mujeres-ar/ar.html

Salidas en impresion/:
    mapa_calles_mujeres_320cm.pdf   vectorial, tamaño real, para el plotter
    mapa_calles_mujeres_preview.png vista previa
    posiciones_qr.csv               dónde queda cada QR (cm desde la esquina superior izquierda)
    tarjetas_qr_prueba.pdf          los 30 pines QR en hojas carta para probar con el celular

Mapa base: teselas vectoriales de OpenFreeMap (OSM, sin API key) dibujadas con la paleta
del estilo Positron. Calles con nombre de mujer: dataset de Geochicas.
Requiere: segno, mapbox-vector-tile, matplotlib (ver README).
"""
import argparse
import csv
import gzip
import json
import math
import random
import textwrap
import time
import urllib.request
from pathlib import Path

import sys

import mapbox_vector_tile
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import segno  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import LineCollection, PatchCollection, PathCollection  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from generar_calles import agrupar  # noqa: E402  (misma agrupación de tramos → calles)
CACHE = RAIZ / ".cache"
SALIDA = RAIZ / "impresion"
TILEJSON = "https://tiles.openfreemap.org/planet"
GEOJSON_URL = (
    "https://raw.githubusercontent.com/geochicasosm/lascallesdelasmujeres/"
    "master/data/cdmx/final_tile.geojson"
)
UA = {"User-Agent": "GeochicasAR-print/1.0 (mapa impreso exposicion Geochicas)"}

LADO_CM = 320.0
LADO_KM = 25.0
CENTRO = (19.409, -99.1185)  # lat, lon: centro de las 30 calles seleccionadas
ZOOM = 14
CM = 1 / 2.54  # pulgadas por cm

# Paleta Positron (OpenFreeMap) un poco más contrastada para leerse desde el suelo
FONDO = "#f2f3f0"
RESIDENCIAL = "#eaeae6"
PARQUE = "#e2e7e0"
BOSQUE = "#dce0dc"
AGUA = "#c2c8ca"
CALLE_MENOR = "#dcdcda"
CASING = "#cfcfcf"
CALLE_MAYOR = "#ffffff"
TREN = "#d4d4d4"
ETIQUETA = "#8a8a8a"
# Paleta del proyecto
MUJER = "#c9a3d9"         # todas las calles con nombre de mujer
MARCA = "#871657"         # color del logo de Geochicas: pines y QR
MARCA_CLARA = "#b23a7e"   # las 30 calles con QR (todas iguales)
MORADO_OSCURO = "#1a0b2e"

QR_CM = 9.5               # lado del QR cuadrado inscrito en el círculo del logo
QR_VERSION = 8            # fija para que todos los pines midan igual (49 × 49 módulos)
QR_MODULOS = 17 + 4 * QR_VERSION
QR_SILENCIO = 1           # módulos blancos entre el código y el relleno decorativo
QR_SILENCIO_BUSCADORES = 2
MARGEN_CM = 4.0


# ---------------------------------------------------------------- utilidades
def http(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def merc(lon, lat):
    x = (lon + 180) / 360
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


class Proyeccion:
    """Web Mercator → cm sobre el lienzo (origen arriba a la izquierda)."""

    def __init__(self, lat, lon, lado_km, lado_cm):
        self.cx, self.cy = merc(lon, lat)
        self.h = (lado_km * 500) / (40075016.686 * math.cos(math.radians(lat)))
        self.k = lado_cm / (2 * self.h)

    def xy(self, X, Y):
        return (X - (self.cx - self.h)) * self.k, (Y - (self.cy - self.h)) * self.k

    def lonlat(self, lon, lat):
        return self.xy(*merc(lon, lat))

    def tiles(self, z):
        n = 2 ** z
        x0, x1 = int((self.cx - self.h) * n), int((self.cx + self.h) * n)
        y0, y1 = int((self.cy - self.h) * n), int((self.cy + self.h) * n)
        return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    def cm_por_km(self):
        return self.k * self.h * 2 / LADO_KM


def fuente(nombre):
    return font_manager.FontProperties(fname=str(CACHE / "fonts" / f"{nombre}.ttf"))


# ---------------------------------------------------------------- datos
def descargar_tiles(proj):
    url = json.loads(http(TILEJSON))["tiles"][0]
    carpeta = CACHE / "tiles" / str(ZOOM)
    carpeta.mkdir(parents=True, exist_ok=True)
    lista = proj.tiles(ZOOM)
    for i, (x, y) in enumerate(lista, 1):
        f = carpeta / f"{x}_{y}.pbf"
        if not f.exists():
            f.write_bytes(http(url.format(z=ZOOM, x=x, y=y)))
            time.sleep(0.15)
        if i % 25 == 0 or i == len(lista):
            print(f"  teselas {i}/{len(lista)}", flush=True)
    return [(x, y, (carpeta / f"{x}_{y}.pbf").read_bytes()) for x, y in lista]


def a_cm(proj, x, y, ext, pts):
    n = 2 ** ZOOM
    return [proj.xy((x + px / ext) / n, (y + py / ext) / n) for px, py in pts]


def lineas(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return c
    if t == "Polygon":
        return c
    if t == "MultiPolygon":
        return [r for p in c for r in p]
    return []


def poligonos(geom):
    t, c = geom["type"], geom["coordinates"]
    return [c] if t == "Polygon" else c if t == "MultiPolygon" else []


def capas_base(proj, tiles):
    rellenos = {RESIDENCIAL: [], PARQUE: [], BOSQUE: [], AGUA: []}
    calles = {k: [] for k in ("menor", "terciaria", "secundaria", "primaria", "autopista", "tren")}
    rios, limites, colonias = [], [], []

    for x, y, data in tiles:
        capas = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
        for nombre, capa in capas.items():
            ext = capa.get("extent", 4096)
            for f in capa["features"]:
                g, p = f["geometry"], f["properties"]
                if nombre in ("water", "park", "landuse", "landcover"):
                    color = {
                        "water": AGUA,
                        "park": PARQUE,
                    }.get(nombre)
                    if nombre == "landuse" and p.get("class") == "residential":
                        color = RESIDENCIAL
                    if nombre == "landcover" and p.get("class") in ("wood", "grass", "farmland"):
                        color = BOSQUE
                    if color:
                        for pol in poligonos(g):
                            rellenos[color].append([a_cm(proj, x, y, ext, r) for r in pol])
                elif nombre == "waterway":
                    rios += [a_cm(proj, x, y, ext, l) for l in lineas(g)]
                elif nombre == "transportation":
                    c = p.get("class")
                    clave = {
                        "motorway": "autopista", "trunk": "autopista", "primary": "primaria",
                        "secondary": "secundaria", "tertiary": "terciaria",
                        "minor": "menor", "service": "menor",
                        "rail": "tren", "transit": "tren",
                    }.get(c)
                    if clave and p.get("brunnel") != "tunnel":
                        calles[clave] += [a_cm(proj, x, y, ext, l) for l in lineas(g)]
                elif nombre == "boundary" and p.get("admin_level") == 4:
                    limites += [a_cm(proj, x, y, ext, l) for l in lineas(g)]
                elif nombre == "place" and p.get("class") in ("suburb", "quarter") and p.get("name"):
                    px, py = g["coordinates"]
                    colonias.append((a_cm(proj, x, y, ext, [(px, py)])[0], p["name"]))
    return rellenos, calles, rios, limites, colonias


def calles_mujeres(proj):
    f = CACHE / "cdmx_final_tile.geojson"
    if not f.exists():
        f.write_bytes(http(GEOJSON_URL))
    datos = json.loads(f.read_text(encoding="utf-8"))
    total = len(agrupar([x for x in datos["features"] if x["properties"].get("gender") == "Female"]))
    por_osm, todas = {}, []
    for feat in datos["features"]:
        if feat["properties"].get("gender") != "Female":
            continue
        trazos = [[proj.lonlat(lon, lat) for lon, lat in l] for l in lineas(feat["geometry"])]
        por_osm[feat["properties"]["id"]] = trazos
        todas += trazos
    return por_osm, todas, total


# ---------------------------------------------------------------- dibujo
def rellenar(ax, anillos_por_poligono, color, z):
    paths = []
    for anillos in anillos_por_poligono:
        verts, codes = [], []
        for r in anillos:
            if len(r) < 3:
                continue
            verts += r + [r[0]]
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(r) - 1) + [MPath.CLOSEPOLY]
        if verts:
            paths.append(MPath(verts, codes))
    ax.add_collection(PathCollection(paths, facecolor=color, edgecolor="none", zorder=z))


def trazar(ax, segs, color, ancho_pt, z, **kw):
    ax.add_collection(LineCollection(segs, colors=color, linewidths=ancho_pt, zorder=z,
                                     capstyle="round", joinstyle="round", **kw))


class Logo:
    """Logo de Geochicas vectorizado desde assets/logo_geochicas.webp (unidades = píxeles del original)."""

    def __init__(self):
        d = json.loads((RAIZ / "assets" / "logo_geochicas.json").read_text())
        self.piezas, self.disco, self.silueta = d["piezas"], d["disco_interior"], d["silueta"]
        self.hueco, self.punta = d["hueco"], d["punta"]
        x0, y0, x1, y1 = d["bbox"]
        self.izq, self.der, self.arriba = self.punta[0] - x0, x1 - self.punta[0], self.punta[1] - y0
        # Círculo para el QR: cabe dentro del hueco blanco del anillo con un pequeño margen
        self.r_qr = min(self.hueco["rx"], self.hueco["ry"]) - 14
        n = QR_MODULOS
        self.lado_qr = self.r_qr / (math.sqrt(2) / 2 + 0.5 / n)  # cuadrado inscrito en el círculo

    def escala(self, qr_cm):
        return qr_cm / self.lado_qr

    def dibujar(self, ax, px, py, k, z, color, fondo=None, con_disco=True):
        """Dibuja el logo con la punta en (px, py) y escala k (cm por unidad)."""
        ox, oy = px - self.punta[0] * k, py - self.punta[1] * k

        def path(pts):
            v = [(ox + x * k, oy + y * k) for x, y in pts]
            return MPath(v + [v[0]], [MPath.MOVETO] + [MPath.LINETO] * (len(v) - 1) + [MPath.CLOSEPOLY])

        if fondo:
            ax.add_patch(PathPatch(path(self.silueta), facecolor=fondo, edgecolor=fondo, linewidth=10,
                                   joinstyle="round", zorder=z))
        piezas = self.piezas + ([self.disco] if con_disco else [])
        ax.add_collection(PathCollection([path(p) for p in piezas], facecolor=color, edgecolor="none", zorder=z + 1))
        return ox + self.hueco["cx"] * k, oy + self.hueco["cy"] * k  # centro del círculo


def qr_circular(ax, cx, cy, radio, url, semilla, z, color=MARCA, silencio=QR_SILENCIO,
                silencio_buscadores=QR_SILENCIO_BUSCADORES):
    """QR circular: el código real (cuadrado) inscrito en el círculo y el resto del círculo relleno con
    módulos decorativos idénticos, del mismo color, para que a la vista todo el círculo sea el QR.

    `silencio`: módulos blancos alrededor de todo el código. `silencio_buscadores`: módulos blancos
    extra alrededor de los tres cuadros de las esquinas, que son los que la cámara busca primero.
    """
    qr = segno.make(url, error="q", version=QR_VERSION, boost_error=False)
    m = [list(f) for f in qr.matrix]
    n = len(m)
    lado = radio / (math.sqrt(2) / 2 + 0.5 / n)  # las esquinas del código tocan casi el borde
    mod = lado / n
    x0, y0 = cx - lado / 2, cy - lado / 2
    ax.add_patch(Circle((cx, cy), radio, facecolor="white", edgecolor="none", zorder=z))

    def libre(i, j):
        if -silencio <= i < n + silencio and -silencio <= j < n + silencio:
            return False
        q = silencio_buscadores
        for bi, bj in ((0, 0), (n - 7, 0), (0, n - 7)):  # buscadores: arriba-izq, arriba-der, abajo-izq
            if bi - q <= i < bi + 7 + q and bj - q <= j < bj + 7 + q:
                return False
        return True

    rnd = random.Random(semilla)
    ext = int(radio / mod) + 2
    celdas = {(i, j) for j, fila in enumerate(m) for i, v in enumerate(fila) if v}
    for j in range(-ext, n + ext):
        for i in range(-ext, n + ext):
            if libre(i, j) and rnd.random() < 0.5:
                # el módulo entero debe quedar dentro del círculo
                esquinas = [(x0 + (i + a) * mod, y0 + (j + b) * mod) for a in (0, 1) for b in (0, 1)]
                if all(math.hypot(x - cx, y - cy) <= radio for x, y in esquinas):
                    celdas.add((i, j))
    rects = []
    for j in range(-ext, n + ext):  # unir módulos contiguos por fila: menos objetos en el PDF
        fila = sorted(i for (i, jj) in celdas if jj == j)
        k = 0
        while k < len(fila):
            ini = fila[k]
            while k + 1 < len(fila) and fila[k + 1] == fila[k] + 1:
                k += 1
            rects.append(Rectangle((x0 + ini * mod, y0 + j * mod), (fila[k] - ini + 1) * mod, mod * 1.02))
            k += 1
    ax.add_collection(PatchCollection(rects, facecolor=color, edgecolor="none", zorder=z + 1))
    return qr.version


def etiqueta(nombre):
    lineas_txt = textwrap.wrap(nombre, 20)[:2]
    ancho = max(len(t) for t in lineas_txt) * 0.7 + 3.0
    alto = len(lineas_txt) * 1.55 + 1.3
    return lineas_txt, ancho, alto


def caja_marcador(logo, k, tx, ty, nombre, pad=0.8):
    """Rectángulo que ocupa el marcador (logo + nombre encima) con la punta en (tx, ty)."""
    _, ancho, alto = etiqueta(nombre)
    arriba = ty - logo.arriba * k - alto - 0.6
    izq = min(tx - logo.izq * k, tx - ancho / 2)
    der = max(tx + logo.der * k, tx + ancho / 2)
    return (izq - pad, arriba - pad, der + pad, ty + pad)


def dibujar_marcador(ax, logo, k, tx, ty, calle, url, fuentes, z=50):
    centro = logo.dibujar(ax, tx, ty, k, z, MARCA, fondo="white", con_disco=False)
    version = qr_circular(ax, *centro, logo.r_qr * k, url, calle["calle_id"], z + 2)
    lineas_txt, ancho, alto = etiqueta(calle["mujer"]["nombre"])
    y_base = ty - logo.arriba * k - 0.6
    ax.add_patch(FancyBboxPatch((tx - ancho / 2, y_base - alto), ancho, alto,
                                boxstyle=f"round,pad=0,rounding_size={min(alto / 2, 1.4)}",
                                facecolor="white", edgecolor=MARCA, linewidth=6, zorder=z + 5))
    for i, t in enumerate(lineas_txt):
        ax.text(tx, y_base - alto + 0.65 + 0.775 + i * 1.55, t, ha="center", va="center",
                fontproperties=fuentes["titulo"], fontsize=34, color=MARCA, zorder=z + 6)
    return version


def se_cruzan(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def colocar_marcadores(calles, puntos, logo, k, zona_reservada):
    """Greedy: la punta del pin va sobre la calle; si choca con otro, se desplaza con una línea guía."""
    colocadas, ocupado = {}, [zona_reservada]

    def vecinos(cid):
        px, py = puntos[cid]
        return sum(1 for o, (qx, qy) in puntos.items() if o != cid and math.hypot(px - qx, py - qy) < 40)

    for cid in sorted(calles, key=vecinos, reverse=True):
        px, py = puntos[cid]
        nombre = calles[cid]["mujer"]["nombre"]
        mejor = None
        for radio in (0, 5, 9, 14, 20, 27, 35, 44, 54, 65, 77, 90, 104):
            for paso in range(1 if radio == 0 else 24):
                ang = 2 * math.pi * paso / 24
                tx, ty = px + radio * math.cos(ang), py + radio * math.sin(ang)
                r = caja_marcador(logo, k, tx, ty, nombre)
                if r[0] < MARGEN_CM or r[1] < MARGEN_CM or r[2] > LADO_CM - MARGEN_CM or r[3] > LADO_CM - MARGEN_CM:
                    continue
                if any(se_cruzan(r, o) for o in ocupado):
                    continue
                tapa = sum(1 for o, (qx, qy) in puntos.items()
                           if o != cid and r[0] - 2 < qx < r[2] + 2 and r[1] - 2 < qy < r[3] + 2)
                coste = radio + tapa * 100
                if mejor is None or coste < mejor[0]:
                    mejor = (coste, tx, ty, r)
            if mejor and mejor[0] < 100:
                break
        if mejor is None:
            raise SystemExit(f"No hubo espacio para el marcador de {cid}")
        _, tx, ty, r = mejor
        colocadas[cid] = (tx, ty)
        ocupado.append(r)
    return colocadas


def punto_de_calle(trazos):
    pts = [p for t in trazos for p in t]
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    return min(pts, key=lambda p: (p[0] - mx) ** 2 + (p[1] - my) ** 2)  # un vértice real de la calle


def cuadro_titulo(ax, x0, y0, w, h, fuentes, total_mujer, proj, logo):
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=2.5",
                                facecolor=MORADO_OSCURO, edgecolor="none", zorder=60))
    tx = x0 + 4
    ax.text(tx, y0 + 4.5, "Las Calles de las Mujeres -\nCiudad de México", fontproperties=fuentes["titulo"],
            fontsize=150, color="white", va="top", linespacing=0.95, zorder=61)
    kl = 6.0 / (logo.arriba)  # logo de 6 cm de alto
    logo.dibujar(ax, tx + logo.izq * kl, y0 + 27, kl, 61, "white")
    ax.text(tx + (logo.izq + logo.der) * kl + 1.5, y0 + 24, "Geochicas", fontproperties=fuentes["subtitulo"],
            fontsize=80, color="#e3d0ff", va="center", zorder=61)
    pasos = ("1  Busca un pin con código QR sobre una calle",
             "2  Escanéalo con la cámara de tu celular",
             "3  Descubre su historia en realidad aumentada")
    for i, t in enumerate(pasos):
        ax.text(tx, y0 + 32 + i * 3.4, t, fontproperties=fuentes["texto"], fontsize=44, color="white",
                va="top", zorder=61)
    ly = y0 + 45
    leyenda = ((MUJER, 10, f"Calle con nombre de mujer ({total_mujer} en la CDMX)"),
               (MARCA_CLARA, 18, "Calle con código QR: escanéalo y descubre su historia"))
    for i, (color, ancho, t) in enumerate(leyenda):
        y = ly + i * 3.6
        ax.plot([tx, tx + 6], [y, y], color=color, linewidth=ancho, solid_capstyle="round", zorder=61)
        ax.text(tx + 8, y, t, fontproperties=fuentes["texto"], fontsize=40, color="white", va="center", zorder=61)
    y = ly + 2 * 3.6
    ax.plot([tx, tx + 6], [y, y], color="#bbbbbb", linewidth=5, linestyle=(0, (3, 2)), zorder=61)
    ax.text(tx + 8, y, "Límite de la Ciudad de México", fontproperties=fuentes["texto"], fontsize=40,
            color="white", va="center", zorder=61)
    # Escala gráfica
    km = proj.cm_por_km()
    sy = y0 + h - 9
    for i in range(2):
        ax.add_patch(Rectangle((tx + i * km, sy), km, 1.0, facecolor="white" if i % 2 == 0 else "#9c7cc4",
                               edgecolor="white", linewidth=2, zorder=61))
    ax.text(tx, sy + 1.6, "0", fontproperties=fuentes["texto"], fontsize=30, color="white", va="top", zorder=61)
    ax.text(tx + 2 * km, sy + 1.6, "2 km", fontproperties=fuentes["texto"], fontsize=30, color="white",
            va="top", ha="center", zorder=61)
    ax.text(tx + 2 * km + 8, sy + 0.5, "N ↑", fontproperties=fuentes["titulo"], fontsize=48, color="white",
            va="center", zorder=61)
    ax.text(tx, y0 + h - 3, "Mapa base © colaboradores de OpenStreetMap · OpenMapTiles · OpenFreeMap.  "
            "Calles: Geochicas, «Las Calles de las Mujeres» (ODbL).  Textos: Wikipedia (CC BY-SA 4.0).",
            fontproperties=fuentes["texto"], fontsize=20, color="#cdbbe6", va="center", zorder=61)


def tarjetas_prueba(calles, urls, fuentes, logo, destino):
    """Hojas carta con 6 pines QR cada una (a escala reducida) para probar con el celular."""
    from matplotlib.backends.backend_pdf import PdfPages

    k = 8.0 / logo.arriba  # pines de 8 cm de alto
    ids = list(calles)
    with PdfPages(destino) as pdf:
        for p in range(0, len(ids), 6):
            fig = plt.figure(figsize=(21.59 * CM, 27.94 * CM))
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, 21.59)
            ax.set_ylim(27.94, 0)
            ax.axis("off")
            for i, cid in enumerate(ids[p:p + 6]):
                tx = 5.9 + (i % 2) * 9.8
                ty = 9.3 + (i // 2) * 8.6
                centro = logo.dibujar(ax, tx, ty, k, 1, MARCA, fondo="white", con_disco=False)
                qr_circular(ax, *centro, logo.r_qr * k, urls[cid], cid, 3)
                ax.text(tx + 3.2, ty - 4, calles[cid]["mujer"]["nombre"], ha="left", va="center", fontsize=10,
                        fontproperties=fuentes["titulo"], color=MARCA, wrap=True)
            ax.text(10.8, 27.2, "Tarjetas de prueba · Las Calles de las Mujeres", ha="center", fontsize=9,
                    fontproperties=fuentes["texto"], color="#777")
            pdf.savefig(fig)
            plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url-base", required=True, help="URL pública de ar.html (sin ?calle_id)")
    ap.add_argument("--datos", default=str(RAIZ / "calles_cdmx.json"))
    ap.add_argument("--dpi-preview", type=int, default=12)
    a = ap.parse_args()

    SALIDA.mkdir(exist_ok=True)
    fuentes = {
        "titulo": fuente("space-grotesk_latest_latin-700-normal"),
        "subtitulo": fuente("space-grotesk_latest_latin-500-normal"),
        "texto": fuente("inter_latest_latin-400-normal"),
        "texto_b": fuente("inter_latest_latin-600-normal"),
    }
    calles = json.loads(Path(a.datos).read_text(encoding="utf-8"))["calles"]
    urls = {cid: f"{a.url_base}?calle_id={cid}" for cid in calles}
    proj = Proyeccion(*CENTRO, LADO_KM, LADO_CM)

    print("Descargando mapa base (OpenFreeMap)…")
    rellenos, viales, rios, limites, colonias = capas_base(proj, descargar_tiles(proj))
    print("Calles con nombre de mujer (Geochicas)…")
    por_osm, trazos_mujer, total_mujer = calles_mujeres(proj)

    fig = plt.figure(figsize=(LADO_CM * CM, LADO_CM * CM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, LADO_CM)
    ax.set_ylim(LADO_CM, 0)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), LADO_CM, LADO_CM, facecolor=FONDO, zorder=0))

    rellenar(ax, rellenos[RESIDENCIAL], RESIDENCIAL, 1)
    rellenar(ax, rellenos[BOSQUE], BOSQUE, 2)
    rellenar(ax, rellenos[PARQUE], PARQUE, 3)
    rellenar(ax, rellenos[AGUA], AGUA, 4)
    trazar(ax, rios, AGUA, 3, 5)
    trazar(ax, viales["menor"], CALLE_MENOR, 1.6, 6)
    trazar(ax, viales["tren"], TREN, 2.5, 7, linestyles=(0, (4, 3)))
    for clave, ancho in (("terciaria", 4), ("secundaria", 6), ("primaria", 8), ("autopista", 11)):
        trazar(ax, viales[clave], CASING, ancho + 2.5, 8)
    for clave, ancho in (("terciaria", 4), ("secundaria", 6), ("primaria", 8), ("autopista", 11)):
        trazar(ax, viales[clave], CALLE_MAYOR, ancho, 9)
    trazar(ax, limites, "#a9a9a9", 6, 10, linestyles=(0, (6, 4)))
    for (x, y), nombre in colonias:
        if 0 < x < LADO_CM and 0 < y < LADO_CM:
            ax.text(x, y, nombre.upper(), ha="center", va="center", fontsize=26, color=ETIQUETA,
                    fontproperties=fuentes["texto_b"], alpha=0.75, zorder=11)

    # Todas las calles con nombre de mujer, pintadas
    trazar(ax, trazos_mujer, "white", 12, 20)
    trazar(ax, trazos_mujer, MUJER, 8, 21)

    # Las 30 calles con QR: todas iguales, sin delatar si su artículo existe
    puntos = {}
    for cid, c in calles.items():
        trazos = [t for osm in c["geo"]["osm_way_ids"] for t in por_osm.get(osm, [])]
        trazar(ax, trazos, "white", 22, 30)
        trazar(ax, trazos, MARCA_CLARA, 15, 31)
        puntos[cid] = punto_de_calle(trazos)

    titulo = (LADO_CM - MARGEN_CM - 112, MARGEN_CM, 112, 74 - 9)  # x, y, ancho, alto (arriba a la derecha)
    reservada = (titulo[0] - 2, titulo[1] - 2, titulo[0] + titulo[2] + 2, titulo[1] + titulo[3] + 2)
    logo = Logo()
    k = logo.escala(QR_CM)
    posiciones = colocar_marcadores(calles, puntos, logo, k, reservada)

    filas = []
    for cid, (tx, ty) in posiciones.items():
        px, py = puntos[cid]
        if math.hypot(tx - px, ty - py) > 0.5:  # pin desplazado: línea guía hasta su calle
            ax.plot([px, tx], [py, ty], color="white", linewidth=12, solid_capstyle="round", zorder=40)
            ax.plot([px, tx], [py, ty], color=MARCA, linewidth=6, solid_capstyle="round", zorder=41)
        ax.add_patch(Circle((px, py), 1.1, facecolor=MARCA, edgecolor="white", linewidth=6, zorder=42))
        version = dibujar_marcador(ax, logo, k, tx, ty, calles[cid], urls[cid], fuentes)
        filas.append({
            "calle_id": cid,
            "nombre_calle": calles[cid]["nombre_calle"],
            "qr_centro_x_cm": round(tx - (logo.punta[0] - logo.hueco["cx"]) * k, 1),
            "qr_centro_y_cm": round(ty - (logo.punta[1] - logo.hueco["cy"]) * k, 1),
            "punta_x_cm": round(tx, 1),
            "punta_y_cm": round(ty, 1),
            "calle_x_cm": round(px, 1),
            "calle_y_cm": round(py, 1),
            "qr_version": version,
            "url": urls[cid],
        })

    cuadro_titulo(ax, *titulo, fuentes, total_mujer, proj, logo)

    pdf = SALIDA / "mapa_calles_mujeres_320cm.pdf"
    print("Escribiendo PDF vectorial…")
    fig.savefig(pdf)
    fig.savefig(SALIDA / "mapa_calles_mujeres_preview.png", dpi=a.dpi_preview)
    plt.close(fig)

    with open(SALIDA / "posiciones_qr.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(sorted(filas, key=lambda f: (f["qr_centro_y_cm"], f["qr_centro_x_cm"])))

    tarjetas_prueba(calles, urls, fuentes, logo, SALIDA / "tarjetas_qr_prueba.pdf")
    print(f"Listo → {SALIDA}  ({pdf.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
