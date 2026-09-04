"""
UC1 y UC3 usan el mismo angulo de achurado (diagonal), solo se diferencian
por el espaciado entre lineas (UC1 ~5.0pt, UC3 ~6.67pt segun la simbologia
del plano). El CAD original tiene poligonos con la trama de UC3 dibujada
por error en la capa "UC1" (confirmado visualmente en el bloque de Pozo
Almonte). Como el nombre de la capa CAD no es confiable para distinguir
estos dos codigos, se reclasifica cada poligono midiendo el espaciado real
de su trama y comparandolo con los valores de referencia de la simbologia.
"""
import sys, os, json
import fitz
import numpy as np
import pyproj
from shapely.geometry import shape

sys.path.insert(0, os.path.dirname(__file__))
from geo_utils import _CALIB

PDF_PATH = "data/raw/LAMINA-2-USO-DE-SUELO-28Febrero2010.pdf"
ZONAS_PATH = "data/processed/uso_suelo_zonas.geojson"
TMP_PDF = ".claude/scratch_preview/_hatch_measure.pdf"

# espaciado de referencia medido en la simbologia del plano (pt PDF)
REF_UC1 = 5.0
REF_UC3 = 6.6667
THRESHOLD = (REF_UC1 + REF_UC3) / 2  # 5.83pt

_transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32719", always_xy=True)


def lonlat_to_pdf_pt(lon, lat, lamina="uso_suelo"):
    E, N = _transformer.transform(lon, lat)
    c = _CALIB[lamina]
    x = (E - c["c1"]) / c["a1"]
    y = (N - c["c2"]) / c["a2"]
    return x, y


def measure_hatch_spacing(page, cx_pt, cy_pt, half=60, zoom=10, n_rows=20):
    clip = fitz.Rect(cx_pt - half, cy_pt - half, cx_pt + half, cy_pt + half)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = img[:, :, 0]
    spacings = []
    for r in np.linspace(0.15, 0.85, n_rows):
        row = gray[int(r * pix.height), :]
        ink = row < 200
        crossings = int(np.sum(ink[1:] & ~ink[:-1]))
        if 2 < crossings < pix.width / 3:
            spacings.append(pix.width / crossings / zoom)
    if not spacings:
        return None
    return float(np.median(spacings))


def isolate_uc_layers(pdf_path):
    doc = fitz.open(pdf_path)
    ocgs = doc.get_ocgs()
    name_to_xref = {v["name"]: k for k, v in ocgs.items()}
    targets = [name_to_xref[l] for l in ("UC1", "UC3") if l in name_to_xref]
    off = [x for x in ocgs.keys() if x not in targets]
    doc.set_layer(-1, on=targets, off=off)
    doc.save(TMP_PDF, garbage=0, deflate=False)
    doc.close()
    doc2 = fitz.open(TMP_PDF)
    return doc2.load_page(0)


def main():
    fc = json.load(open(ZONAS_PATH))
    page = isolate_uc_layers(PDF_PATH)

    n_reclas = 0
    n_sin_medicion = 0
    for feat in fc["features"]:
        if feat["properties"]["codigo"] not in ("UC1", "UC3"):
            continue
        geom = shape(feat["geometry"])
        c = geom.centroid
        cx_pt, cy_pt = lonlat_to_pdf_pt(c.x, c.y)
        spacing = measure_hatch_spacing(page, cx_pt, cy_pt)
        original = feat["properties"]["codigo"]
        if spacing is None:
            n_sin_medicion += 1
            print(f"!! sin medicion valida, se mantiene {original} en ({c.x:.5f},{c.y:.5f})")
            continue
        nuevo = "UC1" if spacing < THRESHOLD else "UC3"
        feat["properties"]["espaciado_trama_pt"] = round(spacing, 2)
        if nuevo != original:
            n_reclas += 1
            print(f"reclasificado {original} -> {nuevo}  (espaciado={spacing:.2f}pt)  centroide=({c.x:.5f},{c.y:.5f})")
        feat["properties"]["codigo"] = nuevo

    with open(ZONAS_PATH, "w") as f:
        json.dump(fc, f)
    print(f"\nTotal reclasificados: {n_reclas}, sin medicion: {n_sin_medicion}")


if __name__ == "__main__":
    main()
