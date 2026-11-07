"""Compact numeric controls for live subtitle settings."""
from . import settings_theme as theme


class NumericScale:
    def __init__(self, parent, *, tk, ttk, label, minimum, maximum, value, command):
        from .dpi import scale_factor
        factor = scale_factor(parent)
        self.minimum, self.maximum = minimum, maximum
        self.command = command
        self.value = int(value)
        self.row = tk.Frame(parent, background=theme.SURFACE)
        self.row.pack(fill="x", pady=7)
        self.label = tk.Label(self.row, text=label, background=theme.SURFACE,
                              foreground=theme.TEXT, anchor="w")
        self.label.pack(side="left")
        self.controls = tk.Frame(self.row, background=theme.SURFACE)
        self.controls.pack(side="right")
        self.variable = tk.StringVar(parent, value=str(self.value))
        self.entry = tk.Spinbox(self.controls, from_=minimum, to=maximum, width=4,
            textvariable=self.variable, command=self.commit,
            background=theme.CONTROL, foreground=theme.TEXT,
            buttonbackground=theme.CONTROL, insertbackground=theme.TEXT,
            relief="flat", borderwidth=0, highlightthickness=1,
            highlightbackground=theme.LINE, highlightcolor=theme.ACCENT,
            justify="right")
        self.entry.pack(side="right", padx=(12, 0), ipady=4)
        self.entry.bind("<Return>", self.commit)
        self.entry.bind("<FocusOut>", self.commit)
        self.scale = ttk.Scale(self.controls, from_=minimum, to=maximum,
            orient="horizontal", style="Settings.Horizontal.TScale",
            length=round(150 * factor), command=self.changed)
        self.scale.pack(side="right", padx=(16, 0))
        # ttk's scale bindings vary by Tk theme/version. Supply explicit,
        # predictable keyboard increments for the integer settings we expose.
        for key, delta in (("Left", -1), ("Down", -1), ("Right", 1), ("Up", 1)):
            self.scale.bind(f"<{key}>", lambda _event, step=delta: self.step(step))
        self.scale.bind("<Home>", lambda _event: self.jump(self.minimum))
        self.scale.bind("<End>", lambda _event: self.jump(self.maximum))
        self.scale.set(self.value)
        self._stacked = False
        self.row.bind("<Configure>", self.layout)

    def layout(self, event):
        required = self.label.winfo_reqwidth() + self.controls.winfo_reqwidth() + 20
        stacked = event.width < required
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self.label.pack_forget()
        self.controls.pack_forget()
        self.label.pack(side="top" if stacked else "left", anchor="w")
        self.controls.pack(side="top" if stacked else "right", anchor="e",
                           pady=(5, 0) if stacked else 0)

    def changed(self, value):
        value = max(self.minimum, min(self.maximum, round(float(value))))
        self.variable.set(str(value))
        if value != self.value:
            self.value = value
            self.command(str(value))

    def set(self, value):
        self.scale.set(value)
        self.changed(value)

    def step(self, delta):
        self.set(max(self.minimum, min(self.maximum, self.value + delta)))
        return "break"

    def jump(self, value):
        self.set(value)
        return "break"

    def commit(self, _event=None):
        try:
            value = float(self.variable.get())
            if not self.minimum <= value <= self.maximum:
                raise ValueError
        except (ValueError, OverflowError):
            self.variable.set(str(self.value))
            return
        self.set(value)
