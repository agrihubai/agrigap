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
