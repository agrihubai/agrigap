"""AgriGap kaynak tarayıcı (yapay zekâsız, ücretsiz).

Kuyruktaki (core/targets.json) sıradaki hedefi alır, OpenAlex'teki yayın kayıtlarını
çeker ve sabit kurallarla (core/scan_rules.json) bir rapor üretir:

  - Mevcut Çözüm Haritası: yayınlar çözüm türüne göre gruplanır (ülke, yıl, örnek).
  - Görünmeyen Bağlantılar: hedefle aynı yayınlarda birlikte geçen, sorguda olmayan alanlar.
  - Boşluk ölçeği (A–D): yayın sayılarına dayalı kaba gösterge (sahadaki yaygınlık değil).
  - Kendini besleme: en güçlü bağlantı alanından en fazla 1 yeni hedef önerir.

Yapay zekâ kullanılmaz; her sayı OpenAlex kayıtlarının sayımıdır. Hiçbir ücretli bileşen yoktur.
OpenAlex anahtarı isteğe bağlıdır (OPENALEX_API_KEY): anahtarsız günlük ücretsiz kota da bu
kullanım için yeterlidir; kota dolarsa tarama yapılmaz, hedef kuyrukta bekler.

Kullanım:
    python scripts/source_scan.py                 # sıradaki pending hedef
    python scripts/source_scan.py --id TRG-001    # belirli hedef
    python scripts/source_scan.py --fixture f.json --id TRG-001   # çevrimdışı deneme
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_engine as hub  # noqa: E402  (ortak dizin ve kuyruk işlevleri)

ROOT = hub.ROOT
RULES = json.loads((ROOT / "core" / "scan_rules.json").read_text(encoding="utf-8"))
ENGINE = "kaynak-tarayici v1"
API = "https://api.openalex.org/works"
UA = "AgriGap/1.0 (+https://github.com/agrihubai/agrigap)"
FROM_YEAR = 2010
SAMPLE_GLOBAL = 200   # en ilgili ilk 200 yayın (2 sayfa)
SAMPLE_REGION = 100   # hedef bölgeden en ilgili ilk 100 yayın
SAMPLE_BASE = 200     # karşılaştırma: ürünün genel literatürü (yalnız ürün adı)

EU27 = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
        "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"]
COUNTRY_TR = {
    "TR": "Türkiye", "ES": "İspanya", "IT": "İtalya", "GR": "Yunanistan", "PT": "Portekiz", "FR": "Fransa",
    "DE": "Almanya", "NL": "Hollanda", "BE": "Belçika", "PL": "Polonya", "RO": "Romanya", "HU": "Macaristan",
    "AT": "Avusturya", "CZ": "Çekya", "SE": "İsveç", "DK": "Danimarka", "FI": "Finlandiya", "IE": "İrlanda",
    "BG": "Bulgaristan", "HR": "Hırvatistan", "SI": "Slovenya", "SK": "Slovakya", "CY": "Kıbrıs",
    "GB": "Birleşik Krallık", "CH": "İsviçre", "NO": "Norveç", "US": "ABD", "CA": "Kanada", "MX": "Meksika",
    "BR": "Brezilya", "AR": "Arjantin", "CL": "Şili", "CO": "Kolombiya", "EC": "Ekvador", "PE": "Peru",
    "CR": "Kosta Rika", "CN": "Çin", "IN": "Hindistan", "PK": "Pakistan", "BD": "Bangladeş", "JP": "Japonya",
    "KR": "Güney Kore", "TW": "Tayvan", "PH": "Filipinler", "ID": "Endonezya", "MY": "Malezya", "TH": "Tayland",
    "VN": "Vietnam", "AU": "Avustralya", "NZ": "Yeni Zelanda", "IR": "İran", "IQ": "Irak", "SA": "Suudi Arabistan",
    "EG": "Mısır", "MA": "Fas", "TN": "Tunus", "DZ": "Cezayir", "IL": "İsrail", "JO": "Ürdün", "LB": "Lübnan",
    "ZA": "Güney Afrika", "NG": "Nijerya", "KE": "Kenya", "ET": "Etiyopya", "UG": "Uganda", "TZ": "Tanzanya",
    "GH": "Gana", "CM": "Kamerun", "RU": "Rusya", "UA": "Ukrayna", "KZ": "Kazakistan", "UZ": "Özbekistan",
    "AZ": "Azerbaycan", "RS": "Sırbistan",
}


class ScanSkipped(Exception):
    """Kaynak alınamadı; hedef kuyrukta kalır."""


# ---------- OpenAlex ----------

def region_codes(region):
    codes = []
    if "TR" in region:
        codes.append("TR")
    if "EU" in region:
        codes += EU27
    return codes


def openalex_get(params):
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params = {**params, "api_key": key}
    url = API + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (401, 402, 403, 409):  # kota/anahtar sorunu: tekrar denemek boşuna
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = type(e).__name__
        time.sleep(5 * (attempt + 1))
    raise ScanSkipped(f"OpenAlex yanıt vermedi ({last}). Ücretsiz kota dolmuş olabilir; hedef kuyrukta bekliyor.")


SELECT = "id,doi,display_name,publication_year,authorships,keywords,abstract_inverted_index,cited_by_count,primary_location"


def search(query, n, countries=None):
    flt = [f"publication_year:>{FROM_YEAR - 1}", "type:article|review"]
    if countries:
        flt.append("authorships.countries:" + "|".join(countries))
    works, total, page = [], 0, 1
    while len(works) < n:
        data = openalex_get({"search.title_and_abstract": query, "filter": ",".join(flt), "per_page": min(100, n),
                             "page": page, "select": SELECT})
        total = data.get("meta", {}).get("count", 0)
        batch = data.get("results", [])
        works += batch
        if len(batch) < min(100, n):
            break
        page += 1
    return works[:n], total


def fetch(t):
    codes = region_codes(t["region"])
    g, total = search(t["query"], SAMPLE_GLOBAL)
    r, total_region = search(t["query"], SAMPLE_REGION, codes) if codes else ([], 0)
    b, _ = search(t["crop_en"], SAMPLE_BASE)
    return {"global": g, "region": r, "base": b, "total": total, "total_region": total_region}


# ---------- sabit kurallı çözümleme ----------

def abstract(w):
    inv = w.get("abstract_inverted_index") or {}
    pos = {}
    for word, idx in inv.items():
        for i in idx:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def countries(w):
    cs = set()
    for a in w.get("authorships") or []:
        for c in a.get("countries") or []:
            if c:
                cs.add(c.upper())
    return cs


def term_re(terms):
    return re.compile(r"\b(" + "|".join(re.escape(x) for x in terms) + r")", re.IGNORECASE)


def link_of(w):
    doi = w.get("doi") or ""
    if doi:
        return doi if doi.startswith("http") else "https://doi.org/" + doi
    return w.get("id") or ""


def cell(s, limit=110):
    s = re.sub(r"\s+", " ", str(s or "")).replace("|", "/").strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def analyse(t, data):
    seen, works = set(), []
    for w in data["global"] + data["region"]:
        if w.get("id") and w["id"] not in seen:
            seen.add(w["id"])
            works.append(w)
    texts = {w["id"]: ((w.get("display_name") or "") + " " + abstract(w)) for w in works}
    reg = set(region_codes(t["region"]))
    qlow = t["query"].lower()

    groups = []
    for g in RULES["solution_groups"]:
        rx = term_re(g["terms"])
        hits = [w for w in works if rx.search(texts[w["id"]])]
        if not hits:
            continue
        cc = Counter(c for w in hits for c in countries(w))
        years = [w["publication_year"] for w in hits if w.get("publication_year")]
        reg_hits = [w for w in hits if countries(w) & reg]
        examples = sorted(hits, key=lambda w: -(w.get("cited_by_count") or 0))[:3]
        reg_ex = sorted(reg_hits, key=lambda w: -(w.get("cited_by_count") or 0))[:1]
        groups.append({**g, "n": len(hits), "countries": cc.most_common(5), "years": (min(years), max(years)) if years else None,
                       "region_n": len(reg_hits), "examples": examples, "region_example": reg_ex[0] if reg_ex else None})
    groups.sort(key=lambda g: -g["n"])

    base = data.get("base") or []
    btexts = [((w.get("display_name") or "") + " " + abstract(w)) for w in base]
    links = []
    for d in RULES["link_domains"]:
        if any(re.search(r"\b" + re.escape(x) + r"\b", qlow) for x in d["terms"]):
            continue  # sorguda zaten var: görünmeyen değil, beklenen bağlantı
        rx = term_re(d["terms"])
        hits, terms = [], Counter()
        for w in works:
            found = rx.findall(texts[w["id"]])
            if found:
                hits.append(w)
                terms.update(x.lower() for x in found)
        if hits:
            ex = sorted(hits, key=lambda w: -(w.get("cited_by_count") or 0))[:2]
            share = len(hits) / max(1, len(works))
            bshare = sum(1 for x in btexts if rx.search(x)) / len(btexts) if btexts else None
            lift = share / max(bshare, 0.02) if bshare is not None else None
            links.append({**d, "n": len(hits), "share": share, "base_share": bshare, "lift": lift,
                          "top_terms": [x for x, _ in terms.most_common(4)], "examples": ex})
    # Önce genel ürün literatürüne göre belirgin biçimde sık geçen alanlar (gerçek "görünmeyen" sinyal)
    links.sort(key=lambda d: (-(d["lift"] or 0) if d["n"] >= 5 else 1, -d["n"]))

    stop = set(re.findall(r"[a-z]+", qlow)) | {"and", "or", "not"}
    kw = Counter()
    for w in works:
        for k in w.get("keywords") or []:
            name = (k.get("display_name") or "").strip()
            if name and not (set(re.findall(r"[a-z]+", name.lower())) & stop):
                kw[name] += 1
    allc = Counter(c for w in works for c in countries(w))
    cons = []
    for cdef in RULES.get("constraints", []):
        rx = term_re(cdef["terms"])
        hits = [w for w in works if rx.search(texts[w["id"]])]
        if hits:
            ex = sorted(hits, key=lambda w: -(w.get("cited_by_count") or 0))[:2]
            cons.append({**cdef, "n": len(hits), "examples": ex})
    cons.sort(key=lambda x: -x["n"])
    return {"works": works, "groups": groups, "links": links, "keywords": kw.most_common(8),
            "countries": allc.most_common(10), "constraints": cons}


COUNTRY_EN = {
    "TR": "Türkiye", "ES": "Spain", "IT": "Italy", "GR": "Greece", "PT": "Portugal", "FR": "France", "DE": "Germany",
    "NL": "Netherlands", "BE": "Belgium", "PL": "Poland", "RO": "Romania", "HU": "Hungary", "AT": "Austria", "CZ": "Czechia",
    "SE": "Sweden", "DK": "Denmark", "FI": "Finland", "IE": "Ireland", "BG": "Bulgaria", "HR": "Croatia", "SI": "Slovenia",
    "SK": "Slovakia", "CY": "Cyprus", "GB": "United Kingdom", "CH": "Switzerland", "NO": "Norway", "US": "USA", "CA": "Canada",
    "MX": "Mexico", "BR": "Brazil", "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "EC": "Ecuador", "PE": "Peru",
    "CR": "Costa Rica", "CN": "China", "IN": "India", "PK": "Pakistan", "BD": "Bangladesh", "JP": "Japan", "KR": "South Korea",
    "TW": "Taiwan", "PH": "Philippines", "ID": "Indonesia", "MY": "Malaysia", "TH": "Thailand", "VN": "Vietnam", "AU": "Australia",
    "NZ": "New Zealand", "IR": "Iran", "IQ": "Iraq", "SA": "Saudi Arabia", "EG": "Egypt", "MA": "Morocco", "TN": "Tunisia",
    "DZ": "Algeria", "IL": "Israel", "JO": "Jordan", "LB": "Lebanon", "ZA": "South Africa", "NG": "Nigeria", "KE": "Kenya",
    "ET": "Ethiopia", "UG": "Uganda", "TZ": "Tanzania", "GH": "Ghana", "CM": "Cameroon", "RU": "Russia", "UA": "Ukraine",
    "KZ": "Kazakhstan", "UZ": "Uzbekistan", "AZ": "Azerbaijan", "RS": "Serbia",
}
STAGE_EN = {"Toprak & Girdi": "Soil & Inputs", "Yetiştirme & Bitki Koruma": "Growing & Crop Protection",
            "Hasat & Mekanizasyon": "Harvest & Mechanisation", "Hasat Sonrası & Biyo-Atık": "Post-harvest & Bio-waste"}
STYPE_EN = {"Makine & Otonomi": "Machinery & Autonomy", "Döngüsel Biyo-Ekonomi": "Circular Bio-economy",
            "Biyolojik Mücadele & Girdi": "Biological Control & Inputs", "Islah & Genetik": "Breeding & Genetics"}


def cname(c, lang="tr"):
    return (COUNTRY_EN if lang == "en" else COUNTRY_TR).get(c, c)


def gap_decision(t, data, lang="tr"):
    r = RULES["gap_rule"]
    total, reg = data["total"], data["total_region"]
    share = reg / total if total else 0
    rn = t["region"]
    en = lang == "en"
    if total < r["D_if_total_below"]:
        return "D", (f"Only {total} publications were found on this topic in the scanned sources." if en
                     else f"Taranan kaynaklarda bu konuda yalnızca {total} yayın bulundu.")
    if reg < r["B_if_region_below"]:
        return "B", (f"{total} publications worldwide; only {reg} have an author from the target region ({rn})." if en
                     else f"Dünyada {total} yayın var; hedef bölgeden ({rn}) yazarı olan yayın sayısı yalnızca {reg}.")
    if reg >= r["A_if_region_at_least"] and share >= r["A_if_region_share_at_least"]:
        return "A", (f"{reg} of {total} publications ({share * 100:.0f}%) have an author from the target region ({rn}); the topic is studied intensively there." if en
                     else f"{total} yayının {reg} tanesinde (%{share * 100:.0f}) hedef bölgeden ({rn}) yazar var; konu bölgede yoğun çalışılmış.")
    return "C", (f"{reg} of {total} publications ({share * 100:.0f}%) have an author from the target region ({rn}); the topic is studied there, but to a limited extent." if en
                 else f"{total} yayının {reg} tanesinde (%{share * 100:.0f}) hedef bölgeden ({rn}) yazar var; konu bölgede çalışılmış ama sınırlı.")


def stype(groups):
    if not groups:
        return "Döngüsel Biyo-Ekonomi"
    c = Counter()
    for g in groups:
        c[g["type"]] += g["n"]
    return c.most_common(1)[0][0]


def study(w, lang="tr"):
    none = "no country data" if lang == "en" else "ülke bilgisi yok"
    cs = ", ".join(cname(c, lang) for c in sorted(countries(w))[:3]) or none
    return f"[{cell(w.get('display_name'), 90)}]({link_of(w)}) ({w.get('publication_year', '?')}, {cs})"


def suggestion(t, links, targets):
    sf = RULES["self_feed"]
    seen = {(hub._norm(x["crop"]), hub._norm(x.get("link_domain", ""))) for x in targets}
    for d in links:
        if d["share"] < sf["min_share"] or d["n"] < sf["min_papers"]:
            continue
        if d["lift"] is not None and d["lift"] < sf.get("min_lift", 1.5):
            continue
        if (hub._norm(t["crop"]), d["key"]) in seen:
            continue
        q = f"({t['query']}) AND (" + " OR ".join(d["query_terms"]) + ")"
        return {"production_system": t["production_system"], "crop_group": t["crop_group"], "crop": t["crop"],
                "crop_en": t["crop_en"], "crop_label_en": t.get("crop_label_en", t["crop"]), "stage": t.get("stage", ""),
                "region": t["region"], "focus": f"{t['focus']} — {d['topic_tr']}",
                "focus_en": f"{t.get('focus_en', t['focus'])} — {d['topic_en']}",
                "query": q, "link_domain": d["key"],
                "why": f"{t['id']} taramasında '{d['tr']}' alanı yayınlarda birlikte geçti (pay: %{d['share'] * 100:.0f}).",
                "why_en": f"In the {t['id']} scan, the '{d['en']}' field co-occurred in publications (share: {d['share'] * 100:.0f}%)."}
    return None


S = {
    "tr": {
        "note": "> **Otomatik tarama.** Bu rapor yapay zekâ kullanılmadan, OpenAlex'teki yayın kayıtlarından sabit kurallarla "
                "üretilmiştir. Sayılar yayın sayısıdır; sahadaki yaygınlığı, çözümün başarısını veya maliyetini göstermez. "
                "İnsan tarafından doğrulanmamıştır.",
        "tax": "Taksonomi", "stage": "Aşama & Çözüm Türü", "region": "Bölge", "dec": "Durum Kararı", "find": "Tek cümlede bulgu",
        "link": "Görünmeyen bağlantı",
        "finding": lambda top, rn, tr: f"Bu taramaya göre en çok çalışılan çözüm türü: {top} ({tr[0]} yayın); hedef bölgeden ({rn}) yazarı olan yayın sayısı {tr[1]}.",
        "nofind": "Bu taramada çözüm türü içeren yayın bulunamadı.",
        "nolink": "Bu taramada, genel literatüre göre belirgin biçimde öne çıkan bir alan bulunmadı.",
        "rel": lambda crop, x: f"; genel {crop} literatürüne göre {x:.1f} kat sık".replace(".", ","),
        "linkline": lambda f, s, rel, ex: f"'{f}' alanı bu konudaki yayınlarda da geçiyor (pay: %{s}{rel}; ör. {ex}). Neden bağlantılı olduğu yayınların kendisinde okunmalı.",
        "h1": "## 1. Sorun ve Tarama Kapsamı", "prob": "Sorun", "q": "Sorgu (OpenAlex, başlık ve özet)", "per": "Dönem",
        "perv": lambda a, b: f"{a}–{b}, makale ve derleme", "match": "Eşleşen yayın",
        "matchv": lambda w, rn, r: f"dünyada {w}, hedef bölgeden ({rn}) yazarı olan {r}", "sample": "İncelenen örnek",
        "samplev": lambda n, g, r: f"en ilgili {n} yayın (dünya ilk {g} + bölge ilk {r}, tekrarlar çıkarıldı)", "date": "Tarama tarihi",
        "h2": "## 2. Görünmeyen Bağlantılar",
        "h2p": lambda ce, cr: ("Hedef sorguda geçmeyen ama aynı yayınlarda birlikte geçen alanlar. Birlikte geçmek bağlantının nedenini "
                               "açıklamaz; nedeni yayınların kendisinde okunmalıdır. \"Genel literatüre göre\" sütunu, aynı alanın "
                               f"yalnızca \"{ce}\" aramasıyla gelen genel {cr} yayınlarındaki sıklığıyla karşılaştırmasıdır; "
                               "1'in belirgin üstü, alanın bu konuya özgü olduğunu düşündürür."),
        "h2t": "| İlgisiz görünen alan | Birlikte geçtiği yayın | Genel literatüre göre | Sık geçen terimler | Örnek yayınlar |",
        "kat": lambda x: f"{x:.1f} kat".replace(".", ","), "pct": lambda s: f"%{s}",
        "nolinks": "Genel literatüre göre daha sık geçen, sorgu dışı bir alan bulunmadı.",
        "hidden": lambda h: f"Genel literatürde bu konudakinden daha sık geçtiği için tabloya alınmayan alanlar: {h}.",
        "kw": "**Sorgu dışında en sık geçen konu başlıkları (OpenAlex anahtar kelimeleri, yayın sayısı):** ",
        "h3": "## 3. Mevcut Çözüm Haritası",
        "h3p": "Yayınlar başlık ve özetlerinde geçen terimlere göre çözüm türlerine ayrıldı (bir yayın birden fazla türde olabilir). "
               "Avantaj ve dezavantaj bu otomatik taramada yazılmaz; yayınların kendisinde okunmalıdır.",
        "h3t": "| Çözüm türü | Yayın | Hedef bölgeden | Öne çıkan ülkeler | Yıllar | Örnek çalışmalar |",
        "fromreg": "Bölgeden: ", "nogroup": "| — | 0 | 0 | — | — | Çözüm türü içeren yayın bulunamadı |",
        "geo": "**Yayınların coğrafyası (incelenen örnekte, yazar ülkesi):** ",
        "missing": lambda m: f"**Hedef bölgede örneği bulunmayan çözüm türleri:** {m}. Bunlar başka bölgelerden aktarım (transfer) adayıdır.",
        "h4": "## 4. Zorluk Sinyalleri (tasarım gerekliliği adayları)",
        "h4p": "Yayınların başlık ve özetlerinde sık geçen engeller. Yeni bir makine, yazılım ya da uygulamanın aşması "
               "gereken koşullar için ham malzemedir; tek başına bir tasarım önerisi değildir.",
        "h4t": "| Zorluk | Geçtiği yayın | Örnek yayınlar |", "nocons": "Taranan yayınlarda tanımlı zorluk terimlerine rastlanmadı.",
        "h5": "## 5. Boşluk Ölçeği Nasıl Hesaplandı",
        "rD": lambda x: f"- **D:** dünyadaki yayın sayısı < {x}",
        "rB": lambda x: f"- **B:** hedef bölgeden yazarı olan yayın sayısı < {x} (çözüm başka yerde çalışılmış)",
        "rA": lambda x, y: f"- **A:** hedef bölgeden yazarı olan yayın sayısı ≥ {x} ve payı ≥ %{y}",
        "rC": "- **C:** diğer durumlar (bölgede çalışılmış ama sınırlı)",
        "rThis": lambda d: f"- **Bu tarama:** `{d}`. Bu gösterge yayın sayısına dayanır; derin bir değerlendirme değildir.",
        "h6": "## 6. Kaynaklar", "h6p": "OpenAlex (CC0 açık veri, https://openalex.org). Atıf sayısına göre ilk 25 yayın:",
        "h7": "## 7. Yeni Hedef Önerileri", "nosugg": "Bu taramada eşiği geçen yeni bir bağlantı alanı çıkmadı.",
    },
    "en": {
        "note": "> **Automatic scan.** This report was generated without AI, by fixed rules, from publication records in OpenAlex. "
                "The numbers are publication counts; they do not show adoption in the field, how well a solution works or what it costs. "
                "It has not been verified by a person.",
        "tax": "Taxonomy", "stage": "Stage & Solution Type", "region": "Region", "dec": "Decision", "find": "Finding in one sentence",
        "link": "Hidden link",
        "finding": lambda top, rn, tr: f"In this scan the most studied solution type is {top} ({tr[0]} publications); {tr[1]} publications have an author from the target region ({rn}).",
        "nofind": "No publications with a solution type were found in this scan.",
        "nolink": "No field stands out clearly against the general literature in this scan.",
        "rel": lambda crop, x: f"; {x:.1f}× as frequent as in the general {crop.lower()} literature",
        "linkline": lambda f, s, rel, ex: f"The '{f}' field also appears in publications on this topic (share: {s}%{rel}; e.g. {ex}). Why they are linked has to be read in the publications themselves.",
        "h1": "## 1. Problem and Scan Scope", "prob": "Problem", "q": "Query (OpenAlex, title and abstract)", "per": "Period",
        "perv": lambda a, b: f"{a}–{b}, articles and reviews", "match": "Matching publications",
        "matchv": lambda w, rn, r: f"{w} worldwide, {r} with an author from the target region ({rn})", "sample": "Sample examined",
        "samplev": lambda n, g, r: f"the {n} most relevant publications (top {g} worldwide + top {r} from the region, duplicates removed)", "date": "Scan date",
        "h2": "## 2. Hidden Links",
        "h2p": lambda ce, cr: ("Fields that are not in the query but appear in the same publications. Co-occurrence does not explain "
                               "the link; the reason has to be read in the publications themselves. The \"vs general literature\" column compares "
                               f"the field's frequency with general {cr.lower()} publications returned by a plain \"{ce}\" search; "
                               "clearly above 1 suggests the field is specific to this topic."),
        "h2t": "| Field that looks unrelated | Co-occurs in | vs general literature | Frequent terms | Example publications |",
        "kat": lambda x: f"{x:.1f}×", "pct": lambda s: f"{s}%",
        "nolinks": "No out-of-query field appears more often than in the general literature.",
        "hidden": lambda h: f"Fields left out of the table because they are more frequent in the general literature: {h}.",
        "kw": "**Most frequent topics outside the query (OpenAlex keywords, publication count):** ",
        "h3": "## 3. Existing Solutions Map",
        "h3p": "Publications were sorted into solution types by terms in their titles and abstracts (one publication can fall into several types). "
               "This automatic scan does not list advantages and disadvantages; read them in the publications themselves.",
        "h3t": "| Solution type | Publications | From target region | Leading countries | Years | Example studies |",
        "fromreg": "From the region: ", "nogroup": "| — | 0 | 0 | — | — | No publications with a solution type |",
        "geo": "**Geography of publications (sample, author country):** ",
        "missing": lambda m: f"**Solution types with no example in the target region:** {m}. These are candidates for transfer from other regions.",
        "h4": "## 4. Difficulty Signals (design requirement candidates)",
        "h4p": "Obstacles frequently mentioned in titles and abstracts. Raw material for the conditions a new machine, software or practice "
               "has to meet; not a design proposal on its own.",
        "h4t": "| Difficulty | Mentioned in | Example publications |", "nocons": "None of the defined difficulty terms appeared in the scanned publications.",
        "h5": "## 5. How the Gap Scale Was Calculated",
        "rD": lambda x: f"- **D:** publications worldwide < {x}",
        "rB": lambda x: f"- **B:** publications with an author from the target region < {x} (solution studied elsewhere)",
        "rA": lambda x, y: f"- **A:** publications with an author from the target region ≥ {x} and share ≥ {y}%",
        "rC": "- **C:** all other cases (studied in the region, but to a limited extent)",
        "rThis": lambda d: f"- **This scan:** `{d}`. The indicator is based on publication counts; it is not an in-depth assessment.",
        "h6": "## 6. Sources", "h6p": "OpenAlex (CC0 open data, https://openalex.org). Top 25 publications by citations:",
        "h7": "## 7. New Target Suggestions", "nosugg": "No new link field passed the threshold in this scan.",
    },
}


def render(t, data, a, today, sugg, lang="tr"):
    s, en = S[lang], lang == "en"
    dec, why = gap_decision(t, data, lang)
    groups, links = a["groups"], a["links"]
    n = len(a["works"])
    crop = t.get("crop_label_en", t["crop"]) if en else t["crop"]
    focus = t.get("focus_en", t["focus"]) if en else t["focus"]
    gname = lambda g: g["en"] if en else g["tr"]  # noqa: E731
    top = groups[0] if groups else None
    finding = s["finding"](gname(top), t["region"], (top["n"], data["total_region"])) if top else s["nofind"]
    lr = RULES["link_rule"]
    lk = links[0] if links and links[0]["n"] >= lr["headline_min_papers"] and (links[0]["lift"] or 0) >= lr["headline_min_lift"] else None
    link_line = s["nolink"] if links else ""
    if lk:
        rel = s["rel"](crop, lk["lift"]) if lk["lift"] else ""
        link_line = s["linkline"](gname(lk), f"{lk['share'] * 100:.0f}", rel, ", ".join(lk["top_terms"][:3]))
    title = f"{crop}: {focus}"
    st = stype(groups)
    L = [f"# {title}", "", s["note"], "",
         f"- **{s['tax']}:** `{t['production_system']}` > `{t['crop_group']}` > `{t['crop']}`",
         f"- **{s['stage']}:** `{t.get('stage', '')}` | `{st}`",
         f"- **{s['region']}:** `{t['region']}`",
         f"- **{s['dec']}:** `{dec}` — {why}",
         f"- **{s['find']}:** {finding}"]
    if link_line:
        L.append(f"- **{s['link']}:** {link_line}")
    L += ["", s["h1"], f"- **{s['prob']}:** {focus}", f"- **{s['q']}:** `{t['query']}`",
          f"- **{s['per']}:** {s['perv'](FROM_YEAR, today[:4])}",
          f"- **{s['match']}:** {s['matchv'](data['total'], t['region'], data['total_region'])}",
          f"- **{s['sample']}:** {s['samplev'](n, SAMPLE_GLOBAL, SAMPLE_REGION)}",
          f"- **{s['date']}:** {today}", ""]

    L += [s["h2"], s["h2p"](t["crop_en"], crop), ""]
    shown = [d for d in links if d["lift"] is None or d["lift"] >= lr["table_min_lift"]]
    hidden = [gname(d) for d in links if d not in shown]
    if shown:
        L += [s["h2t"], "|---|---|---|---|---|"]
        for d in shown[:6]:
            rel = s["kat"](d["lift"]) if d["lift"] else "—"
            L.append(f"| {gname(d)} | {d['n']} / {n} ({s['pct'](f'{d['share'] * 100:.0f}')}) | {rel} | {', '.join(d['top_terms'])} | "
                     + "<br>".join(study(w, lang) for w in d["examples"]) + " |")
    else:
        L.append(s["nolinks"])
    if hidden:
        L += ["", s["hidden"](", ".join(hidden))]
    if a["keywords"]:
        L += ["", s["kw"] + ", ".join(f"{k} ({c})" for k, c in a["keywords"])]

    L += ["", s["h3"], s["h3p"], "", s["h3t"], "|---|---|---|---|---|---|"]
    for g in groups:
        yrs = f"{g['years'][0]}–{g['years'][1]}" if g["years"] else "?"
        ctry = ", ".join(f"{cname(c, lang)} ({k})" for c, k in g["countries"]) or "—"
        ex = "<br>".join(study(w, lang) for w in g["examples"])
        if g["region_example"] and g["region_example"] not in g["examples"]:
            ex += "<br>" + s["fromreg"] + study(g["region_example"], lang)
        L.append(f"| {gname(g)} | {g['n']} | {g['region_n']} | {ctry} | {yrs} | {ex} |")
    if not groups:
        L.append(s["nogroup"])
    if a["countries"]:
        L += ["", s["geo"] + ", ".join(f"{cname(c, lang)} {k}" for c, k in a["countries"])]
    missing = [gname(g) for g in groups if g["region_n"] == 0]
    if missing:
        L += ["", s["missing"](", ".join(missing))]

    L += ["", s["h4"], s["h4p"], ""]
    if a["constraints"]:
        L += [s["h4t"], "|---|---|---|"]
        for cdef in a["constraints"][:8]:
            L.append(f"| {cdef['en'] if en else cdef['tr']} | {cdef['n']} / {n} | " + "<br>".join(study(w, lang) for w in cdef["examples"]) + " |")
    else:
        L.append(s["nocons"])

    r = RULES["gap_rule"]
    L += ["", s["h5"], s["rD"](r["D_if_total_below"]), s["rB"](r["B_if_region_below"]),
          s["rA"](r["A_if_region_at_least"], f"{r['A_if_region_share_at_least'] * 100:.0f}"), s["rC"], s["rThis"](dec), ""]

    L += [s["h6"], s["h6p"], ""]
    for w in sorted(a["works"], key=lambda w: -(w.get("cited_by_count") or 0))[:25]:
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        L.append(f"- {study(w, lang)}{' — ' + cell(src, 60) if src else ''}")

    L += ["", s["h7"]]
    if sugg:
        sf = sugg["focus_en"] if en else sugg["focus"]
        L.append(f"- `{sugg['production_system']} | {sugg['crop_group']} | {sugg['crop']} | {sugg['region']} | {sf}` — {sugg['why_en'] if en else sugg['why']}")
    else:
        L.append(s["nosugg"])
    meta = {"stage_en": STAGE_EN.get(t.get("stage", ""), t.get("stage", "")), "solution_type_en": STYPE_EN.get(st, st)}
    return "\n".join(L) + "\n", title, meta


def write(t, md, today, lang="tr"):
    hub.DISCOVERIES_DIR.mkdir(exist_ok=True)
    suffix = ".en.md" if lang == "en" else ".md"
    path = hub.DISCOVERIES_DIR / f"{today}-{t['id'].lower()}-{hub.slugify(t['crop'])}{suffix}"
    front = ["---", f"id: {t['id']}", f"date: {today}", f"production_system: {t['production_system']}",
             f"crop_group: {t['crop_group']}", f"crop: {t['crop']}", f"region: {t['region']}",
             f"engine: {ENGINE}", "kind: auto", f"lang: {lang}", "status: published", "---", ""]
    path.write_text("\n".join(front) + md, encoding="utf-8")
    return path


def pick(targets, tid):
    for t in targets:
        if tid and t["id"] == tid:
            return t
        if not tid and t.get("status") == "pending" and t.get("query"):
            return t
    return None


def scan_one(targets, tid, fixture=None, dry=False):
    t = pick(targets, tid)
    if not t:
        print("Taranacak hedef yok (sorgusu olan 'pending' hedef bulunamadı).")
        return None
    if not t.get("query"):
        print(f"{t['id']} için 'query' alanı yok; core/targets.json'a İngilizce arama sorgusu ekleyin.")
        return None
    print(f"Taranıyor: {t['id']} — {t['crop']}: {t['focus']}")
    data = json.loads(Path(fixture).read_text(encoding="utf-8")) if fixture else fetch(t)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    a = analyse(t, data)
    sugg = suggestion(t, a["links"], targets)
    md, title, _ = render(t, data, a, today, sugg, "tr")
    md_en, _, meta_en = render(t, data, a, today, sugg, "en")
    if dry:
        print(md)
        print(md_en)
        return None

    path = write(t, md, today, "tr")
    write(t, md_en, today, "en")
    t["status"] = "published"
    t["report"] = str(path.relative_to(ROOT))
    t["processed_at"] = datetime.now(timezone.utc).isoformat()
    if sugg:
        nmax = max(int(x["id"].split("-")[1]) for x in targets if x["id"].startswith("TRG-"))
        nt = {"id": f"TRG-{nmax + 1:03d}", **{k: v for k, v in sugg.items() if k not in ("why", "why_en")},
              "status": "pending", "suggested_by": t["id"]}
        targets.append(nt)
        print(f"[KUYRUK] Yeni hedef: {nt['id']} — {nt['focus']}")
    hub.save_targets(targets)
    print(f"[OK] {path.relative_to(ROOT)} — {len(a['works'])} yayın incelendi")
    return t["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Hedef kimliği; virgülle birden fazla (yeniden tarama için)")
    ap.add_argument("--count", type=int, default=1, help="Bu çalışmada taranacak hedef sayısı")
    ap.add_argument("--fixture", help="OpenAlex yerine kayıtlı JSON (çevrimdışı deneme)")
    ap.add_argument("--dry-run", action="store_true", help="Raporu yazdır, dosyaya kaydetme")
    args = ap.parse_args()

    targets = hub.load_targets()
    done = []
    ids = [x.strip() for x in (args.id or "").split(",") if x.strip()]
    for i in range(len(ids) if ids else max(1, args.count)):
        try:
            tid = scan_one(targets, ids[i] if ids else None, args.fixture, args.dry_run)
        except ScanSkipped as e:
            print(f"::notice::{e}")
            break
        if not tid:
            break
        done.append(tid)
    if done:
        hub.rebuild_index()
    hub.set_output("created", "true" if done else "false")
    hub.set_output("target_id", ",".join(done))
    hub.set_output("title", f"{len(done)} rapor: {', '.join(done)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
