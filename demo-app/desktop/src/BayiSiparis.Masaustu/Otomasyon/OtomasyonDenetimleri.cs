// UI Automation (UIA) dostu yardımcı denetimler. Amaç: Appium NovaWindows sürücüsünün
// AutomationId ile bulduğu elemanların ağaçta deterministik olarak bulunması.
//
// WPF'nin varsayılan davranışındaki üç tuzak ve çözümü:
// 1. Şablon (DataTemplate) içindeki TextBlock'lar UIA "control view"da görünmez (IsControlElement=false).
//    → OtomasyonMetni: her zaman kontrol elemanı, Name = Text.
// 2. Panel/Border gibi elemanların UIA eşi (peer) yoktur; üzerlerindeki AutomationId kaybolur.
//    → OtomasyonGrubu: kendi eşi olan kapsayıcı (Group/List/DataItem…).
// 3. Visibility=Collapsed elemanlar ağaçta kalır (IsOffscreen=true); "yok" ile "gizli" karışır.
//    → Kosullu: koşul yanlışken içerik görsel ağaçtan tamamen çıkarılır (web'deki koşullu render).
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Controls;
using System.Windows.Markup;

namespace BayiSiparis.Masaustu.Otomasyon;

/// <summary>Testlerin metnini doğruladığı eleman. UIA'da Text kontrolü, Name = görünen metin.</summary>
public class OtomasyonMetni : TextBlock
{
    protected override AutomationPeer OnCreateAutomationPeer() => new Es(this);

    private sealed class Es(TextBlock sahip) : TextBlockAutomationPeer(sahip)
    {
        protected override bool IsControlElementCore() => true;

        protected override string GetClassNameCore() => nameof(OtomasyonMetni);
    }
}

/// <summary>AutomationId taşıyan kapsayıcı (web'deki data-testid'li div/article/tr/table karşılığı).</summary>
public class OtomasyonGrubu : Decorator
{
    public static readonly DependencyProperty TurProperty = DependencyProperty.Register(
        nameof(Tur), typeof(AutomationControlType), typeof(OtomasyonGrubu), new PropertyMetadata(AutomationControlType.Group));

    /// <summary>UIA kontrol türü (varsayılan Group).</summary>
    public AutomationControlType Tur
    {
        get => (AutomationControlType)GetValue(TurProperty);
        set => SetValue(TurProperty, value);
    }

    protected override AutomationPeer OnCreateAutomationPeer() => new GrupEsi(this, () => Tur, nameof(OtomasyonGrubu));
}

/// <summary>
/// Sanallaştırmasız liste. ItemsControl'ün varsayılan sarmalayıcı eşi (DataItem + ToString adları) yerine
/// görsel ağacı olduğu gibi yayınlar: liste → öğe şablonundaki OtomasyonGrubu (ör. product-card-P-001).
/// Paneli StackPanel'dir (VirtualizingStackPanel değil): tüm öğeler kaydırma dışındayken de ağaçtadır.
/// </summary>
public class OtomasyonListesi : ItemsControl
{
    protected override AutomationPeer OnCreateAutomationPeer() =>
        new GrupEsi(this, () => AutomationControlType.List, nameof(OtomasyonListesi));
}

/// <summary>
/// Kapsayıcı eşi. ScrollItem desenini destekler: kaydırma alanının dışında kalan kart/satır, sürücü
/// (ScrollIntoView) tarafından görünür alana getirilebilir (web'de Playwright'ın otomatik kaydırması karşılığı).
/// </summary>
internal sealed class GrupEsi(FrameworkElement sahip, Func<AutomationControlType> tur, string sinif)
    : FrameworkElementAutomationPeer(sahip), IScrollItemProvider
{
    public override object? GetPattern(PatternInterface desen) =>
        desen == PatternInterface.ScrollItem ? this : base.GetPattern(desen);

    public void ScrollIntoView() => ((FrameworkElement)Owner).BringIntoView();

    protected override AutomationControlType GetAutomationControlTypeCore() => tur();

    protected override string GetClassNameCore() => sinif;

    protected override bool IsControlElementCore() => true;

    protected override bool IsContentElementCore() => true;
}

/// <summary>
/// Koşullu içerik: <see cref="Goster"/> yanlışken içerik görsel ve UIA ağacında yoktur
/// (Appium'da "bulunamadı"); doğruyken eklenir. Web'deki {kosul &amp;&amp; &lt;Eleman/&gt;} karşılığı.
/// </summary>
[ContentProperty(nameof(Icerik))]
public class Kosullu : Decorator
{
    public static readonly DependencyProperty GosterProperty = DependencyProperty.Register(
        nameof(Goster), typeof(bool), typeof(Kosullu), new PropertyMetadata(false, (d, _) => ((Kosullu)d).Guncelle()));

    public static readonly DependencyProperty IcerikProperty = DependencyProperty.Register(
        nameof(Icerik), typeof(UIElement), typeof(Kosullu), new PropertyMetadata(null, (d, _) => ((Kosullu)d).Guncelle()));

    public bool Goster
    {
        get => (bool)GetValue(GosterProperty);
        set => SetValue(GosterProperty, value);
    }

    public UIElement? Icerik
    {
        get => (UIElement?)GetValue(IcerikProperty);
        set => SetValue(IcerikProperty, value);
    }

    private void Guncelle()
    {
        var hedef = Goster ? Icerik : null;
        if (!ReferenceEquals(Child, hedef))
        {
            Child = hedef;
        }
    }
}
