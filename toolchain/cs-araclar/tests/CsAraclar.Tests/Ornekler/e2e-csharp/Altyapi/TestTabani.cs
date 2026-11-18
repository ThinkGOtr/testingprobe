using System;
using Antreklabs.Bayi.Pages;
using Microsoft.Playwright;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>Test tabanı (örnek).</summary>
public abstract class TestTabani
{
    protected IPage Page { get; private set; } = null!;

    public LoginPage LoginPage => new(Page);

    public CatalogPage CatalogPage => new(Page);

    protected CartPage CartPage => new(Page);

    private OrderHelper Gizlenen => new();

    public static LoginPage StatikErisim => null!;

    /// <summary>Gizli test verisi.</summary>
    protected static string Gizli(string ad) =>
        Environment.GetEnvironmentVariable(ad) ?? throw new InvalidOperationException(ad + " tanımsız");
}

public sealed class OrderHelper
{
}
