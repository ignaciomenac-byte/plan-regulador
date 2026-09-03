"""
Demo: predios (unidad atomica) + atributos de uso_suelo y edificacion,
disueltos por distintas combinaciones de capas, para un sector de muestra.
"""
import sys, os, json
import fitz
import numpy as np
import cv2
from shapely.geometry import shape, Polygon, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(__file__))
from geo_utils import pdf_to_lonlat

SAMPLE_BBOX_PDF = (2800, 900, 3600, 1350)  # x0,y0,x1,y1 en pt del PDF (mismo para las 3 laminas)
ZOOM = 5.0
TMP_PDF = ".claude/scratch_preview/_predios_isolate.pdf"


def isolate_predios_mask():
    doc = fitz.open("data/raw/LAMINA-2-USO-DE-SUELO-28Febrero2010.pdf")
    ocgs = doc.get_ocgs()
    name_to_xref = {v["name"]: k for k, v in ocgs.items()}
    target = name_to_xref["predios"]
    all_xrefs = list(ocgs.keys())
    off = [x for x in all_xrefs if x != target]
    doc.set_layer(-1, on=[target], off=off)
    doc.save(TMP_PDF, garbage=0, deflate=False)
    doc.close()

    doc2 = fitz.open(TMP_PDF)
    page = doc2.load_page(0)
    clip = fitz.Rect(*SAMPLE_BBOX_PDF)
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2GRAY)
    doc2.close()
    return gray


def extract_predio_polygons(gray):
    x0, y0, x1, y1 = SAMPLE_BBOX_PDF
    ink = (gray < 200).astype(np.uint8)
    ink_d = cv2.dilate(ink, np.ones((3, 3), np.uint8), iterations=1)
    free = (1 - ink_d).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])

    polys = []
    for i in range(1, num):
        if i in border:
            continue
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 40 or area > 50000:  # descarta ruido y "islas" gigantes no cerradas
            continue
        mask = (labels == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        eps = 0.01 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, eps, True)
        pts_px = approx.reshape(-1, 2).astype(float)
        # pixel (crop-local) -> pdf pt (absoluto)
        pts_pdf = pts_px / ZOOM
        pts_pdf[:, 0] += x0
        pts_pdf[:, 1] += y0
        ring = [pdf_to_lonlat(px, py) for px, py in pts_pdf]
        if len(ring) < 3:
            continue
        ring.append(ring[0])
        try:
            poly = Polygon(ring)
            if poly.is_valid and poly.area > 0:
                polys.append(poly)
        except Exception:
            continue
    return polys


def load_zone_index(path):
    with open(path) as f:
        fc = json.load(f)
    geoms, codes = [], []
    for feat in fc["features"]:
        g = shape(feat["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        geoms.append(g)
        codes.append(feat["properties"]["codigo"])
    tree = STRtree(geoms)
    return geoms, codes, tree


def lookup_code(pt, geoms, codes, tree):
    idxs = tree.query(pt)
    for idx in idxs:
        idx = int(idx)
        if geoms[idx].contains(pt):
            return codes[idx]
    return None


def save_fc(features, path):
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(f"  -> {path} ({len(features)} features)")


def main():
    gray = isolate_predios_mask()
    predios = extract_predio_polygons(gray)
    print(f"predios detectados en la muestra: {len(predios)}")

    uso_geoms, uso_codes, uso_tree = load_zone_index("data/processed/uso_suelo_zonas.geojson")
    edif_geoms, edif_codes, edif_tree = load_zone_index("data/processed/edificacion_zonas.geojson")

    # los predios vienen de un raster: entre lotes vecinos queda un hueco del
    # ancho de la linea de deslinde, asi que no quedan geometricamente
    # contiguos. Se "hinchan" un poco para que unary_union los pueda fusionar,
    # y se desinflan parcialmente despues de unir.
    BUFFER_DEG = 3e-5  # ~3m

    records = []
    for poly in predios:
        c = poly.representative_point()
        # si un predio no cae en ninguna zona con achurado propio, es la zona
        # base "UV" / "EAb1" (no llevan simbologia grafica propia en el plano,
        # se infieren por omision segun la convencion del instrumento)
        uso = lookup_code(c, uso_geoms, uso_codes, uso_tree) or "UV"
        edif = lookup_code(c, edif_geoms, edif_codes, edif_tree) or "EAb_base"
        records.append({"geom": poly, "geom_buf": poly.buffer(BUFFER_DEG), "uso": uso, "edif": edif})

    # 1) predios atomicos (para mostrar la unidad mas fina)
    feats = [{
        "type": "Feature",
        "properties": {"uso": r["uso"], "edif": r["edif"]},
        "geometry": mapping(r["geom"]),
    } for r in records]
    save_fc(feats, "web/sample_predios.geojson")

    # 2) disuelto solo por uso de suelo
    groups = {}
    for r in records:
        groups.setdefault(r["uso"], []).append(r["geom_buf"])
    feats = []
    for code, geoms in groups.items():
        merged = unary_union(geoms).buffer(-BUFFER_DEG * 0.75)
        parts = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        for p in parts:
            if p.is_empty:
                continue
            feats.append({"type": "Feature", "properties": {"sector": code}, "geometry": mapping(p)})
    save_fc(feats, "web/sample_dissolve_uso.geojson")

    # 3) disuelto por uso de suelo + edificacion (combinacion de 2 capas)
    groups = {}
    for r in records:
        key = f"{r['uso']} / {r['edif']}"
        groups.setdefault(key, []).append(r["geom_buf"])
    feats = []
    for code, geoms in groups.items():
        merged = unary_union(geoms).buffer(-BUFFER_DEG * 0.75)
        parts = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        for p in parts:
            if p.is_empty:
                continue
            feats.append({"type": "Feature", "properties": {"sector": code}, "geometry": mapping(p)})
    save_fc(feats, "web/sample_dissolve_uso_edif.geojson")


if __name__ == "__main__":
    main()
