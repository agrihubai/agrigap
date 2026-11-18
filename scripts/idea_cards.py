"""AgriGap Yeni Öneriler — Aşama 2, Katman 1: öneri yazarı (Gemini, ücretsiz katman).

Katmanlı yapı: her kart ideas/cards/<id>.json içinde 'layers' altında katman katman büyür.
  layers.writer   Bu betik: en güçlü adaylar için yalnızca verilen kaynaklardan öneri kartı yazar.
  layers.audit    (ileride) ikinci, bağımsız bir yapay zekânın denetimi.
Yeni katmanlar aynı dosyaya kendi anahtarıyla eklenir; önceki katmanlar değişmez.

Akış (aday başına):
  1. ideas/candidates.json'dan, henüz kartı olmayan en güçlü adayı seç (türler sırayla).
  2. OpenAlex'ten o hücrenin en ilgili yayınlarını çek (başlık, özet, DOI, ülke) = kaynak paketi.
  3. Zorluk sinyallerini ve ilgili mevzuatı (core/regulations.json) pakete ekle.
  4. Gemini'ye yalnızca bu paketle kart yazdır (JSON, Türkçe + İngilizce).
  5. Otomatik kontroller (yapay zekâsız): DOI'ler pakette mi, uydurma sayı var mı,
     yenilik kontrolü (önerinin anahtar kelimeleriyle OpenAlex'te kaç yayın var).
  6. Geçen kart yayınlanır; geçmeyen ya da "bu iş bu ürün için anlamsız" denen kart kayıtta kalır.

Ücretsiz: GEMINI_API_KEY yoksa hiçbir şey yapmadan biter. Kota dolarsa o gün atlanır.

Kullanım:
    python scripts/idea_cards.py --count 2
    python scripts/idea_cards.py --count 1 --mock     # çevrimdışı deneme (sahte kart, yayınlanmaz)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_engine as hub  # noqa: E402
import source_scan as ss  # noqa: E402

ROOT = hub.ROOT
CANDS = ROOT / "ideas" / "candidates.json"
CARDS_DIR = ROOT / "ideas" / "cards"
INDEX = ROOT / "ideas" / "cards.json"
MATRIX = ROOT / "matrix" / "matrix.json"
REGS = ROOT / "core" / "regulations.json"
API = "https://generativelanguage.googleapis.com/v1beta"
TYPE_ORDER = ["transfer", "neighbor", "layer", "gap"]
PROPOSAL_TYPES = ["machine", "software", "practice", "bio", "business"]
GRADES = ["strong", "medium", "weak"]
N_EVIDENCE = 15
NOVELTY_SEEN = 3   # yenilik kontrolünde bu sayıdan az yayın: "taranan kaynaklarda rastlanmadı"

SYSTEM = """Sen AgriGap'in öneri yazarısın (https://agrihubai.github.io/agrigap/). AgriGap, Türkiye ve Avrupa tarımında
teknoloji boşluklarını bulan açık erişimli bir merkezdir. Amacın: verilen boşluk için tarıma ivme kazandıracak,
daha az iş gücü ve maliyet gerektiren, mevzuata ve çevre yükümlülüklerine uygun en iyi çözüm fikirlerini üretmek.

KESİN KURALLAR
- Yalnızca KAYNAK PAKETİ'ndeki bilgileri kanıt olarak kullan. Pakette olmayan kaynak, DOI, firma, ürün adı,
  patent, mevzuat maddesi, verim, maliyet ya da yüzde YAZMA. Sayı yazacaksan yalnızca paketteki sayıyı kullan.
- "Hiç denenmemiş" deme; "taranan kaynaklarda rastlanmadı" de. Bulgunu "Bu analize göre…" diliyle sun.
- Önce mevcut çözümler: paketteki yayınlarda bu iş için zaten ne yapılmış (nerede, nasıl, avantaj, dezavantaj).
  Sonra daha ideal öneriler: mevcut çözümün dezavantajını gideren, başka ürün/sektörden aktarılan ya da
  görünmeyen bağlantıyı kullanan fikirler.
- Öneri türleri: machine (makine/donanım), software (yazılım/yapay zekâ), practice (uygulama/yöntem),
  bio (biyolojik girdi/enzim), business (iş modeli: paylaşım, kooperatif, hizmet olarak vb.).
  En uygun 2-3 öneriyi seç; türleri çeşitlendir; zorla tür doldurma.
- Ütopik, aşırı pahalı, yüksek enerji isteyen ya da sahada (toz, nem, çamur, eğim, mevsimsellik) dayanmayacak fikri ele.
- Sayısal amorti/ROI tahmini yapma; geri dönüşün hangi varsayımlara bağlı olduğunu yaz.
- Mevzuat yalnızca MEVZUAT bölümündekilerdir; uyum ya da çelişkiyi o maddelere göre yaz, madde uydurma.
- İş adımı bu ürün için anlamsızsa (örn. yabancı otu olmayan bir kültür) relevant=false yap ve kısa gerekçe yaz; öneri üretme.
- Kurum, firma, ülke hakkında övgü/yergi yapma.

ÇIKTI: yalnızca aşağıdaki JSON. Metin alanlarını hem Türkçe (tr) hem İngilizce (en) yaz; içerik aynı olsun.
{
 "relevant": true,
 "relevance_reason": {"tr": "", "en": ""},
 "tr": {"title": "", "finding": "Bu analize göre … (tek cümle)", "problem": "",
        "existing": [{"what": "", "where": "", "how": "", "pros": "", "cons": "", "source_dois": [""]}],
        "proposals": [{"title": "", "how": "", "difference": "mevcut çözümden farkı", "overcomes": [""],
                       "effect_assumptions": "iş gücü/maliyet/çevre etkisi hangi varsayımlara bağlı",
                       "regulation_fit": "", "premortem": "en kritik varsayım ve çöküş riski",
                       "min_experiment": "en ucuz doğrulama deneyi ve başarı eşiği"}]},
 "en": {aynı yapı, İngilizce},
 "proposals_meta": [{"type": "machine|software|practice|bio|business",
                     "grades": {"problem": "strong|medium|weak", "evidence": "", "regulation": "", "field": "", "testability": ""},
                     "regulations": ["mevzuat id"], "source_dois": [""],
                     "novelty_query": "önerinin özünü anlatan 3-6 İngilizce anahtar kelime, AND/OR ile (OpenAlex araması için)"}]
}
proposals_meta sırası tr.proposals ve en.proposals sırasıyla aynı olmalı."""


def now():
    return datetime.now(timezone.utc)


def load(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def slug(cid):
    return re.sub(r"[^a-z0-9]+", "-", cid.lower()).strip("-")


# ---------- Gemini ----------

def gemini_req(path, body=None):
    key = os.environ["GEMINI_API_KEY"].strip()
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key},
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_models():
    """Kullanılabilir 'flash' modellerini sırala: önce kararlı, sonra en yeni. Biri yanıt vermezse sıradaki denenir."""
    if os.environ.get("GEMINI_MODEL"):
        return [os.environ["GEMINI_MODEL"]]
    try:
        models = gemini_req("models?pageSize=200").get("models", [])
    except Exception as e:  # liste alınamazsa bilinen adları dene
        print(f"[UYARI] Model listesi alınamadı ({e}); varsayılanlar deneniyor.")
        return ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    bad = ("image", "tts", "live", "audio", "embedding", "vision", "thinking-exp", "learnlm", "gemma", "robotics", "computer")
    ok = []
    for m in models:
        name = m.get("name", "").split("/")[-1]
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if "flash" in name and not any(b in name for b in bad):
            ver = [int(x) for x in re.findall(r"\d+", name)[:2]] or [0]
            stable = "preview" not in name and "exp" not in name
            ok.append(("lite" not in name, stable, ver, name))
    ok.sort(reverse=True)  # önce tam flash, kararlı, en yeni; lite en sonda yedek
    return [x[3] for x in ok][:5] or ["gemini-2.5-flash"]


class ModelBusy(Exception):
    pass


def gemini_write(models, prompt):
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}}
    tried = []
    for model in models:
        for attempt in range(2):
            try:
                data = gemini_req(f"models/{model}:generateContent", body)
                parts = data["candidates"][0]["content"]["parts"]
                return model, json.loads("".join(p.get("text", "") for p in parts))
            except urllib.error.HTTPError as e:
                tried.append(f"{model}: HTTP {e.code}")
                if e.code in (400, 401, 403):
                    raise ss.ScanSkipped(f"Gemini isteği reddedildi ({model}: HTTP {e.code}); anahtarı kontrol edin.")
                if e.code in (404, 429):  # bu model yok ya da kotası doldu: sıradaki modele geç
                    break
                time.sleep(15 * (attempt + 1))  # 500/503: kısa bekle, bir kez daha dene
            except (KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as e:
                tried.append(f"{model}: {type(e).__name__}")
                time.sleep(5)
    raise ss.ScanSkipped("Gemini yanıt vermedi (" + "; ".join(tried) + "); aday bekliyor.")


# ---------- kaynak paketi ----------

def cell_query(m, c):
    crop = next(x for x in m["crops"] if x["key"] == c["crop"])
    op = next(x for x in m["ops"] if x["key"] == c["op"])
    cfg = load(ROOT / "core" / "matrix_config.json")
    layer = next(x for x in cfg["layers"] if x["key"] == c["layer"])
    return crop, op, f"({crop['en']}) AND ({op['terms']}) AND ({layer['terms']})"


def evidence(q):
    works, total = ss.search(q, N_EVIDENCE)
    ev = []
    for w in works:
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        if not doi:
            continue
        ev.append({"doi": doi, "title": w.get("display_name") or "", "year": w.get("publication_year"),
                   "countries": sorted(ss.countries(w)), "abstract": ss.abstract(w)[:1200],
                   "cited_by": w.get("cited_by_count") or 0})
    return ev, total


def constraints(ev):
    out = []
    for cdef in ss.RULES.get("constraints", []):
        rx = ss.term_re(cdef["terms"])
        n = sum(1 for e in ev if rx.search(e["title"] + " " + e["abstract"]))
        if n:
            out.append({"tr": cdef["tr"], "en": cdef["en"], "n": n})
    return sorted(out, key=lambda x: -x["n"])


def build_prompt(c, crop, op, layer_name, ev, cons, regs, total):
    L = [f"BOŞLUK ADAYI ({c['type']}): Ürün: {crop['tr']} ({crop.get('label_en', '')}) · İş adımı: {op['tr']} ({op.get('en', '')}) · Katman: {layer_name}",
         f"Harita sayıları (OpenAlex, 2010 sonrası, başlık+özet): dünya {c['w']}, Türkiye {c['tr']}, İspanya {c['es']}, AB toplamı ≈{c['eu']}."]
    if c["type"] == "neighbor":
        L.append(f"Ürünün literatür büyüklüğüne göre beklenen ≈{c.get('expected')} yayın; oranca en çok çalışan komşu ürün kodu: {c.get('neighbor')}.")
    if c["type"] == "layer":
        L.append(f"Diğer katmanda ({c.get('other_layer')}) {c.get('other_w')} yayın var; bu katman az çalışılmış.")
    if c["type"] == "gap":
        L.append(f"Aynı gruptaki ürünlerde bu iş için ortanca {c.get('group_median')} yayın var.")
    L += ["", f"KAYNAK PAKETİ (bu sorguda toplam {total} yayın; en ilgili {len(ev)} tanesi):"]
    for i, e in enumerate(ev, 1):
        L.append(f"[{i}] DOI {e['doi']} | {e['year']} | {', '.join(e['countries']) or '?'} | {e['title']}\n    Özet: {e['abstract'] or '(özet yok)'}")
    L += ["", "ZORLUK SİNYALLERİ (paketteki yayınlarda geçen engeller): " + ("; ".join(f"{x['tr']} ({x['n']})" for x in cons) or "yok")]
    L += ["", "MEVZUAT (yalnızca bunlar):"]
    for r in regs:
        dates = "; ".join(f"{d['date']}: {d['tr']}" for d in r["dates"])
        L.append(f"- id={r['id']} | {r['title_tr']} ({r['ref']}) | {dates} | {r['summary_tr']}")
    if not regs:
        L.append("- (bu hücreyle ilişkili madde yok)")
    return "\n".join(L)


# ---------- otomatik kontroller ----------

DOI_RX = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
NUM_RX = re.compile(r"(\d+[.,]?\d*)\s?(%|‰|tl|try|€|eur|usd|\$|ton/ha|t/ha|kg/ha|kwh)", re.IGNORECASE)
PCT_RX = re.compile(r"%\s?(\d+[.,]?\d*)")  # Türkçe yazım: %37


def flat(card):
    """Kartın tr/en metin alanlarındaki bütün yazıları tek metinde topla."""
    out = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
    walk([card.get("tr"), card.get("en")])
    return " ".join(out)


def check(card, ev):
    allowed = {e["doi"].lower() for e in ev}
    corpus = " ".join(e["title"] + " " + e["abstract"] for e in ev).lower()
    issues = []
    used = set()
    for blk in card.get("proposals_meta", []):
        used |= {d.lower() for d in blk.get("source_dois", []) if d}
    for lang in ("tr", "en"):
        for e in (card.get(lang) or {}).get("existing", []):
            used |= {d.lower() for d in e.get("source_dois", []) if d}
    used |= {d.rstrip(".,;)").lower() for d in DOI_RX.findall(flat(card))}
    foreign = sorted(d for d in used if d not in allowed)
    if foreign:
        issues.append({"kind": "unknown_doi", "detail": foreign})
    nums = []
    found = NUM_RX.findall(flat(card)) + [(v, "%") for v in PCT_RX.findall(flat(card))]
    for val, unit in found:
        if val.replace(",", ".") not in corpus.replace(",", "."):
            nums.append(f"{val}{unit}")
    if nums:
        issues.append({"kind": "unsourced_number", "detail": sorted(set(nums))})
    need = ["tr", "en", "proposals_meta"]
    if card.get("relevant", True) and any(k not in card for k in need):
        issues.append({"kind": "schema", "detail": [k for k in need if k not in card]})
    if card.get("relevant", True):
        n_tr = len((card.get("tr") or {}).get("proposals", []))
        if n_tr != len(card.get("proposals_meta", [])) or n_tr != len((card.get("en") or {}).get("proposals", [])):
            issues.append({"kind": "schema", "detail": "proposal counts differ"})
        for pm in card.get("proposals_meta", []):
            if pm.get("type") not in PROPOSAL_TYPES:
                issues.append({"kind": "schema", "detail": f"type {pm.get('type')}"})
            for g in (pm.get("grades") or {}).values():
                if g not in GRADES:
                    issues.append({"kind": "schema", "detail": f"grade {g}"})
                    break
    return issues


def novelty(card, crop_en, mock=False):
    out = []
    for pm in card.get("proposals_meta", []):
        q = (pm.get("novelty_query") or "").strip()
        if not q:
            out.append({"query": "", "count": None})
            continue
        if mock:
            out.append({"query": q, "count": 1})
            continue
        try:
            _, n = ss.search(f"({crop_en}) AND ({q})", 1)
        except ss.ScanSkipped:
            n = None
        out.append({"query": q, "count": n, "seen": None if n is None else n >= NOVELTY_SEEN})
    return out


# ---------- ana akış ----------

def next_candidates(cands, have, n):
    lists = {k: [c for c in cands.get(k, []) if slug(c["id"]) not in have] for k in TYPE_ORDER}
    out, i = [], 0
    while len(out) < n and any(lists.values()):
        k = TYPE_ORDER[i % len(TYPE_ORDER)]
        if lists[k]:
            out.append(lists[k].pop(0))
        i += 1
    return out


def mock_card(ev):
    d = [ev[0]["doi"]] if ev else []
    p = {"title": "Deneme önerisi", "how": "Deneme", "difference": "Deneme", "overcomes": ["Deneme"],
         "effect_assumptions": "Deneme", "regulation_fit": "Deneme", "premortem": "Deneme", "min_experiment": "Deneme"}
    part = {"title": "Deneme kartı", "finding": "Bu analize göre deneme.", "problem": "Deneme",
            "existing": [{"what": "Deneme", "where": "Deneme", "how": "Deneme", "pros": "Deneme", "cons": "Deneme", "source_dois": d}],
            "proposals": [p]}
    return {"relevant": True, "relevance_reason": {"tr": "Deneme", "en": "Test"}, "tr": part, "en": part,
            "proposals_meta": [{"type": "software", "grades": {k: "medium" for k in ("problem", "evidence", "regulation", "field", "testability")},
                                "regulations": [], "source_dois": d, "novelty_query": "test AND mock"}]}


def rebuild_index():
    items = []
    for f in sorted(CARDS_DIR.glob("*.json")):
        c = load(f)
        w = (c.get("layers") or {}).get("writer") or {}
        cont = w.get("content") or {}
        items.append({"id": c["id"], "file": f.name, "type": c["candidate"]["type"], "crop": c["candidate"]["crop"],
                      "op": c["candidate"]["op"], "layer": c["candidate"]["layer"], "status": w.get("status"),
                      "published": c.get("published", False), "created": c.get("created"),
                      "title_tr": (cont.get("tr") or {}).get("title", ""), "title_en": (cont.get("en") or {}).get("title", "")})
    items.sort(key=lambda x: x["created"] or "", reverse=True)
    INDEX.write_text(json.dumps({"generated": now().isoformat(), "cards": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--mock", action="store_true", help="Gemini ve OpenAlex olmadan deneme; kart yayınlanmaz")
    ap.add_argument("--fixture", help="--mock ile: OpenAlex yerine kaynak paketi JSON'u")
    args = ap.parse_args()

    if not args.mock and not os.environ.get("GEMINI_API_KEY", "").strip():
        print("::notice::GEMINI_API_KEY tanımlı değil; öneri kartı yazılmadı.")
        hub.set_output("cards", "0")
        return 0
    cands, m, regs = load(CANDS), load(MATRIX), (load(REGS, {}) or {}).get("items", [])
    if not cands or not m:
        print("Aday ya da harita yok.")
        hub.set_output("cards", "0")
        return 0
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    have = {f.stem for f in CARDS_DIR.glob("*.json")}
    picks = next_candidates(cands["candidates"], have, args.count)
    models = ["mock"] if args.mock else pick_models()
    print(f"Modeller (sırayla): {', '.join(models)} · {len(picks)} aday")
    model = models[0]
    layers = {x["key"]: x for x in m["layers"]}
    made = 0
    for c in picks:
        crop, op, q = cell_query(m, c)
        try:
            if args.mock:
                ev = load(Path(args.fixture)) if args.fixture else []
                total = len(ev)
            else:
                ev, total = evidence(q)
            if len(ev) < 3:
                card, status, reason = None, "skipped", f"Kaynak paketi çok küçük ({len(ev)} yayın)."
            else:
                cons = constraints(ev)
                rel_regs = [r for r in regs if r["id"] in c.get("regulations", [])]
                prompt = build_prompt(c, crop, op, layers[c["layer"]]["tr"], ev, cons, rel_regs, total)
                if args.mock:
                    card = mock_card(ev)
                else:
                    model, card = gemini_write(models, prompt)
                issues = check(card, ev)
                if not card.get("relevant", True):
                    status, reason = "irrelevant", (card.get("relevance_reason") or {}).get("tr", "")
                elif issues:
                    status, reason = "rejected", "; ".join(f"{i['kind']}: {i['detail']}" for i in issues)
                else:
                    status, reason = "ok", ""
        except ss.ScanSkipped as e:
            print(f"::notice::{e}")
            break
        nov = novelty(card, crop["en"], args.mock) if card and status == "ok" else []
        rec = {"id": c["id"], "created": now().isoformat(), "candidate": c, "query": q,
               "published": status == "ok" and not args.mock,
               "layers": {"writer": {"engine": "gemini", "model": model, "date": now().strftime("%Y-%m-%d"),
                                     "status": status, "reason": reason, "content": card if status in ("ok", "rejected") else None,
                                     "relevance": (card or {}).get("relevance_reason"),
                                     "sources": [{k: e[k] for k in ("doi", "title", "year", "countries")} for e in ev],
                                     "constraints": constraints(ev) if ev else [], "novelty": nov,
                                     "checks": {"issues": check(card, ev) if card else []}},
                          "audit": None}}
        (CARDS_DIR / f"{slug(c['id'])}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[KART] {c['id']} → {status}{(' (' + reason[:120] + ')') if reason else ''}")
        made += 1
    if made:
        rebuild_index()
    hub.set_output("cards", str(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
