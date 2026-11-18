using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Antreklabs.Tp.CsAraclar;

/// <summary>
/// Kimlik onarımı (java-araclar KimlikYamasi karşılığı; yalnızca kimlik değeri değişir).
/// - `Bul`: bir kimlik değerini taşıyan sabitler.
/// - `Yamala`: Kimlikler.cs'de YALNIZCA o sabitin literal içeriğini değiştirir; sonuç belirteç
///   düzeyinde yeniden doğrulanır (`Fark`) ve tek satır farkı olmalıdır.
/// - `Fark`: iki Kimlikler.cs sürümü arasında yalnızca kimlik literal'lerinin değiştiğini doğrular.
/// </summary>
public static class KimlikYamasi
{
    public sealed class YamaHatasi : Exception
    {
        public YamaHatasi(string mesaj) : base(mesaj) { }
    }

    /// <summary>Kökteki Kimlikler dosyaları (göreli): `Pages/Kimlikler.cs` ve/veya `Ekranlar/Kimlikler.cs`.</summary>
    public static List<string> KimlikDosyalari(string kok)
    {
        var tam = Path.GetFullPath(kok);
        if (!Directory.Exists(tam)) throw new IOException("kök dizini okunamadı: " + kok);
        var cikti = new List<string>();
        foreach (var p in new[] { Kaynaklar.WEB, Kaynaklar.WINDOWS })
        {
            var y = KimlikDosyasi.Yol(p);
            var f = Path.Combine(tam, y);
            if (File.Exists(f) && new FileInfo(f).LinkTarget == null) cikti.Add(y);
        }
        if (cikti.Count == 0) throw new IOException("Kimlikler.cs bulunamadı (Pages/ ya da Ekranlar/)");
        return cikti;
    }

    public static Harita Bul(string kok, string testId)
    {
        var eslesen = new List<Harita>();
        foreach (var g in KimlikDosyalari(kok))
        {
            var s = KimlikDosyasi.Coz(Kaynaklar.Oku(Path.Combine(kok, g)));
            foreach (var k in s.Kimlikler.Values)
            {
                bool tam = k.TestIdDegeri == testId;
                bool onekle = k.Onek && testId.StartsWith(k.TestIdDegeri, StringComparison.Ordinal);
                if (!tam && !onekle) continue;
                eslesen.Add(new Harita
                {
                    ["key"] = k.Anahtar, ["testId"] = k.TestIdDegeri, ["prefix"] = k.Onek,
                    ["intent"] = k.Niyet, ["file"] = g, ["line"] = k.Satir,
                });
            }
        }
        return new Harita { ["ok"] = true, ["test_id"] = testId, ["matches"] = eslesen };
    }

    public static Harita Yamala(string kok, string? eski, string? yeni, string? anahtar, string? onekYol)
    {
        if (eski == null || !KimlikDosyasi.TestId.IsMatch(eski)) throw new YamaHatasi("eski kimlik geçersiz: " + eski);
        if (yeni == null || !KimlikDosyasi.TestId.IsMatch(yeni)) throw new YamaHatasi("yeni kimlik geçersiz: " + yeni);
        if (eski == yeni) throw new YamaHatasi("eski ve yeni kimlik aynı");

        var adaylar = new List<(string dosya, string metin, KimlikDosyasi.Kimlik k)>();
        var hepsi = new List<KimlikDosyasi.Kimlik>();
        foreach (var g in KimlikDosyalari(kok))
        {
            var metin = Kaynaklar.Oku(Path.Combine(Path.GetFullPath(kok), g));
            var s = KimlikDosyasi.Coz(metin);
            hepsi.AddRange(s.Kimlikler.Values);
            foreach (var k in s.Kimlikler.Values)
            {
                if (k.TestIdDegeri != eski) continue;
                if (!string.IsNullOrEmpty(anahtar) && !(k.Anahtar == anahtar || k.Anahtar.EndsWith("." + anahtar, StringComparison.Ordinal)))
                    continue;
                if (!s.Saf) throw new YamaHatasi($"{g} saf veri değil ({s.Hatalar[0].Mesaj}); yama üretilmez");
                adaylar.Add((g, metin, k));
            }
        }
        if (adaylar.Count == 0) throw new YamaHatasi($"'{eski}' kimliğini taşıyan sabit bulunamadı");
        if (adaylar.Count > 1)
            throw new YamaHatasi($"'{eski}' birden çok sabitte geçiyor ({string.Join(", ", adaylar.Select(a => a.k.Anahtar))}); --key ile seçin");
        var (dosya, kaynak, hedef) = adaylar[0];
        if (hedef.Onek) throw new YamaHatasi(hedef.Anahtar + " önek kimliktir (_ONEK); onarım kapsamı dışı");
        foreach (var d in hepsi)
        {
            if (ReferenceEquals(d, hedef)) continue;
            if (d.TestIdDegeri == yeni || (d.Onek && yeni.StartsWith(d.TestIdDegeri, StringComparison.Ordinal)))
                throw new YamaHatasi($"'{yeni}' başka bir kimliğin değeri ya da öneki ({d.Anahtar})");
        }
        var lit = hedef.Literal;
        if (lit.Text != "\"" + eski + "\"")
            throw new YamaHatasi(hedef.Anahtar + " literal'i kaçış dizisi içeriyor; metin düzeyinde güvenle değiştirilemez");
        var span = lit.Span;
        var sonuc = kaynak[..span.Start] + "\"" + yeni + "\"" + kaynak[span.End..];

        var fark = Fark(kaynak, sonuc, dosya);
        if (!(bool)fark["ok"]!) throw new YamaHatasi("yama doğrulanamadı: " + fark["summary"]);
        var once = Satirlar(kaynak);
        var sonra = Satirlar(sonuc);
        if (once.Count != sonra.Count) throw new YamaHatasi("yama satır sayısını değiştirdi");
        int degisen = -1;
        for (int i = 0; i < once.Count; i++)
        {
            if (once[i] == sonra[i]) continue;
            if (degisen >= 0) throw new YamaHatasi("yama birden çok satırı değiştirdi");
            degisen = i;
        }
        if (degisen < 0) throw new YamaHatasi("yama hiçbir satırı değiştirmedi");
        var yol = string.IsNullOrEmpty(onekYol) ? dosya : onekYol.TrimEnd('/') + "/" + dosya;
        return new Harita
        {
            ["ok"] = true, ["file"] = dosya, ["key"] = hedef.Anahtar, ["line"] = degisen + 1,
            ["before"] = eski, ["after"] = yeni, ["diff"] = BirlesikFark(yol, once, sonra, degisen), ["content"] = sonuc,
        };
    }

    /// <summary>İki Kimlikler.cs sürümü: yalnızca kimlik literal'leri değişebilir (repair modu).</summary>
    public static Harita Fark(string taban, string bas, string dosya)
    {
        var ihlaller = new List<Harita>();
        var degisimler = new List<Harita>();
        var ts = KimlikDosyasi.Coz(taban);
        var hs = KimlikDosyasi.Coz(bas);
        if (!ts.Saf)
            ihlaller.Add(Kaynaklar.Ihlal("base_not_pure", dosya, ts.Hatalar[0].Satir, "taban Kimlikler.cs saf veri değil: " + ts.Hatalar[0].Mesaj));
        foreach (var h in hs.Hatalar) ihlaller.Add(Kaynaklar.Ihlal(h.Kod, dosya, h.Satir, h.Mesaj));
        if (ihlaller.Count == 0)
        {
            var tlit = ts.Kimlikler.Values.ToDictionary(k => k.Literal.SpanStart);
            var hlit = hs.Kimlikler.Values.ToDictionary(k => k.Literal.SpanStart);
            var a = Belirtecler(taban);
            var b = Belirtecler(bas);
            int n = Math.Min(a.Count, b.Count);
            bool yapi = false;
            for (int i = 0; i < n; i++)
            {
                var x = a[i];
                var y = b[i];
                if (x.ToFullString() == y.ToFullString()) continue;
                tlit.TryGetValue(x.SpanStart, out var kx);
                hlit.TryGetValue(y.SpanStart, out var ky);
                int satir = Kaynaklar.Satir(y);
                bool sadeceLiteral = kx != null && ky != null && kx.Anahtar == ky.Anahtar
                    && x.LeadingTrivia.ToFullString() == y.LeadingTrivia.ToFullString()
                    && x.TrailingTrivia.ToFullString() == y.TrailingTrivia.ToFullString();
                if (!sadeceLiteral)
                {
                    ihlaller.Add(Kaynaklar.Ihlal("non_testid_change", dosya, satir,
                        $"kimlik literal'i dışında değişiklik: '{Kaynaklar.TekSatir(x.ToFullString(), 60)}' → '{Kaynaklar.TekSatir(y.ToFullString(), 60)}'"));
                    yapi = true;
                    break;
                }
                if (kx!.Onek)
                    ihlaller.Add(Kaynaklar.Ihlal("prefix_changed", dosya, satir, kx.Anahtar + ": önek kimlik (_ONEK) onarımla değiştirilemez"));
                degisimler.Add(new Harita { ["file"] = dosya, ["entry"] = kx.Anahtar, ["before"] = kx.TestIdDegeri, ["after"] = ky!.TestIdDegeri });
            }
            if (a.Count != b.Count && !yapi)
                ihlaller.Add(Kaynaklar.Ihlal("non_testid_change", dosya, 0, "belirteç sayısı değişti (yapı değişikliği)"));
        }
        bool noop = taban == bas;
        var cf = new List<Harita>();
        if (!noop) cf.Add(new Harita { ["path"] = dosya, ["status"] = "modified", ["locator"] = true });
        bool ok = ihlaller.Count == 0;
        return new Harita
        {
            ["tool"] = "cs-araclar", ["schema_version"] = 1, ["mode"] = "repair", ["ok"] = ok, ["noop"] = noop,
            ["root"] = ".", ["changed_files"] = cf, ["testid_changes"] = degisimler,
            ["added_entries"] = new List<object>(), ["removed_entries"] = new List<object>(), ["violations"] = ihlaller,
            ["summary"] = (ok ? "Kimlik koruması geçti (mod: repair)" : "Kimlik koruması başarısız (mod: repair)")
                + " · kimlik değişikliği: " + degisimler.Count + (ok ? "" : " · ihlal: " + ihlaller.Count),
        };
    }

    /// <summary>Belirteçler (dosya sonu dahil; trivia ToFullString ile karşılaştırılır).</summary>
    static List<SyntaxToken> Belirtecler(string metin)
    {
        var kok = Kaynaklar.Ayristir(metin).GetRoot();
        var l = kok.DescendantTokens(descendIntoTrivia: false).ToList();
        if (string.Concat(l.Select(t => t.ToFullString())) != metin)
            throw new InvalidOperationException("kaynak belirteçlerden aynen yeniden kurulamadı");
        return l;
    }

    internal static List<string> Satirlar(string s)
    {
        var cikti = new List<string>();
        int bas = 0;
        for (int i = 0; i < s.Length; i++)
        {
            char c = s[i];
            if (c != '\n' && c != '\r') continue;
            if (c == '\r' && i + 1 < s.Length && s[i + 1] == '\n') i++;
            cikti.Add(s[bas..(i + 1)]);
            bas = i + 1;
        }
        if (bas < s.Length) cikti.Add(s[bas..]);
        return cikti;
    }

    static string BirlesikFark(string yol, List<string> once, List<string> sonra, int i)
    {
        int bas = Math.Max(0, i - 1);
        int son = Math.Min(once.Count, i + 2);
        var sb = new StringBuilder();
        sb.Append("--- a/").Append(yol).Append('\n');
        sb.Append("+++ b/").Append(yol).Append('\n');
        var aralik = son - bas == 1 ? (bas + 1).ToString() : $"{bas + 1},{son - bas}";
        sb.Append("@@ -").Append(aralik).Append(" +").Append(aralik).Append(" @@\n");
        for (int j = bas; j < son; j++)
        {
            if (j == i)
            {
                sb.Append('-').Append(SonSatir(once[j]));
                sb.Append('+').Append(SonSatir(sonra[j]));
            }
            else sb.Append(' ').Append(SonSatir(once[j]));
        }
        return sb.ToString();
    }

    static string SonSatir(string s) => s.EndsWith('\n') || s.EndsWith('\r') ? s : s + "\n\\ No newline at end of file\n";
}
