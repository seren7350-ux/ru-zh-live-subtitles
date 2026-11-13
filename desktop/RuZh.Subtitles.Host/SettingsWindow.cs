using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;

namespace RuZh.Subtitles.Host;

internal sealed class SettingsWindow : Window
{
    internal SettingsWindow(Task<CoreWebView2Environment> environment, SubtitleWindow subtitle,
        Action showSubtitle, Action hideSubtitle, Action hideSettings, Action exit, Action<string> report)
    {
        Title = "俄中实时字幕 · 设置";
        Width = Math.Min(1040, SystemParameters.WorkArea.Width);
        Height = Math.Min(820, SystemParameters.WorkArea.Height);
        MinWidth = 560;
        MinHeight = 540;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Background = new SolidColorBrush(Color.FromRgb(16, 16, 16));

        var layout = new DockPanel();
        var controls = new StackPanel { Margin = new Thickness(12, 8, 12, 0) };
        DockPanel.SetDock(controls, Dock.Top);
        layout.Children.Add(controls);
        var commands = new WrapPanel();
        controls.Children.Add(commands);

        var appearance = new WrapPanel();
        controls.Children.Add(appearance);
        var background = AddOpacity(appearance, "背景不透明度", SubtitleWindow.DefaultBackgroundOpacity);
        var text = AddOpacity(appearance, "文字不透明度", SubtitleWindow.DefaultTextOpacity);
        async Task ApplyAppearance() => await subtitle.SetAppearance((int)background.Value, (int)text.Value);
        background.ValueChanged += async (_, _) => await ApplyAppearance();
        text.ValueChanged += async (_, _) => await ApplyAppearance();

        AddButton(commands, "显示字幕", showSubtitle);
        AddButton(commands, "隐藏字幕", hideSubtitle);
        AddButton(commands, "恢复字幕", () =>
        {
            background.Value = SubtitleWindow.DefaultBackgroundOpacity;
            text.Value = SubtitleWindow.DefaultTextOpacity;
            showSubtitle();
        });
        AddButton(commands, "隐藏设置", hideSettings);
        AddButton(commands, "退出程序", exit);

        var topmost = new CheckBox
        {
            Content = "字幕置顶",
            Foreground = Brushes.White,
            IsChecked = subtitle.Topmost,
            Margin = new Thickness(8, 0, 8, 6),
            VerticalAlignment = VerticalAlignment.Center
        };
        topmost.Click += (_, _) =>
        {
            subtitle.Topmost = topmost.IsChecked == true;
            report($"Subtitle topmost={subtitle.Topmost}");
        };
        commands.Children.Add(topmost);

        var page = new LocalPage(this, "settings.html", environment, report);
        layout.Children.Add(page.Surface);
        Content = layout;
    }

    private static void AddButton(Panel panel, string label, Action action)
    {
        var button = new Button
        {
            Content = label,
            Padding = new Thickness(10, 4, 10, 4),
            Margin = new Thickness(0, 0, 6, 6)
        };
        button.Click += (_, _) => action();
        panel.Children.Add(button);
    }

    private static Slider AddOpacity(Panel panel, string label, int initial)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 16, 0) };
        panel.Children.Add(row);
        var caption = new TextBlock { Foreground = Brushes.White, VerticalAlignment = VerticalAlignment.Center };
        row.Children.Add(caption);
        var slider = new Slider
        {
            Width = 110, Minimum = 0, Maximum = 100, Value = initial,
            TickFrequency = 1, IsSnapToTickEnabled = true
        };
        AutomationProperties.SetName(slider, label);
        row.Children.Add(slider);
        caption.Text = $"{label} {initial}%";
        slider.ValueChanged += (_, args) => caption.Text = $"{label} {args.NewValue:F0}%";
        return slider;
    }
}
