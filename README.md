# AgriGap

**An open-access hub that scans bottlenecks in Turkish & European farming on a schedule, by itself: it maps solutions already published worldwide first and shows the links that look unrelated at first sight.**

*Türkiye ve Avrupa tarımındaki darboğazları düzenli aralıklarla kendiliğinden tarayan, açık erişimli ve ücretsiz bir sorun tespit merkezi. Her sorun için önce dünyada yayımlanmış çözümleri haritalar, ilk bakışta ilgisiz görünen bağlantıları gösterir ve yeni konular önerir. Bir [AgriHub-AI](https://agrihubai.wordpress.com/) projesidir.*

🌱 **Uygulama:** https://agrihubai.github.io/agrigap/ · 📚 **Raporlar:** [`discoveries/`](discoveries/README.md) · ✍️ **Blog:** https://agrihubai.wordpress.com/

## Nasıl çalışır?

Her Pazartesi, Çarşamba ve Cuma GitHub Actions kendiliğinden başlar, Teknoloji Boşluk Haritası'nda 12 ürünü yeniler ve kuyruktaki sıradaki 3 hedefi tarar ([`agrigap-tarama.yml`](.github/workflows/agrigap-tarama.yml)):

1. `core/targets.json` kuyruğundaki sıradaki `pending` hedefleri alır.
2. [OpenAlex](https://openalex.org)'ten (açık, CC0 lisanslı yayın veri tabanı) üç sorgu çalıştırır: konu (dünya), konu (hedef bölge) ve karşılaştırma için ürünün genel literatürü.
3. [`scripts/source_scan.py`](scripts/source_scan.py), [`core/scan_rules.json`](core/scan_rules.json) kural sözlüğüyle raporu üretir. **Yapay zekâ kullanılmaz;** her sayı yayın kayıtlarının sayımıdır:
   - **Mevcut Çözüm Haritası:** yayınlar çözüm türüne göre gruplanır (makine, biyolojik mücadele, enzim, kompost, enerji, ıslah…): kaç yayın, hangi ülkeler, hangi yıllar, örnek çalışmalar ve hedef bölgede örneği olmayan çözüm türleri.
   - **Görünmeyen Bağlantılar:** sorguda geçmeyen ama aynı yayınlarda birlikte geçen alanlar (hastalık, su, enerji, işçilik, taşıma, mevzuat, pazar, iklim…). Ürünün genel literatürüyle karşılaştırılır; bu konuya özgü biçimde sık geçen alan öne çıkar.
   - **Boşluk ölçeği (A–D):** yayın sayılarına dayalı kaba gösterge (kural raporda yazılıdır).
4. **Kendini besleme:** En güçlü bağlantı alanı eşiği geçerse kuyruğa en fazla 1 yeni hedef ekler (`suggested_by`).
5. Raporu `discoveries/` altına yazar, `main` dalına yükler; site kendiliğinden güncellenir.

Elle başlatmak için: **Actions → AgriGap Otomatik Tarama → Run workflow** (isteğe bağlı hedef kimliğiyle).

### Teknoloji Boşluk Haritası

Uygulamanın ikinci sekmesi. 48 ürün × 18 iş adımı (toprak işlemeden hasada, depolamadan stok ve maliyet takibine) tablosunun her hücresi için iki katmanda yayın sayar: **makine & donanım** ve **yazılım & yapay zekâ**. Sayılar yazar ülkesine göre bölünür (dünya, Türkiye, İspanya, AB). Mor hücreler dünyada neredeyse hiç çalışılmamış konuları, sarı hücreler dünyada çalışılmış ama seçilen bölgede yayını olmayan (aktarım adayı) konuları gösterir.

- Ayarlar: [`core/matrix_config.json`](core/matrix_config.json) (ürünler, iş adımları, katman terimleri). Ürün listesi [Halden Anlayan](https://agrihubai.github.io/halden-anlayan/) ürünlerinden ve tarla/bahçe bitkilerinden seçildi.
- Her çalışmada 12 ürün yenilenir (kayan güncelleme). İş akışı her gün çalışır: rapor olmayan günlerde yalnızca hiç taranmamış ürünler doldurulur, harita tamamlanınca bu günlerde hiçbir şey yapılmaz. Veri: `matrix/matrix.json`.
- **Kendini besleme:** dünyada en az 50 yayını olup Türkiye'den hiç yayını olmayan en güçlü hücre ayrıntılı tarama kuyruğuna eklenir.
- Ayrıntılı raporlardaki **Zorluk Sinyalleri** bölümü, yayınlarda sık geçen engelleri (eğim, ürün hasarı, görüş engeli, dar alan, maliyet, enerji…) listeler: yeni bir makine, yazılım ya da uygulama için tasarım gerekliliği adayları.

### Yeni Öneriler (Sekme 2)

**Aşama 1, kural tabanlı aday bulma (çalışıyor, yapay zekâsız):** [`scripts/ideas.py`](scripts/ideas.py) haritadan dört tür aday çıkarır ve `ideas/candidates.json` dosyasına yazar:
- **Aktarım:** dünyada çok çalışılmış, Türkiye'den yayını olmayan ya da çok az olan konular.
- **Komşu üründen aktarım:** bir iş adımı, ürünün kendi literatür büyüklüğüne göre aynı gruptaki ürünlerden belirgin biçimde az çalışılmışsa.
- **Katman değişimi:** aynı işte makine ile yazılım/yapay zekâ arasında büyük fark varsa.
- **Gerçek boşluk:** dünyada neredeyse hiç yayın yoksa ama iş adımı aynı gruptaki ürünlerde çalışılıyorsa.

Her adaya ilgili mevzuat ve varsa ayrıntılı tarama bağlanır.

**Aşama 2, öneri kartları (planlandı):** Ücretsiz bir yapay zekâ en güçlü 2 aday için yalnızca verilen kaynaklardan öneri kartı yazacak (makine, yazılım/yapay zekâ, uygulama/yöntem, biyolojik girdi/enzim, iş modeli). Ardından otomatik kaynak ve yenilik kontrolünden geçecek; ikinci bir ücretsiz yapay zekânın denetimi ayrıca planlanıyor.

### Mevzuat listesi

[`core/regulations.json`](core/regulations.json): Türkiye ve AB'nin 2026–2030 döneminde tarımı etkileyen kuralları. Her madde kaynaklarıyla birlikte ve doğrulama tarihiyle yer alır; uygulamada **Mevzuat listesi** düğmesinden görülür. Hukuki tavsiye değildir.

### Dil

Arayüz Türkçe ve İngilizcedir. Otomatik raporlar iki dilde üretilir (`*.md` ve `*.en.md`); derin raporlar (ör. TRG-002) yalnızca Türkçedir ve uygulamada bu şekilde işaretlenir.

### Rapor türleri

| Tür | Nasıl üretilir | Ne söyler, ne söylemez |
|---|---|---|
| **Otomatik tarama** | OpenAlex + sabit kurallar, yapay zekâsız | Nerede, ne kadar, kim çalışmış. Avantaj/dezavantaj, maliyet ve sahadaki yaygınlık yazmaz. |
| **Derin rapor** | Claude ile web kaynakları okunarak (ör. TRG-002) | Mekanizma, avantaj/dezavantaj, öneri ve doğrulama deneyi. |

Hiçbir rapor insan tarafından doğrulanmaz ve sahada denenmez.

### Maliyet

| Bileşen | Ücret |
|---|---|
| GitHub repo, Actions (public repo), Pages | Ücretsiz |
| OpenAlex API | Ücretsiz günlük kota (anahtarsız da çalışır; ücretsiz anahtarla kota 10 katına çıkar). Çalışma başına yaklaşık 450 sorgu (harita 432, raporlar 15); ücretsiz günlük kota yaklaşık 1.000 aramadır. Kota dolarsa o gün tarama yapılmaz, ücret çıkmaz. |
| Yapay zekâ | Kullanılmıyor |

İsteğe bağlı: openalex.org'da ücretsiz hesap açıp anahtarı **Settings → Secrets and variables → Actions** altına `OPENALEX_API_KEY` adıyla ekleyin.

`agrigap-scan.yml` (Claude API) ücretli olduğu için kapalıdır; zamanlayıcısı yoktur ve anahtar olmadan hiçbir şey yapmaz.

## Hedef ekleme

`core/targets.json` dosyasına yeni bir nesne ekleyin. `query`, OpenAlex için İngilizce arama sorgusudur (`AND`, `OR`, tırnaklı ifade kullanılabilir):

```json
{
  "id": "TRG-0XX",
  "production_system": "Örtü Altı Yetiştiriciliği",
  "crop_group": "Sebzeler",
  "crop": "Domates",
  "crop_en": "tomato",
  "stage": "Yetiştirme & Bitki Koruma",
  "region": "TR+EU",
  "focus": "Sorunun Türkçe tanımı",
  "query": "tomato AND greenhouse AND (\"biological control\" OR robot)",
  "status": "pending"
}
```

Çözüm türü veya bağlantı alanı eklemek için `core/scan_rules.json` dosyasını düzenleyin.

## Sınırlar

- Sayılar yayın sayısıdır; bir çözümün sahada ne kadar kullanıldığını, ne kadar işe yaradığını veya maliyetini göstermez.
- Türkçe yayınlar OpenAlex'te kısmen yer alır; Türkiye'deki çalışmalar eksik sayılabilir.
- Patent, mevzuat metni ve haber taranmaz.
- Terim eşleştirmesi kaba bir yöntemdir; bir yayın yanlış çözüm türüne düşebilir.

## Lisans

- **Kod** (`scripts/`, `.github/`, `index.html`): [MIT](LICENSE)
- **Raporlar ve talimatlar** (`discoveries/`, `core/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.tr). Kaynak gösterilerek paylaşılabilir ve uyarlanabilir. Yayın verisi: OpenAlex (CC0).
