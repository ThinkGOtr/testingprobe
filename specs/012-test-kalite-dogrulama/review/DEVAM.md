# 012 — kaldığımız yer (2026-11-12 22:10)

Haftalık kullanım sınırı doldu (açılış: 17 Kasım 16:00). Hiçbir ajan çalışmıyor.

- Dal `feat/test-kalite-dogrulama` (worktree `tp-wt-kalite`), push'lu. Tur 1 düzeltmeleri birleşik;
  tam çekirdek paketi 4963 geçti (kırmızı yalnız asistan paketi değerlendirme kaydı, iki test).
- Review turu 2 bitti: bulgular `review/tur2.md` (g2 güvenlik+bağımsızlık, u2 ön yüz+analist, t2 test+mimari).
- Tur 2 düzeltme şeritleri AÇILDI ama başlamadan sınıra takıldı (worktree'ler temiz, commit yok):
  - Q1 oracle `tp-wt-kalite-q1-oracle` (feat/tkd-q1-oracle): g2 Y1–Y6, Y9, Y11–Y14; t2 N1, N5, N6, N8, N10 (oracle), N11, N14; mimari-17/18/19; u2 N1 (core), N2 (T2 taslak golden `<= 750` AI hatası), N3; güvenlik-13.
  - Q2 hata+triage `tp-wt-kalite-q2-hata` (feat/tkd-q2-hata): g2 Y7, Y8, Y10, Y15, güvenlik-12; t2 N3, N4, N9, N10 (hata), N12, N13; mimari-15; u2 N6.
  - Q3 portal `tp-wt-kalite-q3-portal` (feat/tkd-q3-portal): S1 (çekirdek kuralı izle), u2 N1–N19, onyuz 21/22, t2 N15, g2 O2; yeni sözleşme alanları `damga`/`oracle_kayit_damgasi`, `kismen_nedeni`.
  - Q4 belgeler `tp-wt-kalite-q4-belge` (feat/tkd-q4-belge): ANALIZ §14 v3 birleştirme planı (0029/0028, nesne_turu CHECK birleşimi, kanca taşıma), demo dokümanları, test rehberi.
- Kararlar (tur 2): saklı geçerli istisna aynı tür/hash/tablo kümesinde yeniden kullanılabilir (audit `oracle.exception_reused`); T2 sınır hatası AI taslağının hatasıdır, PO ızgarada yakalar.
- İzole yığın `tp-kalite` ayakta (portal 8380, API 8300); yeniden doğrulama yarıda kaldı (bir düzeltme commit'i: f28635f). Kapatmak: `docker compose -p tp-kalite down`.
- Sonra: Q1–Q4 → birleştir → tam paket → izole yığında gerçek koşu + Chrome for Testing ekran turu → review turu 3.
