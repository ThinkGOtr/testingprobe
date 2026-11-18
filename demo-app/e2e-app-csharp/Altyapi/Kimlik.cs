using System;
using OpenQA.Selenium;
using OpenQA.Selenium.Appium;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Erişilebilirlik kimliği → Appium seçicisi (plan §2.2). Windows'ta WPF
/// <c>AutomationProperties.AutomationId</c> = <c>MobileBy.AccessibilityId</c>. Ekran nesneleri
/// <c>Kimlikler</c> sabitleriyle <see cref="Bul"/> çağırır.
/// </summary>
public static class Kimlik
{
    /// <summary>Kimliğin seçicisi.</summary>
    public static By Bul(string kimlik)
    {
        if (string.IsNullOrEmpty(kimlik))
        {
            throw new ArgumentException("kimlik boş olamaz");
        }
        return MobileBy.AccessibilityId(kimlik);
    }

    /// <summary>Önek kimliğe sonek ekler (<c>URUN_KARTI_ONEK + "P-001"</c>); önek '-' ile bitmeli.</summary>
    public static string Ekli(string onek, string sonek)
    {
        if (!onek.EndsWith('-'))
        {
            throw new ArgumentException($"'{onek}' önek kimlik değil ('-' ile bitmeli)");
        }
        if (string.IsNullOrEmpty(sonek))
        {
            throw new ArgumentException($"'{onek}' önek kimliği için sonek (ürün kodu / sipariş no) gerekli");
        }
        return onek + sonek;
    }
}
