using System.IO;
using System.Windows;
using Microsoft.Web.WebView2.Core;

namespace RuZh.Subtitles.Host;

internal sealed class App : Application
{
    private SubtitleWindow subtitle = null!;
    private SettingsWindow settings = null!;
    private bool exiting;
    private readonly string logPath = Path.Combine(AppContext.BaseDirectory, $"host-{Environment.ProcessId}.log");

    [STAThread]
    public static void Main() => new App { ShutdownMode = ShutdownMode.OnExplicitShutdown }.Run();

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        Report($"Windows={Environment.OSVersion.Version}; .NET={Environment.Version}");
        var profile = Path.Combine(AppContext.BaseDirectory, "WebView2Profile");
        var environment = CoreWebView2Environment.CreateAsync(userDataFolder: profile);

        subtitle = new SubtitleWindow(environment, ShowSettings, HideSubtitle, Report);
        settings = new SettingsWindow(environment, subtitle, ShowSubtitle, HideSubtitle, HideSettings, ExitHost, Report);
        MainWindow = settings;

        subtitle.Closing += (_, args) =>
        {
            if (exiting) return;
            args.Cancel = true;
            HideSubtitle();
        };
        settings.Closing += (_, args) =>
        {
            if (exiting) return;
            args.Cancel = true;
            HideSettings();
        };

        ShowSubtitle();
        ShowSettings();
    }

    private void ShowSettings()
    {
        if (!settings.IsVisible) settings.Show();
        if (settings.WindowState == WindowState.Minimized) settings.WindowState = WindowState.Normal;
        settings.Activate();
        Report("Settings shown");
    }

    private void HideSettings()
    {
        if (subtitle.CanOpenSettings)
        {
            settings.Hide();
            Report("Settings hidden; subtitle menu can reopen it");
        }
        else
        {
            settings.WindowState = WindowState.Minimized;
            Report("Settings minimized for taskbar recovery");
        }
    }

    private void ShowSubtitle()
    {
        if (!subtitle.IsVisible) subtitle.Show();
        if (subtitle.WindowState == WindowState.Minimized) subtitle.WindowState = WindowState.Normal;
        Report("Subtitle shown");
    }

    private void HideSubtitle()
    {
        subtitle.Hide();
        ShowSettings();
        Report("Subtitle hidden");
    }

    private void ExitHost()
    {
        exiting = true;
        Report("Exit requested");
        Shutdown();
    }

    private void Report(string message)
    {
        string line = $"{DateTimeOffset.Now:O} {message}";
        try { File.AppendAllText(logPath, line + Environment.NewLine); }
        catch (IOException) { System.Diagnostics.Trace.WriteLine(line); }
        catch (UnauthorizedAccessException) { System.Diagnostics.Trace.WriteLine(line); }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        Report($"Host exited with code {e.ApplicationExitCode}");
        base.OnExit(e);
    }
}
