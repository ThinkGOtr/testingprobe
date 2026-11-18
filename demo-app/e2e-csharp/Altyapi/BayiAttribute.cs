using System;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Test sınıfını belirli bir e2e bayisine sabitler: <c>[Bayi("bayi2")]</c> (TS:
/// <c>test.use({ dealerUsername: "bayi2" })</c>, Java: <c>@Bayi("bayi2")</c>). İzinli bayiler
/// <see cref="Bayiler.E2E"/>; doğrulama ajanının bayisi (<see cref="Bayiler.AjanBayisi"/>) sabitlenemez.
/// </summary>
[AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = true)]
public sealed class BayiAttribute : Attribute
{
    public BayiAttribute(string kullaniciAdi) => KullaniciAdi = kullaniciAdi;

    /// <summary>Bayi kullanıcı adı (ör. "bayi2").</summary>
    public string KullaniciAdi { get; }
}

/// <summary>
/// Her test, testin bayisiyle API üzerinden oturum açmış olarak başlar (TS: <c>signedInTest</c>).
/// Yalnız elle yazılmış testler içindir; üretilen testler girişi case adımı olarak içerir
/// (cs-araclar guard bu özniteliğe izin vermez).
/// </summary>
[AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = true)]
public sealed class OturumAcikAttribute : Attribute
{
}
