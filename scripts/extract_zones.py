"""
Extrae poligonos de zona desde las capas (OCG) originales del PDF del Plan
Regulador y los georreferencia a GeoJSON (lon/lat, WGS84).

Estrategia: aislar cada capa CAD (OCG) prendiendo solo esa capa, renderizar
a raster, cerrar el patron de achurado con morfologia, sacar contornos, y
transformar pixel -> pt PDF -> UTM -> lon/lat.
"""
import sys, os, json
import fitz
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(__file__))
from geo_utils import pdf_to_lonlat

PDF_PATH = "data/raw/LAMINA-2-USO-DE-SUELO-28Febrero2010.pdf"
MAPW = 5230.0  # recorta la columna de leyenda de la derecha
OUT_RES_W = 4000  # ancho de render en px, mas resolucion = contornos mas finos
TMP_PDF = ".claude/scratch_preview/_layer_isolate.pdf"

# capa CAD (OCG) -> codigo de zona segun la simbologia del plano
LAYER_TO_CODE = {
    "UVO": "UvO",
    "Uv3": "Uv3",
    "UV2_255": "Uv2",
    "UC1": "UC1",
    "UC2": "UC2",
    "UC3": "UC3",
    "UM": "UM",
    "UEe1": "UEe1",
    "UEe2": "UEe2",
    "UEe3": "UEe3",
    "UEe4": "UEe4",
    "UEe5": "UEe5",
    "Default_usuelo": "UV_base",  # base/residual - pendiente de verificar contra leyenda
}


def isolate_layer_mask(doc_path, layer_name, zoom):
    doc = fitz.open(doc_path)
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


def mask_to_polygons(gray, zoom, min_area_px=120, close_kernel=27):
    ink = (gray < 250).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
    closed = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    polys = []
    if hierarchy is None:
        return polys
    hierarchy = hierarchy[0]
    for i, cnt in enumerate(contours):
        parent = hierarchy[i][3]
        if parent != -1:
            continue  # es un hueco, no un poligono independiente (los ignoramos por ahora)
        area = cv2.contourArea(cnt)
        if area < min_area_px:
            continue
        eps = 0.0015 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, eps, True)
        pts_px = approx.reshape(-1, 2)
        pts_pdf = pts_px / zoom
        ring = [pdf_to_lonlat(float(x), float(y)) for x, y in pts_pdf]
        if len(ring) < 3:
            continue
        ring.append(ring[0])
        polys.append(ring)
    return polys


def main():
    zoom = OUT_RES_W / MAPW
    features = []
    for layer_name, code in LAYER_TO_CODE.items():
        gray, w, h = isolate_layer_mask(PDF_PATH, layer_name, zoom)
        if gray is None:
            print(f"!! capa no encontrada: {layer_name}")
            continue
        polys = mask_to_polygons(gray, zoom)
        print(f"{layer_name:20s} -> {code:8s}  poligonos: {len(polys)}")
        for ring in polys:
            features.append({
                "type": "Feature",
                "properties": {"codigo": code, "capa_cad": layer_name, "lamina": "uso_suelo"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })

    fc = {"type": "FeatureCollection", "features": features}
    out_path = "data/processed/uso_suelo_zonas.geojson"
    with open(out_path, "w") as f:
        json.dump(fc, f)
    print(f"\nGuardado {len(features)} poligonos en {out_path}")


if __name__ == "__main__":
    main()
