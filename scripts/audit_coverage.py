"""AgriGap kapsam denetimi (tek seferlik, elle çalıştırılır; ~30 ücretsiz OpenAlex sorgusu).

Ölçer: (1) bir yazarın yayınları OpenAlex'te ne kadar var ve Türkiye'ye sayılıyor mu,
(2) Türk dergilerinde yazar ülkesi eksikliği, (3) belirsiz ürün kelimeleri, (4) belge türü ve dil,
(5) başlık-özet ile yalnız başlık araması farkı.
"""
import json
import os
import time
import urllib.parse
import urllib.request

BASE = "https://api.openalex.org/"
UA = "AgriGap-audit (https://github.com/agrihubai/agrigap)"
MECH = ("machine OR machinery OR mechanization OR mechanisation OR mechanical OR mechanized OR robot OR robotic "
        "OR automation OR automated OR autonomous OR prototype OR drone OR UAV OR sensor")
HARV = "harvesting OR harvester OR harvest OR picking"


def get(path, **params):
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            print("  ! hata:", e)
            time.sleep(5 * (a + 1))
    return {}


def cc(k):
    return str(k or "").rstrip("/").split("/")[-1]


def section(t):
    print("\n==== " + t)


import sys
MED = "primary_topic.field.id:!27,primary_topic.field.id:!35,primary_topic.field.id:!36,primary_topic.field.id:!29"
DIGI = ("software OR \"mobile app\" OR smartphone OR \"decision support\" OR \"artificial intelligence\" OR \"machine learning\" "
        "OR \"deep learning\" OR \"computer vision\" OR IoT OR \"internet of things\" OR \"digital twin\" OR \"information system\" OR blockchain")


def n(q, extra=""):
    f = "publication_year:>2009,type:article|review|conference-paper" + ("," + extra if extra else "")
    d = get("works", **{"search.title_and_abstract": q, "filter": f, "per_page": 1})
    return d.get("meta", {}).get("count")


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_terms  # noqa: E402
CFG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "matrix_config.json"), encoding="utf-8"))
CR = {x["key"]: x for x in CFG["crops"]}; OP = {x["key"]: x for x in CFG["ops"]}; LY = {x["key"]: x for x in CFG["layers"]}
section("T) Türkçe terimlerle, yazar ülkesi kayıtsız yayınlar")
for ck, ok, lk in [("c26", "harvest", "mech"), ("c43", "harvest", "mech"), ("c33", "soil", "mech"), ("c00", "irrig", "digi"),
                   ("c26", "finance", "digi")]:
    q = " AND ".join(f"({tr_terms.query(x['tr_words'])})" for x in (CR[ck], OP[ok], LY[lk]))
    f = "publication_year:>2009,type:article|review|conference-paper," + MED + ",authorships.countries:null"
    d = get("works", **{"search.title_and_abstract": q, "filter": f, "per_page": 5, "select": "display_name,primary_location"})
    print(f"  {CR[ck]['tr']} · {OP[ok]['tr']} · {LY[lk]['tr']}: {d.get('meta', {}).get('count')}")
    for w in d.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        print("     -", (w["display_name"] or "")[:80], "|", src)
sys.exit(0)
section("A) Tıp alanı dışlama + bildiriler dahil (Hasat × Makine)")
for k, crop in [("incir", "fig OR \"Ficus carica\""), ("narenciye", "citrus OR orange OR mandarin OR lemon"),
                ("elma", "apple"), ("domates", "tomato"), ("mısır", "maize OR corn")]:
    q = f"({crop}) AND ({HARV}) AND ({MECH})"
    print(f"  {k}: tıp dahil {n(q)}, tıp hariç {n(q, MED)}")
q = f"(fig OR \"Ficus carica\") AND ({HARV}) AND ({MECH})"
d = get("works", **{"search.title_and_abstract": q, "filter": "publication_year:>2009,type:article|review|conference-paper," + MED,
                    "per_page": 10, "select": "display_name"})
for w in d.get("results", []):
    print("     -", (w["display_name"] or "")[:90])

section("B) Elma × Yazılım: Apple şirketi gürültüsü")
q = f"(apple) AND ({HARV}) AND ({DIGI})"
print("  apple:", n(q, MED), " NOT iPhone/iOS/Apple Watch:", n(f"(apple) AND ({HARV}) AND ({DIGI}) NOT (iPhone OR iOS OR \"Apple Watch\" OR macOS)", MED))

section("C) Ülkesi boş yayınlarda Türkiye tahmini (Narenciye × Hasat × Makine, tıp hariç)")
q = f"(citrus OR orange OR mandarin OR lemon) AND ({HARV}) AND ({MECH})"
print("  TR yazar ülkesi:", n(q, MED + ",authorships.countries:TR"))
print("  ülkesiz:", n(q, MED + ",authorships.countries:null"))
for extra in ["authorships.countries:null,language:tr",
              "authorships.countries:null,primary_location.source.country_code:TR",
              "authorships.countries:null,locations.source.country_code:TR"]:
    print(f"  {extra}:", n(q, MED + "," + extra))
section("C2) Aynı tahmin, Tarım Makinaları Bilimi Dergisi bütününde")
s = get("sources", search="Tarım Makinaları Bilimi Dergisi", per_page=1, select="id,country_code")
src = s["results"][0]; print("  dergi country_code:", src.get("country_code"))
sid = cc(src["id"])
for extra in ["authorships.countries:null", "authorships.countries:null,language:tr",
              "authorships.countries:null,primary_location.source.country_code:TR"]:
    d = get("works", filter=f"primary_location.source.id:{sid},publication_year:>2009,{extra}", per_page=1)
    print(f"  {extra}:", d.get("meta", {}).get("count"))
d = get("works", filter="publication_year:>2009,authorships.countries:null,primary_location.source.country_code:TR", per_page=1)
print("  tüm OpenAlex, 2010+, ülkesiz ama TR dergisi:", d.get("meta", {}).get("count"))
sys.exit(0)

# --- ilk denetim (2026-11-20) ---
section("1) Yazar kapsamı: ORCID 0000-0001-8154-6993 (H. K. Çelik)")
d = get("works", filter="author.orcid:0000-0001-8154-6993", group_by="publication_year")
print("toplam iş:", sum(g["count"] for g in d.get("group_by", [])))
for gb in ["type", "authorships.countries", "language", "primary_location.source.type"]:
    d = get("works", filter="author.orcid:0000-0001-8154-6993", group_by=gb)
    print(f"  {gb}:", {cc(g['key']): g['count'] for g in d.get("group_by", [])[:10]})
d = get("works", filter="author.orcid:0000-0001-8154-6993", per_page=100,
        select="display_name,publication_year,type,authorships,primary_location")
notr = []
for w in d.get("results", []):
    me = [a for a in w["authorships"] if ((a.get("author") or {}).get("orcid") or "").endswith("0000-0001-8154-6993")]
    ctry = sorted({c for a in me for c in a.get("countries", [])})
    if "TR" not in ctry:
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        notr.append((w["publication_year"], w["type"], ctry, src, w["display_name"][:80]))
print("  Türkiye'ye SAYILMAYAN yayınları:", len(notr), "/", len(d.get("results", [])))
for r in notr[:25]:
    print("   ", r)
d = get("authors", search="Kursat Celik", per_page=10, select="id,display_name,orcid,works_count,last_known_institutions")
print("  ad araması (yinelenen profil var mı):")
for a in d.get("results", []):
    inst = [i.get("display_name") for i in (a.get("last_known_institutions") or [])]
    print("   ", a["display_name"], a.get("orcid"), a["works_count"], inst)

section("2) Türk dergilerinde yazar ülkesi eksikliği")
for name in ["Tarım Makinaları Bilimi Dergisi", "Turkish Journal of Agriculture and Forestry",
             "Mediterranean Agricultural Sciences", "Akademik Ziraat Dergisi"]:
    s = get("sources", search=name, per_page=1, select="id,display_name,works_count,host_organization_name")
    if not s.get("results"):
        print("  bulunamadı:", name); continue
    src = s["results"][0]
    sid = cc(src["id"])
    tot = get("works", filter=f"primary_location.source.id:{sid},publication_year:>2009", per_page=1).get("meta", {}).get("count")
    tr = get("works", filter=f"primary_location.source.id:{sid},publication_year:>2009,authorships.countries:TR",
             per_page=1).get("meta", {}).get("count")
    noc = get("works", filter=f"primary_location.source.id:{sid},publication_year:>2009,authorships.countries:null",
              per_page=1).get("meta", {}).get("count")
    print(f"  {src['display_name']} ({src.get('host_organization_name')}): 2010+ {tot} yayın, TR'li {tr}, ülkesiz {noc}")

section("3) Belirsiz ürün kelimeleri (Hasat × Makine)")
tests = {
    "incir_eski": "fig OR \"Ficus carica\"",
    "incir_yeni": "\"Ficus carica\" OR \"fig fruit\" OR \"fig fruits\" OR \"fig tree\" OR \"fig trees\" OR \"fig orchard\" OR \"dried fig\" OR \"dried figs\"",
    "narenciye_eski": "citrus OR orange OR mandarin OR lemon",
    "narenciye_yeni": "citrus OR \"orange fruit\" OR \"orange fruits\" OR \"orange tree\" OR \"orange trees\" OR \"orange orchard\" OR \"sweet orange\" OR mandarin OR tangerine OR lemon",
    "elma_eski": "apple",
    "elma_yeni": "\"apple fruit\" OR \"apple fruits\" OR \"apple tree\" OR \"apple trees\" OR \"apple orchard\" OR \"apple orchards\" OR \"Malus domestica\"",
}
for k, crop in tests.items():
    q = f"({crop}) AND ({HARV}) AND ({MECH})"
    d = get("works", **{"search.title_and_abstract": q, "filter": "publication_year:>2009,type:article|review",
                        "per_page": 6, "select": "display_name"})
    print(f"  {k}: {d.get('meta', {}).get('count')}")
    if k.endswith("eski"):
        for w in d.get("results", []):
            print("     -", (w["display_name"] or "")[:90])

section("4) Belge türü, kaynak türü ve dil (Narenciye × Hasat × Makine, tür filtresi yok)")
q = f"({tests['narenciye_eski']}) AND ({HARV}) AND ({MECH})"
for gb in ["type", "primary_location.source.type", "language"]:
    d = get("works", **{"search.title_and_abstract": q, "filter": "publication_year:>2009", "group_by": gb})
    print(f"  {gb}:", {cc(g['key']): g['count'] for g in d.get("group_by", [])[:10]})

section("5) Yalnız başlık araması (Narenciye × Hasat × Makine)")
for name, prm in [("başlık+özet", "title_and_abstract.search"), ("yalnız başlık", "title.search")]:
    d = get("works", filter=f"{prm}:{q},publication_year:>2009,type:article|review", group_by="authorships.countries")
    g = {cc(x["key"]): x["count"] for x in d.get("group_by", [])}
    print(f"  {name}: dünya {d.get('meta', {}).get('count')}, TR {g.get('TR', 0)}, ES {g.get('ES', 0)}")
