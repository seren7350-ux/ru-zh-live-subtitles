"""Compact, keyboard-accessible settings pages with local vertical scrolling."""
from __future__ import annotations

from typing import Any

from . import settings_theme as theme


def create_settings_pages(window: Any, root: Any, tk: Any, ttk: Any) -> dict[str, Any]:
    from .dpi import scale_factor
    factor = scale_factor(root)
    shell = tk.Frame(window, background=theme.SIDEBAR)
    shell.pack(fill="both", expand=True)
    navigation = tk.Frame(shell, background=theme.SIDEBAR, padx=10, pady=20)
    navigation.pack(side="left", fill="y")
    content = tk.Frame(shell, background=theme.SURFACE)
    content.pack(side="left", fill="both", expand=True)
    buttons = {}
    containers = {}
    def select(title: str) -> None:
        for name, container in containers.items():
            if name == title:
                container.pack(fill="both", expand=True)
            else:
                container.pack_forget()
            buttons[name].configure(
                background=theme.SELECTED if name == title else theme.SIDEBAR,
                foreground=theme.ACCENT if name == title else theme.MUTED,
            )
    pages = {}
    scrollers = []
    for title, label in (("Appearance", "Subtitles"), ("General", "Input"),
                         ("More", "Window & files"), ("Diagnostics", "Diagnostics")):
        button = tk.Button(navigation, text=label, anchor="w", width=16,
                           relief="flat", borderwidth=0, padx=12, pady=10,
                           activebackground=theme.SELECTED, activeforeground=theme.ACCENT,
                           command=lambda name=title: select(name))
        button.pack(side="bottom" if title == "Diagnostics" else "top", fill="x", pady=3)
        buttons[title] = button
        page = tk.Frame(content, background=theme.SURFACE)
        containers[title] = page
        canvas = tk.Canvas(page, background=theme.SURFACE, highlightthickness=0,
                           width=380, height=380, yscrollincrement=round(16 * factor))
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview, style="Settings.Vertical.TScrollbar")
        canvas.pack(side="left", fill="both", expand=True)
        def update_scrollbar(first: Any, last: Any, s: Any = scroll, c: Any = canvas) -> None:
            s.set(first, last)
            overflowing = float(first) > 0.0001 or float(last) < 0.9999
            if overflowing and not s.winfo_manager():
                s.pack(side="right", fill="y", before=c)
            elif not overflowing and s.winfo_manager():
                s.pack_forget()
        canvas.configure(yscrollcommand=update_scrollbar)
        body = tk.Frame(canvas, background=theme.SURFACE, padx=24, pady=18)
        tk.Label(body, text=label, anchor="w", background=theme.SURFACE,
                 foreground=theme.TEXT, font=("Segoe UI", 16, "bold")).pack(fill="x", pady=(0, 14))
        item = canvas.create_window(0, 0, anchor="nw", window=body)
        body.bind("<Configure>", lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        def resize(event: Any, c: Any = canvas, i: Any = item, b: Any = body) -> None:
            c.itemconfigure(i, width=event.width)
            def wrap_labels(widget: Any) -> None:
                for child in widget.winfo_children():
                    if child.winfo_class() == "Label":
                        # The body reserves 24 px on BOTH sides. Wrapping to
                        # canvas width minus one inset clips diagnostic text.
                        child.configure(wraplength=max(80, event.width - 48))
                    wrap_labels(child)
            wrap_labels(b)
        canvas.bind("<Configure>", resize)
        # Bind locally, never bind_all: scrolling settings must not affect the
        # subtitle view or another settings page.
        def wheel(event: Any, c: Any = canvas) -> str:
            bounds = c.bbox("all")
            if not bounds or bounds[3] - bounds[1] <= c.winfo_height():
                return "break"
            # Windows reports multiples of WHEEL_DELTA (120), sometimes
            # coalescing several notches into one event. Preserve that amount.
            delta = event.delta
            if delta:
                steps = max(1, round(abs(delta) / 120)) * 3
                c.yview_scroll(-steps if delta > 0 else steps, "units")
            return "break"
        scrollers.append((body, canvas, wheel))
        pages[title] = body
    select("Appearance")
    def route_wheel(event: Any) -> str | None:
        for body, canvas, wheel in scrollers:
            widget = event.widget
            while widget is not None:
                if widget in (body, canvas):
                    return wheel(event)
                widget = getattr(widget, "master", None)
        return None
    def reveal_focus(event: Any) -> None:
        for body, canvas, _wheel in scrollers:
            widget = event.widget
            parent = widget
            while parent is not None and parent is not body:
                parent = getattr(parent, "master", None)
            if parent is body:
                y = widget.winfo_rooty() - body.winfo_rooty()
                top = canvas.canvasy(0)
                bottom = top + canvas.winfo_height()
                if y < top or y + widget.winfo_height() > bottom:
                    canvas.yview_moveto(max(0, y - 12) / max(1, body.winfo_height()))
                break
    window.bind("<MouseWheel>", route_wheel)
    window.bind("<FocusIn>", reveal_focus)
    from .workarea import work_area, fit_rectangle
    x = getattr(root, "winfo_x", lambda: 0)()
    y = getattr(root, "winfo_y", lambda: 0)()
    wanted_width, wanted_height = round(720 * factor), round(560 * factor)
    area = work_area((x, y, wanted_width, wanted_height),
                     (root.winfo_screenwidth(), root.winfo_screenheight()))
    # Leave room for the framed dialog's title bar and borders.
    left, top, width, height = area
    # Prefer the space above the subtitle on first open. Subsequent shows use
    # SettingsPanel.last_geometry, so dragging settings remains respected.
    gap = round(16 * factor)
    if y - wanted_height - gap >= top + 32:
        y -= wanted_height + gap
    else:
        y = top + 32
    x, y, width, height = fit_rectangle((x, y, wanted_width, wanted_height),
                                       (left + 8, top + 32, width - 16, height - 48))
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(min(width, round(520 * factor)), min(height, round(320 * factor)))
    return pages
