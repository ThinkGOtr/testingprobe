using System;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Test sınıfını bir e2e bayisine sabitler (Java <c>@Bayi</c>, web <c>test.use({ dealerUsername })</c>):
/// <c>[Bayi("bayi2")]</c>. Üretilen testler case metnindeki bayiye bu yolla sabitlenir.
/// </summary>
[AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = true)]
public sealed class BayiAttribute : Attribute
{
    public BayiAttribute(string kullaniciAdi)
    {
        KullaniciAdi = kullaniciAdi;
    }

    public string KullaniciAdi { get; }
}
