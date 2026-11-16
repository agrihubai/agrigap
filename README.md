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

🌱 **Uygulama:** https://agrihubai.github.io/agrigap/ · 📚 **Raporlar:** [`discoveries/`](discoveries/README.md) · ✍️ **Blog:** https://agrihubai.wordpress.com/

## Nasıl çalışır?

### Varsayılan akış (ücretsiz): Claude.ai sohbeti

1. Claude.ai sohbetinde `AGRIHUB SCAN: TRG-00X` komutu verilir.
2. Claude, `core/system_prompt.md` talimatıyla web araması yaparak raporu hazırlar ve `main` dalına yükler (`python scripts/hub_engine.py --id TRG-00X --from-file rapor.md`).
3. Rapor uygulamada **"Uzman incelemesinde"** rozetiyle görünür.
4. Uzman raporu okur; düzeltmeleri sohbette iletir. Onaylanınca `review_status: published` yapılır ve rozet **"Uzman onaylı"** olur.

Bu akışta API anahtarı gerekmez; ek maliyet yoktur.

### Uygulama (GitHub Pages)

`index.html` tek sayfalık uygulamadır; `discoveries/index.json` dosyasını okur ve raporları `discoveries/*.md` dosyalarından gösterir. Dizin her rapor eklendiğinde kendiliğinden güncellenir; elle yenilemek için `python scripts/hub_engine.py --reindex`.

Yayına almak için bir kez: Settings → Pages → *Build and deployment* → Source: **Deploy from a branch** → Branch: **main** / **(root)** → Save.

### İsteğe bağlı akış (ücretli): Claude API

`.github/workflows/agrigap-scan.yml` aynı taramayı GitHub sunucularında Claude API ile yapar. **Claude API, Claude.ai aboneliğinden ayrı ve kullandıkça ücretlendirilen bir hizmettir.** Varsayılan olarak kapalıdır: zamanlayıcı yoktur ve `ANTHROPIC_API_KEY` secret'ı tanımlı değilse iş akışı hiçbir şey yapmadan biter.

Etkinleştirmek için: `ANTHROPIC_API_KEY` secret'ını ekleyin, Settings → Actions → General altında "Allow GitHub Actions to create and approve pull requests" seçeneğini açın, Actions → *AgriGap Tarama* → *Run workflow*. Zamanlayıcıyı açma talimatı iş akışı dosyasının başındadır.

### Maliyet özeti

| Bileşen | Ücret |
|---|---|
| GitHub repo, Actions (public repo), Pull Request'ler | Ücretsiz |
| Claude.ai sohbetinde tarama | Mevcut abonelik kapsamında |
| Claude API ile otomatik tarama | **Ücretli** (isteğe bağlı, varsayılan kapalı) |

## Hedef ekleme

`core/targets.json` dosyasına yeni bir nesne ekleyin (`status: "pending"`). Durumlar: `pending` → `review` (rapor PR'da) → elle `published` yapılabilir.

## Sınırlar

- Model patent veri tabanlarına doğrudan erişemez; patent hakkında yalnızca aramada bulunan yayımlanmış belgelerden söz eder.
- Maliyet, verim ve amorti süresi yalnızca kaynaklıysa sayı olarak verilir; aksi hâlde varsayımlar yazılır.
- Her rapor saha doğrulaması yapılmamış bir hipotez setidir.

## Lisans

- **Kod** (`scripts/`, `.github/`): [MIT](LICENSE)
- **Raporlar ve talimatlar** (`discoveries/`, `core/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.tr) — kaynak gösterilerek paylaşılabilir ve uyarlanabilir.
