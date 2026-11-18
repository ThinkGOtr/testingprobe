using System.Threading.Tasks;
using Microsoft.Playwright;
using static Antreklabs.Bayi.Pages.Kimlikler;

namespace Antreklabs.Bayi.Pages;

/// <summary>Bayi giriş sayfası. İkinci cümle.</summary>
public class LoginPage : Ekran
{
    public LoginPage(IPage page) : base(page)
    {
    }

    /// <summary>Giriş sayfasını açar.</summary>
    public async Task GotoAsync() => await Sayfa.GotoAsync("/giris");

    /// <summary>Kullanıcı adı ve parolayla giriş yapar.</summary>
    public async Task LoginAsync(string username, string password)
    {
        await Sayfa.GetByTestId(Login.USERNAME).FillAsync(username);
        await Sayfa.GetByTestId(Kimlikler.Login.PASSWORD).FillAsync(password);
        await Sayfa.GetByTestId(Login.SUBMIT).ClickAsync();
    }

    public static Task StatikAsync() => Task.CompletedTask;

    private Task GizliAsync() => Task.CompletedTask;
}
