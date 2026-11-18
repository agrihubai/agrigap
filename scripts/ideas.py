"""AgriGap Yeni Öneriler — Aşama 1: kural tabanlı aday bulma (yapay zekâsız, API çağrısı yok).

Teknoloji Boşluk Haritası'ndan (matrix/matrix.json) dört tür aday çıkarır:

  transfer   Aktarım adayı: dünyada çok çalışılmış, hedef bölgede (TR) yayını yok ya da çok az.
  neighbor   Komşu üründen aktarım: bu iş adımı, ürünün kendi literatür büyüklüğüne göre aynı gruptaki
             ürünlerden belirgin biçimde az çalışılmış (oran karşılaştırması; büyük ürünler baskın olmasın diye).
  layer      Katman değişimi: aynı hücrede makine ile yazılım/yapay zekâ arasında büyük fark var.
  gap        Gerçek boşluk: dünyada neredeyse hiç yayın yok, ama aynı gruptaki ürünlerde bu iş çalışılıyor
             (yani iş adımı bu ürün grubu için anlamlı).

Her adaya ilgili mevzuat (core/regulations.json etiketleri) ve varsa ilgili rapor bağlanır.
Aşama 2'de (yapay zekâ) en güçlü adaylardan öneri kartı yazılır; bu betik yalnızca adayları üretir.

Kullanım:
    python scripts/ideas.py      # ideas/candidates.json üretir
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "matrix" / "matrix.json"
REGS = ROOT / "core" / "regulations.json"
TARGETS = ROOT / "core" / "targets.json"
OUT = ROOT / "ideas" / "candidates.json"

RULE = {
    "transfer": {"min_world": 30, "max_region": 1},
    "neighbor": {"max_share_ratio": 0.2, "min_expected": 10},
    "layer": {"min_big": 30, "ratio": 5, "max_small": 10},
    "gap": {"max_world": 4, "min_group_median": 20},
    "per_type": 40,
    "per_crop": 2,
}
# Her aday için Aşama 2'de değerlendirilecek öneri türleri
PROPOSAL_TYPES = ["machine", "software", "practice", "bio", "business"]


def load(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def main():
    m = load(MATRIX)
    if not m or not m.get("cells"):
        print("Harita verisi yok; aday üretilmedi.")
        return 0
    regs = (load(REGS, {}) or {}).get("items", [])
    targets = load(TARGETS, []) or []
    crops = {c["key"]: c for c in m["crops"]}
    ops = {o["key"]: o for o in m["ops"]}
    layers = [layer["key"] for layer in m["layers"]]
    cells = m["cells"]
    lay_tag = {"mech": "machine", "digi": "software"}

    def regs_for(op, layer):
        out = []
        for r in regs:
            tags = set(r.get("tags", []))
            if op in tags or lay_tag.get(layer) in tags:
                out.append(r["id"])
        return out

    def target_for(ck, ok, lk):
        for t in targets:
            if t.get("matrix_cell") == f"{ck}|{ok}|{lk}":
                return t["id"]
        return ""

    def base(kind, ck, ok, lk, v, score, **extra):
        return {"id": f"{kind}:{ck}:{ok}:{lk}", "type": kind, "crop": ck, "op": ok, "layer": lk,
                "w": v["w"], "tr": v["tr"], "es": v["es"], "eu": v["eu"], "score": round(score, 3),
                "regulations": regs_for(ok, lk), "target": target_for(ck, ok, lk),
                "proposal_types": PROPOSAL_TYPES, **extra}

    out = {k: [] for k in ("transfer", "neighbor", "layer", "gap")}
    by_group = {}
    for c in m["crops"]:
        by_group.setdefault(c["group"], []).append(c["key"])

    totals = {}
    for key, cell in cells.items():
        ck = key.split("|")[0]
        for lk in layers:
            totals[(ck, lk)] = totals.get((ck, lk), 0) + (cell.get(lk) or {}).get("w", 0)

    for key, cell in cells.items():
        ck, ok = key.split("|")
        c = crops.get(ck)
        if not c or ok not in ops:
            continue
        peers = [p for p in by_group[c["group"]] if p != ck and f"{p}|{ok}" in cells]
        for lk in layers:
            v = cell.get(lk)
            if not v:
                continue
            r = RULE["transfer"]
            if v["w"] >= r["min_world"] and v["tr"] <= r["max_region"]:
                out["transfer"].append(base("transfer", ck, ok, lk, v, math.log10(v["w"] + 1)))

            r = RULE["neighbor"]
            tot = totals.get((ck, lk), 0)
            if peers and tot:
                shares = {p: cells[f"{p}|{ok}"].get(lk, {}).get("w", 0) / totals[(p, lk)]
                          for p in peers if totals.get((p, lk))}
                med = median(list(shares.values()))
                expected = med * tot
                if shares and expected >= r["min_expected"] and v["w"] / tot <= r["max_share_ratio"] * med:
                    best = max(shares, key=shares.get)
                    out["neighbor"].append(base("neighbor", ck, ok, lk, v, math.log10(expected + 1) - math.log10(v["w"] + 1),
                                                neighbor=best, neighbor_w=cells[f"{best}|{ok}"][lk]["w"],
                                                expected=round(expected)))

            r = RULE["gap"]
            if v["w"] <= r["max_world"] and peers:
                med = median([cells[f"{p}|{ok}"].get(lk, {}).get("w", 0) for p in peers])
                if med >= r["min_group_median"]:
                    out["gap"].append(base("gap", ck, ok, lk, v, math.log10(med + 1), group_median=med))

        r = RULE["layer"]
        mv, dv = cell.get("mech"), cell.get("digi")
        if mv and dv:
            for big, small, bk, sk in ((mv, dv, "mech", "digi"), (dv, mv, "digi", "mech")):
                if big["w"] >= r["min_big"] and small["w"] <= r["max_small"] and big["w"] >= r["ratio"] * max(small["w"], 1):
                    out["layer"].append(base("layer", ck, ok, sk, small, math.log10(big["w"] + 1) - math.log10(small["w"] + 1),
                                             other_layer=bk, other_w=big["w"]))

    for k in out:
        out[k].sort(key=lambda x: -x["score"])
        seen, kept = {}, []
        for x in out[k]:  # çeşitlilik: aynı üründen tür başına en fazla per_crop aday
            if seen.get(x["crop"], 0) < RULE["per_crop"]:
                kept.append(x)
                seen[x["crop"]] = seen.get(x["crop"], 0) + 1
        out[k] = kept[: RULE["per_type"]]
    total = sum(len(v) for v in out.values())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(), "rules": RULE,
                               "matrix_generated": m.get("generated"), "candidates": out},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[ÖNERİ] {total} aday: " + ", ".join(f"{k} {len(v)}" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
