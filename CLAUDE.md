# Plan Regulador Las Condes — visor + detector de arbitraje

## Qué es esto

Visor web del Plan Regulador Comunal de Las Condes (Modificación N°8, feb. 2010)
que muestra, para cualquier punto de la comuna: qué se puede construir ahí
(uso de suelo + norma de edificación: pisos/altura máxima) y el precio de
mercado actual de esa zona (consultado en vivo a Portal Inmobiliario). La idea
de fondo es detectar oportunidades de arbitraje: zonas donde el potencial
normativo es alto pero el precio de mercado todavía no lo refleja.

Está deployado en Render (`render.yaml`, plan free) — el link vigente lo
tiene el usuario. Para desarrollo local ver "Cómo correrlo" más abajo.

## Arquitectura del pipeline

El Plan Regulador viene en 3 PDFs oficiales (planos CAD exportados a PDF,
cada capa de AutoCAD sobrevive como un OCG/"Optional Content Group" dentro
del PDF):

- `LAMINA-1-EDIFICACION` → altura/densidad de edificación permitida
- `LAMINA-2-USO-DE-SUELO` → qué actividades se permiten (vivienda/comercio/equipamiento)
- `LAMINA-3-VIALIDAD` → red vial (poco usado hoy, quedó como POC)

Estos PDFs **no están en git** (están en `.gitignore`, pesan ~80MB y son
documentos públicos de la Municipalidad de Las Condes) — viven en
`data/raw/`. Si esa carpeta no existe (clonaste el repo en otra máquina),
el visor **igual funciona** porque los `.geojson` ya extraídos SÍ están en
`data/processed/` y `web/`, pero no vas a poder re-correr el pipeline de
extracción sin volver a conseguir esos PDFs originales del usuario o del
sitio de la Municipalidad.

### Extracción (PDF CAD → GeoJSON)

`scripts/extract_layer_zones.py` es el script real del pipeline (**NO**
`scripts/extract_zones.py`, que es una versión vieja/abandonada que quedó en
el repo por error de una sesión anterior — no usarlo, tiene un mapeo de capas
desactualizado que mete basura como "UV_base").

Estrategia por cada capa CAD (OCG) de interés:
1. Aislar esa capa prendiéndola sola (`doc.set_layer`) y renderizar a raster.
2. Binarizar tinta, cerrar con morfología (`cv2.MORPH_CLOSE`) para puentear
   los huecos del achurado/hatch, sacar contornos (`cv2.findContours`,
   `RETR_CCOMP` para preservar huecos tipo anillo como UEe3).
3. Simplificar (`approxPolyDP`) y transformar pixel → punto PDF → UTM 19S
   (SIRGAS/WGS84) → lon/lat, usando la calibración afín por lámina en
   `scripts/geo_utils.py::_CALIB` (cada lámina tiene su propio offset interno
   de registro, no comparten el mismo origen).

Salida: `data/processed/{uso_suelo,edificacion}_zonas.geojson`, copiados a
`web/` para que los sirva el visor.

### Filtro de límite comunal

`scripts/filter_boundary.py` descarta polígonos cuyo centroide cae fuera del
límite real de Las Condes. El límite se obtiene de OpenStreetMap/Nominatim
(`data/raw/las_condes_osm.json`, tampoco está en git — se puede regenerar
con una consulta a Nominatim, ver el script) porque **el límite dibujado en
el propio PDF (capas "LIMITE URBANO"/"LIMITE COMUNAL") es un polígono
punteado demasiado disperso para cerrar geométricamente** (se probó con
kernels de cierre morfológico de hasta 100px y nunca cerró un área
razonable — está documentado en el historial de conversación, no vale la
pena reintentar esa vía). Sin este filtro aparecían "manchas" de zonas de
Vitacura/Providencia/Lo Barnechea coloreadas como si fueran de Las Condes.

### Bug conocido y corregido: confusión UC1/UC3

`scripts/fix_uc_hatch.py` corrige un error real del PDF fuente (no del
pipeline): los códigos **UC1** ("comercio e instituciones comunales") y
**UC3** ("taller y comercio menor") usan el mismo ángulo de achurado
diagonal en la simbología, y solo se diferencian por el espaciado entre
líneas (UC1 ≈ 5.0pt, UC3 ≈ 6.67pt). El CAD original tiene varios polígonos
con la trama de UC3 dibujada por error en la capa "UC1". Detectado porque el
usuario notó que un bloque marcado UC1 en el visor decía UC3 en el PDF
original. Se corrigió midiendo el espaciado real de cada polígono (en vez de
confiar en el nombre de la capa CAD) y reclasificando contra ese umbral.

**Validado y descartado como problema real**: se auditaron también
Uv1/Uv2/Uv3/UvO, UM, y varios códigos de edificación (EAa1-4, EAa+ca/cm,
EAm1) cruzando contra el texto impreso del plano y contra la leyenda — todos
usan tipos de trama visualmente distintos entre sí (puntos vs. líneas vs.
cuadrícula vs. sólido), no solo densidad, así que el riesgo de confusión tipo
UC1/UC3 es bajo y no se encontró ningún otro caso.

**Limitación de origen, no bug**: `Uv1` (vivienda N°1) y `EAb1/EAb2/EAb3` no
tienen ninguna trama en el plano — son zonas base sin marca gráfica propia,
así que estructuralmente no se pueden extraer por este método (no hay tinta
que aislar). El visor ya maneja esto: al pinchar una zona sin polígono
extraído, muestra un mensaje genérico de "vivienda (zona base)" en vez de
fallar.

### Precios (Portal Inmobiliario)

`scripts/precio_utils.py` arma una URL de búsqueda de Portal Inmobiliario
filtrada por bounding box (`location_lat:...,lon:...`), scrapea el HTML
(server-side rendered, no necesita browser) y calcula una mediana UF/m²
**solo con m² útiles** (se descartó "totales" a pedido del usuario porque
mezclarlos distorsiona la comparación entre departamentos y casas). Portal
Inmobiliario devuelve 404 si el bbox es muy chico (`MIN_BBOX_DEG`), por eso
se infla el bbox a un mínimo antes de consultar.

`scripts/server.py` es el puente: sirve `web/` como estáticos y expone
`/api/precio` como proxy (evita CORS desde el browser). La consulta de
precio se hace **al pinchar**, no precalculada para toda la comuna.

## Cómo correrlo localmente

```bash
./.venv/bin/pip install -r requirements.txt   # si el venv no existe: python3 -m venv .venv
./.venv/bin/python3 scripts/server.py
# abrir http://localhost:8743
```

Para exponerlo públicamente sin depender de que el PC quede prendido, usar
Render (`render.yaml`, ya configurado con gunicorn). Para una demo rápida
con el PC prendido, `cloudflared tunnel --url http://localhost:8743`
funciona pero se cae solo cada tanto (quick tunnel sin cuenta, sin garantía
de uptime).

## Para regenerar todo desde cero (si tienes los PDFs originales)

```bash
# 1. poner los 3 PDFs en data/raw/ (nombres exactos en LAMINAS dict de extract_layer_zones.py)
./.venv/bin/python3 scripts/extract_layer_zones.py       # genera uso_suelo y edificacion
./.venv/bin/python3 scripts/fix_uc_hatch.py               # corrige UC1/UC3
# 2. regenerar el limite comunal si data/raw/las_condes_osm.json no existe:
#    ver scripts/filter_boundary.py (usa Nominatim, ver conversación para el query exacto)
./.venv/bin/python3 scripts/filter_boundary.py             # filtra fuera de Las Condes
cp data/processed/*.geojson web/
```

## Archivos que son POCs/descartables

`poc_georef.html`, `web/poc_*.html`, `web/visor_dissolve.html`,
`web/sample_*.geojson`, `scripts/dissolve_demo.py`, `scripts/fetch_precios.py`
(batch alternativo al fetch on-click, no se usa) quedaron de etapas de
validación intermedia. No son parte del flujo actual (`web/visor.html` +
`scripts/server.py`) pero se dejaron por si sirven de referencia.
