using System.Threading.Tasks;
using Microsoft.Playwright;
using static Antreklabs.Bayi.Pages.Kimlikler;
using static Microsoft.Playwright.Assertions;

namespace Antreklabs.Bayi.Pages;

/// <summary>Bayi giriş sayfası.</summary>
public class LoginPage : Ekran
{
    public LoginPage(IPage page)
        : base(page)
    {
    }

    /// <summary>Giriş sayfasını açar.</summary>
    public async Task GotoAsync()
    {
        await GitAsync(LoginYolu);
        await DogrulaAsync(() => Expect(Kimlik(Login.USERNAME)).ToBeVisibleAsync());
    }

    /// <summary>Kullanıcı adı ve parolayı girip giriş yapar.</summary>
    public async Task LoginAsync(string username, string password)
    {
        await Kimlik(Login.USERNAME).FillAsync(username);
        await Kimlik(Login.PASSWORD).FillAsync(password);
        await Kimlik(Login.SUBMIT).ClickAsync();
    }

    /// <summary>Oturumu kapatır.</summary>
    public async Task LogoutAsync()
    {
        await Kimlik(Nav.LOGOUT).ClickAsync();
    }

    /// <summary>Giriş hatası mesajının verilen metin olduğunu doğrular.</summary>
    public async Task ExpectLoginErrorAsync(string message)
    {
        await DogrulaAsync(() => Expect(Kimlik(Login.ERROR)).ToHaveTextAsync(message));
    }

    /// <summary>Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular.</summary>
    public async Task ExpectLoggedInAsync(string dealerName)
    {
        await DogrulaAsync(() => Expect(Kimlik(Nav.CURRENT_DEALER)).ToHaveTextAsync(dealerName));
        await DogrulaYolAsync(CatalogYolu);
    }

    /// <summary>Giriş sayfasında olunduğunu doğrular.</summary>
    public async Task ExpectOnLoginPageAsync()
    {
        await DogrulaYolAsync(LoginYolu);
        await DogrulaAsync(() => Expect(Kimlik(Login.SUBMIT)).ToBeVisibleAsync());
    }
}
