using Microsoft.Playwright;

namespace Antreklabs.Bayi.Pages;

/// <summary>Page object tabanı.</summary>
public abstract class Ekran
{
    protected readonly IPage Sayfa;

    protected Ekran(IPage page) => Sayfa = page;

    public void TabanMetodu()
    {
    }
}
