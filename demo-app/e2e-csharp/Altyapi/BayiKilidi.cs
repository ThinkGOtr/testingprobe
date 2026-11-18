using System;
using System.Collections.Concurrent;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Bayiyi bir test süresince özel alır (TS: tests/fixtures.ts <c>acquireDealer</c>, Java:
/// <c>BayiKilidi</c>). Aynı uygulamaya karşı koşan süreçler (yerel koşu ve test-runner) ve aynı
/// süreçteki paralel testler aynı bayiyi aynı anda sıfırlamasın diye işletim sistemi dosya kilidi
/// (<see cref="FileShare.None"/> ile açılmış dosya) kullanılır; süreç ölünce kilit kendiliğinden düşer.
/// Aynı süreçteki testler önce bir <see cref="SemaphoreSlim"/> ile sıraya girer.
/// </summary>
public sealed class BayiKilidi : IDisposable
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> SurecIci = new();

    private readonly SemaphoreSlim _surecIci;
    private FileStream? _dosya;

    private BayiKilidi(SemaphoreSlim surecIci, FileStream dosya)
    {
        _surecIci = surecIci;
        _dosya = dosya;
    }

    /// <summary>Aynı uygulamaya (web + API adresi) karşı koşan süreçlerin paylaştığı kilit dizini.</summary>
    public static string Dizin(string baseUrl, string demoApiUrl)
    {
        var ozet = SHA256.HashData(Encoding.UTF8.GetBytes($"web-csharp|{baseUrl}|{demoApiUrl}"));
        var kisa = Convert.ToHexString(ozet)[..12].ToLowerInvariant();
        return Path.Combine(Path.GetTempPath(), $"demoapp-e2e-csharp-kilit-{kisa}");
    }

    /// <summary>Bayi kilidini alır; <paramref name="bekleme"/> içinde alınamazsa açıklayıcı hata.</summary>
    public static BayiKilidi Al(string dizin, string kullaniciAdi, TimeSpan bekleme)
    {
        var dosyaYolu = Path.GetFullPath(Path.Combine(dizin, kullaniciAdi + ".kilit"));
        var bitis = DateTime.UtcNow + bekleme;
        var sem = SurecIci.GetOrAdd(dosyaYolu, _ => new SemaphoreSlim(1, 1));
        if (!sem.Wait(bekleme))
        {
            throw ZamanAsimi(kullaniciAdi, bekleme, dosyaYolu);
        }
        try
        {
            Directory.CreateDirectory(dizin);
            var aralik = TimeSpan.FromMilliseconds(20);
            while (true)
            {
                try
                {
                    var fs = new FileStream(dosyaYolu, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
                    fs.SetLength(0);
                    var pid = Encoding.UTF8.GetBytes(Environment.ProcessId + "\n");
                    fs.Write(pid, 0, pid.Length);
                    fs.Flush();
                    return new BayiKilidi(sem, fs);
                }
                catch (IOException) when (DateTime.UtcNow < bitis)
                {
                    // Başka süreç tutuyor: kısa aralıklarla yeniden dene (kilit yoklaması; test akışında bekleme değildir).
                    Thread.Sleep(aralik);
                    aralik = TimeSpan.FromMilliseconds(Math.Min(aralik.TotalMilliseconds * 2, 200));
                }
                catch (IOException)
                {
                    throw ZamanAsimi(kullaniciAdi, bekleme, dosyaYolu);
                }
            }
        }
        catch
        {
            sem.Release();
            throw;
        }
    }

    private static InvalidOperationException ZamanAsimi(string kullaniciAdi, TimeSpan bekleme, string dosya) =>
        new($"'{kullaniciAdi}' bayisi {(int)bekleme.TotalSeconds} sn içinde serbest kalmadı (kilit: {dosya})");

    /// <summary>Kilidi bırakır (birden çok çağrı zararsız).</summary>
    public void Dispose()
    {
        var fs = Interlocked.Exchange(ref _dosya, null);
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
            _surecIci.Release();
        }
    }
}
