using System;
using System.Collections.Concurrent;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Bayiyi bir test süresince özel alır (Java <c>BayiKilidi</c>): aynı demo API'ye karşı koşan
/// süreçler işletim sistemi dosya kilidiyle (<see cref="FileShare.None"/>) sıraya girer; süreç ölünce
/// kilit düşer. Aynı süreçteki iş parçacıkları önce bir <see cref="SemaphoreSlim"/> ile sıralanır.
/// Kilit dizini Java uygulama e2e'siyle AYNIDIR (<c>demoapp-e2e-app-kilit-&lt;özet&gt;</c>): Java ve
/// C# uygulama koşuları aynı bayiyi aynı anda sıfırlamaz.
/// </summary>
public sealed class BayiKilidi : IDisposable
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> SurecIci = new();

    private readonly SemaphoreSlim surecIci;
    private FileStream? dosya;

    private BayiKilidi(SemaphoreSlim surecIci, FileStream dosya)
    {
        this.surecIci = surecIci;
        this.dosya = dosya;
    }

    /// <summary>Aynı demo API'ye karşı koşan süreçlerin paylaştığı kilit dizini.</summary>
    public static string Dizin(string demoApiUrl)
    {
        byte[] ozet = SHA256.HashData(Encoding.UTF8.GetBytes("app|" + demoApiUrl));
        string kisa = Convert.ToHexString(ozet).ToLowerInvariant()[..12];
        return Path.Combine(Path.GetTempPath(), "demoapp-e2e-app-kilit-" + kisa);
    }

    /// <summary>Bayi kilidini alır; <paramref name="bekleme"/> içinde alınamazsa açıklayıcı hata.</summary>
    public static BayiKilidi Al(string dizin, string kullaniciAdi, TimeSpan bekleme)
    {
        string yol = Path.GetFullPath(Path.Combine(dizin, kullaniciAdi + ".kilit"));
        DateTime bitis = DateTime.UtcNow + bekleme;
        SemaphoreSlim sem = SurecIci.GetOrAdd(yol, _ => new SemaphoreSlim(1, 1));
        if (!sem.Wait(bekleme))
        {
            throw ZamanAsimi(kullaniciAdi, bekleme, yol);
        }
        try
        {
            Directory.CreateDirectory(dizin);
            int aralik = 20;
            while (true)
            {
                try
                {
                    var fs = new FileStream(yol, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
                    fs.SetLength(0);
                    byte[] pid = Encoding.UTF8.GetBytes(Environment.ProcessId + "\n");
                    fs.Write(pid, 0, pid.Length);
                    fs.Flush();
                    return new BayiKilidi(sem, fs);
                }
                catch (IOException)
                {
                    if (DateTime.UtcNow >= bitis)
                    {
                        throw ZamanAsimi(kullaniciAdi, bekleme, yol);
                    }
                    // Kilit yoklamasının bekleme aralığı (test akışında bekleme değildir; Bekle oradadır).
                    using var olay = new ManualResetEventSlim(false);
                    olay.Wait(aralik);
                    aralik = Math.Min(aralik * 2, 200);
                }
            }
        }
        catch
        {
            sem.Release();
            throw;
        }
    }

    private static InvalidOperationException ZamanAsimi(string kullaniciAdi, TimeSpan bekleme, string yol) =>
        new($"'{kullaniciAdi}' bayisi {(int)bekleme.TotalSeconds} sn içinde serbest kalmadı (kilit: {yol})");

    /// <summary>Kilidi bırakır (birden çok çağrı zararsız).</summary>
    public void Dispose()
    {
        FileStream? fs = Interlocked.Exchange(ref dosya, null);
        if (fs is null)
        {
            return;
        }
        try
        {
            fs.Dispose();
        }
        finally
        {
            surecIci.Release();
        }
    }
}
