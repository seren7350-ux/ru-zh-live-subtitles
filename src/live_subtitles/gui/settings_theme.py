"""Local settings palette and ttk styles; independent of subtitle transparency."""

SURFACE = "#24272e"
SIDEBAR = "#1c1f25"
TEXT = "#edf0f5"
MUTED = "#a5adbb"
ACCENT = "#79aaff"
SELECTED = "#303e58"
CONTROL = "#343a46"
LINE = "#414958"
ERROR = "#ff9c95"


def raster_icon(tk, window, width, height, pixel):
    """Rasterize at final device size with 4x4 coverage, without bitmap resizing.

    Only boundary pixels blend; interior pixels remain solid and sharp. The
    background is the settings surface so no transparent fringe is introduced.
    """
    image = tk.PhotoImage(master=window, width=width, height=height)
    colors = {}
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            samples = [pixel(x+(sx+.5)/4, y+(sy+.5)/4)
                       for sy in range(4) for sx in range(4)]
            key = tuple(samples)
            if key not in colors:
                rgb = [round(sum(int(c[i:i+2], 16) for c in samples)/16)
                       for i in (1, 3, 5)]
                colors[key] = "#" + "".join(f"{v:02x}" for v in rgb)
            row.append(colors[key])
        rows.append("{" + " ".join(row) + "}")
    image.put(" ".join(rows))
    return image


def install(ttk, window, tk):
    if getattr(window, "_settings_theme_images", None):
        return
    style = ttk.Style(window)
    # Clam supports explicit colors on Windows; the native theme ignores them.
    style.theme_use("clam")
    # ttk's popdown is a separate Tk Listbox, outside the themed combobox.
    for option, value in (("background", CONTROL), ("foreground", TEXT),
                          ("selectBackground", SELECTED), ("selectForeground", TEXT)):
        window.option_add(f"*TCombobox*Listbox.{option}", value)
    factor = max(1.0, window.winfo_fpixels("1i") / 96)
    size = round(18 * factor)
    def thumb_pixel(x, y):
        distance = ((x-size/2)**2 + (y-size/2)**2)**.5
        if distance <= size/2-1:
            return TEXT if distance < size/2-2 else ACCENT
        return SURFACE
    thumb = raster_icon(tk, window, size, size, thumb_pixel)
    images = [thumb]
    track = tk.PhotoImage(master=window, width=size, height=size)
    track.put(SURFACE, to=(0, 0, size, size))
    track.put(LINE, to=(0, size//2-1, size, size//2+2))
    images.append(track)
    switch_images = []
    for selected in (False, True):
        width, height = round(34*factor), round(20*factor)
        def switch_pixel(x, y):
            center = min(width-height/2, max(height/2, x))
            color = SURFACE
            if (x-center)**2 + (y-height/2)**2 <= (height/2-1)**2:
                color = ACCENT if selected else LINE
            knob_x = width-height/2 if selected else height/2
            if (x-knob_x)**2 + (y-height/2)**2 <= (height/2-3*factor)**2:
                color = TEXT
            return color
        image = raster_icon(tk, window, width, height, switch_pixel)
        switch_images.append(image)
    images.extend(switch_images)
    window._settings_theme_images = images
    style.element_create("Settings.slider", "image", thumb)
    style.element_create("Settings.trough", "image", track, border=0, sticky="we")
    style.layout("Settings.Horizontal.TScale", [
        ("Settings.trough", {"sticky": "we", "children": [
            ("Settings.slider", {"side": "left", "sticky": ""})]})])
    style.element_create("Settings.switch", "image", switch_images[0],
                         ("selected", switch_images[1]))
    style.layout("Settings.TCheckbutton", [("Checkbutton.focus", {
        "sticky": "nswe", "children": [("Settings.switch", {"sticky": ""})]})])
    style.configure("Settings.TCheckbutton", background=SURFACE,
                    focuscolor=ACCENT, focusthickness=1)
    style.configure("Settings.Horizontal.TScale", background=ACCENT,
                    troughcolor=LINE, bordercolor=SURFACE, lightcolor=ACCENT,
                    darkcolor=ACCENT, sliderlength=16)
    style.configure("Settings.Vertical.TScrollbar", background=CONTROL,
                    troughcolor=SURFACE, bordercolor=SURFACE,
                    arrowcolor=MUTED, lightcolor=CONTROL, darkcolor=CONTROL)
    style.configure("Settings.TCombobox", fieldbackground=CONTROL,
                    background=CONTROL, foreground=TEXT, arrowcolor=TEXT)
    style.map("Settings.TCombobox", fieldbackground=[("readonly", CONTROL)],
              foreground=[("readonly", TEXT), ("disabled", MUTED)])
