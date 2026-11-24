"""Paint Tk caption lines onto a premultiplied-alpha Windows surface."""

from contextlib import ExitStack
import ctypes as c
from ctypes import wintypes as w


class _StartupInput(c.Structure):
    _fields_ = [("version", w.UINT), ("debug_callback", c.c_void_p),
                ("no_background_thread", w.BOOL), ("no_external_codecs", w.BOOL)]


class _BitmapHeader(c.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bit_count", w.WORD), ("compression", w.DWORD),
                ("image_size", w.DWORD), ("x_resolution", w.LONG), ("y_resolution", w.LONG),
                ("colors_used", w.DWORD), ("important_colors", w.DWORD)]


class _Rect(c.Structure):
    _fields_ = [(name, c.c_float) for name in ("x", "y", "width", "height")]


class _Blend(c.Structure):
    _fields_ = [(name, w.BYTE) for name in ("operation", "flags", "opacity", "per_pixel_alpha")]


def _load(dll, signatures):
    library = c.WinDLL(dll, use_last_error=True)
    for name, result, arguments in signatures:
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments
    return library


def _check(status):
    if status:
        raise OSError(f"GDI+ caption drawing failed (status {status}).")


class CaptionBitmap:
    """Render with grayscale antialiasing and let Windows composite each pixel."""

    def __init__(self):
        ptr, out, status = c.c_void_p, c.POINTER(c.c_void_p), c.c_int
        self.gdi = _load("gdi32", (
            ("CreateCompatibleDC", w.HDC, (w.HDC,)),
            ("DeleteDC", w.BOOL, (w.HDC,)),
            ("CreateDIBSection", w.HBITMAP, (w.HDC, c.POINTER(_BitmapHeader), w.UINT, out, w.HANDLE, w.DWORD)),
            ("SelectObject", w.HANDLE, (w.HDC, w.HANDLE)),
            ("DeleteObject", w.BOOL, (w.HANDLE,)),
        ))
        self.user = _load("user32", (
            ("UpdateLayeredWindow", w.BOOL, (w.HWND, w.HDC, c.POINTER(w.POINT), c.POINTER(w.SIZE),
                                             w.HDC, c.POINTER(w.POINT), w.DWORD, c.POINTER(_Blend), w.DWORD)),
        ))
        self.plus = _load("gdiplus", (
            ("GdiplusStartup", status, (c.POINTER(c.c_size_t), c.POINTER(_StartupInput), ptr)),
            ("GdiplusShutdown", None, (c.c_size_t,)),
            ("GdipCreateBitmapFromScan0", status, (c.c_int, c.c_int, c.c_int, c.c_int, ptr, out)),
            ("GdipDisposeImage", status, (ptr,)),
            ("GdipGetImageGraphicsContext", status, (ptr, out)),
            ("GdipDeleteGraphics", status, (ptr,)),
            ("GdipGraphicsClear", status, (ptr, w.DWORD)),
            ("GdipSetTextRenderingHint", status, (ptr, c.c_int)),
            ("GdipStringFormatGetGenericTypographic", status, (out,)),
            ("GdipDeleteStringFormat", status, (ptr,)),
            ("GdipCreateFontFamilyFromName", status, (w.LPCWSTR, ptr, out)),
            ("GdipGetGenericFontFamilySansSerif", status, (out,)),
            ("GdipDeleteFontFamily", status, (ptr,)),
            ("GdipCreateFont", status, (ptr, c.c_float, c.c_int, c.c_int, out)),
            ("GdipDeleteFont", status, (ptr,)),
            ("GdipCreateSolidFill", status, (w.DWORD, out)),
            ("GdipDeleteBrush", status, (ptr,)),
            ("GdipDrawString", status, (ptr, w.LPCWSTR, c.c_int, ptr, c.POINTER(_Rect), ptr, ptr)),
        ))
        self.token = c.c_size_t()
        _check(self.plus.GdiplusStartup(c.byref(self.token), c.byref(_StartupInput(1)), None))

    def close(self):
        self.plus.GdiplusShutdown(self.token)

    @staticmethod
    def _resource(stack, create, release, *args):
        value = c.c_void_p()
        _check(create(*args, c.byref(value)))
        stack.callback(release, value)
        return value

    def paint(self, hwnd, size, specs, offsets, opacity, anchor):
        width, height = size
        with ExitStack() as stack:
            dc = self.gdi.CreateCompatibleDC(None)
            if not dc:
                raise c.WinError(c.get_last_error())
            stack.callback(self.gdi.DeleteDC, dc)
            bits = c.c_void_p()
            header = _BitmapHeader(c.sizeof(_BitmapHeader), width, -height, 1, 32)
            dib = self.gdi.CreateDIBSection(dc, c.byref(header), 0, c.byref(bits), None, 0)
            if not dib:
                raise c.WinError(c.get_last_error())
            stack.callback(self.gdi.DeleteObject, dib)
            old = self.gdi.SelectObject(dc, dib)
            if not old:
                raise c.WinError(c.get_last_error())
            stack.callback(self.gdi.SelectObject, dc, old)
            self._draw(size, bits, specs, offsets, anchor)
            blend = _Blend(0, 0, round(255 * opacity), 1)  # AC_SRC_OVER, AC_SRC_ALPHA
            if not self.user.UpdateLayeredWindow(
                hwnd, None, None, c.byref(w.SIZE(width, height)), dc, c.byref(w.POINT()),
                0, c.byref(blend), 2,  # ULW_ALPHA
            ):
                raise c.WinError(c.get_last_error())

    def _draw(self, size, bits, specs, offsets, anchor):
        plus, resource = self.plus, self._resource
        width, height = size
        with ExitStack() as stack:
            bitmap = resource(stack, plus.GdipCreateBitmapFromScan0, plus.GdipDisposeImage,
                              width, height, width * 4, 0x000E200B, bits)  # 32bpp PARGB
            graphics = resource(stack, plus.GdipGetImageGraphicsContext, plus.GdipDeleteGraphics, bitmap)
            format_ = resource(stack, plus.GdipStringFormatGetGenericTypographic, plus.GdipDeleteStringFormat)
            _check(plus.GdipGraphicsClear(graphics, 0))
            _check(plus.GdipSetTextRenderingHint(graphics, 3))  # AntiAliasGridFit, no RGB subpixels
            for spec, offset in zip(specs, offsets):
                self._draw_line(graphics, format_, spec, offset, anchor)

    def _draw_line(self, graphics, format_, spec, offset, anchor):
        plus, resource = self.plus, self._resource
        font_spec = spec["font"]
        family = anchor.tk.call("font", "actual", font_spec, "-family")
        points, *styles = font_spec[1:]
        pixels = round(points * float(anchor.tk.call("tk", "scaling")))
        x, y = round(spec["x"]) - offset, round(spec["y"])
        with ExitStack() as stack:
            font_family = c.c_void_p()
            status = plus.GdipCreateFontFamilyFromName(family, None, c.byref(font_family))
            if status == 14:  # FontFamilyNotFound
                status = plus.GdipGetGenericFontFamilySansSerif(c.byref(font_family))
            _check(status)
            stack.callback(plus.GdipDeleteFontFamily, font_family)
            font = resource(stack, plus.GdipCreateFont, plus.GdipDeleteFont,
                            font_family, pixels, int("bold" in styles), 2)  # UnitPixel

            def draw(color, positions):
                rgb = tuple(channel >> 8 for channel in anchor.winfo_rgb(color))
                argb = int.from_bytes(bytes((255, *rgb)), "big")
                brush = resource(stack, plus.GdipCreateSolidFill, plus.GdipDeleteBrush, argb)
                for dx, dy in positions:
                    layout = _Rect(x + dx, y + dy, 0, 0)
                    _check(plus.GdipDrawString(graphics, spec["text"], -1, font,
                                              c.byref(layout), format_, brush))

            if spec["outline"]:
                draw(spec["outline"], ((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy))
            draw(spec["fill"], ((0, 0),))
