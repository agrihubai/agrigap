# AgriGap

**Finds the gaps in Turkish & European farming: maps existing solutions worldwide first, proposes new ones only where none exist. AI-assisted, expert-reviewed.**

*Türkiye ve Avrupa tarımındaki boşlukları bulur: önce dünyada var olan çözümleri haritalar, yenisini yalnızca çözüm yoksa önerir. Yapay zekâ destekli, uzman denetimli. Bir [AgriHub-AI](https://agrihubai.wordpress.com/) projesidir.*

Türkiye ve Avrupa tarımında belirli bir üretim sistemi ve ürün için:

1. Çözülmemiş üretim darboğazlarını ve 2026–2030 mevzuat baskılarını bulur,
2. **Önce dünyada var olan çözümleri haritalar** (nerede, nasıl, avantaj/dezavantaj, ölçülmüş etkinlik),
3. Her sorunu bir **durum kararına** bağlar:
   - **A** — çözüm var ve yaygın → etkinlik ölçümü önerilir
   - **B** — çözüm başka coğrafyada/üründe var → transfer önerisi
   - **C** — çözüm var ama zayıf → daha iyi varyant
   - **D** — taranan kaynaklarda çözüm yok → icat hipotezi
4. Lider öneri için ucuz bir doğrulama deneyi tasarlar.

Raporlar yapay zekâ (Claude API + web araması) ile hazırlanan **ön analizlerdir** ve uzman incelemesinden geçmeden yayınlanmaz.

📚 **Raporlar:** [`discoveries/`](discoveries/README.md) · ✍️ **Blog:** https://agrihubai.wordpress.com/

## Nasıl çalışır?

```
core/targets.json  ──►  scripts/hub_engine.py  ──►  discoveries/<tarih>-<id>-<ürün>.md
 (hedef kuyruğu)         (Claude + web araması)       + discoveries/README.md (dizin)
                                   │
                                   ▼
                    GitHub Actions bir Pull Request açar
                    (dal: scan/<hedef-id>, kontrol listesiyle)
                                   │
                    Uzman inceler → düzeltir → birleştirir = YAYIN
```

İncelemede bekleyen bir hedef için yeni PR açılmaz; sıradaki hedefe geçilir.

## Kurulum

1. **Secret:** Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY`
2. **PR izni:** Settings → Actions → General → *Workflow permissions* → "Allow GitHub Actions to create and approve pull requests" kutusunu işaretleyin.
3. **İlk deneme:** Actions → *AgriGap Tarama* → *Run workflow* (isterseniz `target_id` olarak `TRG-002` yazın).
4. Zamanlayıcı Pazartesi ve Perşembe sabahı çalışır; kapatmak için `.github/workflows/agrigap-scan.yml` içindeki `schedule` bloğunu silin.

### Yerel çalıştırma

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python scripts/hub_engine.py --dry-run        # yalnızca sorguyu gösterir
python scripts/hub_engine.py --id TRG-002     # tek hedef
```

İsteğe bağlı ortam değişkenleri: `AGRIHUB_MODEL` (varsayılan `claude-sonnet-5-5`), `AGRIHUB_MAX_TOKENS` (16000), `AGRIHUB_MAX_SEARCHES` (15).

## Hedef ekleme

`core/targets.json` dosyasına yeni bir nesne ekleyin (`status: "pending"`). Durumlar: `pending` → `review` (rapor PR'da) → elle `published` yapılabilir. Hata durumunda iş başarısız olur ve hedef kuyrukta kalır.

## Sınırlar

- Model patent veri tabanlarına doğrudan erişemez; patent hakkında yalnızca aramada bulunan yayımlanmış belgelerden söz eder.
- Maliyet, verim ve amorti süresi yalnızca kaynaklıysa sayı olarak verilir; aksi hâlde varsayımlar yazılır.
- Her rapor saha doğrulaması yapılmamış bir hipotez setidir.

## Lisans

- **Kod** (`scripts/`, `.github/`): [MIT](LICENSE)
- **Raporlar ve talimatlar** (`discoveries/`, `core/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.tr) — kaynak gösterilerek paylaşılabilir ve uyarlanabilir.
