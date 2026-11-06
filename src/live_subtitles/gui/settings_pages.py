"""Compact, keyboard-accessible settings pages with local vertical scrolling."""
from __future__ import annotations

from typing import Any


def create_settings_pages(window: Any, root: Any, tk: Any, ttk: Any) -> dict[str, Any]:
    notebook = ttk.Notebook(window)
    notebook.pack(fill="both", expand=True, pady=(6, 8))
    pages = {}
    scrollers = []
    for title in ("General", "Appearance", "More", "Diagnostics"):
        page = tk.Frame(notebook, background="#20242c")
        notebook.add(page, text=title)
        canvas = tk.Canvas(page, background="#20242c", highlightthickness=0,
                           width=380, height=380)
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        body = tk.Frame(canvas, background="#20242c", padx=8, pady=6)
        item = canvas.create_window(0, 0, anchor="nw", window=body)
        body.bind("<Configure>", lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        def resize(event: Any, c: Any = canvas, i: Any = item, b: Any = body) -> None:
            c.itemconfigure(i, width=event.width)
            def wrap_labels(widget: Any) -> None:
                for child in widget.winfo_children():
                    if child.winfo_class() == "Label":
                        child.configure(wraplength=max(80, event.width - 24))
                    wrap_labels(child)
            wrap_labels(b)
        canvas.bind("<Configure>", resize)
        # Bind locally, never bind_all: scrolling settings must not affect the
        # subtitle view or another settings page.
        def wheel(event: Any, c: Any = canvas) -> str:
            c.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        scrollers.append((body, canvas, wheel))
        pages[title] = body
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
    area = work_area((x, y, 440, 560),
                     (root.winfo_screenwidth(), root.winfo_screenheight()))
    # Leave room for the framed dialog's title bar and borders.
    left, top, width, height = area
    x, y, width, height = fit_rectangle((x, y, 440, 560),
                                       (left + 8, top + 32, width - 16, height - 48))
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(360, 260)
    return pages
