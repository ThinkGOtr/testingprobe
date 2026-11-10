namespace BayiSiparis.Cekirdek.Mvvm;

/// <summary>
/// Uygulama genelinde süren API çağrısı sayacı. Sayaç sıfırdan büyükken pencerede
/// "busy-indicator" kimlikli eleman görünür; testler bu elemanın kaybolmasını bekleyebilir.
/// </summary>
public sealed class MesgulTakipcisi : GozlemlenebilirNesne
{
    private int _sayac;

    public bool Mesgul => _sayac > 0;

    /// <summary>Kapsam açar; Dispose edildiğinde sayaç azalır.</summary>
    public IDisposable Basla()
    {
        _sayac++;
        if (_sayac == 1)
        {
            Bildir(nameof(Mesgul));
        }

        return new Kapsam(this);
    }

    /// <summary>Verilen işi meşgul kapsamında çalıştırır.</summary>
    public async Task<T> IzleAsync<T>(Task<T> is_)
    {
        using (Basla())
        {
            return await is_;
        }
    }

    public async Task IzleAsync(Task is_)
    {
        using (Basla())
        {
            await is_;
        }
    }

    private void Bitir()
    {
        _sayac--;
        if (_sayac == 0)
        {
            Bildir(nameof(Mesgul));
        }
    }

    private sealed class Kapsam(MesgulTakipcisi sahip) : IDisposable
    {
        private bool _bitti;

        public void Dispose()
        {
            if (!_bitti)
            {
                _bitti = true;
                sahip.Bitir();
            }
        }
    }
}
