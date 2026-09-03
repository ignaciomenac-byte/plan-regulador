"""
Script batch opcional: recorre todos los poligonos de vivienda/comercio de
uso_suelo_zonas.geojson y precalcula su precio UF/m2 (misma logica que usa
el servidor en vivo, ver precio_utils.py). Util para un reporte offline;
el visor normalmente consulta esto al vuelo por zona al hacer clic.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
from precio_utils import fetch_zone_price

CODIGOS_MERCADO = {"UvO", "Uv2", "Uv3", "UC1", "UC2", "UC3", "UM"}


def main():
    fc = json.load(open("data/processed/uso_suelo_zonas.geojson"))
    feats = [f for f in fc["features"] if f["properties"]["codigo"] in CODIGOS_MERCADO]
    print(f"Zonas a consultar: {len(feats)}")

    out = []
    for i, f in enumerate(feats):
        ring = f["geometry"]["coordinates"][0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        lon0, lon1, lat0, lat1 = min(lons), max(lons), min(lats), max(lats)
        codigo = f["properties"]["codigo"]

        try:
            res = fetch_zone_price(lon0, lon1, lat0, lat1)
        except Exception as e:
            res = {"error": str(e)}
        res["codigo"] = codigo
        res["idx"] = i
        res["bbox"] = [lon0, lat0, lon1, lat1]
        out.append(res)

        status = res.get("uf_m2_mediana", "sin datos / error")
        print(f"[{i+1}/{len(feats)}] {codigo:6s} -> UF/m2 mediana: {status}  (n={res.get('n_listados_validos','-')})")
        time.sleep(1.2)

    with open("data/processed/precios_zonas.json", "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\nGuardado en data/processed/precios_zonas.json")


if __name__ == "__main__":
    main()
