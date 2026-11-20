# AgriGap

**An open-access hub that scans bottlenecks in Turkish & European farming on a schedule, by itself: it maps solutions already published worldwide first and shows the links that look unrelated at first sight.**

*Türkiye ve Avrupa tarımındaki darboğazları düzenli aralıklarla kendiliğinden tarayan, açık erişimli ve ücretsiz bir sorun tespit merkezi. Her sorun için önce dünyada yayımlanmış çözümleri haritalar, ilk bakışta ilgisiz görünen bağlantıları gösterir ve yeni konular önerir. Bir [AgriHub-AI](https://agrihubai.wordpress.com/) projesidir.*

🌱 **Uygulama:** https://agrihubai.github.io/agrigap/ · 📚 **Raporlar:** [`discoveries/`](discoveries/README.md) · ✍️ **Blog:** https://agrihubai.wordpress.com/

## Nasıl çalışır?

Her Pazartesi, Çarşamba ve Cuma GitHub Actions kendiliğinden başlar, Teknoloji Boşluk Haritası'nda 10 ürünü yeniler ve kuyruktaki sıradaki 3 hedefi tarar ([`agrigap-tarama.yml`](.github/workflows/agrigap-tarama.yml)):

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
- Her çalışmada 10 ürün yenilenir (kayan güncelleme). İş akışı her gece çalışır (00:13–06:13 UTC arası saat başı denenir, günde yalnız bir kez tarar; sabah site günceldir): rapor olmayan günlerde yalnızca hiç taranmamış ya da eski yöntemle sayılmış ürünler doldurulur, harita tamamlanınca bu günlerde hiçbir şey yapılmaz. Veri: `matrix/matrix.json`.
- **Kendini besleme:** dünyada en az 50 yayını olup Türkiye'den hiç yayını olmayan en güçlü hücre ayrıntılı tarama kuyruğuna eklenir.
- Ayrıntılı raporlardaki **Zorluk Sinyalleri** bölümü, yayınlarda sık geçen engelleri (eğim, ürün hasarı, görüş engeli, dar alan, maliyet, enerji…) listeler: yeni bir makine, yazılım ya da uygulama için tasarım gerekliliği adayları.

### Yeni Öneriler (Sekme 2)

**Aşama 1, kural tabanlı aday bulma (çalışıyor, yapay zekâsız):** [`scripts/ideas.py`](scripts/ideas.py) haritadan dört tür aday çıkarır ve `ideas/candidates.json` dosyasına yazar:
- **Aktarım:** dünyada çok çalışılmış, Türkiye'den yayını olmayan ya da çok az olan konular.
- **Komşu üründen aktarım:** bir iş adımı, ürünün kendi literatür büyüklüğüne göre aynı gruptaki ürünlerden belirgin biçimde az çalışılmışsa.
- **Katman değişimi:** aynı işte makine ile yazılım/yapay zekâ arasında büyük fark varsa.
- **Gerçek boşluk:** dünyada neredeyse hiç yayın yoksa ama iş adımı aynı gruptaki ürünlerde çalışılıyorsa.

Her adaya ilgili mevzuat ve varsa ayrıntılı tarama bağlanır.

**Aşama 2, öneri kartları (katmanlı):** Her kart `ideas/cards/<id>.json` dosyasında katman katman büyür.
- **Katman 1, yazar ([`scripts/idea_cards.py`](scripts/idea_cards.py)):** Gemini'nin ücretsiz katmanı (`GEMINI_API_KEY` secret'ı) her çalışmada en güçlü 2 aday için kart yazar. Kaynak olarak yalnızca OpenAlex'ten çekilen kaynak paketini (en ilgili 15 yayın), zorluk sinyallerini ve mevzuat listesini kullanır. Kart, Türkçe ve İngilizce olarak şu sırayı izler: sorun, mevcut çözümler (avantaj/dezavantaj), 2–3 öneri, etki varsayımları, mevzuat uyumu, çöküş riski, en küçük deney ve Güçlü/Orta/Zayıf değerlendirmesi. Öneri türleri: makine, yazılım/yapay zekâ, uygulama/yöntem, biyolojik girdi/enzim, iş modeli.
- **Otomatik kontroller (yapay zekâsız):** pakette olmayan bir DOI ya da kaynaksız bir sayı/yüzde varsa kart reddedilir ve yayınlanmaz. "Bu iş bu ürün için anlamsız" denen adaylar elenir. Yenilik kontrolünde önerinin anahtar kelimeleri OpenAlex'te aranır.
- **Katman 2, denetçi (planlandı):** ikinci, bağımsız bir ücretsiz yapay zekâ.

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
| OpenAlex API | Ücretsiz günlük kota (anahtarsız da çalışır; ücretsiz anahtarla kota 10 katına çıkar). Çalışma başına yaklaşık 735 sorgu (harita 10 ürün × 72: her hücre için bir sayım ve bir Türkçe yayın sorgusu; raporlar 15). 20 Kasım 2026'da günde yaklaşık 1.000 sorgudan sonra HTTP 429 (kota) alındı; çalışma başına ürün sayısı bu yüzden 10. Kota dolarsa o gün tarama yapılmaz, ücret çıkmaz. |
| Yapay zekâ | Kullanılmıyor |

İsteğe bağlı: openalex.org'da ücretsiz hesap açıp anahtarı **Settings → Secrets and variables → Actions** altına `OPENALEX_API_KEY` adıyla ekleyin.

Ücretli Claude API iş akışı (`agrigap-scan.yml`) 20 Kasım 2026'da kaldırıldı: bu depo yalnızca ücretsiz servislerle çalışır.

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

### Sayım yöntemi (v2, 20 Kasım 2026)
- Belge türü: makale, derleme ve konferans bildirisi. Tıp, hemşirelik, diş hekimliği ve sağlık meslekleri alanları dışlanır ("robotic flap harvest" gibi cerrahi yayınlar hasat sayımına karışıyordu).
- Belirsiz terimler daraltıldı: incir ("fig", şekil kısaltmasıyla karışıyordu), narenciye ("orange" renk anlamıyla karışıyordu). Hasat sütunundan "energy harvesting" ve "pick and place" dışlanır.
- Türkiye sayısı: Türkiye adresli yayınlar + yazar ülkesi kayıtsız Türkçe yayınlar. Denetimde OpenAlex'teki Tarım Makinaları Bilimi Dergisi yayınlarının 485'inden 390'ında yazar ülkesi kayıtsız çıktı.
- Google Scholar kullanılmaz: resmî bir veri arayüzü yoktur ve otomatik taramayı kullanım koşullarıyla yasaklar. Scopus, Web of Science ve CAB Abstracts abonelikle çalışır.
- Denetim: `scripts/audit_coverage.py` (Actions → AgriGap Kapsam Denetimi, elle).
