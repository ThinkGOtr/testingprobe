using System;
using System.IO;

namespace Antreklabs.Bayi.Birim;

/// <summary>Birim testlerinin dosya kökleri (çalışma dizini bin/ altı olduğundan proje kökü yukarı doğru aranır).</summary>
internal static class Kok
{
    private static readonly Lazy<string> ProjeKoku = new(() =>
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null && !File.Exists(Path.Combine(d.FullName, "Antreklabs.Bayi.E2e.csproj")))
        {
            d = d.Parent;
        }
        return d?.FullName ?? throw new InvalidOperationException("e2e-csharp proje kökü bulunamadı");
    });

    /// <summary><c>demo-app/e2e-csharp</c>.</summary>
    public static string Proje => ProjeKoku.Value;

    /// <summary><c>demo-app</c>.</summary>
    public static string DemoApp => Path.GetFullPath(Path.Combine(Proje, ".."));

    /// <summary>Depo kökü.</summary>
    public static string Depo => Path.GetFullPath(Path.Combine(Proje, "..", ".."));
}
