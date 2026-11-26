"""AgriGap Etki ve Değer Atlası — resmî istatistik çekici (yapay zekâsız, ücretsiz, anahtarsız).

Eurostat'ın açık API'sinden (https://ec.europa.eu/eurostat/api/dissemination) atlas/config.json'daki ürünler
için şu değerleri çeker ve atlas/official.json dosyasına yazar:

  apro_cpsh1       hasat alanı (1000 ha) ve üretim miktarı (1000 t), toplam ve sera (örtü altı) — TR, ES, AB-27
  aact_eaa01       toplam üretim değeri (milyon €, temel fiyatlarla) — ES, AB-27 (Türkiye bu tabloda yok)
  apri_ap_crpouta  üretici satış fiyatı (€/100 kg → €/kg) — ES (AB toplamı ve Türkiye bu tabloda yok)

Türetilen tek değer: hektar başına brüt değer = üretim değeri ÷ hasat alanı (aynı bölge, aynı yıl); açıkça
'official_derived' olarak işaretlenir. Kaynakta olmayan değer yazılmaz; kontrol edildiği hâlde bulunamayan
her değer 'checks' listesine 'verified_gap' olarak kaydedilir (veri tabanı eksikliğinden ayırmak için).

Kullanım:
    python scripts/atlas_fetch.py            # atlas/official.json üretir (~10 istek)
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "atlas" / "config.json").read_text(encoding="utf-8"))
OUT = ROOT / "atlas" / "official.json"
API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
UA = "AgriGap/1.0 (+https://github.com/agrihubai/agrigap)"
YEARS = 6  # son 6 yıl istenir; her değer için en son dolu yıl kullanılır
FLAG = {"p": "provisional", "e": "estimated", "b": "break_in_series", "c": "confidential", "u": "low_reliability",
        "d": "definition_differs", "s": "eurostat_estimate", "n": "not_significant", "z": "not_applicable"}


def get(dataset, params):
    q = [("format", "JSON"), ("lang", "EN"), ("lastTimePeriod", str(YEARS))]
    for k, v in params.items():
        for x in (v if isinstance(v, list) else [v]):
            q.append((k, x))
    url = API + dataset + "?" + urllib.parse.urlencode(q)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8")), url
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 404):
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = type(e).__name__
        time.sleep(4 * (attempt + 1))
    print(f"::warning::Eurostat {dataset} alınamadı ({last}); bu tablo atlandı.")
    return None, url


def cells(js):
    """JSON-stat 2.0 → [{dim: code, ..., value, flag}]"""
    if not js or "dimension" not in js:
        return []
    ids, size = js["id"], js["size"]
    idx = {d: {v: k for k, v in js["dimension"][d]["category"]["index"].items()} for d in ids}
    vals, st = js.get("value", {}), js.get("status", {})
    out = []
    for flat, v in vals.items():
        n, coords = int(flat), {}
        for d, s in zip(reversed(ids), reversed(size)):
            coords[d] = idx[d][n % s]
            n //= s
        out.append({**coords, "value": v, "flag": st.get(flat, "")})
    return out


def latest(rows, **match):
    hit = [r for r in rows if all(r.get(k) == v for k, v in match.items()) and r["value"] is not None]
    return max(hit, key=lambda r: r["time"]) if hit else None


def main():
    now = datetime.now(timezone.utc).isoformat()
    geo = {r["eurostat"]: r["id"] for r in CFG["regions"] if r.get("eurostat")}
    obs, checks = [], []

    def add(pid, rid, sysid, ind, value, unit, row, src, url, quality="official", method="", note=""):
        flag = FLAG.get((row.get("flag") or "").strip()[:1], "") if row else ""
        obs.append({"id": f"{src}:{pid}:{rid}:{sysid}:{ind}", "product_id": pid, "region_id": rid, "production_system_id": sysid,
                    "indicator_id": ind, "value": value, "unit": unit, "data_year": int(row["time"]) if row else None,
                    "source_id": f"eurostat-{src}", "query_url": url, "data_quality": quality, "eurostat_flag": flag,
                    "methodology": method, "note": note, "comparability_status": "same_source"})

    def gap(pid, rid, sysid, ind, src, why):
        checks.append({"product_id": pid, "region_id": rid, "production_system_id": sysid, "indicator_id": ind,
                       "source_id": f"eurostat-{src}", "status": "verified_gap", "why": why, "checked": now[:10]})

    prods = CFG["products"]
    # 1) Üretim ve alan
    codes = sorted({c for p in prods for c in (p.get("eurostat", {}).get("crops") or {}).values()})
    js, url = get("apro_cpsh1", {"crops": codes, "strucpro": ["AR_THS_HA", "HPRD_HUMD_EU_THS_T"], "geo": list(geo)})
    rows = cells(js)
    area = {}
    for p in prods:
        cm = (p.get("eurostat") or {}).get("crops") or {}
        for g, rid in geo.items():
            if not cm:
                gap(p["id"], rid, "all", "production_volume", "apro_cpsh1", "not_in_nomenclature")
                continue
            for sysid, code in cm.items():
                pr = latest(rows, crops=code, strucpro="HPRD_HUMD_EU_THS_T", geo=g)
                if pr:
                    add(p["id"], rid, sysid, "production_volume", pr["value"], "1000 t", pr, "apro_cpsh1", url,
                        method="Bitkisel üretim, AB standart nemi · Crop production, EU standard humidity")
                else:
                    gap(p["id"], rid, sysid, "production_volume", "apro_cpsh1", "no_value_for_geo")
                for r in rows:  # alan tüm yıllar için saklanır: değer/ha, değer ile aynı yılın alanını kullanır
                    if r["crops"] == code and r["strucpro"] == "AR_THS_HA" and r["geo"] == g and r["value"]:
                        area[(p["id"], rid, sysid, r["time"])] = r["value"]
    # 2) Üretim değeri (EAA)
    items = [p["eurostat"]["eaa"] for p in prods if (p.get("eurostat") or {}).get("eaa")]
    js, url2 = get("aact_eaa01", {"am_item": items, "indic_agr": "PRD_BP", "unit": "MIO_EUR", "geo": list(geo)})
    rows = cells(js)
    for p in prods:
        it = (p.get("eurostat") or {}).get("eaa")
        for g, rid in geo.items():
            if not it:
                gap(p["id"], rid, "all", "production_value", "aact_eaa01", "no_item_for_product")
                continue
            v = latest(rows, am_item=it, geo=g)
            if not v:
                gap(p["id"], rid, "all", "production_value", "aact_eaa01", "no_value_for_geo")
                continue
            add(p["id"], rid, "all", "production_value", v["value"], "milyon €", v, "aact_eaa01", url2,
                method="EAA, temel fiyatlarla üretim değeri, cari fiyatlar · EAA, production value at basic prices, current prices")
            a = area.get((p["id"], rid, "all", v["time"]))
            if a:
                add(p["id"], rid, "all", "value_per_ha", round(v["value"] * 1e6 / (a * 1000)), "€/ha", v, "aact_eaa01", url2,
                    quality="official_derived",
                    method=f"Türetilmiş: üretim değeri ({v['value']} milyon €) ÷ hasat alanı ({a} bin ha), {v['time']} · "
                           f"Derived: production value ({v['value']} million €) ÷ harvested area ({a} thousand ha), {v['time']}")
            else:
                gap(p["id"], rid, "all", "value_per_ha", "aact_eaa01", "no_area_same_year")
    # 3) Üretici fiyatı
    pcodes = sorted({c for p in prods for c in ((p.get("eurostat") or {}).get("price") or {}).values()})
    js, url3 = get("apri_ap_crpouta", {"prod_veg": pcodes, "currency": "EUR", "geo": list(geo)})
    rows = cells(js)
    for p in prods:
        pm = (p.get("eurostat") or {}).get("price") or {}
        for g, rid in geo.items():
            if not pm:
                gap(p["id"], rid, "all", "value_per_kg", "apri_ap_crpouta", "no_item_for_product")
                continue
            for sysid, code in pm.items():
                v = latest(rows, prod_veg=code, geo=g)
                if not v:
                    gap(p["id"], rid, sysid, "value_per_kg", "apri_ap_crpouta", "no_value_for_geo")
                    continue
                add(p["id"], rid, sysid, "value_per_kg", round(v["value"] / 100, 3), "€/kg", v, "apri_ap_crpouta", url3,
                    method="Üretici satış fiyatı, €/100 kg ÷ 100 · Producer selling price, €/100 kg ÷ 100",
                    note=(p.get("eurostat") or {}).get("_price_note", ""))
    # Aynı ürün/bölge/yıl için açık tarla ve sera fiyatı birebir aynıysa kaynak sisteme göre ayırmamış olabilir: not düş
    by = {}
    for o in obs:
        if o["indicator_id"] == "value_per_kg":
            by.setdefault((o["product_id"], o["region_id"], o["data_year"]), []).append(o)
    for group in by.values():
        if len(group) > 1 and len({o["value"] for o in group}) == 1:
            for o in group:
                o["note"] = (o["note"] + " " if o["note"] else "") + "same_value_across_systems"
    if not obs:
        print("Eurostat'tan hiçbir değer alınamadı; atlas/official.json değiştirilmedi.")
        return 0
    OUT.write_text(json.dumps({"generated": now, "observations": obs, "checks": checks}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"[OK] atlas/official.json — {len(obs)} değer, {len(checks)} doğrulanmış eksik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
