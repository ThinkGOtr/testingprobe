using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using OpenQA.Selenium;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Başarısız testin kanıtı (Java <c>Kanit</c>): <c>&lt;KANIT_DIZINI&gt;/&lt;Sınıf&gt;.&lt;Metot&gt;/</c>
/// altında <c>ekran.png</c> ve <c>sayfa-kaynagi.xml</c> (UI Automation ağacı); triage okur. Kanıt
/// toplanamazsa testin asıl hatası gölgelenmez: yalnızca <c>kanit-hatasi.txt</c> yazılır.
/// </summary>
public static class Kanit
{
    public const string Ekran = "ekran.png";
    public const string SayfaKaynagi = "sayfa-kaynagi.xml";

    /// <summary>Testin kanıt dizini: güvenli karakterlere indirgenmiş <c>Sınıf.Metot</c>.</summary>
    public static string Dizin(string kok, string sinif, string metot) =>
        Path.Combine(kok, Regex.Replace(sinif + "." + metot, "[^A-Za-z0-9._-]", "_"));

    /// <summary>Kanıtı toplar; yazılan dizini döndürür.</summary>
    public static string Topla(IWebDriver surucu, string kok, string sinif, string metot)
    {
        string hedef = Dizin(kok, sinif, metot);
        var hatalar = new StringBuilder();
        try
        {
            Directory.CreateDirectory(hedef);
        }
        catch (Exception)
        {
            return hedef;
        }
        try
        {
            byte[] png = ((ITakesScreenshot)surucu).GetScreenshot().AsByteArray;
            File.WriteAllBytes(Path.Combine(hedef, Ekran), png);
        }
        catch (Exception e) when (e is WebDriverException or InvalidCastException or IOException)
        {
            hatalar.Append("ekran görüntüsü: ").Append(e.GetType().Name).Append('\n');
        }
        try
        {
            File.WriteAllText(Path.Combine(hedef, SayfaKaynagi), surucu.PageSource, Encoding.UTF8);
        }
        catch (Exception e) when (e is WebDriverException or IOException)
        {
            hatalar.Append("sayfa kaynağı: ").Append(e.GetType().Name).Append('\n');
        }
        if (hatalar.Length > 0)
        {
            try
            {
                File.WriteAllText(Path.Combine(hedef, "kanit-hatasi.txt"), hatalar.ToString(), Encoding.UTF8);
            }
            catch (IOException)
            {
                // kanıt yazılamadı; asıl test hatası yine raporlanır
            }
        }
        return hedef;
    }
}
