"""AgriGap Teknoloji Boşluk Haritası (yapay zekâsız, ücretsiz).

Ürün × iş adımı tablosunun her hücresi için iki katmanda (makine & donanım, yazılım & yapay zekâ)
OpenAlex'te yayın sayar ve yazar ülkesine göre böler (dünya, Türkiye, İspanya, AB toplamı).
Her çalışmada en eski güncellenen birkaç ürünü yeniler (kayan güncelleme); sonuç matrix/matrix.json.

Kendini besleme: dünyada çok çalışılmış ama hedef bölgede (varsayılan TR) hiç yayını olmayan
en güçlü hücreyi ayrıntılı tarama için kuyruğa ekler.

Kullanım:
    python scripts/matrix_scan.py               # sıradaki ürün grubunu yenile
    python scripts/matrix_scan.py --crops 2     # bu çalışmada yalnızca 2 ürün
    python scripts/matrix_scan.py --fixture f.json   # çevrimdışı deneme (sahte sayılar)
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_engine as hub  # noqa: E402
import source_scan as ss  # noqa: E402

ROOT = hub.ROOT
CFG = json.loads((ROOT / "core" / "matrix_config.json").read_text(encoding="utf-8"))
OUT = ROOT / "matrix" / "matrix.json"
SYSTEM = {"Sebzeler": "Sebze Yetiştiriciliği", "Meyveler": "Çok Yıllık Bahçe & Bağcılık",
          "Zeytin & Sert Kabuklular": "Çok Yıllık Bahçe & Bağcılık", "Tarla Bitkileri": "Açık Tarla Tarımı"}


def cell_query(crop, op, layer):
    return f"({crop['en']}) AND ({op['terms']}) AND ({layer['terms']})"


def country_key(k):
    return str(k or "").rstrip("/").split("/")[-1].upper()


def count_cell(q, fixture_rng=None):
    if fixture_rng is not None:  # çevrimdışı deneme: sahte ama tutarlı sayılar
        w = int(fixture_rng.expovariate(1 / 120)) if fixture_rng.random() > 0.15 else fixture_rng.randint(0, 4)
        tr = int(w * fixture_rng.choice([0, 0, 0.01, 0.03, 0.06]))
        es = int(w * fixture_rng.choice([0.02, 0.05, 0.08]))
        return {"w": w, "tr": tr, "es": es, "eu": int(w * 0.25)}
    data = ss.openalex_get({"search.title_and_abstract": q,
                            "filter": f"publication_year:>{CFG['from_year'] - 1},type:article|review",
                            "group_by": "authorships.countries"})
    groups = {country_key(g.get("key")): g.get("count", 0) for g in data.get("group_by") or []}
    return {"w": data.get("meta", {}).get("count", 0), "tr": groups.get("TR", 0), "es": groups.get("ES", 0),
            "eu": sum(groups.get(c, 0) for c in ss.EU27)}


def load():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"cells": {}, "crop_updated": {}}


def save(m):
    m["generated"] = datetime.now(timezone.utc).isoformat()
    m["crops"] = CFG["crops"]
    m["ops"] = CFG["ops"]
    m["layers"] = [{k: v for k, v in layer.items() if k != "terms"} for layer in CFG["layers"]]
    m["from_year"] = CFG["from_year"]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def auto_queue(m, targets):
    aq = CFG["auto_queue"]
    have = {t.get("matrix_cell") for t in targets}
    crops = {c["key"]: c for c in CFG["crops"]}
    ops = {o["key"]: o for o in CFG["ops"]}
    layers = {layer["key"]: layer for layer in CFG["layers"]}
    region = aq["region"].lower()
    cands = []
    for key, cell in m["cells"].items():
        ck, ok = key.split("|")
        for lk, v in cell.items():
            if lk not in layers or not isinstance(v, dict):
                continue
            mk = f"{ck}|{ok}|{lk}"
            if mk in have or ck not in crops or ok not in ops:
                continue
            if v["w"] >= aq["min_world"] and v.get(region, 0) <= aq["max_region"]:
                cands.append((v["w"], mk, crops[ck], ops[ok], layers[lk]))
    cands.sort(key=lambda x: -x[0])
    added = []
    for w, mk, c, o, layer in cands[: aq["max_per_run"]]:
        nmax = max(int(x["id"].split("-")[1]) for x in targets if x["id"].startswith("TRG-"))
        t = {"id": f"TRG-{nmax + 1:03d}", "production_system": SYSTEM.get(c["group"], c["group"]),
             "crop_group": c["group"], "crop": c["tr"], "crop_en": c["en"], "stage": o["stage"],
             "region": aq["region"],
             "focus": f"{o['tr']} işinde {layer['tr'].lower()}: dünyada {w} yayın var, {aq['region']} kaynaklı yayın yok",
             "query": cell_query(c, o, layer), "status": "pending", "suggested_by": "Teknoloji Boşluk Haritası",
             "matrix_cell": mk}
        targets.append(t)
        added.append(t)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crops", type=int, default=CFG["crops_per_run"])
    ap.add_argument("--fixture", action="store_true", help="OpenAlex yerine sahte sayılar (yalnız deneme)")
    ap.add_argument("--only-missing", action="store_true", help="Yalnızca hiç taranmamış ürünler (ilk doldurma)")
    args = ap.parse_args()

    m = load()
    upd = m.setdefault("crop_updated", {})
    order = sorted(CFG["crops"], key=lambda c: upd.get(c["key"], ""))
    if args.only_missing:
        order = [c for c in order if c["key"] not in upd]
        if not order:
            print("Haritada taranmamış ürün kalmadı.")
    batch = order[: args.crops]
    rng = random.Random(7) if args.fixture else None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    done = 0
    try:
        for c in batch:
            for o in CFG["ops"]:
                cell = {}
                for layer in CFG["layers"]:
                    cell[layer["key"]] = count_cell(cell_query(c, o, layer), rng)
                m["cells"][f"{c['key']}|{o['key']}"] = cell
            upd[c["key"]] = today
            done += 1
            print(f"[HARİTA] {c['tr']} güncellendi")
    except ss.ScanSkipped as e:
        print(f"::notice::Harita yarıda kaldı ({done} ürün güncellendi): {e}")

    if done:
        targets = hub.load_targets()
        added = auto_queue(m, targets)
        if added:
            hub.save_targets(targets)
            for t in added:
                print(f"[KUYRUK] {t['id']} — {t['crop']}: {t['focus']}")
        save(m)
    hub.set_output("matrix_updated", "true" if done else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
