# Sözleşme: Asistan çıktı şeması ve deterministik son işlem

Kaynak: plan §7.2–7.3. Dosyalar (Şerit A): `rules/schemas/assistant.schema.json` ve
`rules/schemas/assistant_deep.schema.json` — **birebir aynı içerik** (eşitlik testi). Prompt paketi
`rules/prompts/assistant.md` (iki amaç da `bundle="assistant"`).

## Şema (mantıksal görünüm)

```json
{
  "cevap_bloklari": [{"tur": "baslik|paragraf|liste|kod", "metin": "string", "maddeler": ["string"]}],
  "guven": "yuksek|orta|dusuk",
  "kaynaklar": [{"tur": "urun_kodu|uygulama_kodu|uygulama_verisi|probe_verisi|jira|ci_log|dokuman|genel_bilgi",
                 "ref": "string", "alinti": "string"}],
  "yonlendirmeler": [{"etiket": "string", "rota": "string"}],
  "jira_anahtarlari": ["string"],
  "eylem_reddi": "boolean",
  "oneriler": [{"baslik": "string", "neden": "string",
                "eylem": {"tur": "rota|jira_taslak|jira_yorum|jira_kaydi|bilgi",
                          "rota": "anyOf[string, null]",
                          "anahtar": "anyOf[string, null]",
                          "taslak": "anyOf[{tur: Task|Bug|Story|yorum, ozet, aciklama}, null]"}}]
}
```

## Biçim kuralları (`test_schema_compat`)

- Her nesne `additionalProperties: false`; **tüm alanlar `required`**.
- "Yok" değeri **yalnız** `anyOf: [{type: string}, {type: null}]` / `anyOf: [{obje}, {type: null}]`.
  Tip dizisi (`["string","null"]`) **yasak** (`transform_schema`'yı çökertir; Şerit A şema testine
  "tip dizisi yok" kuralı eklenir).
- Uzunluk/adet sınırları (`maxLength`, `maxItems`) şemada **yok**; son işlemde deterministik kırpılır
  (aşım geçit doğrulamasında yeniden istemeye ve maliyete yol açmasın).
- `oneriler` her cevapta zorunlu dizi: soru kipinde `[]`, öneri kipinde ≤ 3 (kırpma son işlemde).
- Golden'lar (`rules/replay/assistant{,_deep}/golden/ornek.json`) `oneriler: []` içerir.

## Tek eylem sözleşmesi (kural kartı = model kartı)

| `eylem.tur` | Zorunlu | Anlam |
|---|---|---|
| `rota` | `rota` (iç rota) | portal ekranına "Git" |
| `jira_taslak` | `taslak` (`tur` ∈ Task\|Bug\|Story) | yeni kayıt taslağı; `anahtar` ilgili kayıt (bilinmiyorsa null) |
| `jira_yorum` | `anahtar` (bilinen), `taslak.tur = yorum` | mevcut kayda yorum taslağı |
| `jira_kaydi` | `anahtar` (bilinen) | kaydı aç; taslak yok |
| `bilgi` | — | yalnız metin |

## `ref` biçimi

| `kaynaklar[].tur` | `ref` |
|---|---|
| `urun_kodu`, `dokuman` | `yol:satır` veya `yol:başlangıç-bitiş` (MANIFEST yolu) |
| `uygulama_kodu` | `yol:satır` (forge yolu, aynı sha) |
| `uygulama_verisi`, `probe_verisi`, `jira`, `ci_log` | kanıt havuzu kimliği `kN` (araç sonucunun başındaki `[kanit:kN]`) |
| `genel_bilgi` | boş |

## Son işlem (worker; saklamadan ve göstermeden önce)

1. **Metin**: URL ve `![..](..)` / `[..](..)` kalıpları düz metne; toplam 6000 karakterde kırpma;
   Markdown yok.
2. **Linkler**: yalnız (a) `yonlendirmeler[].rota` — `rules/assistant/rotalar.json` kalıbına uyan iç
   rota; (b) `jira_anahtarlari` — `^[A-Z][A-Z0-9]+-\d+$` **ve** Testing Probe'da kaydı olan anahtar,
   bağlantıyı sunucu `RestJira.issue_url` / `JIRA_BROWSE_URL` ile kurar. Başka dış link yok.
3. **Kaynak doğrulama**:
   - `urun_kodu`/`dokuman`: MANIFEST'te dosya, satır aralıkta, `alinti` satırda (boşluk normalize).
   - `uygulama_kodu`: aynı sha'da `forge.read_file` ile aynı kontrol.
   - `uygulama_verisi`: havuzdaki (yalnız `sqlguard`'dan geçmiş) SQL yeniden çalıştırılır (≤ 5 kaynak,
     `bitis` içinde), `digest_matches_any` ile havuzdaki `result_digest` karşılaştırılır; zaman aşımı →
     "doğrulanmadı".
   - `probe_verisi`, `jira`, `ci_log`: `kN`'nin türü kaynak türüyle uyuşmalı; `alinti`, havuzdaki metnin
     aynı oturumla maskesi açılmış hâlinde geçmeli (yalnız bellekte); uzunluk sınırı yok.
   - Doğrulanmayan kaynak silinmez, `dogrulandi=false`.
4. **Öneri eylemleri**: rota kalıp dışıysa → `bilgi`; `jira_taslak` metinleri düz metne, URL'ler
   "[bağlantı kaldırıldı]", Jira wiki bağlantı (`[..|..]`) ve mention (`[~accountid:..]`, `@..`)
   temizlenir; proje daima sunucudaki `JIRA_PROJECT`; bilinmeyen `anahtar` → null (`jira_yorum`/
   `jira_kaydi` için eylem `bilgi`'ye düşer); > 3 kırpılır; kural önerisiyle aynı başlık (normalize)
   atılır.
5. **Güven gösterimi**:

| Gösterilen | Koşul |
|---|---|
| `Kaynakla doğrulandı` | ≥ 1 doğrulanmış kaynak **ve** `guven ∈ {yuksek, orta}` |
| `Kısmen` | doğrulanmış kaynak var ama `guven = dusuk`; **veya** ürüne özgü soruda yalnız `genel_bilgi` |
| `Emin değil` | ürüne özgü soruda doğrulanmış kaynak yok; **veya** toparlama ile bitti |
| `Genel bilgi` | ürüne özgü olmayan soruda `genel_bilgi` |

**Ürüne özgü soru** (deterministik): bağlamda varlık/rota (ana sayfa dışı) **veya** soruda
`[A-Z]+-\d+` / `rules/assistant/urun-terimleri.yaml` eşleşmesi **veya** model bir ürün/probe/uygulama
aracı çağırdı.

6. Müşteri verisi kurulumunda cevap saklanmadan önce aynı oturumla yeniden maskelenir; her kaynağın
   sonuç sha256'sı `asistan_mesaj.cevap.dogrulama`'ya yazılır.

## Saklanan `asistan_mesaj.cevap` biçimi

Şema çıktısı (son işlenmiş) + `{"guven_gosterimi": "...", "dogrulama": {"<ref>": {"dogrulandi":
bool, "sha256": "..."}}, "urune_ozgu": bool, "toparlama": bool}`. Portal yalnız bu nesneyi çizer
(HTML yok, blok render).

Spec 013 ekleri: `sinyaller` (girdi niyet sinyali kimlikleri; yalnız DB'de, `mesaj_ozeti` istemciye
döndürmez), `model` (cevabı üreten amaç modeli; portal kip rozeti önce bunu kullanır) ve istem
sızıntısı yerine gelen cevapta `sizinti: true` (portal güven rozetini göstermez). Ayrıntı:
[013 ANALIZ §5.2, §6.3, §7](../../013-asistan-guvenlik/ANALIZ.md).
