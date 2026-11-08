namespace BayiSiparis.Cekirdek.Api;

/// <summary>API çağrısı başarısız oldu. <see cref="Durum"/> 0 ise sunucuya ulaşılamadı.</summary>
public sealed class ApiHatasi : Exception
{
    public ApiHatasi(int durum, string mesaj)
        : base(mesaj)
    {
        Durum = durum;
    }

    public int Durum { get; }
}
