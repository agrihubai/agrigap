"""AgriGap tarama motoru.

Kuyruktaki (core/targets.json) sıradaki hedefi alır, Claude API + web araması ile
rapor üretir, discoveries/ altına Markdown olarak yazar ve discoveries/README.md
dizinini günceller. Yayın, GitHub Actions'ın açtığı Pull Request birleştirilince olur.

İki mod:
  - Ücretsiz (varsayılan): Rapor Claude.ai sohbetinde hazırlanır, sonra
        python scripts/hub_engine.py --id TRG-002 --from-file rapor.md
    ile arşive eklenir (API çağrısı yapılmaz).
  - Ücretli (isteğe bağlı): ANTHROPIC_API_KEY tanımlıysa Claude API + web araması.

Kullanım:
    python scripts/hub_engine.py               # sıradaki 'pending' hedef (API)
    python scripts/hub_engine.py --id TRG-002  # belirli bir hedef
    python scripts/hub_engine.py --dry-run     # API çağırmadan sorguyu göster
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS_FILE = ROOT / "core" / "targets.json"
PROMPT_FILE = ROOT / "core" / "system_prompt.md"
DISCOVERIES_DIR = ROOT / "discoveries"
INDEX_FILE = DISCOVERIES_DIR / "README.md"

MODEL = os.environ.get("AGRIHUB_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.environ.get("AGRIHUB_MAX_TOKENS", "16000"))
MAX_SEARCHES = int(os.environ.get("AGRIHUB_MAX_SEARCHES", "15"))
MAX_CONTINUATIONS = 5  # sunucu araç döngüsü 'pause_turn' ile durursa en fazla bu kadar devam

REQUIRED_SECTIONS = [
    "## 1.", "## 2. Görünmeyen Bağlantılar", "## 3. Mevcut Çözüm Haritası", "## 4.",
    "## 5.", "## 6.", "## 7.", "## 8. Kaynaklar", "## 9. Yeni Hedef Önerileri",
    "**Durum Kararı:**", "**Görünmeyen bağlantı:**",
]

TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slugify(text: str) -> str:
    text = text.translate(TR_MAP)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_targets():
    return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))


def save_targets(targets):
    TARGETS_FILE.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def pick_target(targets, target_id=None, exclude=()):
    for t in targets:
        if target_id and t["id"] == target_id:
            return t
        if not target_id and t.get("status") == "pending" and t["id"] not in exclude:
            return t
    return None


def build_query(t):
    return (
        f"AGRIHUB SCAN: {t['production_system']} > {t['crop_group']} > {t['crop']} | "
        f"Bölge: {t['region']} | Odak: {t['focus']}"
    )


def run_claude(system_prompt: str, query: str):
    from anthropic import Anthropic

    client = Anthropic()  # ANTHROPIC_API_KEY ortam değişkeninden okunur
    messages = [{"role": "user", "content": query}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}]

    all_blocks = []
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        all_blocks.extend(resp.content)
        if resp.stop_reason == "pause_turn":
            # Uzun arama döngüsü: kaldığı yerden devam ettir
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Yanıt max_tokens sınırında kesildi; AGRIHUB_MAX_TOKENS artırın.")
        break

    text_parts, citations = [], {}
    for block in all_blocks:
        if getattr(block, "type", None) != "text":
            continue
        text_parts.append(block.text)
        for c in getattr(block, "citations", None) or []:
            url = getattr(c, "url", None)
            if url:
                citations[url] = getattr(c, "title", None) or url
    return "".join(text_parts).strip(), citations


def strip_preamble(md: str) -> str:
    """İlk '# ' başlığından önceki her şeyi (ör. arama sırasında yazılan ara metin) at."""
    m = re.search(r"^# .+$", md, re.MULTILINE)
    return md[m.start():] if m else md


def quality_check(md: str):
    return [s for s in REQUIRED_SECTIONS if s not in md]


def append_citations(md: str, citations: dict) -> str:
    if not citations:
        return md + "\n\n> ⚠️ Bu raporda otomatik kaynak bağlantısı yakalanmadı; yayından önce kaynakları elle kontrol edin.\n"
    lines = "\n".join(f"- [{title}]({url})" for url, title in citations.items())
    return md + "\n\n### Aramada kullanılan kaynaklar (otomatik liste)\n" + lines + "\n"


def write_report(t, md: str, missing):
    DISCOVERIES_DIR.mkdir(exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DISCOVERIES_DIR / f"{date}-{t['id'].lower()}-{slugify(t['crop'])}.md"
    front = [
        "---",
        f"id: {t['id']}",
        f"date: {date}",
        f"production_system: {t['production_system']}",
        f"crop_group: {t['crop_group']}",
        f"crop: {t['crop']}",
        f"region: {t['region']}",
        f"model: {MODEL}",
        "status: published",
        f"format_check: {'eksik: ' + '; '.join(missing) if missing else 'tam'}",
        "---",
        "",
    ]
    path.write_text("\n".join(front) + md + "\n", encoding="utf-8")
    return path


def extract_title(md: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _field(body, label):
    m = re.search(r"\*\*" + re.escape(label) + r":\*\*\s*(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _ticks(text):
    return re.findall(r"`([^`]+)`", text)


def parse_report(p):
    body = p.read_text(encoding="utf-8")
    meta = {}
    if body.startswith("---"):
        meta = dict(re.findall(r"^(\w+): (.+)$", body.split("---")[1], re.MULTILINE))
    tax = _ticks(_field(body, "Taksonomi"))
    stage = _ticks(_field(body, "Aşama & Çözüm Türü"))
    dec_line = _field(body, "Durum Kararı")
    dec = re.match(r"`?([ABCD])`?\s*[—-]?\s*(.*)", dec_line)
    mat = re.match(r"`([a-z_]+)`\s*[—-]?\s*(.*)", _field(body, "Çözüm olgunluğu"))
    return {
        "id": meta.get("id", p.stem),
        "file": p.name,
        "date": meta.get("date", ""),
        "title": extract_title(body, p.stem),
        "production_system": meta.get("production_system", tax[0] if tax else ""),
        "crop_group": meta.get("crop_group", tax[1] if len(tax) > 1 else ""),
        "crop": meta.get("crop", tax[2] if len(tax) > 2 else ""),
        "region": meta.get("region", ""),
        "stage": stage[0] if stage else "",
        "solution_type": stage[1] if len(stage) > 1 else "",
        "decision": dec.group(1) if dec else "",
        "decision_reason": dec.group(2).strip() if dec else "",
        "finding": _field(body, "Tek cümlede bulgu"),
        "link": _field(body, "Görünmeyen bağlantı"),
        "suggested_by": "",
        "engine": meta.get("engine", "claude"),
        "kind": meta.get("kind", "deep"),
        # Olgunluk kuralından (Kasım 2026) önce üretilen raporlarda alan yoktur: "not_assessed" (yeniden taramada dolar)
        "maturity": mat.group(1) if mat else "not_assessed",
        "maturity_reason": mat.group(2).strip() if mat else "",
        "d_candidate": meta.get("d_candidate", "") == "true",
    }


def parse_report_en(p):
    """İngilizce sürüm (ör. 2026-11-18-trg-006-zeytin.en.md) varsa başlık ve özet alanlarını döndürür."""
    if not p.exists():
        return {}
    body = p.read_text(encoding="utf-8")
    stage = _ticks(_field(body, "Stage & Solution Type"))
    dec = re.match(r"`?([ABCD])`?\s*[—-]?\s*(.*)", _field(body, "Decision"))
    mat = re.match(r"`([a-z_]+)`\s*[—-]?\s*(.*)", _field(body, "Solution maturity"))
    return {"maturity_reason_en": mat.group(2).strip() if mat else "", "file_en": p.name, "title_en": extract_title(body, ""), "finding_en": _field(body, "Finding in one sentence"),
            "link_en": _field(body, "Hidden link"), "decision_reason_en": dec.group(2).strip() if dec else ""}


def rebuild_index():
    reports = []
    for p in sorted(DISCOVERIES_DIR.glob("*.md"), reverse=True):
        if p.name == "README.md" or p.name.endswith(".en.md"):
            continue
        r = parse_report(p)
        r.update(parse_report_en(p.with_name(p.stem + ".en.md")))
        reports.append(r)
    (DISCOVERIES_DIR / "index.json").write_text(
        json.dumps({"generated": datetime.now(timezone.utc).isoformat(), "reports": reports},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = [f"| {r['date']} | [{r['title']}]({r['file']}) | {r['crop']} | {r['region']} | {r['decision'] or '?'} | {r['maturity']} | {'Otomatik tarama' if r['kind'] == 'auto' else 'Derin rapor'} |"
            for r in reports]
    INDEX_FILE.write_text(
        "# AgriGap Raporları\n\n"
        "Uygulama: https://agrihubai.github.io/agrigap/\n\n"
        "Otomatik taramalar OpenAlex yayın kayıtlarından yapay zekâ kullanılmadan, sabit kurallarla üretilir; "
        "derin raporlar Claude ile yazılmıştır. Hiçbiri insan tarafından doğrulanmaz.\n"
        "Durum kararı: **A** çözüm var ve yaygın · **B** çözüm başka yerde var · "
        "**C** çözüm var ama zayıf · **D** taranan kaynaklarda çok az yayın (çözüm durumu belirsiz; olgunluk sütununa bakın).\n\n"
        "| Tarih | Rapor | Ürün | Bölge | Durum | Olgunluk | Tür |\n|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def set_output(key, value):
    """GitHub Actions adımları arasında değer aktarır."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Belirli bir hedef kimliği (ör. TRG-002)")
    ap.add_argument("--exclude", default="", help="Atlanacak hedefler, virgülle (incelemede bekleyen PR'lar)")
    ap.add_argument("--from-file", help="Hazır Markdown raporu arşive ekle (API çağrısı yok)")
    ap.add_argument("--reindex", action="store_true", help="Yalnızca discoveries/index.json ve README dizinini yeniden üret")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = load_targets()
    if args.reindex:
        rebuild_index()
        print("[OK] Dizin yenilendi")
        return 0

    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    t = pick_target(targets, args.id, exclude)
    if not t:
        print("İşlenecek hedef yok. core/targets.json dosyasına 'pending' hedef ekleyin.")
        set_output("created", "false")
        return 0

    query = build_query(t)
    print(f"İşleniyor: {t['id']} — {query}")
    if args.dry_run:
        return 0

    if args.from_file:
        md, citations = Path(args.from_file).read_text(encoding="utf-8"), {}
        md = strip_preamble(md)
        global MODEL
        MODEL = "claude.ai (sohbet)"
        return finalize(t, targets, md, citations)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY yok. Ücretsiz akış: raporu Claude.ai'de hazırlayıp --from-file ile ekleyin.")
        set_output("created", "false")
        return 0

    try:
        md, citations = run_claude(PROMPT_FILE.read_text(encoding="utf-8"), query)
    except Exception as e:  # hedef kuyrukta kalsın, hata kaydedilsin
        t["status"] = "failed"
        t["last_error"] = f"{type(e).__name__}: {e}"[:500]
        t["processed_at"] = datetime.now(timezone.utc).isoformat()
        save_targets(targets)
        print(f"[HATA] {t['last_error']}", file=sys.stderr)
        set_output("created", "false")
        return 1

    return finalize(t, targets, append_citations(strip_preamble(md), citations), citations)


MAX_SUGGESTIONS = 2


def _norm(x):
    return re.sub(r"\s+", " ", x.strip().lower())


def queue_suggestions(md, targets, source_id):
    """Rapordaki '## 9. Yeni Hedef Önerileri' satırlarını kuyruğa ekler (kendini besleme)."""
    sec = md.split("## 9. Yeni Hedef Önerileri", 1)
    if len(sec) < 2:
        return []
    added = []
    seen = {(_norm(t["crop"]), _norm(t["focus"])) for t in targets}
    nmax = max([int(t["id"].split("-")[1]) for t in targets if t["id"].startswith("TRG-")] or [0])
    for line in re.findall(r"^-\s*`([^`]+)`", sec[1], re.MULTILINE):
        parts = [x.strip() for x in line.split("|")]
        if len(parts) != 5 or not all(parts):
            continue
        ps, cg, crop, region, focus = parts
        if (_norm(crop), _norm(focus)) in seen:
            continue
        nmax += 1
        nt = {"id": f"TRG-{nmax:03d}", "production_system": ps, "crop_group": cg, "crop": crop,
              "region": region, "focus": focus, "status": "pending", "suggested_by": source_id}
        targets.append(nt)
        seen.add((_norm(crop), _norm(focus)))
        added.append(nt["id"])
        if len(added) >= MAX_SUGGESTIONS:
            break
    return added


def finalize(t, targets, md, citations):
    missing = quality_check(md)
    path = write_report(t, md, missing)
    rebuild_index()

    t["status"] = "published"
    t["report"] = str(path.relative_to(ROOT))
    added = queue_suggestions(md, targets, t["id"])
    if added:
        print(f"[KUYRUK] Yeni hedefler eklendi: {', '.join(added)}")
    t["processed_at"] = datetime.now(timezone.utc).isoformat()
    t.pop("last_error", None)
    save_targets(targets)

    title = extract_title(md, f"{t['crop']} raporu")
    print(f"[OK] {path.relative_to(ROOT)} — {len(citations)} kaynak bağlantısı")
    if missing:
        print(f"[UYARI] Eksik bölümler: {', '.join(missing)}")
    set_output("created", "true")
    set_output("target_id", t["id"])
    set_output("report", str(path.relative_to(ROOT)))
    set_output("title", title.replace("\n", " "))
    set_output("missing", ", ".join(missing) or "yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
