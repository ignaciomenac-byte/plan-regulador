"""
Logica compartida para consultar Portal Inmobiliario filtrado por bounding
box y calcular un precio UF/m2 de referencia a partir de publicaciones
individuales con precio fijo (se descartan los "PROYECTO...Desde UF X").
"""
import re
import statistics
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "es-CL,es;q=0.9",
}
MIN_MUESTRA = 3
# Portal Inmobiliario devuelve 404 si el area de busqueda es muy chica
# (probado empiricamente: falla bajo ~0.001 grados de radio, ~110m).
MIN_BBOX_DEG = 0.0015


def bbox_url(lon0, lon1, lat0, lat1):
    if lon1 - lon0 < MIN_BBOX_DEG * 2:
        cx = (lon0 + lon1) / 2
        lon0, lon1 = cx - MIN_BBOX_DEG, cx + MIN_BBOX_DEG
    if lat1 - lat0 < MIN_BBOX_DEG * 2:
        cy = (lat0 + lat1) / 2
        lat0, lat1 = cy - MIN_BBOX_DEG, cy + MIN_BBOX_DEG
    return (
        "https://www.portalinmobiliario.com/venta/_DisplayType_M_item*"
        f"location_lat:{lat0:.5f}*{lat1:.5f},lon:{lon0:.5f}*{lon1:.5f}"
    )


def parse_listing(item):
    if item.select_one(".poly-pill__pill"):
        return None
    price_el = item.select_one('[aria-label*="unidades de fomento"]')
    if not price_el:
        return None
    m = re.search(r"([\d.]+)\s*unidades de fomento", price_el["aria-label"])
    if not m:
        return None
    precio_uf = float(m.group(1).replace(".", ""))

    # Solo m2 utiles: mezclar con "totales" (raro, y son casas/sitios que no
    # son comparables 1 a 1 con departamentos) distorsiona la mediana.
    m2 = None
    m2_tipo = None
    for li in item.select(".poly-attributes_list__item"):
        txt = li.get_text(strip=True)
        mm = re.search(r"([\d.]+)(?:\s*-\s*([\d.]+))?\s*m²\s*(útiles)", txt)
        if mm:
            a = float(mm.group(1).replace(".", ""))
            b = float(mm.group(2).replace(".", "")) if mm.group(2) else a
            m2 = (a + b) / 2
            m2_tipo = mm.group(3)
            break
    if not m2 or m2 <= 0:
        return None

    title_el = item.select_one(".poly-component__title")
    link_el = item.select_one("a.poly-component__title")
    return {
        "titulo": title_el.get_text(strip=True) if title_el else "",
        "precio_uf": precio_uf,
        "m2": m2,
        "m2_tipo": m2_tipo,
        "uf_m2": round(precio_uf / m2, 1),
        "url": link_el["href"].split("#")[0] if link_el and link_el.has_attr("href") else None,
    }


def fetch_zone_price(lon0, lon1, lat0, lat1, timeout=20):
    url = bbox_url(lon0, lon1, lat0, lat1)
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    items = soup.select("li.ui-search-layout__item")
    listings = [parse_listing(it) for it in items]
    listings = [l for l in listings if l]
    result = {
        "url": url,
        "n_items_pagina": len(items),
        "n_listados_validos": len(listings),
    }
    if len(listings) >= MIN_MUESTRA:
        vals = [l["uf_m2"] for l in listings]
        result["uf_m2_mediana"] = round(statistics.median(vals), 1)
        result["uf_m2_promedio"] = round(statistics.mean(vals), 1)
        result["n_m2_totales"] = sum(1 for l in listings if l["m2_tipo"] == "totales")
        result["n_m2_utiles"] = sum(1 for l in listings if l["m2_tipo"] == "útiles")
        result["muestra"] = sorted(listings, key=lambda l: l["uf_m2"])[:8]
    else:
        result["uf_m2_mediana"] = None
        result["muestra_insuficiente"] = True
        result["muestra"] = listings
    return result
