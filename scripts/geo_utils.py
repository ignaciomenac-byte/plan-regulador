import math

# Calibracion por lamina, ajustada por minimos cuadrados contra las lineas
# geometricas reales de la capa CAD "GRILLA" (no contra centros de texto,
# que resultaron poco confiables). Cada lamina tiene un registro interno
# ligeramente distinto (offset de ~7-30pt entre archivos), asi que NO
# comparten una unica calibracion. Residuales del ajuste: <1m en las 3.
# La escala resulto isotropica (igual en X e Y) y sin rotacion apreciable
# una vez medida contra la grilla real en vez de las etiquetas de texto.
_CALIB = {
    "vialidad": {"a1": 2.674460780968004, "c1": 348471.86410538875,
                 "a2": -2.6742436655540076, "c2": 6305848.013781094},
    "uso_suelo": {"a1": 2.6742564377757483, "c1": 348400.6036756787,
                  "a2": -2.674690639223767, "c2": 6305829.265431821},
    "edificacion": {"a1": 2.674358612950509, "c1": 348090.12593378924,
                    "a2": -2.673796791445072, "c2": 6305851.6042780755},
}


def pdf_to_utm(x, y, lamina="uso_suelo"):
    c = _CALIB[lamina]
    E = c["a1"] * x + c["c1"]
    N = c["a2"] * y + c["c2"]
    return E, N


def utm_to_latlon(E, N, zone=19, southern=True):
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e = math.sqrt(f * (2 - f))
    x = E - 500000.0
    y = N - 10000000.0 if southern else N
    m = y / k0
    mu = m / (a * (1 - e * e / 4 - 3 * e**4 / 64 - 5 * e**6 / 256))
    e1 = (1 - math.sqrt(1 - e * e)) / (1 + math.sqrt(1 - e * e))
    j1 = 3 * e1 / 2 - 27 * e1**3 / 32
    j2 = 21 * e1**2 / 16 - 55 * e1**4 / 32
    j3 = 151 * e1**3 / 96
    j4 = 1097 * e1**4 / 512
    fp = mu + j1 * math.sin(2 * mu) + j2 * math.sin(4 * mu) + j3 * math.sin(6 * mu) + j4 * math.sin(8 * mu)
    e2 = e * e / (1 - e * e)
    c1 = e2 * math.cos(fp) ** 2
    t1 = math.tan(fp) ** 2
    r1 = a * (1 - e * e) / (1 - e * e * math.sin(fp) ** 2) ** 1.5
    n1 = a / math.sqrt(1 - e * e * math.sin(fp) ** 2)
    d = x / (n1 * k0)
    q2 = d * d / 2
    q3 = (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * e2) * d**4 / 24
    q4 = (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * e2 - 3 * c1 * c1) * d**6 / 720
    q1 = n1 * math.tan(fp) / r1
    lat = fp - q1 * (q2 - q3 + q4)
    q6 = (1 + 2 * t1 + c1) * d**3 / 6
    q7 = (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * e2 + 24 * t1 * t1) * d**5 / 120
    lon = (d - q6 + q7) / math.cos(fp)
    lon0 = math.radians(zone * 6 - 183)
    lon = lon0 + lon
    return math.degrees(lat), math.degrees(lon)


def pdf_to_lonlat(x, y, lamina="uso_suelo"):
    E, N = pdf_to_utm(x, y, lamina)
    lat, lon = utm_to_latlon(E, N)
    return lon, lat
