using System.Windows;
using System.Windows.Controls;
using BayiSiparis.Cekirdek.GorunumModelleri;

namespace BayiSiparis.Masaustu.Gorunumler;

public partial class GirisEkrani : UserControl
{
    public GirisEkrani()
    {
        InitializeComponent();
        Loaded += (_, _) => KullaniciAdiKutusu.Focus();
    }

    // PasswordBox.Password bağlanabilir değildir (güvenlik gereği); değer görünüm modeline elle aktarılır.
    private void ParolaDegisti(object sender, RoutedEventArgs e)
    {
        if (DataContext is GirisGorunumModeli gm)
        {
            gm.Parola = ParolaKutusu.Password;
        }
    }
}
