"""TP'nin config'ini aiprobe-home'dan alması (Config R1, UYGULAMA-PLANI-R1 §6, §8).

`CONFIG_SOURCE=env` (varsayılan): hiçbir şey değişmez, Home'a çağrı yapılmaz (on-prem ve yerel
geliştirme bugünkü gibi). `CONFIG_SOURCE=home`: `GET /v1/config/effective?project=$TP_HOME_PROJECT`
ile kurulumun aktif projesinin etkin config'i alınır ve TP'nin env görünümünün ÜZERİNE uygulanır
(env'de olup Home'da olmayan değer kalır).

Modüller:

- `yukleyici` — yalnız standart kütüphane: Home istemcisi (ETag), son bilinen iyi değer (LKG),
  env görünümü, Secret Manager çözücü, env dosyası birleştirme. VM açılış betiği bunu çekirdek
  imajı olmadan `python3 -m tp_core.home_config` ile host'ta da çalıştırır.
- `durum` — çalışan süreç (core-api, core-worker): 60 sn'de bir yenileme, çalışma anında etkiyen
  anahtarlar, proje özellikleri ve bağlantı kipleri.
- `baglanti` — `POST /v1/connections/access-token` istemcisi (Jira OAuth, GitHub App).
- `kapi` — özellik kapısı (kapalı özellik → 409 `ozellik_kapali`).

Bu `__init__` bilerek boştur: host'taki açılış betiği çekirdeğin bağımlılıklarını yüklemeden
`yukleyici`yi içe aktarabilmelidir.
"""
