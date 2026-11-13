using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace RuZh.Subtitles.Host;

internal sealed class LocalPage
{
    private const string Host = "subtitle.example";
    private const string Origin = "https://" + Host + "/";
    private readonly WebView2CompositionControl web = new() { DefaultBackgroundColor = System.Drawing.Color.Transparent };
    private readonly Action<string> report;
    private bool ready;
    private bool closed;

    internal Grid Surface { get; } = new();
    internal bool IsReady => ready;

    internal LocalPage(Window window, string entry, Task<CoreWebView2Environment> environment,
        Action<string> writeLog, Func<Task>? onReady = null)
    {
        report = message => writeLog($"{entry} {message}");
        Surface.Children.Add(web);
        var error = new TextBlock
        {
            Foreground = Brushes.White, Background = Brushes.DarkRed, TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(12), Padding = new Thickness(6), Visibility = Visibility.Collapsed
        };
        Surface.Children.Add(error);

        async void Load(object sender, RoutedEventArgs args)
        {
            window.Loaded -= Load;
            try
            {
                var runtime = await environment;
                if (closed) return;
                await web.EnsureCoreWebView2Async(runtime);
                if (closed) return;
                var core = web.CoreWebView2;
                core.SetVirtualHostNameToFolderMapping(Host, Path.Combine(AppContext.BaseDirectory, "web"),
                    CoreWebView2HostResourceAccessKind.DenyCors);
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.NavigationStarting += (_, e) => e.Cancel = !e.Uri.StartsWith(Origin, StringComparison.Ordinal);
                core.NewWindowRequested += (_, e) => e.Handled = true;
                core.ProcessFailed += (_, e) =>
                {
                    ready = false;
                    report($"WebView process failure: {e.ProcessFailedKind}");
                    ShowError("页面运行失败，请查看宿主日志。");
                };
                core.NavigationCompleted += async (_, e) =>
                {
                    if (closed) return;
                    ready = e.IsSuccess;
                    report($"Navigation success={e.IsSuccess}; runtime={runtime.BrowserVersionString}");
                    if (!ready)
                    {
                        ShowError($"页面加载失败 ({e.WebErrorStatus})");
                        return;
                    }
                    if (onReady != null) await onReady();
                };

                await ObserveConsole(core);
                if (!closed) web.Source = new Uri(Origin + entry);
            }
            catch (Exception ex)
            {
                if (!closed)
                {
                    report($"Initialization failed: {ex}");
                    ShowError("页面初始化失败，请查看宿主日志。");
                }
            }
        }

        void ShowError(string message)
        {
            error.Text = message;
            error.Visibility = Visibility.Visible;
        }

        window.Loaded += Load;
        window.Closed += (_, _) =>
        {
            closed = true;
            web.Dispose();
            report("WebView disposed");
        };
    }

    private async Task ObserveConsole(CoreWebView2 core)
    {
        core.GetDevToolsProtocolEventReceiver("Runtime.exceptionThrown").DevToolsProtocolEventReceived +=
            (_, e) => report($"JavaScript exception: {e.ParameterObjectAsJson}");
        core.GetDevToolsProtocolEventReceiver("Runtime.consoleAPICalled").DevToolsProtocolEventReceived += (_, e) =>
        {
            using var data = JsonDocument.Parse(e.ParameterObjectAsJson);
            string? level = data.RootElement.GetProperty("type").GetString();
            if (level is "error" or "warning") report($"Console {level}: {e.ParameterObjectAsJson}");
        };
        core.GetDevToolsProtocolEventReceiver("Log.entryAdded").DevToolsProtocolEventReceived += (_, e) =>
        {
            using var data = JsonDocument.Parse(e.ParameterObjectAsJson);
            string? level = data.RootElement.GetProperty("entry").GetProperty("level").GetString();
            if (level is "error" or "warning") report($"Web log {level}: {e.ParameterObjectAsJson}");
        };
        await core.CallDevToolsProtocolMethodAsync("Runtime.enable", "{}");
        if (closed) return;
        await core.CallDevToolsProtocolMethodAsync("Log.enable", "{}");
        report("Console monitoring enabled");
    }

    internal async Task ApplyStyle(string css)
    {
        if (!ready || closed) return;
        try
        {
            string value = JsonSerializer.Serialize(css);
            string result = await web.ExecuteScriptAsync($$"""
                (() => {
                    let style = document.getElementById('host-appearance');
                    if (!style) {
                        style = document.createElement('style');
                        style.id = 'host-appearance';
                        document.head.append(style);
                    }
                    style.textContent = {{value}};
                    return true;
                })()
                """);
            if (result != "true" && !closed) report("Appearance script failed to apply");
        }
        catch (Exception ex)
        {
            if (!closed) report($"Appearance script failed: {ex.Message}");
        }
    }
}
