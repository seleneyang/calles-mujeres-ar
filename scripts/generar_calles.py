#!/usr/bin/env python3
"""
Genera calles_cdmx.json a partir del dataset abierto de Las Calles de las Mujeres (Geochicas).

Uso básico (solo datos locales, sin red salvo la descarga del GeoJSON):
    python3 scripts/generar_calles.py -o calles_cdmx.json

Enriquecido (verifica en vivo Wikipedia/Wikidata y guarda extractos de respaldo
para que la exposición funcione aunque falle el wifi de la galería):
    python3 scripts/generar_calles.py -o calles_cdmx.json --enriquecer

Posición física en el plotter (para colocar los QR): pasa la caja envolvente
exacta del mapa impreso y su ancho en cm:
    python3 scripts/generar_calles.py --bbox -99.36,19.05,-98.94,19.59 --ancho-cm 320

Solo usa la biblioteca estándar de Python 3.9+.
"""
import argparse
import json
import math
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date

GEOJSON_URL = (
    "https://raw.githubusercontent.com/geochicasosm/lascallesdelasmujeres/"
    "master/data/cdmx/final_tile.geojson"
)
WIKI_API = "https://es.wikipedia.org/w/api.php"
USER_AGENT = "GeochicasAR/1.0 (exposicion 10 aniversario Geochicas; contacto: cambiar@ejemplo.org)"
RADIO_CLUSTER_M = 600  # tramos con el mismo nombre a menos de esto = la misma calle

PREFIJOS = re.compile(
    r"^(calle|cda\.?|cerrada|av\.?|avenida|privada|priv\.?|calz\.?|calzada|"
    r"andador|and\.?|callejón|cjón\.?|prolongación|prol\.?|retorno|ret\.?|"
    r"\d+a\.?|primera|segunda|tercera|cuarta)\s+(de\s+)?",
    re.IGNORECASE,
)


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def nombre_mujer(nombre_calle):
    previo, n = None, nombre_calle.strip()
    while previo != n:  # "Cda. de Calle X" -> "X"
        previo, n = n, PREFIJOS.sub("", n).strip()
    return n


def punto_medio(geom):
    coords = geom["coordinates"]
    if geom["type"] == "MultiLineString":
        coords = max(coords, key=len)
    lon, lat = coords[len(coords) // 2]
    return lat, lon


def distancia_m(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    p = math.pi / 180
    h = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))


def agrupar(features):
    """Agrupa tramos OSM por nombre y cercanía: una calle física = un QR."""
    clusters = []
    for f in features:
        p = f["properties"]
        pt = punto_medio(f["geometry"])
        for c in clusters:
            if c["nombre"] == p["name"] and any(
                distancia_m(pt, q) < RADIO_CLUSTER_M for q in c["puntos"]
            ):
                c["puntos"].append(pt)
                c["osm"].append(p["id"])
                break
        else:
            clusters.append({
                "nombre": p["name"],
                "link": p.get("wikipedia_link") or "",
                "puntos": [pt],
                "osm": [p["id"]],
            })
    return clusters


def titulo_desde_link(link):
    if not link:
        return None
    return urllib.parse.unquote(link.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def enriquecer(registros):
    """Consulta Wikipedia en lotes de 20: existencia real, QID y extracto de respaldo."""
    titulos = sorted({r["mujer"]["wikipedia_titulo"] for r in registros.values()})
    info = {}
    for i in range(0, len(titulos), 20):
        lote = titulos[i:i + 20]
        q = urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": 2,
            "redirects": 1, "prop": "pageprops|extracts", "ppprop": "wikibase_item|disambiguation",
            "exintro": 1, "explaintext": 1, "exsentences": 3, "exlimit": 20,
            "titles": "|".join(lote),
        })
        d = http_json(f"{WIKI_API}?{q}")["query"]
        norm = {x["from"]: x["to"] for x in d.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in d.get("redirects", [])}
        paginas = {p["title"]: p for p in d["pages"]}
        for t in lote:
            final = redir.get(norm.get(t, t), norm.get(t, t))
            info[t] = (final, paginas.get(final))
        print(f"  Wikipedia: {min(i + 20, len(titulos))}/{len(titulos)}", file=sys.stderr)
        time.sleep(1)  # cortesía con la API (hay límites de tasa)

    for r in registros.values():
        m = r["mujer"]
        final, pag = info.get(m["wikipedia_titulo"], (None, None))
        existe = bool(pag) and not pag.get("missing") and "disambiguation" not in pag.get("pageprops", {})
        m["tiene_articulo"] = existe
        if existe:
            m["wikipedia_titulo"] = final
            m["wikidata_id"] = pag.get("pageprops", {}).get("wikibase_item")
            m["extracto_respaldo"] = pag.get("extract")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geojson", default=GEOJSON_URL, help="ruta o URL del final_tile.geojson")
    ap.add_argument("-o", "--salida", default="calles_cdmx.json")
    ap.add_argument("--enriquecer", action="store_true", help="verificar contra Wikipedia y guardar extractos")
    ap.add_argument("--bbox", help="minLon,minLat,maxLon,maxLat del mapa impreso")
    ap.add_argument("--ancho-cm", type=float, default=320.0)
    ap.add_argument("--url-base", help="si se indica, escribe qr_urls.csv para generar los QR en lote")
    ap.add_argument("--seleccion", help="JSON con las calles curadas (con_articulo / sin_articulo / nombres)")
    a = ap.parse_args()

    if a.geojson.startswith("http"):
        datos = http_json(a.geojson)
    else:
        with open(a.geojson, encoding="utf-8") as fh:
            datos = json.load(fh)

    mujeres = [f for f in datos["features"] if f["properties"].get("gender") == "Female"]
    clusters = agrupar(mujeres)

    todos = [pt for c in clusters for pt in c["puntos"]]
    if a.bbox:
        min_lon, min_lat, max_lon, max_lat = map(float, a.bbox.split(","))
    else:
        min_lat, max_lat = min(p[0] for p in todos), max(p[0] for p in todos)
        min_lon, max_lon = min(p[1] for p in todos), max(p[1] for p in todos)
    # Equirectangular con corrección por latitud: suficiente a escala de ciudad.
    k = math.cos(math.radians((min_lat + max_lat) / 2))
    escala = a.ancho_cm / ((max_lon - min_lon) * k)
    alto_cm = (max_lat - min_lat) * escala

    registros = {}
    for c in clusters:
        lat = sum(p[0] for p in c["puntos"]) / len(c["puntos"])
        lon = sum(p[1] for p in c["puntos"]) / len(c["puntos"])
        mujer = nombre_mujer(c["nombre"])
        calle_id = f"{slug(mujer)}-{min(c['osm'])}"  # estable: no cambia entre ejecuciones
        titulo = titulo_desde_link(c["link"]) or mujer
        registros[calle_id] = {
            "calle_id": calle_id,
            "nombre_calle": c["nombre"],
            "mujer": {
                "nombre": mujer,
                "wikidata_id": None,
                "wikipedia_titulo": titulo,
                "tiene_articulo": bool(c["link"]),
                "extracto_respaldo": None,
            },
            "geo": {
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "osm_way_ids": sorted(c["osm"]),
            },
            "mapa_fisico": {
                "x_cm": round((lon - min_lon) * k * escala, 1),
                "y_cm": round((max_lat - lat) * escala, 1),  # desde el borde superior
            },
        }

    if a.seleccion:
        with open(a.seleccion, encoding="utf-8") as fh:
            sel = json.load(fh)
        elegidas = sel.get("con_articulo", []) + sel.get("sin_articulo", [])
        faltan = [i for i in elegidas if i not in registros]
        if faltan:
            sys.exit(f"calle_id inexistentes en el dataset: {faltan}")
        registros = {i: registros[i] for i in elegidas}
        for i, nombre in sel.get("nombres", {}).items():
            registros[i]["mujer"]["nombre"] = nombre
        for i in sel.get("sin_articulo", []):  # el artículo a crear lleva el nombre corregido
            registros[i]["mujer"]["wikipedia_titulo"] = registros[i]["mujer"]["nombre"]

    if a.enriquecer:
        enriquecer(registros)

    salida = {
        "version": "1.0.0",
        "generado": date.today().isoformat(),
        "fuente": {
            "proyecto": "Las Calles de las Mujeres — Geochicas",
            "url": "https://geochicasosm.github.io/lascallesdelasmujeres/",
            "licencia_datos": "ODbL (© colaboradores de OpenStreetMap)",
        },
        "mapa_fisico": {
            "ancho_cm": a.ancho_cm,
            "alto_cm": round(alto_cm, 1),
            "bbox": [min_lon, min_lat, max_lon, max_lat],
        },
        "calles": dict(sorted(registros.items())),
    }
    with open(a.salida, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    if a.url_base:
        with open("qr_urls.csv", "w", encoding="utf-8") as fh:
            fh.write("calle_id,nombre_calle,x_cm,y_cm,url\n")
            for r in registros.values():
                url = f"{a.url_base}?calle_id={urllib.parse.quote(r['calle_id'])}"
                fh.write(f"{r['calle_id']},\"{r['nombre_calle']}\",{r['mapa_fisico']['x_cm']},"
                         f"{r['mapa_fisico']['y_cm']},{url}\n")

    con = sum(r["mujer"]["tiene_articulo"] for r in registros.values())
    print(f"{len(registros)} calles · {con} con artículo · {len(registros) - con} en la brecha → {a.salida}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
