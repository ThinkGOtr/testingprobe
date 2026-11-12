# Kurum politikaları — Agent Probe denetimi (P9) için VARSAYILAN liste

> **Bu dosya varsayılandır.** Testing Probe ekibinin makul bir başlangıç listesidir; kurumun
> güvenlik, gizlilik (KVKK) ve ortam kullanım politikalarının yerine geçmez. Kurum bu dosyayı kendi
> politikalarıyla güncellemelidir (Git'te sürümlenir; değişiklik denetim girdisini değiştirir,
> önceki denetim kayıtları kendi girdileriyle kalır).

Kullanım: `features/cases/denetim_akisi.py` bu dosyanın "## Politikalar" bölümündeki her madde
imli satırı denetim girdisine (`CaseSetAuditRequest.policies`) güvenilir metin olarak koyar;
"## İzinli test ortamları" bölümündeki ana makineler deterministik ortam kontrolünde kullanılır
(case metnindeki ya da verisindeki bir URL'nin — şemasız `ad.uzantı/yol` dahil — ana makinesi bu
listede değilse karar ENGELLE olur: üretim ya da üçüncü taraf hedef, denetim karar kuralı).

## Politikalar

- KVKK: test verisinde gerçek kişi, müşteri ya da çalışan verisi (ad-soyad + iletişim, TCKN, telefon, adres, e-posta) kullanılmaz; kişisel veri yalnız sentetik ve açıkça uydurma olabilir.
- Test verisi sentetiktir (`synthetic: true`); geçerli sağlama toplamlı TCKN, IBAN veya kart numarası, gerçek parola, token, API anahtarı ve üretim verisi kullanılmaz. E-posta adresleri ayrılmış/test alan adlarındadır (example.com, *.test, *.local, sim.local).
- Testler yalnız izinli test ortamlarında koşar (aşağıdaki liste); üretim (prod/canlı) sistemlerine, gerçek üçüncü taraf servislerine ve gerçek kullanıcı hesaplarına istek atan adım yazılmaz.
- Gerçek ödeme, gerçek e-posta ve gerçek SMS gönderimi yapılmaz; ödeme, bildirim ve mesaj servisleri yalnız simülatör/sahte (sandbox) uçlarla test edilir.
- Negatif ve güvenlik testleri (enjeksiyon, XSS, SQLi, yetki aşımı) yalnız izinli test ortamında ve saldırı verisi `is_attack_payload: true` ile işaretlenmiş olarak yazılır; saldırı metni adım/başlık metnine talimat olarak yazılmaz.
- Geri alınamaz değişiklik yaratan adım (kayıt silme, toplu güncelleme, hesap kapatma) yalnız test ortamında ve temizlik (teardown) adımıyla yazılır.
- Testler ve denetim, gereksinimde yazmayan davranışı (mesaj, kod, eşik) beklenen sonuç olarak kabul etmez; varsayım işaretlenir ve sahibi yazılır.

## İzinli test ortamları

- localhost
- 127.0.0.1
- demo-app
- jira-sim
- *.local
- *.test
- example.com
- *.example.com
