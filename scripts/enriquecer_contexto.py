#!/usr/bin/env python3
"""
Agrega a calles_cdmx.json lo que usan las funciones interactivas de ar.html:

  contexto        imágenes curadas en contextos.json, con autor y licencia leídos de Wikimedia Commons
  linea_tiempo    nacimiento, muerte, premios, obras y cargos (Wikidata)
  temas           para los recorridos: escritoras, artistas, científicas, educadoras, insurgentas…
  mapa_fisico     dónde está cada pin QR sobre el mapa del piso (de impresion/posiciones_qr.csv)

Orden de ejecución: generar_calles.py → generar_mapa_impreso.py → enriquecer_contexto.py

    python3 scripts/enriquecer_contexto.py
"""
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "GeochicasAR/1.0 (https://github.com/seleneyang/calles-mujeres-ar)"}
COMMONS = "https://commons.wikimedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"

# Ocupaciones de Wikidata (etiqueta en español) → tema del recorrido
TEMAS = [
    ("insurgentas", "Insurgentas y revolucionarias",
     r"revolucionari|insurgent|militar|independent|activista|polític|soldad|guerriller"),
    ("escritoras", "Escritoras y periodistas", r"escrit|poet|novel|periodist|ensay|dramaturg|articulist"),
    ("artistas", "Artistas", r"pint|actriz|artist|cantante|escultor|fotógraf|bailar|music"),
    ("cientificas", "Científicas", r"físic|químic|científic|arqueólog|médic|investigador|matemátic|ingenier"),
    ("educadoras", "Maestras y educadoras", r"profesor|maestr|educador|pedagog|docente"),
    ("feministas", "Feministas", r"feminist|sufrag"),
]


def http_json(url, params):
    u = f"{url}?{urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})}"
    for intento in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(15 * (intento + 1))
    raise SystemExit("Wikimedia está limitando las peticiones; intenta más tarde.")


def limpiar_html(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()


# ---------------------------------------------------------------- Commons
def creditos_commons(archivos):
    """Autor, licencia y URL (1280 px) de cada archivo de Commons."""
    info = {}
    for i in range(0, len(archivos), 40):
        lote = archivos[i:i + 40]
        d = http_json(COMMONS, {"action": "query", "titles": "|".join(lote), "prop": "imageinfo",
                                "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
                                "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit"})
        norm = {n["from"]: n["to"] for n in d["query"].get("normalized", [])}
        paginas = {p["title"]: p for p in d["query"]["pages"]}
        for a in lote:
            p = paginas.get(norm.get(a, a))
            if not p or p.get("missing") or "imageinfo" not in p:
                print(f"  ⚠️  no existe en Commons: {a}", file=sys.stderr)
                continue
            ii = p["imageinfo"][0]
            md = ii.get("extmetadata", {})
            info[a] = {
                "src": ii.get("thumburl") or ii["url"],
                "pagina": ii["descriptionurl"],
                "autor": limpiar_html(md.get("Artist", {}).get("value")) or "Autor desconocido",
                "licencia": md.get("LicenseShortName", {}).get("value", ""),
                "licencia_url": md.get("LicenseUrl", {}).get("value", ""),
                "horizontal": ii["width"] >= ii["height"],
            }
        time.sleep(1)
    return info


# ---------------------------------------------------------------- Wikidata
def entidades(ids, props="claims|labels"):
    out = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 50):
        d = http_json(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
                                 "props": props, "languages": "es|en"})
        out.update(d["entities"])
        time.sleep(1)
    return out


def etiqueta(ent):
    if not ent:
        return None
    lab = ent.get("labels", {})
    return (lab.get("es") or lab.get("en") or {}).get("value")


def valores(ent, prop):
    return [c for c in ent.get("claims", {}).get(prop, []) if c["mainsnak"].get("datavalue")]


def anio(claim_o_snak):
    snak = claim_o_snak.get("mainsnak", claim_o_snak)
    t = snak["datavalue"]["value"].get("time", "")
    m = re.match(r"([+-])0*(\d+)-", t)
    return int(m.group(2)) * (-1 if m.group(1) == "-" else 1) if m else None


def anio_calificador(claim, *props):
    for p in props:
        for q in claim.get("qualifiers", {}).get(p, []):
            if q.get("datavalue"):
                return anio(q)
    return None


def qid(claim):
    return claim["mainsnak"]["datavalue"]["value"].get("id")


def etiqueta_es(ent):
    """Solo la etiqueta en español: mejor omitir un dato que mostrarlo en inglés."""
    return ((ent or {}).get("labels", {}).get("es") or {}).get("value")


FEMENINO = [(r"^embajador\b", "embajadora"), (r"^diputado\b", "diputada"), (r"^senador\b", "senadora"),
            (r"^presidente\b", "presidenta"), (r"^secretario\b", "secretaria"), (r"^director\b", "directora"),
            (r"^ministro\b", "ministra"), (r"^cónsul\b", "cónsul"), (r"^rector\b", "rectora")]


def en_femenino(cargo):
    for rx, rep in FEMENINO:
        cargo = re.sub(rx, rep, cargo, flags=re.IGNORECASE)
    return cargo


def con_articulo(premio):
    primera = premio.split()[0].lower()
    if primera in ("medalla", "orden", "condecoración", "gran", "beca", "presea", "insignia"):
        return f"la {premio}"
    if primera in ("premio", "doctorado", "título", "reconocimiento", "galardón"):
        return f"el {premio}"
    return premio


def linea_tiempo(ent, refs, obras):
    nace = muere = None
    eventos = []
    for prop, verbo, lugar in (("P569", "Nace", "P19"), ("P570", "Muere", "P20")):
        for c in valores(ent, prop)[:1]:
            sitio = next((etiqueta_es(refs.get(qid(l))) for l in valores(ent, lugar)), None)
            eventos.append({"anio": anio(c), "texto": f"{verbo}{' en ' + sitio if sitio else ''}"})
            nace, muere = (anio(c), muere) if prop == "P569" else (nace, anio(c))
    premios = []
    for c in valores(ent, "P166"):
        a, nombre = anio_calificador(c, "P585"), etiqueta_es(refs.get(qid(c)))
        if a and nombre:
            premios.append({"anio": a, "texto": f"Recibe {con_articulo(nombre)}", "nobel": "Nobel" in nombre})
    premios.sort(key=lambda e: (not e["nobel"], e["anio"]))  # los Nobel primero, luego por fecha
    eventos += [{"anio": e["anio"], "texto": e["texto"]} for e in premios[:3]]
    for c in valores(ent, "P39"):  # cargos
        a, nombre = anio_calificador(c, "P580"), etiqueta_es(refs.get(qid(c)))
        if a and nombre:
            eventos.append({"anio": a, "texto": f"Es nombrada {en_femenino(nombre)}"})
    for c in valores(ent, "P800"):  # obras destacadas
        o = obras.get(qid(c))
        fecha = next((anio(x) for x in valores(o, "P577") + valores(o, "P571")), None) if o else None
        if fecha and etiqueta_es(o):
            if muere and fecha > muere + 30:
                continue  # fecha de una reedición, no de la obra
            postuma = " (póstuma)" if muere and fecha > muere else ""
            eventos.append({"anio": fecha, "texto": f"«{etiqueta_es(o)}»{postuma}"})
    vistos, limpio = set(), []
    for e in sorted((e for e in eventos if e["anio"]), key=lambda e: e["anio"]):
        clave = (e["anio"], e["texto"])
        if clave not in vistos:
            vistos.add(clave)
            limpio.append(e)
    if len(limpio) > 9:  # se conservan nacimiento, muerte y los hitos más antiguos
        fin = [e for e in limpio if e["texto"].startswith("Muere")]
        limpio = [e for e in limpio if e not in fin][:9 - len(fin)] + fin
        limpio.sort(key=lambda e: e["anio"])
    return limpio


def temas(ent, refs):
    ocup = " ".join(filter(None, (etiqueta_es(refs.get(qid(c))) for c in valores(ent, "P106")))).lower()
    return [clave for clave, _, rx in TEMAS if re.search(rx, ocup)]


# ---------------------------------------------------------------- main
def main():
    ruta_datos = RAIZ / "calles_cdmx.json"
    datos = json.loads(ruta_datos.read_text(encoding="utf-8"))
    calles = datos["calles"]
    curaduria = json.loads((RAIZ / "contextos.json").read_text(encoding="utf-8"))

    # 1. Posición de cada pin en el mapa del piso
    with open(RAIZ / "impresion" / "posiciones_qr.csv", encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            if fila["calle_id"] in calles:
                calles[fila["calle_id"]]["mapa_fisico"] = {
                    "qr_x_cm": float(fila["qr_centro_x_cm"]), "qr_y_cm": float(fila["qr_centro_y_cm"])}

    # 2. Imágenes de contexto
    archivos = [img["archivo"] for c in curaduria.values() if isinstance(c, dict)
                for img in c.get("imagenes", []) if img.get("archivo")]
    print(f"Commons: {len(archivos)} imágenes…", file=sys.stderr)
    cred = creditos_commons(archivos) if archivos else {}
    for cid, calle in calles.items():
        imgs = []
        for img in curaduria.get(cid, {}).get("imagenes", []):
            if img.get("archivo") in cred:
                imgs.append({**cred[img["archivo"]], "pie": img.get("pie", "")})
            elif img.get("url"):  # imagen fuera de Commons: créditos escritos a mano
                faltan = [k for k in ("autor", "licencia") if not img.get(k)]
                if faltan:
                    print(f"  ⚠️  {cid}: falta {', '.join(faltan)} en {img['url']}", file=sys.stderr)
                    continue
                imgs.append({"src": img["url"], "pagina": img.get("pagina", img["url"]), "autor": img["autor"],
                             "licencia": img["licencia"], "licencia_url": img.get("licencia_url", ""),
                             "horizontal": img.get("horizontal", True), "pie": img.get("pie", "")})
        calle["contexto"] = imgs

    # 3. Línea de tiempo y temas
    qids = {cid: c["mujer"]["wikidata_id"] for cid, c in calles.items() if c["mujer"].get("wikidata_id")}
    qids.update({cid: c["wikidata_id"] for cid, c in curaduria.items()
                 if isinstance(c, dict) and c.get("wikidata_id") and cid in calles})
    print(f"Wikidata: {len(qids)} mujeres…", file=sys.stderr)
    mujeres = entidades(qids.values())
    ref_ids, obra_ids = set(), set()
    for ent in mujeres.values():
        for prop in ("P19", "P20", "P106", "P166", "P39"):
            ref_ids.update(qid(c) for c in valores(ent, prop) if qid(c))
        obra_ids.update(qid(c) for c in valores(ent, "P800") if qid(c))
    refs = entidades(ref_ids, props="labels") if ref_ids else {}
    obras = entidades(obra_ids) if obra_ids else {}
    for cid, calle in calles.items():
        ent = mujeres.get(qids.get(cid))
        calle["linea_tiempo"] = linea_tiempo(ent, refs, obras) if ent else []
        calle["temas"] = temas(ent, refs) if ent else []
        calle["temas"] = sorted(set(calle["temas"]) | set(curaduria.get(cid, {}).get("temas", [])))

    datos["temas"] = {clave: nombre for clave, nombre, _ in TEMAS}
    ruta_datos.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    con_img = sum(bool(c["contexto"]) for c in calles.values())
    print(f"Listo: {con_img}/{len(calles)} con imágenes de contexto · "
          f"{sum(bool(c['linea_tiempo']) for c in calles.values())} con línea de tiempo", file=sys.stderr)
    for clave, nombre, _ in TEMAS:
        nombres = [c["mujer"]["nombre"] for c in calles.values() if clave in c["temas"]]
        print(f"  {nombre}: {', '.join(nombres) or '—'}", file=sys.stderr)


if __name__ == "__main__":
    main()
