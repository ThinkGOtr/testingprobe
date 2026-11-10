// Uygulama girişi: API adresini çözer, kabuk görünüm modelini kurar, ana pencereyi açar.
using System.IO;
using System.Windows;
using System.Windows.Threading;
using BayiSiparis.Cekirdek;
using BayiSiparis.Cekirdek.Api;
using BayiSiparis.Cekirdek.GorunumModelleri;

namespace BayiSiparis.Masaustu;

public partial class App : Application
{
    private ApiIstemcisi? _api;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += BeklenmeyenHata;

        string tabanAdres;
        try
        {
            var ayarDosyasi = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
            var json = File.Exists(ayarDosyasi) ? File.ReadAllText(ayarDosyasi) : null;
            tabanAdres = ApiAyarlari.Coz(e.Args, Environment.GetEnvironmentVariable(ApiAyarlari.OrtamDegiskeni), json);
        }
        catch (ArgumentException hata)
        {
            MessageBox.Show(hata.Message, AnaGorunumModeli.UygulamaAdi, MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(2);
            return;
        }

        // Kabuk, 401 bildirimlerini arayüz iş parçacığına bu bağlam üzerinden taşır.
        if (SynchronizationContext.Current is not DispatcherSynchronizationContext)
        {
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(Dispatcher));
        }

        _api = new ApiIstemcisi(tabanAdres);
        var kabuk = new AnaGorunumModeli(_api);
        var pencere = new AnaPencere { DataContext = kabuk };
        MainWindow = pencere;
        pencere.Show();
        await kabuk.BaslatAsync();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _api?.Dispose();
        base.OnExit(e);
    }

    private static void BeklenmeyenHata(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        // Demo uygulaması: beklenmeyen hata kullanıcıya gösterilir, uygulama açık kalır.
        MessageBox.Show(
            "Beklenmeyen bir hata oluştu.\n\n" + e.Exception.Message,
            AnaGorunumModeli.UygulamaAdi,
            MessageBoxButton.OK,
            MessageBoxImage.Error);
        e.Handled = true;
    }
}
