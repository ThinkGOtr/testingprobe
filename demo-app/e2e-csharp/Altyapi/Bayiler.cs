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

    /// <summary>Testin bayisi: <paramref name="sabit"/> verilmişse o, yoksa işçi yuvasının bayisi.</summary>
    public static BayiBilgisi Sec(string? sabit, int isciSirasi)
    {
        if (sabit is not null)
        {
            var b = E2E.FirstOrDefault(x => x.KullaniciAdi == sabit);
            if (b is not null)
            {
                return b;
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
        return E2E[isciSirasi];
    }

    /// <summary>Test sınıfının bayisi: <see cref="BayiAttribute"/> (kalıtılmış dahil), yoksa işçi bayisi.</summary>
    public static BayiBilgisi SinifIcin(Type testSinifi, int isciSirasi) =>
        Sec(testSinifi.GetCustomAttribute<BayiAttribute>(inherit: true)?.KullaniciAdi, isciSirasi);
}
