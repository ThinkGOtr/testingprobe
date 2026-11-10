using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace BayiSiparis.Cekirdek.Mvvm;

/// <summary>INotifyPropertyChanged tabanı (WPF bağlamaları bu olayı dinler).</summary>
public abstract class GozlemlenebilirNesne : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool Ayarla<T>(ref T alan, T deger, [CallerMemberName] string? ad = null)
    {
        if (EqualityComparer<T>.Default.Equals(alan, deger))
        {
            return false;
        }

        alan = deger;
        Bildir(ad!);
        return true;
    }

    protected void Bildir(string ad) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(ad));
}
