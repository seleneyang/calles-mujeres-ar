# Las Calles de las Mujeres · AR (10 años de Geochicas)

Una experiencia WebAR para un mapa impreso de la CDMX de 3.20 m que se coloca en el suelo. Cada calle con nombre de mujer tiene un QR al lado. Al escanearlo se abre `ar.html?calle_id=…`, que muestra la biografía de la mujer (desde Wikipedia) o, si su artículo no existe, una invitación a escribirlo.

```
geochicas-ar/
├── ar.html                  # App completa (HTML + CSS + JS, sin build ni dependencias)
├── calles_cdmx.json         # Datos de las 30 calles del mapa impreso
├── seleccion_30.json        # Curaduría: 15 con artículo + 15 sin artículo, y nombres corregidos
├── contextos.json           # Curaduría: imágenes de contexto de cada mujer (para llenar)
├── impresion/               # ← ARCHIVOS PARA IMPRIMIR
│   ├── mapa_calles_mujeres_320cm.pdf   # vectorial, 320 × 320 cm, para el plotter
│   ├── mapa_calles_mujeres_preview.png # vista previa
│   ├── posiciones_qr.csv               # dónde queda cada QR (cm) para revisar en sitio
│   └── tarjetas_qr_prueba.pdf          # los 30 QR en hojas carta para probar con el celular
└── scripts/
    ├── generar_calles.py        # dataset de Geochicas → calles_cdmx.json
    ├── enriquecer_contexto.py   # imágenes (Commons), línea de tiempo y temas (Wikidata), posiciones
    └── generar_mapa_impreso.py  # calles_cdmx.json + OpenFreeMap → PDF del plotter
```

## Arquitectura

| Capa | Qué hace | Dónde |
|---|---|---|
| **Datos** | `calles_cdmx.json` indexado por `calle_id`. Se genera desde el `final_tile.geojson` de Geochicas y agrupa los tramos de OSM que forman una misma calle. | `scripts/generar_calles.py` |
| **Enrutamiento** | Cada QR codifica `https://<dominio>/ar.html?calle_id=<id>`. El id es `slug-del-nombre` + `id OSM más bajo`, así que no cambia si vuelves a generar el JSON (importante porque los QR ya estarán impresos). | URL |
| **Visualización** | Cámara trasera (`getUserMedia`) a pantalla completa y un panel en CSS 3D que contra-rota con el giroscopio para que parezca flotar sobre el QR del suelo. | `ar.html` |

**Por qué no uso AR.js ni A-Frame:** el marcador de AR.js tendría que ser un patrón propio impreso (no detecta QR); el modo de AR.js basado en GPS no sirve en interiores ni a la escala de una alfombra de 3 m; y A-Frame añade unos 1.5 MB que hay que descargar con el wifi de una galería. La cámara nativa con un panel en CSS 3D funciona igual en iOS Safari y en Android Chrome, carga al instante y no necesita instalar nada. Si más adelante quieres un anclaje real al suelo, el paso siguiente sería **MindAR (image tracking)**, entrenado con recortes del mapa impreso.

### Flujo lógico de `ar.html`

1. **Paso A:** lee `calle_id` de la URL y lo valida con `[a-z0-9-]`.
2. **Paso B:** pide el JSON local en cuanto carga la página, mientras la persona decide sobre los permisos de cámara. Con el título obtenido consulta `https://es.wikipedia.org/api/rest_v1/page/summary/{Titulo_Articulo}`. Esta llamada depende del título que trae el JSON, así que va encadenada a la primera.
3. **Paso C:**
   - Si la API responde **200** → panel con el título, el extracto, el retrato y el botón **«Leer artículo completo»**.
   - Si responde **404** o es una página de desambiguación → antes de mostrar la brecha se consulta Wikidata (`sitelinks.eswiki`). Si alguien escribió el artículo después de imprimir el mapa, la experiencia ya lo muestra.
   - Si de verdad no existe → **Info Box de brecha**: borde animado magenta, vibración y botones a *Escribir este artículo*, a la guía de Geochicas y a [Ayuda:Tu primer artículo](https://es.wikipedia.org/wiki/Ayuda:Tu_primer_art%C3%ADculo).
   - **Sin red o timeout (7 s)** → se usan `tiene_articulo` y `extracto_respaldo` del JSON. El wifi de una galería suele fallar, y si fallara se le estaría diciendo a la gente que una biografía no existe cuando sí existe.

## Esquema de `calles_cdmx.json`

```jsonc
{
  "version": "1.0.0",
  "mapa_fisico": { "ancho_cm": 320, "alto_cm": 324.5, "bbox": [minLon, minLat, maxLon, maxLat] },
  "calles": {
    "<calle_id>": {
      "calle_id": "leona-vicario-24850916",
      "nombre_calle": "Leona Vicario",
      "mujer": {
        "nombre": "Leona Vicario",
        "wikidata_id": "Q2525584",          // null si no hay entidad
        "wikipedia_titulo": "Leona Vicario",
        "tiene_articulo": true,             // verificado al generar; la app re-verifica en vivo
        "extracto_respaldo": "…"            // para cuando no hay red
      },
      "geo": { "lat": 19.435887, "lon": -99.126644, "osm_way_ids": [24850916] },
      "mapa_fisico": { "x_cm": 172.2, "y_cm": 121.4 }   // dónde pegar el QR en el plotter
    }
  }
}
```

Generar el archivo con **todas** las calles con nombre de mujer (≈480):

```bash
python3 scripts/generar_calles.py -o calles_cdmx.json --enriquecer --bbox=-99.36,19.05,-98.94,19.59 --url-base https://mi-exposicion.org/ar.html
```

- `--bbox` debe ser **la caja exacta del mapa impreso**. Así `x_cm`/`y_cm` indican dónde colocar cada QR medido desde la esquina superior izquierda.
- `--url-base` crea `qr_urls.csv`, que sirve para generar todos los QR en lote (por ejemplo con `qrencode`).
- `--enriquecer` hace una petición a Wikipedia por cada lote de 20 calles, con 1 s de pausa entre lotes. Cambia el `USER_AGENT` del script y pon un correo de contacto real.

> ⚠️ **Hay que curar los datos antes de imprimir.** El dataset de Geochicas incluye nombres ambiguos («Adelita», «Ana María», «Santa María…») que no siempre se refieren a una mujer concreta. Revisa el JSON y quita o corrige esas entradas.

## Las 30 calles y el mapa impreso

`seleccion_30.json` reúne 15 calles **con** artículo en Wikipedia en español y 15 **sin** artículo. Las 15 sin artículo se verificaron a mano el 9 de octubre de 2026 buscando cada nombre en Wikipedia y Wikidata, porque el dataset está desactualizado. Por ejemplo, Lucrecia Toriz, Ernestina Larráinzar, Ángela Alessio Robles y Elvira Vargas aparecían sin enlace y sí tienen artículo. Los nombres mal escritos en OSM («Calle Frida Kalho», «Madame Cuirie») se corrigen en el campo `nombres`.

```bash
python3 scripts/generar_calles.py --seleccion seleccion_30.json --enriquecer --bbox=-99.2376,19.2964,-98.9995,19.5216 -o calles_cdmx.json
```
```bash
python3 -m venv .venv && .venv/bin/pip install segno mapbox-vector-tile matplotlib
```
```bash
.venv/bin/python scripts/generar_mapa_impreso.py --url-base https://seleneyang.github.io/calles-mujeres-ar/ar.html
```

El mapa impreso cubre un cuadrado de 25 × 25 km centrado en las 30 calles (escala aproximada de 1 cm por cada 78 m) e incluye:

- **Mapa base:** teselas vectoriales de OpenFreeMap con la paleta Positron. Es la misma que usa la app y no necesita API key. Las teselas se guardan en `.cache/`.
- **Calles con nombre de mujer:** todas las del dataset, pintadas en lila.
- **Tarjeta de leyenda:** lleva el título, el logotipo horizontal de Geochicas en vectores (`assets/logo_geochicas_horizontal.json`, extraído de `assets/logo_geochicas_horizontal.pdf`), el texto de presentación, las instrucciones, la leyenda, la escala y los créditos. Su tamaño se calcula a partir del texto real, para que no quede espacio vacío.
- **Las 30 seleccionadas:** todas se ven iguales, con el mismo color de calle y el mismo pin. Desde el mapa no se puede saber cuál tiene artículo en Wikipedia: cada persona lo descubre al escanear.
- **Los pines:** son el logo de Geochicas (vectorizado en `assets/logo_geochicas.json` a partir de `assets/logo_geochicas.webp`), de 29 × 21.5 cm, con la punta sobre la calle. Si dos pines chocan, uno se desplaza y una línea lo une a su calle.
- **El QR circular:** ocupa todo el interior del círculo del logo y está en el mismo color de Geochicas. La parte que la cámara lee es un QR cuadrado normal de 9.5 cm, versión 8 y corrección de errores nivel Q. Alrededor lleva módulos decorativos idénticos que completan el círculo. Entre el código y la decoración se dejan **1 módulo blanco**, y **2 módulos** alrededor de los tres cuadros de las esquinas (`QR_SILENCIO` y `QR_SILENCIO_BUSCADORES`). En las pruebas, sin ese margen no se leyó ninguno (0/30), y con él ZXing leyó los 30 de frente, inclinados, girados y desenfocados. **No reduzcas esos valores sin volver a probar.**

> ⚠️ Los QR llevan la URL de `--url-base`. Si cambias el dominio o el nombre del repositorio, **vuelve a generar el PDF antes de imprimir**.

## Funciones interactivas de `ar.html`

- **Su mundo:** detrás de la tarjeta pasan las imágenes de contexto elegidas en `contextos.json`, con un acercamiento lento y un efecto de profundidad al inclinar el teléfono. Arriba se muestra el pie de foto con su crédito y licencia. El botón «Ver cámara» las oculta.
- **Marco vacío:** si una mujer no tiene imágenes, la tarjeta de brecha invita a subir una a Wikimedia Commons.
- **Línea de tiempo:** nacimiento, muerte, obras, premios y cargos, tomados de Wikidata, en una pestaña aparte.
- **Escuchar:** el teléfono lee la tarjeta en voz alta (`speechSynthesis`, sin servidor).
- **Tu recorrido:** el teléfono guarda las calles que ya escaneaste (solo en ese teléfono) y muestra «3/30». La hoja del pasaporte incluye recorridos por tema (insurgentas, escritoras, artistas, científicas, educadoras y feministas), con un botón «Guíame».
- **Siguiente en el mapa:** una flecha y la distancia real sobre el piso hasta el pin más cercano que falta, calculadas con `posiciones_qr.csv`.
  - **Calibración automática de la brújula:** no hay que medir nada al montar. Todos los QR están impresos derechos, con su borde de arriba hacia el norte del mapa. Cuando la cámara ve un QR del piso, la app mide qué tan girado aparece y le suma el rumbo de la brújula del teléfono: el resultado es hacia dónde queda el norte del mapa en la sala.
    - Toma 5 lecturas estables y guarda el resultado en ese teléfono durante 24 horas. Usa [jsQR](https://github.com/cozmo/jsQR), que solo se descarga si la persona activa la cámara.
    - Si el teléfono no tiene brújula o la persona no usa la cámara, la flecha indica la dirección «en el mapa», tomando la parte de arriba del mapa como norte.
    - `CONFIG.NORTE_MAPA_RUMBO` solo sirve para fijar un valor a mano, si algún día hiciera falta.

### Curaduría de imágenes (`contextos.json`)

Para cada mujer se agregan de 2 a 4 imágenes de Wikimedia Commons (`archivo` + `pie`). El autor y la licencia se leen automáticamente. Después se ejecuta:

```bash
.venv/bin/python scripts/enriquecer_contexto.py
```

Orden completo de los scripts: `generar_calles.py` → `generar_mapa_impreso.py` → `enriquecer_contexto.py`. El último también agrega la línea de tiempo, los temas y la posición de cada pin. Si se vuelve a ejecutar `generar_calles.py`, hay que repetir los tres en ese orden.

> ⚠️ **Derechos de autor:** la obra de Frida Kahlo (y la de cualquier autora fallecida hace menos de 100 años) está protegida en México. Usa fotos de lugares, objetos, documentos o imágenes en dominio público, no reproducciones de sus obras.

## Guía de despliegue gratuito en GitHub Pages

La cámara solo funciona con **HTTPS**, y GitHub Pages lo da por defecto.

1. Crea un repositorio público, por ejemplo `calles-mujeres-ar`, y sube `ar.html` y `calles_cdmx.json` a la raíz:
   ```bash
   git init && git add ar.html calles_cdmx.json scripts README.md && git commit -m "WebAR Calles de las Mujeres"
   ```
   ```bash
   git remote add origin https://github.com/<usuario>/calles-mujeres-ar.git && git push -u origin main
   ```
2. En GitHub ve a **Settings → Pages → Build and deployment → Source: Deploy from a branch**, elige `main` / `(root)` y guarda.
3. Al cabo de 1 o 2 minutos el sitio estará en `https://<usuario>.github.io/calles-mujeres-ar/ar.html?calle_id=leona-vicario-24850916`.
4. **Prueba de campo:** genera el QR de esa URL, imprímelo, pégalo en el suelo y escanéalo con la cámara nativa del teléfono. Prueba al menos:
   - iPhone con Safari (pide dos permisos: cámara y movimiento)
   - Android con Chrome
   - Un `calle_id` sin artículo (`emilia-romero-de-valle-25154829`)
   - Modo avión después de cargar la página, para comprobar el respaldo sin red
5. **Dominio propio (opcional):** en **Settings → Pages → Custom domain** escribe `mi-exposicion.org`, añade el registro CNAME o los registros A en tu DNS y activa *Enforce HTTPS*. Haz esto **antes** de imprimir los QR, porque después no se pueden cambiar.

**Pruebas en local:** abrir `ar.html` como archivo (`file://`) no funciona porque el `fetch` del JSON queda bloqueado. Sírvelo así:

```bash
python3 -m http.server 8765
```

En el escritorio abre `http://localhost:8765/ar.html?calle_id=leona-vicario-24850916`. Para probar la cámara en un teléfono necesitas HTTPS, así que usa GitHub Pages o un túnel como `cloudflared`.

## Antes de la inauguración

- [ ] Cambiar `GUIA_GEOCHICAS_URL` en `ar.html` por la guía de edición oficial (ahora apunta al sitio del proyecto).
- [ ] Regenerar el JSON con `--enriquecer` lo más cerca posible de la fecha. Las calles que sigan en la brecha son el mensaje de la exposición.
- [ ] Imprimir en material mate o con laminado antideslizante mate, porque el brillo de los focos impide leer los QR. Antes de mandar a imprimir el plotter, probar `tarjetas_qr_prueba.pdf` con varios teléfonos.
- [ ] Si se espera mucho público con la misma IP (el wifi de la galería), revisar los [límites de tasa de Wikimedia](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits). El `extracto_respaldo` evita que la experiencia se rompa si se alcanzan.
