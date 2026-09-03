"""
Filtra los GeoJSON extraidos del PDF (uso de suelo, edificacion, quebradas)
para descartar poligonos cuyo centroide cae fuera del limite comunal real
de Las Condes (obtenido de OpenStreetMap/Nominatim, relation 162991).

Esto corrige "manchas" que aparecian en territorio de Vitacura: la lamina
del plano regulador incluye referencias/quebradas de comunas vecinas para
dar contexto cartografico, pero esas no son zonas normadas por Las Condes.
"""
import json
from shapely.geometry import shape, Point

BOUNDARY_PATH = "data/raw/las_condes_osm.json"

TARGETS = [
    "data/processed/uso_suelo_zonas.geojson",
    "data/processed/edificacion_zonas.geojson",
    "data/processed/restriccion_quebradas.geojson",
]


def load_boundary():
    d = json.load(open(BOUNDARY_PATH))
    return shape(d[0]["geojson"])


def filter_file(path, boundary):
    fc = json.load(open(path))
    kept = []
    dropped = 0
    for feat in fc["features"]:
        geom = shape(feat["geometry"])
        c = geom.centroid
        if boundary.contains(Point(c.x, c.y)):
            kept.append(feat)
        else:
            dropped += 1
    fc["features"] = kept
    with open(path, "w") as f:
        json.dump(fc, f)
    print(f"{path}: {len(kept)} mantenidos, {dropped} descartados (fuera de Las Condes)")


def main():
    boundary = load_boundary()
    for path in TARGETS:
        filter_file(path, boundary)


if __name__ == "__main__":
    main()
