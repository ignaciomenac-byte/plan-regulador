"""
Servidor local: sirve los archivos estaticos del visor (web/) y expone
/api/precio como puente hacia Portal Inmobiliario (evita el bloqueo CORS
que impide llamarlo directo desde el navegador). Cachea en memoria por
bbox para no repetir la misma consulta si el usuario pincha la misma
zona varias veces.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from flask import Flask, request, jsonify, send_from_directory
from precio_utils import fetch_zone_price

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
app = Flask(__name__, static_folder=WEB_DIR)

_cache = {}
CACHE_TTL = 60 * 30  # 30 min


@app.route("/api/precio")
def api_precio():
    try:
        lon0 = float(request.args["lon0"])
        lon1 = float(request.args["lon1"])
        lat0 = float(request.args["lat0"])
        lat1 = float(request.args["lat1"])
    except (KeyError, ValueError):
        return jsonify({"error": "faltan parametros lon0,lon1,lat0,lat1"}), 400

    key = (round(lon0, 5), round(lon1, 5), round(lat0, 5), round(lat1, 5))
    cached = _cache.get(key)
    if cached and time.time() - cached["t"] < CACHE_TTL:
        return jsonify(cached["data"])

    try:
        data = fetch_zone_price(lon0, lon1, lat0, lat1)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    _cache[key] = {"t": time.time(), "data": data}
    return jsonify(data)


@app.route("/")
@app.route("/<path:path>")
def static_files(path="visor.html"):
    return send_from_directory(WEB_DIR, path)


if __name__ == "__main__":
    # threaded=True: sin esto, una consulta lenta a Portal Inmobiliario en
    # /api/precio bloquea el servidor entero (incluso servir archivos
    # estaticos simples) hasta que esa request termine.
    app.run(host="0.0.0.0", port=8743, debug=False, threaded=True)
