# Data Model: Portal Asistanı ve Öneri (migrasyon `0017_asistan`)

Sahip: Şerit B (migrasyon + SQLAlchemy modelleri aynı PR'da; `test_modeller_ve_migrasyon_ayni` ve
`test_check_kisitlari_gecersiz_degeri_reddeder` yeşil kalır). Kaynak: plan §8.

## Tablolar

```
asistan_sohbet
  id uuid pk
  kullanici_id uuid fk app_user
  baslik text
  oneri_kural_id text null            -- öneriden açılan sohbetin bağlamı (§17.6)
  olusturma timestamptz, guncelleme timestamptz
  silindi bool default false, silinme timestamptz null

asistan_mesaj
  id uuid pk
  sohbet_id uuid fk asistan_sohbet
  kullanici_id uuid fk app_user
  sira int
  rol text            CHECK IN ('user','assistant')
  ust_mesaj_id uuid null fk asistan_mesaj     -- "Daha ayrıntılı" / otomatik yükseltme çocuğu
  icerik text                                  -- soru metni (kullanıcı) / null (asistan)
  baglam jsonb                                 -- doğrulanmış ekran bağlamı (≤ 2 KB) + oneri{kural_id,…}
  cevap jsonb                                  -- son işlenmiş şema çıktısı + dogrulama{} + guven_gosterimi
  durum text          CHECK IN ('pending','running','done','error','iptal')
  hata_kodu text null                          -- butce_asildi | girdi_tavani | zaman_asimi | model_hatasi
  kaynak text null    CHECK IN ('model','sozluk','sablon','kapali')
  amac text null      CHECK IN ('assistant','assistant_deep')   -- sözlük/şablonda NULL
  kip text  default 'soru'       CHECK IN ('soru','oneri')
  tetik text default 'kullanici' CHECK IN ('kullanici','otomatik')
  job_id uuid null, ai_call_id uuid null
  maliyet_usd numeric null, token_girdi int null, token_cikti int null
  sure_ms int null                             -- uçtan uca
  geri_bildirim smallint null                  -- -1 | 1
  olusturma timestamptz, tamamlanma timestamptz null

  unique(sohbet_id, sira)
  unique(ust_mesaj_id) WHERE ust_mesaj_id IS NOT NULL
  unique(kullanici_id) WHERE rol='assistant' AND tetik='kullanici'
                         AND durum IN ('pending','running')          -- atomik "1 bekleyen"
  index(kullanici_id, olusturma); index(ai_call_id)
  check(tetik='kullanici' OR (ust_mesaj_id IS NOT NULL AND amac='assistant_deep'))

asistan_durum          -- tekil satır; YALNIZ worker yazar, core-api okur
  id smallint pk CHECK (id = 1)
  mod text CHECK IN ('live','off')
  model_hazir bool, maskeleme bool, musteri_verisi bool
  paket_commit text null, paket_uretim timestamptz null
  kalp_atisi timestamptz

asistan_oneri_geri_bildirim
  id uuid pk
  kullanici_id uuid fk app_user
  kural_id text
  varlik_id uuid null
  varlik_durum text null          -- SUNUCUDA hesaplanır (istemciden alınmaz)
  deger smallint CHECK IN (-1, 1, 2)   -- gizle | faydalı | yaptım
  jira_anahtari text null         -- yalnız deger=2; ^[A-Z][A-Z0-9]+-[0-9]+$
  olusturma timestamptz
  index(kullanici_id, kural_id, varlik_id)

asistan_hiz
  kullanici_id uuid null          -- jira_global kovasında NULL
  kova text                       -- oneri_liste | oneri_geri_bildirim | jira_global
  pencere_baslangic timestamptz
  sayi int
  unique nulls not distinct (kullanici_id, kova, pencere_baslangic)   -- postgresql_nulls_not_distinct=True
```

## Değişen kısıtlar ve yetkiler

- `tool_call_kanal_ck` → `kanal IN ('agent','ide','asistan')` (`drop_constraint` +
  `create_check_constraint`; append-only tetikleyicisi/yetkisi değişmez). Downgrade, `asistan` satırı
  varken bilerek başarısız olur.
- `models/enums.TOOL_KANAL` += `asistan`; yeni enum kümeleri `ASISTAN_*` (`models/enums.py`).
- `GRANT SELECT, INSERT, UPDATE, DELETE ON asistan_sohbet, asistan_mesaj, asistan_durum,
  asistan_oneri_geri_bildirim, asistan_hiz TO tp_app`.
- `ai_call`'a kolon eklenmez: kişi bağı `ai_call.ek = {kanal:"asistan", kullanici_id, mesaj_id}` +
  `asistan_mesaj.ai_call_id` (`deterministic_call_id(mesaj_id, amac)`; iş `running`'e alınırken yazılır).
- `asistan_mesaj.durum` `workflow/states.MACHINES`'e **konmaz** (insan kapısı yok; altyapı kaydı).

## Kurallar

- **Saklama**: 90 gün (`TP_ASISTAN_SAKLAMA_GUN`); yumuşak silinen sohbetler de bu sürede fiziksel
  silinir; `asistan_oneri_geri_bildirim` aynı süre; `asistan_hiz` 1 günden eski satırlar temizlenir;
  `ai_call`/`tool_call` etkilenmez.
- **Yarış korumaları**: `pending→running` ve içerik yazımı `WHERE durum='running'`; maliyet/token
  `WHERE durum IN ('running','iptal')`.
- **Eşzamanlı POST**: `sira` veya bekleyen indeksi ihlali → kısıt adına göre 409 `bekleyen_var`;
  `unique(ust_mesaj_id)` ihlali → 409 `zaten_derin`.
- Öneri kuralları tabloda tutulmaz (`rules/assistant/oneriler.yaml`, her istekte hesaplanır).
- Geçmiş metnindeki eski yer tutucular yeni maskeleme oturumunda etkisizleşir (`< <PII…`); sızıntı değildir.
