using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shell;
using Microsoft.Web.WebView2.Core;

namespace RuZh.Subtitles.Host;

internal sealed class SubtitleWindow : Window
{
    internal const int DefaultBackgroundOpacity = 45;
    internal const int DefaultTextOpacity = 100;

    private readonly LocalPage page;
    private int backgroundOpacity = DefaultBackgroundOpacity;
    private int textOpacity = DefaultTextOpacity;

    internal bool CanOpenSettings => IsVisible && WindowState != WindowState.Minimized &&
        page.IsReady && backgroundOpacity > 0;

    internal SubtitleWindow(Task<CoreWebView2Environment> environment, Action openSettings, Action hideSubtitle, Action<string> report)
    {
        Title = "俄中实时字幕";
        Width = 680;
        Height = 140;
        MinWidth = 420;
        MinHeight = 108;
        Rect workArea = SystemParameters.WorkArea;
        Left = workArea.Left + (workArea.Width - Width) / 2;
        Top = workArea.Bottom - Height - 40;
        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.CanResize;
        Background = Brushes.Transparent;
        AllowsTransparency = true;
        Topmost = true;
        WindowChrome.SetWindowChrome(this, new WindowChrome
        {
            CaptionHeight = 0,
            ResizeBorderThickness = new Thickness(6),
            GlassFrameThickness = new Thickness(0),
            CornerRadius = new CornerRadius(0)
        });

        page = new LocalPage(this, "subtitle.html", environment, report, ApplyAppearance);
        var grip = new Border
        {
            Background = Brushes.Transparent,
            Height = 14,
            Width = 180,
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top,
            Margin = new Thickness(40, 0, 0, 0),
            Cursor = Cursors.SizeAll,
            ToolTip = "拖动字幕。右键打开设置"
        };
        grip.MouseLeftButtonDown += (_, e) => { if (e.ClickCount == 1) DragMove(); };
        var menu = new ContextMenu();
        var settingsItem = new MenuItem { Header = "打开设置" };
        settingsItem.Click += (_, _) => openSettings();
        var hideItem = new MenuItem { Header = "隐藏字幕" };
        hideItem.Click += (_, _) => hideSubtitle();
        menu.Items.Add(settingsItem);
        menu.Items.Add(hideItem);
        grip.ContextMenu = menu;
        page.Surface.Children.Add(grip);
        Content = page.Surface;

        SizeChanged += (_, _) => report($"Subtitle size {ActualWidth:F0}x{ActualHeight:F0} DIP");
        LocationChanged += (_, _) => report($"Subtitle position ({Left:F0},{Top:F0}) DIP");
    }

    internal async Task SetAppearance(int background, int text)
    {
        backgroundOpacity = background;
        textOpacity = text;
        await ApplyAppearance();
    }

    private Task ApplyAppearance()
    {
        string background = JsonSerializer.Serialize(backgroundOpacity / 100d);
        string hideMaterial = backgroundOpacity == 0 ? ".subtitle-material{display:none!important}" : "";
        string css = $".subtitle-card{{width:100%;height:100%;--subtitle-background-opacity:{background}!important}}" +
            hideMaterial + $".subtitle-appearance{{opacity:{textOpacity}%!important}}";
        return page.ApplyStyle(css);
    }
}
