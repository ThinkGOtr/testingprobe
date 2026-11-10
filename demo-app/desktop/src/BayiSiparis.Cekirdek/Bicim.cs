// Tutar ve tarih biçimleri — web'deki demo-app/web/src/format.ts ile birebir aynı çıktı:
// tutar "1.250,00 TL", tarih "8 Kas 2026 14:30" (tr-TR, dateStyle medium + timeStyle short).
// İşletim sisteminin ICU/NLS verisine bağlı kalmamak için biçim elle tanımlanır (testler macOS'ta da aynı sonucu verir).
using System.Globalization;

namespace BayiSiparis.Cekirdek;

public static class Bicim
{
    private static readonly NumberFormatInfo TrSayi = new()
    {
        NumberDecimalSeparator = ",",
        NumberGroupSeparator = ".",
        NumberGroupSizes = [3],
        NegativeSign = "-",
        NumberNegativePattern = 1,
    };

    private static readonly string[] AyKisaltmalari =
        ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

    /// <summary>API tutar metnini ("1250.00") "1.250,00 TL" biçimine çevirir.</summary>
    public static string TL(string deger) =>
        TL(decimal.Parse(deger, NumberStyles.Number, CultureInfo.InvariantCulture));

    public static string TL(decimal deger) =>
        Math.Round(deger, 2, MidpointRounding.AwayFromZero).ToString("N2", TrSayi) + " TL";

    /// <summary>API tutar metnini sayıya çevirir (geçersizse 0).</summary>
    public static decimal Sayi(string deger) =>
        decimal.TryParse(deger, NumberStyles.Number, CultureInfo.InvariantCulture, out var d) ? d : 0m;

    /// <summary>Tarih-saat: "8 Kas 2026 14:30" (verilen saat diliminde; varsayılan yerel saat).</summary>
    public static string TarihSaat(DateTimeOffset an, TimeZoneInfo? dilim = null)
    {
        var yerel = TimeZoneInfo.ConvertTime(an, dilim ?? TimeZoneInfo.Local);
        return string.Create(
            CultureInfo.InvariantCulture,
            $"{yerel.Day} {AyKisaltmalari[yerel.Month - 1]} {yerel.Year} {yerel.Hour:00}:{yerel.Minute:00}");
    }
}
