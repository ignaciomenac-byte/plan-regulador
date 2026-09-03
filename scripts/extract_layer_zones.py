"""
Extrae poligonos de zona desde las capas (OCG) del CAD original para
cualquiera de las 3 laminas, aislando capa por capa y vectorizando.
"""
import sys, os, json
import fitz
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(__file__))
from geo_utils import pdf_to_lonlat

MAPW = 5230.0
OUT_RES_W = 4000
TMP_PDF = ".claude/scratch_preview/_layer_isolate.pdf"

LAMINAS = {
    "uso_suelo": {
        "path": "data/raw/LAMINA-2-USO-DE-SUELO-28Febrero2010.pdf",
        "layer_to_code": {
            "UVO": "UvO", "Uv3": "Uv3", "UV2_255": "Uv2",
            "UC1": "UC1", "UC2": "UC2", "UC3": "UC3", "UM": "UM",
            "UEe1": "UEe1", "UEe2": "UEe2", "UEe3": "UEe3", "UEe4": "UEe4", "UEe5": "UEe5",
        },
    },
    "edificacion": {
        "path": "data/raw/LAMINA-1-EDIFICACION-28Febrero2010.pdf",
        "layer_to_code": {
            "EAa1_255": "EAa1", "EAa2": "EAa2", "EAa3": "EAa3", "EAa4": "EAa4",
            "EAa + ca": "EAa+ca", "EAa+ cm": "EAa+cm",
            "EAm1": "EAm1", "EAm1 prima": "EAm1p", "EAm2": "EAm2", "EAm4": "EAm4",
            "EAb4": "EAb4", "EAb4 prima": "EAb4p",
            "Ee1": "Ee1", "Ee2": "Ee2", "Ee3": "Ee3", "Ee4": "Ee4", "Ee5": "Ee5",
        },
    },
}


def isolate_layer_mask(pdf_path, layer_name, zoom):
    doc = fitz.open(pdf_path)
    ocgs = doc.get_ocgs()
    name_to_xref = {v["name"]: k for k, v in ocgs.items()}
    if layer_name not in name_to_xref:
        return None, 0, 0
    target = name_to_xref[layer_name]
    all_xrefs = list(ocgs.keys())
    off_xrefs = [x for x in all_xrefs if x != target]
    doc.set_layer(-1, on=[target], off=off_xrefs)
    doc.save(TMP_PDF, garbage=0, deflate=False)
    doc.close()

    doc2 = fitz.open(TMP_PDF)
    page = doc2.load_page(0)
    mat = fitz.Matrix(zoom, zoom)
    clip = fitz.Rect(0, 0, MAPW, page.rect.height)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2GRAY)
    doc2.close()
    return gray, pix.width, pix.height


def mask_to_polygons(gray, zoom, lamina, min_area_px=120, close_kernel=27):
    ink = (gray < 250).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
    closed = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    def contour_to_ring(cnt):
        eps = 0.0015 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, eps, True)
        pts_px = approx.reshape(-1, 2)
        pts_pdf = pts_px / zoom
        ring = [pdf_to_lonlat(float(x), float(y), lamina) for x, y in pts_pdf]
        if len(ring) < 3:
            return None
        ring.append(ring[0])
        return ring

    polys = []
    if hierarchy is None:
        return polys
    hierarchy = hierarchy[0]
    for i, cnt in enumerate(contours):
        if hierarchy[i][3] != -1:
            continue  # es un hueco, se procesa junto a su contorno exterior
        area = cv2.contourArea(cnt)
        if area < min_area_px:
            continue
        outer = contour_to_ring(cnt)
        if outer is None:
            continue
        rings = [outer]
        # agrega los huecos (hijos directos de este contorno) como anillos interiores,
        # para no rellenar zonas como UEe3 que en realidad tienen un anillo con hueco
        child = hierarchy[i][2]
        while child != -1:
            hole_area = cv2.contourArea(contours[child])
            if hole_area >= min_area_px:
                hole_ring = contour_to_ring(contours[child])
                if hole_ring is not None:
                    rings.append(hole_ring)
            child = hierarchy[child][0]
        polys.append(rings)
    return polys


def extract_lamina(lamina_key):
    cfg = LAMINAS[lamina_key]
    zoom = OUT_RES_W / MAPW
    features = []
    for layer_name, code in cfg["layer_to_code"].items():
        gray, w, h = isolate_layer_mask(cfg["path"], layer_name, zoom)
        if gray is None:
            print(f"!! capa no encontrada en {lamina_key}: {layer_name}")
            continue
        polys = mask_to_polygons(gray, zoom, lamina_key)
        print(f"[{lamina_key}] {layer_name:16s} -> {code:8s}  poligonos: {len(polys)}")
        for rings in polys:
            features.append({
                "type": "Feature",
                "properties": {"codigo": code, "capa_cad": layer_name, "lamina": lamina_key},
                "geometry": {"type": "Polygon", "coordinates": rings},
            })
    fc = {"type": "FeatureCollection", "features": features}
    out_path = f"data/processed/{lamina_key}_zonas.geojson"
    with open(out_path, "w") as f:
        json.dump(fc, f)
    print(f"-> Guardado {len(features)} poligonos en {out_path}\n")
    return fc


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    keys = LAMINAS.keys() if which == "all" else [which]
    for k in keys:
        extract_lamina(k)
