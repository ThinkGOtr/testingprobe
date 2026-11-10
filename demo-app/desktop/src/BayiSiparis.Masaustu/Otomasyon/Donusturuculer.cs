// XAML bağlama dönüştürücüleri.
using System.Globalization;
using System.Windows.Data;

namespace BayiSiparis.Masaustu.Otomasyon;

/// <summary>Değer null değilse ve boş metin değilse true (Kosullu.Goster için).</summary>
public sealed class DoluMuDonusturucu : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value switch
        {
            null => false,
            string s => s.Length > 0,
            bool b => b,
            _ => true,
        };

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>Değer, parametreye eşitse "current" (UIA ItemStatus; web'deki aria-current="page"), değilse "".</summary>
public sealed class EtkinMenuDonusturucu : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        Equals(value as string, parameter as string) ? "current" : "";

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
