using System;
using System.IO;

namespace Antreklabs.Bayi.Birim;

/// <summary>Birim testlerinin kaynak dosyalarına erişimi: proje kökü (csproj'un dizini) ve demo-app.</summary>
internal static class ProjeYolu
{
    public static string Kok
    {
        get
        {
            var d = new DirectoryInfo(AppContext.BaseDirectory);
            while (d is not null && !File.Exists(Path.Combine(d.FullName, "Antreklabs.Bayi.E2eApp.csproj")))
            {
                d = d.Parent;
            }
            return d?.FullName ?? throw new InvalidOperationException("proje kökü bulunamadı (Antreklabs.Bayi.E2eApp.csproj)");
        }
    }

    /// <summary><c>demo-app/</c> dizini.</summary>
    public static string DemoApp => Path.GetFullPath(Path.Combine(Kok, ".."));
}
