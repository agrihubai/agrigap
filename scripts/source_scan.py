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
        data = openalex_get({"search": query, "filter": ",".join(flt), "per_page": min(100, n),
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


def cname(c):
    return COUNTRY_TR.get(c, c)


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
        if any(re.search(r"\b" + re.escape(x), qlow) for x in d["terms"]):
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
    return {"works": works, "groups": groups, "links": links, "keywords": kw.most_common(8), "countries": allc.most_common(10)}


def gap_decision(t, data):
    r = RULES["gap_rule"]
    total, reg = data["total"], data["total_region"]
    share = reg / total if total else 0
    rn = t["region"]
    if total < r["D_if_total_below"]:
        return "D", f"Taranan kaynaklarda bu konuda yalnızca {total} yayın bulundu."
    if reg < r["B_if_region_below"]:
        return "B", f"Dünyada {total} yayın var; hedef bölgeden ({rn}) yazarı olan yayın sayısı yalnızca {reg}."
    if reg >= r["A_if_region_at_least"] and share >= r["A_if_region_share_at_least"]:
        return "A", f"{total} yayının {reg} tanesinde (%{share * 100:.0f}) hedef bölgeden ({rn}) yazar var; konu bölgede yoğun çalışılmış."
    return "C", f"{total} yayının {reg} tanesinde (%{share * 100:.0f}) hedef bölgeden ({rn}) yazar var; konu bölgede çalışılmış ama sınırlı."


def stype(groups):
    if not groups:
        return "Döngüsel Biyo-Ekonomi"
    c = Counter()
    for g in groups:
        c[g["type"]] += g["n"]
    return c.most_common(1)[0][0]


# ---------- rapor ----------

def study(w):
    cs = ", ".join(cname(c) for c in sorted(countries(w))[:3]) or "ülke bilgisi yok"
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
        focus = f"{t['focus']} — {d['topic_tr']}"
        q = f"({t['query']}) AND (" + " OR ".join(d["query_terms"]) + ")"
        return {"production_system": t["production_system"], "crop_group": t["crop_group"], "crop": t["crop"],
                "crop_en": t["crop_en"], "stage": t.get("stage", ""), "region": t["region"], "focus": focus,
                "query": q, "link_domain": d["key"], "why": f"{t['id']} taramasında '{d['tr']}' alanı yayınlarda birlikte geçti (pay: %{d['share'] * 100:.0f})."}
    return None


def render(t, data, a, today, sugg):
    dec, why = gap_decision(t, data)
    groups, links = a["groups"], a["links"]
    n = len(a["works"])
    top = groups[0] if groups else None
    finding = (f"Bu taramaya göre en çok çalışılan çözüm türü: {top['tr']} ({top['n']} yayın); "
               f"hedef bölgeden ({t['region']}) yazarı olan yayın sayısı {data['total_region']}.") if top else \
              "Bu taramada çözüm türü içeren yayın bulunamadı."
    lk = links[0] if links else None
    link_line = ""
    if lk:
        rel = f"; genel {t['crop']} literatürüne göre {lk['lift']:.1f} kat sık".replace(".", ",") if lk["lift"] else ""
        link_line = (f"'{lk['tr']}' alanı bu konudaki yayınlarda da geçiyor (pay: %{lk['share'] * 100:.0f}{rel}; "
                     f"ör. {', '.join(lk['top_terms'][:3])}). Neden bağlantılı olduğu yayınların kendisinde okunmalı.")
    title = f"{t['crop']}: {t['focus']}"
    L = [
        f"# {title}", "",
        "> **Otomatik tarama.** Bu rapor yapay zekâ kullanılmadan, OpenAlex'teki yayın kayıtlarından sabit kurallarla "
        "üretilmiştir. Sayılar yayın sayısıdır; sahadaki yaygınlığı, çözümün başarısını veya maliyetini göstermez. "
        "İnsan tarafından doğrulanmamıştır.", "",
        f"- **Taksonomi:** `{t['production_system']}` > `{t['crop_group']}` > `{t['crop']}`",
        f"- **Aşama & Çözüm Türü:** `{t.get('stage', '')}` | `{stype(groups)}`",
        f"- **Bölge:** `{t['region']}`",
        f"- **Durum Kararı:** `{dec}` — {why}",
        f"- **Tek cümlede bulgu:** {finding}",
    ]
    if link_line:
        L.append(f"- **Görünmeyen bağlantı:** {link_line}")
    L += ["", "## 1. Sorun ve Tarama Kapsamı",
          f"- **Sorun:** {t['focus']}",
          f"- **Sorgu (OpenAlex):** `{t['query']}`",
          f"- **Dönem:** {FROM_YEAR}–{today[:4]}, makale ve derleme",
          f"- **Eşleşen yayın:** dünyada {data['total']}, hedef bölgeden ({t['region']}) yazarı olan {data['total_region']}",
          f"- **İncelenen örnek:** en ilgili {n} yayın (dünya ilk {SAMPLE_GLOBAL} + bölge ilk {SAMPLE_REGION}, tekrarlar çıkarıldı)",
          f"- **Tarama tarihi:** {today}", ""]

    L += ["## 2. Görünmeyen Bağlantılar",
          "Hedef sorguda geçmeyen ama aynı yayınlarda birlikte geçen alanlar. Birlikte geçmek bağlantının nedenini "
          "açıklamaz; nedeni yayınların kendisinde okunmalıdır. \"Genel literatüre göre\" sütunu, aynı alanın "
          f"yalnızca \"{t['crop_en']}\" aramasıyla gelen genel {t['crop']} yayınlarındaki sıklığıyla karşılaştırmasıdır; "
          "1'in belirgin üstü, alanın bu konuya özgü olduğunu düşündürür.", ""]
    if links:
        L += ["| İlgisiz görünen alan | Birlikte geçtiği yayın | Genel literatüre göre | Sık geçen terimler | Örnek yayınlar |", "|---|---|---|---|---|"]
        for d in links[:6]:
            rel = (f"{d['lift']:.1f} kat".replace(".", ",")) if d["lift"] else "—"
            L.append(f"| {d['tr']} | {d['n']} / {n} (%{d['share'] * 100:.0f}) | {rel} | {', '.join(d['top_terms'])} | "
                     + "<br>".join(study(w) for w in d["examples"]) + " |")
    else:
        L.append("Taranan yayınlarda sorgu dışı bir alan bulunmadı.")
    if a["keywords"]:
        L += ["", "**Sorgu dışında sık geçen anahtar kelimeler (OpenAlex):** "
              + ", ".join(f"{k} ({c})" for k, c in a["keywords"])]

    L += ["", "## 3. Mevcut Çözüm Haritası",
          "Yayınlar başlık ve özetlerinde geçen terimlere göre çözüm türlerine ayrıldı (bir yayın birden fazla türde olabilir). "
          "Avantaj ve dezavantaj bu otomatik taramada yazılmaz; yayınların kendisinde okunmalıdır.", "",
          "| Çözüm türü | Yayın | Hedef bölgeden | Öne çıkan ülkeler | Yıllar | Örnek çalışmalar |", "|---|---|---|---|---|---|"]
    for g in groups:
        yrs = f"{g['years'][0]}–{g['years'][1]}" if g["years"] else "?"
        ctry = ", ".join(f"{cname(c)} ({k})" for c, k in g["countries"]) or "—"
        ex = "<br>".join(study(w) for w in g["examples"])
        if g["region_example"] and g["region_example"] not in g["examples"]:
            ex += "<br>Bölgeden: " + study(g["region_example"])
        L.append(f"| {g['tr']} | {g['n']} | {g['region_n']} | {ctry} | {yrs} | {ex} |")
    if not groups:
        L.append("| — | 0 | 0 | — | — | Çözüm türü içeren yayın bulunamadı |")
    if a["countries"]:
        L += ["", "**Yayınların coğrafyası (incelenen örnekte, yazar ülkesi):** "
              + ", ".join(f"{cname(c)} {k}" for c, k in a["countries"])]
    missing = [g["tr"] for g in groups if g["region_n"] == 0]
    if missing:
        L += ["", f"**Hedef bölgede örneği bulunmayan çözüm türleri:** {', '.join(missing)}. "
              "Bunlar başka bölgelerden aktarım (transfer) adayıdır."]

    r = RULES["gap_rule"]
    L += ["", "## 4. Boşluk Ölçeği Nasıl Hesaplandı",
          f"- **D:** dünyadaki yayın sayısı < {r['D_if_total_below']}",
          f"- **B:** hedef bölgeden yazarı olan yayın sayısı < {r['B_if_region_below']} (çözüm başka yerde çalışılmış)",
          f"- **A:** hedef bölgeden yazarı olan yayın sayısı ≥ {r['A_if_region_at_least']} ve payı ≥ %{r['A_if_region_share_at_least'] * 100:.0f}",
          "- **C:** diğer durumlar (bölgede çalışılmış ama sınırlı)",
          f"- **Bu tarama:** `{dec}`. Bu gösterge yayın sayısına dayanır; derin bir değerlendirme değildir.", ""]

    L += ["## 5. Kaynaklar",
          "OpenAlex (CC0 açık veri, https://openalex.org). Atıf sayısına göre ilk 25 yayın:", ""]
    for w in sorted(a["works"], key=lambda w: -(w.get("cited_by_count") or 0))[:25]:
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        L.append(f"- {study(w)}{' — ' + cell(src, 60) if src else ''}")

    L += ["", "## 6. Yeni Hedef Önerileri"]
    if sugg:
        L.append(f"- `{sugg['production_system']} | {sugg['crop_group']} | {sugg['crop']} | {sugg['region']} | {sugg['focus']}` — {sugg['why']}")
    else:
        L.append("Bu taramada eşiği geçen yeni bir bağlantı alanı çıkmadı.")
    return "\n".join(L) + "\n", title


def write(t, md, today):
    hub.DISCOVERIES_DIR.mkdir(exist_ok=True)
    path = hub.DISCOVERIES_DIR / f"{today}-{t['id'].lower()}-{hub.slugify(t['crop'])}.md"
    front = ["---", f"id: {t['id']}", f"date: {today}", f"production_system: {t['production_system']}",
             f"crop_group: {t['crop_group']}", f"crop: {t['crop']}", f"region: {t['region']}",
             f"engine: {ENGINE}", "kind: auto", "status: published", "---", ""]
    path.write_text("\n".join(front) + md, encoding="utf-8")
    return path


def pick(targets, tid):
    for t in targets:
        if tid and t["id"] == tid:
            return t
        if not tid and t.get("status") == "pending" and t.get("query"):
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--fixture", help="OpenAlex yerine kayıtlı JSON (çevrimdışı deneme)")
    ap.add_argument("--dry-run", action="store_true", help="Raporu yazdır, dosyaya kaydetme")
    args = ap.parse_args()

    targets = hub.load_targets()
    t = pick(targets, args.id)
    if not t:
        print("Taranacak hedef yok (sorgusu olan 'pending' hedef bulunamadı).")
        hub.set_output("created", "false")
        return 0
    if not t.get("query"):
        print(f"{t['id']} için 'query' alanı yok; core/targets.json'a İngilizce arama sorgusu ekleyin.")
        hub.set_output("created", "false")
        return 0
    print(f"Taranıyor: {t['id']} — {t['crop']}: {t['focus']}")

    try:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8")) if args.fixture else fetch(t)
    except ScanSkipped as e:
        print(f"::notice::{e}")
        hub.set_output("created", "false")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    a = analyse(t, data)
    sugg = suggestion(t, a["links"], targets)
    md, title = render(t, data, a, today, sugg)
    if args.dry_run:
        print(md)
        return 0

    path = write(t, md, today)
    t["status"] = "published"
    t["report"] = str(path.relative_to(ROOT))
    t["processed_at"] = datetime.now(timezone.utc).isoformat()
    if sugg:
        nmax = max(int(x["id"].split("-")[1]) for x in targets if x["id"].startswith("TRG-"))
        nt = {"id": f"TRG-{nmax + 1:03d}", **{k: v for k, v in sugg.items() if k != "why"},
              "status": "pending", "suggested_by": t["id"]}
        targets.append(nt)
        print(f"[KUYRUK] Yeni hedef: {nt['id']} — {nt['focus']}")
    hub.save_targets(targets)
    hub.rebuild_index()
    print(f"[OK] {path.relative_to(ROOT)} — {len(a['works'])} yayın incelendi")
    hub.set_output("created", "true")
    hub.set_output("target_id", t["id"])
    hub.set_output("title", title.replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
