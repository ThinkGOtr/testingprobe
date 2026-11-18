using System;
using Antreklabs.Bayi.Ekranlar;

namespace Antreklabs.Bayi.Altyapi;

public abstract class TestTabani
{
    public GirisEkrani GirisEkrani => new();

    public KatalogEkrani KatalogEkrani => new();

    public SepetEkrani SepetEkrani => new();

    protected static string Gizli(string ad) =>
        Environment.GetEnvironmentVariable(ad) ?? throw new InvalidOperationException(ad);
}
