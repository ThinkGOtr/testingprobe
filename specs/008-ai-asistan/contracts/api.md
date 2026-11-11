# Sözleşme: HTTP API, hata `kod` enum'u, SSE olayları

Kaynak: plan §9, §17. Bağlayıcı karşılığı `docs/MIMARI-SOZLESME.md` §5'tedir; çelişkide o belge geçer.
Modül: `core/src/tp_core/features/assistant/api.py` (otomatik keşif). Tüm uçlar `CurrentUser`
(yalnız çerez; `tpt_` bearer → 401 `yetkisiz`); CSRF global Origin koruması (403 `kaynak_reddi`).
Başkasının kaynağına her uç (cancel/feedback/`ust_mesaj_id` dahil) → 404 `bulunamadi`.

## Uçlar (11)

| # | Yöntem | Yol | Gövde / sorgu | Başarı | Hatalar |
|---|---|---|---|---|---|
| 1 | GET | `/assistant/status` | — | `{etkin, neden?, mod, varsayilan_model, degerlendirme, paket_commit, kalan_soru}` | — (kalp atışı > 2 dk → `etkin=false, neden="worker_yok"`) |
| 2 | GET | `/assistant/conversations` | — | kendi sohbetleri, son 50 | |
| 3 | POST | `/assistant/conversations` | `{baslik?}` | 201 sohbet | |
| 4 | DELETE | `/assistant/conversations/{id}` | — | 204 (yumuşak silme) | 404 |
| 5 | GET | `/assistant/conversations/{id}/messages` | — | mesajlar (bekleyen dahil) | 404 |
| 6 | POST | `/assistant/conversations/{id}/messages` | `{soru ≤ 2000, baglam ≤ 2 KB, kip?: "soru"\|"oneri", oneri_kural_id?}` **veya** `{ust_mesaj_id}` | 202 `{mesaj_id}` | 422 `gecersiz_istek` / `sir_icerik` / `kisisel_veri`; 404; 409 `bekleyen_var` / `zaten_derin` / `oneri_gecersiz`; 429 `hiz_siniri` / `mesgul`; 402 `butce_asildi`; 503 `asistan_kapali` (+ `neden`: `worker_yok`\|`maskeleme_kapali`) |
| 7 | GET | `/assistant/messages/{id}` | — | tek mesaj (SSE yokken yoklama) | 404 |
| 8 | POST | `/assistant/messages/{id}/cancel` | — | `pending→iptal` (ücretsiz) / `running→iptal` (harcanan yazılır) | 404 |
| 9 | POST | `/assistant/messages/{id}/feedback` | `{deger: -1\|1}` | 200 | 422 (`0`), 404 |
| 10 | GET | `/assistant/suggestions?rota=&varlik_tur=&varlik_id=` | — | `{oneriler: [{kural_id, baslik, neden, oncelik, eylem}], hesaplandi, ekranda_kural_var, bastirilan, diger_ekranlar}` | 404 (varlık yok / role kapalı); 429 `hiz_siniri` (60/dk) |
| 11 | POST | `/assistant/suggestions/{kural_id}/feedback` | `{deger: -1\|1\|2, varlik_id?, jira_anahtari?}` | 200 | 422 (bilinmeyen kural, regex); 404 (varlık); 429 (30/dk) |

### Kurallar

- **POST mesaj (6)**: `kip=oneri`'de `soru` boş olabilir; sunucu sabit "Bu ekranda başka ne
  yapabilirim?" yazar. `oneri_kural_id` verilirse sunucu öneriyi yeniden hesaplar; geçerli değilse 409
  `oneri_gecersiz`. `{ust_mesaj_id}`: aynı sohbette, `rol='assistant'`, `durum='done'`,
  `amac IS DISTINCT FROM 'assistant_deep'` (sözlük/şablonda NULL kabul) — değilse 422/404; ikinci kez
  409 `zaten_derin`; soru ve amaç sunucuda üst mesajdan türetilir (istemci `soru`'su yok sayılır).
  Eşzamanlı POST'ta hangi tekil kısıt patlarsa patlasın (`sira` veya bekleyen indeksi) kısıt adına göre
  409 `bekleyen_var`. Model gerekip gerekmediğine (sözlük/şablon) worker karar verir.
- **Sayaçlar**: global = 2 × `TP_WORKER_ASISTAN_PARALEL` (varsayılan 6), `job` tablosundaki bitmemiş
  `assistant.answer` işlerinden, `pg_advisory_xact_lock` altında (aşım → 429 `mesgul`); kullanıcı başı
  bekleme kısmi tekil indeksle (yalnız `tetik='kullanici'`). Saatlik 30 soru mesaj tablosundan, iptal
  ve hata dahil, otomatik çocuklar hariç; `assistant_deep` 2 sayılır.
- **İş yükü**: daima `{mesaj_id, kullanici_id, tetik}`; idempotency anahtarı
  `assistant.answer:<mesaj_id>`.
- **Öneri (10)**: modelsiz, worker gerekmez, model kapalıyken çalışır, `ai_call` yazmaz; rol oturumdan;
  rota `rotalar.json` kalıbına indirgenir; `(kullanici, rota, varlik)` için 4 sn sunucu önbelleği (5 sn SSE debounce'undan kısa);
  `eylem.baglanti` yalnız sunucu kurar (contracts/oneri-kurallari.md §Bağlantı). `TP_ASISTAN_ONERI=0` →
  uç kapalı (404 `bulunamadi`; portal yetenek kapısı gizler).
- **Geri bildirim (11)**: `varlik_durum` sunucuda hesaplanır; istemcinin gönderdiği yok sayılır.
  `deger=-1` yalnız o kullanıcıya, varlık aynı durumdayken bastırır; `deger=2` ("Yaptım") o kuralı o
  varlık aynı durumdayken tüm rollerde bastırır, `tekrar_saat` dolunca yeniden gösterir.

## Hata gövdesi ve `kod` enum'u

Her hata: `{"detail": "<Türkçe metin>", "kod": "<enum>"}` (+ uca özgü ek alanlar: `budget`,
`neden`). `kod` asla istisna adından veya `str(exc)`'ten türetilmez.

| Grup | `kod` | HTTP | Kaynak |
|---|---|---|---|
| Genel (durum kodundan) | `gecersiz_istek` | 400, 415, 422 | `api/errors.GENEL_KODLAR` |
| | `yetkisiz` | 401 (`WWW-Authenticate` korunur) | |
| | `yasak` | 403 | |
| | `bulunamadi` | 404, 410 | |
| | `yontem_desteklenmiyor` | 405 | |
| | `cakisma` | 409 | |
| | `govde_cok_buyuk` | 413 | |
| | `hiz_siniri` | 429 | |
| | `istek_hatasi` | listede olmayan diğer 4xx | |
| | `ic_hata` | her 5xx (tek istisna aşağıda) | |
| İş akışı (`WorkflowError.kod`) | `gecersiz_gecis` | 409 | `InvalidTransition` |
| | `eszamanli_gecis` | 409 | `ConcurrentTransition` |
| | `kapi_kapali` | 409 | `GateClosed` |
| | `onay_hash_uyusmuyor` | 409 | `OnayHashUyusmuyor(GateClosed)` |
| | `kosul_saglanmadi` | 422 | `GuardFailed` |
| | `onay_yetkisi_yok` | 403 | `ApprovalNotAllowed` |
| | `gecersiz_karar` | 422 | `InvalidDecision` |
| Bütçe | `butce_asildi` | 402 | `BudgetExceeded` ve asistan bütçe ön kontrolü |
| CSRF | `kaynak_reddi` | 403 | `api/csrf.py` (ara katman, gövdeye doğrudan) |
| Asistan (`KodluHata`) | `sir_icerik` | 422 | soru/bağlamda sır deseni; değer yanıtta yok |
| | `kisisel_veri` | 422 | soru/bağlamda Luhn'lu kart numarası; değer yanıtta yok (spec 013) |
| | `bekleyen_var` | 409 | kullanıcının bekleyen mesajı var |
| | `zaten_derin` | 409 | `ust_mesaj_id` tekilliği |
| | `oneri_gecersiz` | 409 | `oneri_kural_id` artık geçerli değil |
| | `mesgul` | 429 | global bekleyen sınırı |
| | `hiz_siniri` | 429 | saatlik soru / öneri kovaları |
| | `asistan_kapali` | 503 | `neden`: `worker_yok` \| `maskeleme_kapali` |

**5xx istisnası**: `asistan_kapali` bilinçli hizmet durumudur, iç ayrıntı taşımaz; `kod` olarak
korunur. Diğer tüm 5xx yanıtlarda `kod` = `ic_hata`, `detail` = "Sunucu hatası".

Yeni `kod` değeri ancak bu tabloya ve MIMARI-SOZLESME §5'e eklenerek kullanılabilir; hata sözlüğü
(`rules/assistant/hata-sozlugu.yaml`) `kod` **veya** normalize `detail`/`gorunen_metin` ile eşleşir.

**Mesaj `hata_kodu` (yanıt değil, `asistan_mesaj.hata_kodu`)**: `butce_asildi`, `girdi_tavani`,
`zaman_asimi`, `model_hatasi`. Portal bunları `lib/etiketler.ts` ile Türkçeleştirir.

## SSE

- `assistant.step {mesaj_id, kullanici_id, adim_kodu}` — `adim_kodu` sabit sözlükten (ör.
  `yanitlaniyor`, `arac`, `dogrulaniyor`); argüman/soru metni yok.
- `assistant.answered {mesaj_id, kullanici_id, durum, derin_bekliyor}`.
- `events/bus.py` `KIMLIK_ALANLARI` += `mesaj_id`, `kullanici_id` (kırpılmış yükte korunur).
- `api/routers/events.py` `_akis`: `assistant.*` olayı `kullanici_id` taşımıyorsa veya oturum
  kullanıcısı değilse **teslim edilmez** (fail-closed).
- Portal: `BILINEN_OLAYLAR` += iki ad; `olayEslesir` `data.mesaj_id` ile de eşleşir; `CORE_OLAYLARI`
  değişmez.

## Hız sınırı mekanizması

`asistan_hiz` üzerinde sabit pencere: `INSERT … ON CONFLICT DO UPDATE SET sayi = sayi + 1 RETURNING
sayi`. Kovalar: `oneri_liste` 60/dk, `oneri_geri_bildirim` 30/dk, `jira_global` 30/dk
(`kullanici_id` NULL; worker). Saatlik soru sınırı mesaj tablosundan sayılır.
