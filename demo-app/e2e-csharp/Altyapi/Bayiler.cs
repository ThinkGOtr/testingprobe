using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>Bir e2e bayi kullanıcısı.</summary>
/// <param name="KullaniciAdi">Giriş kullanıcı adı.</param>
/// <param name="Parola">Seed parolası (demo-app/api seed.py; sır değildir).</param>
/// <param name="Ad">Arayüzde gösterilen bayi adı (ör. "Merkez Bayi").</param>
public sealed record BayiBilgisi(string KullaniciAdi, string Parola, string Ad)
{
    public override string ToString() => KullaniciAdi;
}

/// <summary>e2e bayi kullanıcıları ve testin bayisini seçme kuralı (TS: tests/fixtures.ts <c>DEALERS</c>, <c>pickDealer</c>).</summary>
public static class Bayiler
{
    /// <summary>e2e bayileri (paralel işçi başına bir bayi); web e2e ile aynı.</summary>
    public static readonly IReadOnlyList<BayiBilgisi> E2E = new[]
    {
        new BayiBilgisi("bayi1", "Demo123!", "Merkez Bayi"),
        new BayiBilgisi("bayi2", "Demo123!", "Sahil Bayi"),
    };

    /// <summary>Doğrulama ajanının bayisi; e2e testleri kullanamaz ve sıfırlamaz.</summary>
    public const string AjanBayisi = "bayi3";

    /// <summary>
    /// Koşu hesabı başına parola: test-runner <c>TP_RUN_DEALER_PASSWORDS</c> = JSON
    /// <c>{"&lt;kullanıcı&gt;": "&lt;parola&gt;"}</c> verir (AI Probe › Test kullanıcıları; yalnız parolası
    /// girilen hesaplar). Hesabın parolası yoksa seed (ortak) parolası kullanılır.
    /// </summary>
    public const string KosuParolalariEnv = "TP_RUN_DEALER_PASSWORDS";

    /// <summary><c>TP_RUN_DEALER_PASSWORDS</c> değerini çözer (boş/null = boş). Bozuk değer açık hatayla
    /// durur (değer iletiye yazılmaz); boş ve metin olmayan parolalar atlanır.</summary>
    public static IReadOnlyDictionary<string, string> KosuParolalari(string? ham)
    {
        var sonuc = new Dictionary<string, string>();
        if (string.IsNullOrWhiteSpace(ham))
        {
            return sonuc;
        }
        System.Text.Json.JsonDocument belge;
        try
        {
            belge = System.Text.Json.JsonDocument.Parse(ham);
        }
        catch (System.Text.Json.JsonException)
        {
            throw new ArgumentException($"{KosuParolalariEnv} geçerli JSON değil");
        }
        using (belge)
        {
            if (belge.RootElement.ValueKind != System.Text.Json.JsonValueKind.Object)
            {
                throw new ArgumentException($"{KosuParolalariEnv} bir JSON nesnesi olmalı");
            }
            foreach (var p in belge.RootElement.EnumerateObject())
            {
                if (p.Value.ValueKind == System.Text.Json.JsonValueKind.String && p.Value.GetString() is { Length: > 0 } parola)
                {
                    sonuc[p.Name] = parola;
                }
            }
        }
        return sonuc;
    }

    /// <summary>Bayinin bu koşudaki parolası: koşu ortamında girilmişse o, yoksa seed (ortak) parolası.</summary>
    public static BayiBilgisi KosuParolasiyla(BayiBilgisi bayi, IReadOnlyDictionary<string, string> parolalar) =>
        parolalar.TryGetValue(bayi.KullaniciAdi, out var p) ? bayi with { Parola = p } : bayi;

    /// <summary>Koşu hesabı parolasının ortam adı (core <c>render.kosu_parola_adi</c> ile aynı kural); 64'ü aşarsa null.</summary>
    public static string? KosuParolaAdi(string kullaniciAdi)
    {
        var ad = "TP_TESTVERI_KOSU_" + System.Text.RegularExpressions.Regex.Replace(
            kullaniciAdi.ToUpperInvariant(), "[^A-Z0-9]", "_");
        return System.Text.RegularExpressions.Regex.IsMatch(ad, "^TP_TESTVERI_[A-Z0-9_]{1,64}$") ? ad : null;
    }

    /// <summary>
    /// Üretilen testin <c>Gizli("TP_TESTVERI_KOSU_&lt;KULLANICI&gt;")</c> okuması runner'dan gelmediyse: o e2e
    /// bayisinin bu koşudaki parolası (koşu ortamı → seed; geriye uyum). Eşleşen bayi yoksa null.
    /// </summary>
    public static string? KosuParolasiAdla(string ad) =>
        E2E.Where(b => KosuParolaAdi(b.KullaniciAdi) == ad)
            .Select(b => KosuParolasiyla(b).Parola)
            .FirstOrDefault();

    private static BayiBilgisi KosuParolasiyla(BayiBilgisi bayi) =>
        KosuParolasiyla(bayi, KosuParolalari(Environment.GetEnvironmentVariable(KosuParolalariEnv)));

    /// <summary>Testin bayisi: <paramref name="sabit"/> verilmişse o, yoksa işçi yuvasının bayisi.</summary>
    public static BayiBilgisi Sec(string? sabit, int isciSirasi)
    {
        if (sabit is not null)
        {
            var b = E2E.FirstOrDefault(x => x.KullaniciAdi == sabit);
            if (b is not null)
            {
                return KosuParolasiyla(b);
            }
            var ayrilmis = sabit == AjanBayisi ? " (doğrulama ajanına ayrılmıştır)" : "";
            throw new ArgumentException(
                $"[Bayi(\"{sabit}\")] bir e2e bayisi değil{ayrilmis}; izinli: {string.Join(", ", E2E.Select(x => x.KullaniciAdi))}");
        }
        if (isciSirasi < 0 || isciSirasi >= E2E.Count)
        {
            throw new ArgumentException(
                $"En fazla {E2E.Count} paralel işçi desteklenir (bayi kullanıcısı sayısı); işçi sırası {isciSirasi}");
        }
        return KosuParolasiyla(E2E[isciSirasi]);
    }

    /// <summary>Test sınıfının bayisi: <see cref="BayiAttribute"/> (kalıtılmış dahil), yoksa işçi bayisi.</summary>
    public static BayiBilgisi SinifIcin(Type testSinifi, int isciSirasi) =>
        Sec(testSinifi.GetCustomAttribute<BayiAttribute>(inherit: true)?.KullaniciAdi, isciSirasi);
}
