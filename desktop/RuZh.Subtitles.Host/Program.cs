using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shell;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace RuZh.Subtitles.Host;

// Phase 3 slice 1 only. No engine, preferences, tray, settings window or IPC.
internal sealed class App : Application
{
    [STAThread]
    public static void Main() => new App().Run(new ExperimentControls());
}

internal sealed class SubtitleExperiment : Window
{
    private readonly WebView2CompositionControl web = new() { DefaultBackgroundColor = System.Drawing.Color.Transparent };
    private readonly TextBlock overlay = new()
    {
        Text = "WPF overlay", Background = Brushes.DarkGreen, Foreground = Brushes.White,
        HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Bottom,
        Margin = new Thickness(10), Padding = new Thickness(5), Visibility = Visibility.Collapsed,
        IsHitTestVisible = false
    };
    private readonly Action<string> report;
    private readonly bool layered;
    private int material = 3; // DWMSBT_TRANSIENTWINDOW: documented Desktop Acrylic.
    private int backgroundOpacity = 45;
    private int textOpacity = 100;
    private bool longSample;
    private bool loaded;
    private bool closed;

    internal SubtitleExperiment(Action<string> report, bool layered)
    {
        this.report = report;
        this.layered = layered;
        Title = layered ? "RU-ZH layered transparency experiment" : "RU-ZH native composition experiment";
        Width = 680; Height = 140; MinWidth = 420; MinHeight = 108;
        Left = 340; Top = 440;
        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.CanResize;
        Background = Brushes.Transparent;
        // WPF chooses the top-level HWND composition path before it is created.
        AllowsTransparency = layered;
        Topmost = true;
        WindowChrome.SetWindowChrome(this, new WindowChrome
        {
            CaptionHeight = 0, ResizeBorderThickness = new Thickness(6),
            GlassFrameThickness = new Thickness(layered ? 0 : -1), CornerRadius = new CornerRadius(0)
        });
        var grid = new Grid();
        grid.Children.Add(web);
        // Small experimental drag grip. Does not intercept text or toolbar buttons.
        var grip = new Border
        {
            Background = Brushes.Transparent, Height = 14, Width = 180,
            HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top,
            Margin = new Thickness(40, 0, 0, 0), Cursor = Cursors.SizeAll,
            ToolTip = "Experiment: drag here; resize at the window edges"
        };
        grip.MouseLeftButtonDown += (_, e) => { if (e.ClickCount == 1) DragMove(); };
        grid.Children.Add(grip);
        grid.Children.Add(overlay);
        Content = grid;
        SourceInitialized += (_, _) =>
        {
            var source = (HwndSource)PresentationSource.FromVisual(this);
            source.CompositionTarget.BackgroundColor = Colors.Transparent;
            report($"Host mode: AllowsTransparency={AllowsTransparency}; layered={layered}; IsVisible={IsVisible}");
            if (layered) return; // No DWM frame or material in the layered comparison.
            int dark = 1, corner = 2;
            DwmSetWindowAttribute(source.Handle, 20, ref dark, sizeof(int));
            DwmSetWindowAttribute(source.Handle, 33, ref corner, sizeof(int));
            var margins = new Margins { Left = -1, Right = -1, Top = -1, Bottom = -1 };
            report($"DwmExtendFrame=0x{DwmExtendFrameIntoClientArea(source.Handle, ref margins):X8}");
            ApplyMaterial();
        };
        Loaded += async (_, _) =>
        {
            try
            {
                var profile = Path.Combine(AppContext.BaseDirectory, "WebView2Profile");
                var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: profile);
                if (closed) return;
                await web.EnsureCoreWebView2Async(environment);
                if (closed) return;
                web.CoreWebView2.SetVirtualHostNameToFolderMapping("subtitle.example", Path.Combine(AppContext.BaseDirectory, "web"), CoreWebView2HostResourceAccessKind.DenyCors);
                web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                web.CoreWebView2.NavigationStarting += (_, args) =>
                {
                    if (!args.Uri.StartsWith("https://subtitle.example/", StringComparison.Ordinal)) args.Cancel = true;
                };
                web.CoreWebView2.NewWindowRequested += (_, args) => args.Handled = true;
                web.CoreWebView2.ProcessFailed += (_, args) => report($"WebView process failure: {args.ProcessFailedKind}");
                web.CoreWebView2.NavigationCompleted += async (_, args) =>
                {
                    loaded = args.IsSuccess;
                    report($"Navigation success={args.IsSuccess}, error={args.WebErrorStatus}; runtime={web.CoreWebView2.Environment.BrowserVersionString}");
                    if (!loaded) return;
                    await UpdatePageVisibility();
                };
                NavigateSample();
            }
            catch (Exception ex) { if (!closed) report($"Initialization failed: {ex}"); }
        };
        SizeChanged += (_, _) => GeometryReport();
        LocationChanged += (_, _) => GeometryReport();
        Activated += (_, _) => report("Subtitle activated");
        Deactivated += (_, _) => report("Subtitle deactivated (observe native inactive material)");
        Closed += (_, _) => { closed = true; loaded = false; web.Dispose(); report("Subtitle closed"); };
    }

    private void GeometryReport() => report($"Geometry DIP: ({Left:F0},{Top:F0}) {ActualWidth:F0}x{ActualHeight:F0}; DPI={VisualTreeHelper.GetDpi(this).DpiScaleX:F2}; topmost={Topmost}");
    internal void SetMaterial(int value) { material = value; ApplyMaterial(); }
    private void ApplyMaterial()
    {
        if (layered) return;
        var hwnd = new WindowInteropHelper(this).Handle;
        if (hwnd == IntPtr.Zero) return;
        int value = backgroundOpacity == 0 ? 1 : material;
        int hr = DwmSetWindowAttribute(hwnd, 38, ref value, sizeof(int));
        report($"DWM_SYSTEMBACKDROP_TYPE={value}; HRESULT=0x{hr:X8}; background={backgroundOpacity}% (success alone does not prove transparency)");
    }
    internal async Task SetAppearance(int background, int text)
    {
        backgroundOpacity = Math.Clamp(background, 0, 100);
        textOpacity = Math.Clamp(text, 0, 100);
        ApplyMaterial();
        await UpdatePageVisibility();
        report($"Appearance: background={backgroundOpacity}%, text={textOpacity}%; host visible={IsVisible}; layered={layered}");
    }
    private async Task UpdatePageVisibility()
    {
        if (!loaded) return;
        // Experiment-only overrides reuse the existing material and appearance layers.
        // Do not hide the HTML root or disturb SubtitleText's transition opacity.
        string css = ".subtitle-card{width:100%;height:100%;--subtitle-background-opacity:" + JsonSerializer.Serialize(backgroundOpacity / 100d) + "!important}" +
            (backgroundOpacity == 0 ? ".subtitle-material{display:none!important}" : "") +
            $".subtitle-appearance{{opacity:{textOpacity}%!important}}";
        var result = await RunScript($"(()=>{{let s=document.getElementById('native-experiment-style');if(!s){{s=document.createElement('style');s.id='native-experiment-style';document.head.append(s)}}s.textContent={JsonSerializer.Serialize(css)};return 'applied'}})()");
        if (result != null && result != "\"applied\"") report("Appearance script did not apply: " + result);
    }
    private async Task<string?> RunScript(string script)
    {
        if (!loaded || closed) return null;
        try { return await web.ExecuteScriptAsync(script); }
        catch (Exception ex) { if (!closed) report("Script failed: " + ex.Message); return null; }
    }
    internal void SetLongSample(bool value) { longSample = value; if (loaded) NavigateSample(); }
    private void NavigateSample() => web.Source = new Uri($"https://subtitle.example/subtitle.html?sample={(longSample ? "long" : "short")}");
    internal void SetOverlay(bool value) => overlay.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    internal async Task InspectPage()
    {
        if (!loaded) { report("Page not ready"); return; }
        var page = await RunScript("JSON.stringify({url:location.href,status:document.querySelector('.subtitle-card')?.dataset.status,canvas:!!document.querySelector('.preview'),background:getComputedStyle(document.body).backgroundColor,rootOpacity:getComputedStyle(document.documentElement).opacity,materialDisplay:getComputedStyle(document.querySelector('.subtitle-material')).display,textOpacity:getComputedStyle(document.querySelector('.subtitle-appearance')).opacity,text:document.querySelector('.subtitle-appearance')?.innerText})");
        if (closed) return;
        report("Page: " + page);
        report($"Host visible={IsVisible}; AllowsTransparency={AllowsTransparency}; background={backgroundOpacity}%; text={textOpacity}%");
        GeometryReport();
    }
    [StructLayout(LayoutKind.Sequential)] private struct Margins { public int Left, Right, Top, Bottom; }
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
    [DllImport("dwmapi.dll")] private static extern int DwmExtendFrameIntoClientArea(IntPtr hwnd, ref Margins margins);
}

internal sealed class ExperimentControls : Window
{
    private SubtitleExperiment? subtitle;
    private readonly ComboBox material = new() { Width = 145, ItemsSource = new[] { "Desktop Acrylic", "Mica (wallpaper)", "None (comparison)" }, SelectedIndex = 0 };
    private readonly CheckBox topmost = new() { Content = "Actual topmost", IsChecked = true, Margin = new Thickness(12, 0, 0, 0) };
    private readonly CheckBox overlay = new() { Content = "WPF overlay test", Margin = new Thickness(12, 0, 0, 0) };
    private readonly CheckBox layered = new() { Content = "Layered / AllowsTransparency=true (recreate subtitle)", Margin = new Thickness(0, 4, 0, 4) };
    private readonly CheckBox longSample = new() { Content = "Long bilingual sample", Margin = new Thickness(0, 4, 0, 4) };
    private readonly TextBox log = new() { IsReadOnly = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Height = 230 };
    private readonly string logPath = Path.Combine(AppContext.BaseDirectory, "experiment.log");
    internal ExperimentControls()
    {
        Title = "RU-ZH experiment controls (not SettingsWindow)";
        Width = 660; Height = 500; Left = 30; Top = 30;
        var panel = new StackPanel { Margin = new Thickness(14) };
        Content = panel;
        panel.Children.Add(new TextBlock { Text = "Phase 3 / slice 1 — native composition experiment", FontWeight = FontWeights.SemiBold });
        panel.Children.Add(new TextBlock { Text = "Local React subtitle.html · no server/engine. Keep this window for recovery.", Margin = new Thickness(0, 8, 0, 8) });
        var row = new WrapPanel(); panel.Children.Add(row);
        AddButton(row, "Show / restore", async () => { EnsureSubtitle(); subtitle!.Show(); await subtitle.SetAppearance(45, 100); });
        AddButton(row, "Hide subtitle", () => { subtitle?.Hide(); Report("Subtitle hidden; controls remain"); return Task.CompletedTask; });
        AddButton(row, "Background 0 / text 100", async () => { if (subtitle != null) await subtitle.SetAppearance(0, 100); });
        AddButton(row, "Background 0 / text 0", async () => { if (subtitle != null) await subtitle.SetAppearance(0, 0); });
        AddButton(row, "Inspect page", async () => { if (subtitle != null) await subtitle.InspectPage(); });
        var options = new WrapPanel { Margin = new Thickness(0, 6, 0, 6) }; panel.Children.Add(options);
        material.SelectionChanged += (_, _) => subtitle?.SetMaterial(material.SelectedIndex switch { 0 => 3, 1 => 2, _ => 1 });
        options.Children.Add(material);
        topmost.Click += (_, _) => { if (subtitle != null) { subtitle.Topmost = topmost.IsChecked == true; Report($"Actual topmost={subtitle.Topmost}"); } };
        options.Children.Add(topmost);
        overlay.Click += (_, _) => subtitle?.SetOverlay(overlay.IsChecked == true);
        options.Children.Add(overlay);
        layered.Click += (_, _) =>
        {
            subtitle?.Close();
            material.IsEnabled = layered.IsChecked != true;
            EnsureSubtitle();
            subtitle!.Show();
            Report("Mode switched by recreating subtitle only; controls remain available");
        };
        panel.Children.Add(layered);
        longSample.Click += (_, _) => subtitle?.SetLongSample(longSample.IsChecked == true);
        panel.Children.Add(longSample);
        panel.Children.Add(log);
        var close = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) }; panel.Children.Add(close);
        AddButton(close, "Close experiment", () => { Close(); return Task.CompletedTask; });
        Loaded += (_, _) => { Report($"Windows={Environment.OSVersion.Version}; .NET={Environment.Version}; SDK WebView2=1.0.4314.35"); EnsureSubtitle(); subtitle!.Show(); };
        Closed += (_, _) => { subtitle?.Close(); Application.Current.Shutdown(); };
    }
    private void EnsureSubtitle()
    {
        if (subtitle != null) return;
        subtitle = new SubtitleExperiment(Report, layered.IsChecked == true);
        subtitle.SetMaterial(material.SelectedIndex switch { 0 => 3, 1 => 2, _ => 1 });
        subtitle.Topmost = topmost.IsChecked == true;
        subtitle.SetOverlay(overlay.IsChecked == true);
        subtitle.SetLongSample(longSample.IsChecked == true);
        subtitle.Closed += (_, _) => subtitle = null;
    }
    private void Report(string message)
    {
        var line = $"{DateTimeOffset.Now:O} {message}";
        log.AppendText(line + Environment.NewLine); log.ScrollToEnd();
        File.AppendAllText(logPath, line + Environment.NewLine);
    }
    private static void AddButton(Panel panel, string text, Func<Task> action)
    {
        var button = new Button { Content = text, Padding = new Thickness(8, 4, 8, 4), Margin = new Thickness(0, 0, 6, 4) };
        button.Click += async (_, _) => await action();
        panel.Children.Add(button);
    }
}
