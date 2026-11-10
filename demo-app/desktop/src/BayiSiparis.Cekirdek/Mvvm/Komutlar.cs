// ICommand uygulamaları. ICommand System.ObjectModel'dedir (WPF'ye bağımlı değil).
// CanExecuteChanged elle tetiklenir (WPF CommandManager'a dayanılmaz); bu sayede düğmelerin
// etkin/pasif durumu UI Automation'da (IsEnabled) gecikmesiz ve deterministik değişir.
using System.Windows.Input;

namespace BayiSiparis.Cekirdek.Mvvm;

public sealed class Komut : ICommand
{
    private readonly Action<object?> _calistir;
    private readonly Func<object?, bool>? _calisabilir;

    public Komut(Action<object?> calistir, Func<object?, bool>? calisabilir = null)
    {
        _calistir = calistir;
        _calisabilir = calisabilir;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parametre) => _calisabilir?.Invoke(parametre) ?? true;

    public void Execute(object? parametre)
    {
        if (CanExecute(parametre))
        {
            _calistir(parametre);
        }
    }

    public void YenidenDegerlendir() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}

/// <summary>Asenkron komut; çalışırken kendini pasifleştirir (çift tıklamaya karşı).</summary>
public sealed class AsenkronKomut : ICommand
{
    private readonly Func<object?, Task> _calistir;
    private readonly Func<object?, bool>? _calisabilir;
    private bool _calisiyor;

    public AsenkronKomut(Func<object?, Task> calistir, Func<object?, bool>? calisabilir = null)
    {
        _calistir = calistir;
        _calisabilir = calisabilir;
    }

    public event EventHandler? CanExecuteChanged;

    public bool Calisiyor => _calisiyor;

    public bool CanExecute(object? parametre) => !_calisiyor && (_calisabilir?.Invoke(parametre) ?? true);

    /// <summary>WPF'nin çağırdığı giriş noktası; hatalar görünüm modelinde ele alınır.</summary>
    public async void Execute(object? parametre) => await CalistirAsync(parametre);

    /// <summary>Testlerin beklediği giriş noktası.</summary>
    public async Task CalistirAsync(object? parametre = null)
    {
        if (!CanExecute(parametre))
        {
            return;
        }

        _calisiyor = true;
        YenidenDegerlendir();
        try
        {
            await _calistir(parametre);
        }
        finally
        {
            _calisiyor = false;
            YenidenDegerlendir();
        }
    }

    public void YenidenDegerlendir() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
