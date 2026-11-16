# AgriGap

**An open-access, self-running AI hub that finds the gaps in Turkish & European farming: it maps existing solutions worldwide first and proposes new ones only where none exist.**

*Açık erişimli, yapay zekâ destekli ve kendi kendine çalışan bir sorun tespit ve çözüm önerisi merkezi. Türkiye ve Avrupa tarımındaki darboğazlar için önce dünyada var olan çözümleri haritalar, yenisini yalnızca çözüm yoksa önerir. Bir [AgriHub-AI](https://agrihubai.wordpress.com/) projesidir.*

Türkiye ve Avrupa tarımında belirli bir üretim sistemi ve ürün için:

1. Çözülmemiş üretim darboğazlarını ve 2026–2030 mevzuat baskılarını bulur,
2. **Önce dünyada var olan çözümleri haritalar** (nerede, nasıl, avantaj/dezavantaj, ölçülmüş etkinlik),
3. Her sorunu bir **durum kararına** bağlar:
   - **A** — çözüm var ve yaygın → etkinlik ölçümü önerilir
   - **B** — çözüm başka coğrafyada/üründe var → transfer önerisi
   - **C** — çözüm var ama zayıf → daha iyi varyant
   - **D** — taranan kaynaklarda çözüm yok → icat hipotezi
4. Lider öneri için ucuz bir doğrulama deneyi tasarlar.

Raporlar yapay zekâ tarafından web araması ile **otomatik** hazırlanır; insan tarafından doğrulanmaz ve sahada denenmez. Her iddianın kaynağı raporun sonundadır.

**Kendini besleme:** Her rapor, taramada karşılaştığı en fazla 2 yeni darboğazı önerir; motor bunları `core/targets.json` kuyruğuna ekler (`suggested_by` alanı).

🌱 **Uygulama:** https://agrihubai.github.io/agrigap/ · 📚 **Raporlar:** [`discoveries/`](discoveries/README.md) · ✍️ **Blog:** https://agrihubai.wordpress.com/

## Nasıl çalışır?

### Varsayılan akış (ücretsiz): Claude zamanlanmış görevi

1. Claude.ai'de tanımlı bir zamanlanmış görev, belirli günlerde kendiliğinden başlar.
2. Kuyruktaki sıradaki `pending` hedefi alır, `core/system_prompt.md` talimatıyla web araması yaparak raporu hazırlar.
3. `python scripts/hub_engine.py --id TRG-00X --from-file rapor.md` ile arşive ekler; motor rapordaki yeni hedef önerilerini kuyruğa yazar ve dizini yeniler.
4. `main` dalına yükler; rapor sitede yayınlanır.

İstenirse aynı tarama sohbette `AGRIHUB SCAN: TRG-00X` komutuyla elle de başlatılabilir. API anahtarı gerekmez.

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
