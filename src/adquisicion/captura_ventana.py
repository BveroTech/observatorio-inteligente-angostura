"""
Captura de la ventana de UNA aplicación como fuente de video (solo Windows).

Sirve para analizar un video de aves que se reproduce en una aplicación concreta
(Chrome, Edge, Firefox, VLC, Películas y TV…) sin depender de en qué monitor esté
ni de que esté encima de las demás ventanas.

La aplicación se elige por el nombre de su programa (p. ej. "chrome.exe") y,
opcionalmente, por un texto del título de la ventana (p. ej. "YouTube"). Si hay varias,
se usa la más grande. Si la ventana se cierra y se vuelve a abrir, se encuentra sola.

Método: PrintWindow con PW_RENDERFULLCONTENT (captura aunque la tapen otras ventanas).
Si la aplicación entrega la imagen en negro (algunos reproductores con aceleración
por GPU), pasa a capturar la zona de la pantalla donde está la ventana (en ese caso
la ventana debe estar visible). Imita la interfaz de cv2.VideoCapture.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import numpy as np

ES_WINDOWS = sys.platform == "win32"
# Ventanas del propio Observatorio: nunca se ofrecen (la IA se analizaría a sí misma).
TITULOS_PROPIOS = ("Observatorio Inteligente", "Centro Interactivo de Visitantes", "Acceso restringido")
PROGRAMAS_PROPIOS = ("observatorio.exe", "admin.exe")
PROGRAMAS_SISTEMA = ("explorer.exe", "textinputhost.exe", "applicationframehost.exe", "shellexperiencehost.exe",
                     "searchhost.exe", "startmenuexperiencehost.exe", "systemsettings.exe", "lockapp.exe")

if ES_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
    DWMWA_CLOAKED = 14
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x00000080

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    # Tipos explícitos: en Windows de 64 bits los identificadores (HDC, HBITMAP, punteros)
    # no caben en el int por defecto de ctypes ("int too long to convert").
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _programa(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proceso = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not proceso:
        return pid.value, ""
    try:
        tamano = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(proceso, 0, buffer, ctypes.byref(tamano)):
            return pid.value, os.path.basename(buffer.value).lower()
        return pid.value, ""
    finally:
        kernel32.CloseHandle(proceso)


def _rect_cliente(hwnd):
    """(x, y, ancho, alto) del área de contenido de la ventana, en coordenadas de pantalla."""
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origen = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origen))
    return origen.x, origen.y, rect.right - rect.left, rect.bottom - rect.top


def listar_ventanas():
    """Ventanas de aplicaciones abiertas: [{hwnd, titulo, programa, ancho, alto, minimizada}]."""
    if not ES_WINDOWS:
        return []
    resultado = []
    propio = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visitar(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # 4 = GW_OWNER (ventanas hijas/diálogos)
            return True
        if user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        oculta = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta))
        if oculta.value:
            return True
        largo = user32.GetWindowTextLengthW(hwnd)
        if not largo:
            return True
        texto = ctypes.create_unicode_buffer(largo + 1)
        user32.GetWindowTextW(hwnd, texto, largo + 1)
        titulo = texto.value.strip()
        pid, programa = _programa(hwnd)
        if (pid == propio or not titulo or programa in PROGRAMAS_PROPIOS + PROGRAMAS_SISTEMA
                or any(t in titulo for t in TITULOS_PROPIOS)):
            return True
        zona = _rect_cliente(hwnd) or (0, 0, 0, 0)
        resultado.append({"hwnd": hwnd, "titulo": titulo, "programa": programa or "?",
                          "ancho": zona[2], "alto": zona[3], "minimizada": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(visitar, 0)
    return resultado


def buscar_ventana(programa="", titulo=""):
    """La ventana más grande que coincide con el programa y/o el texto del título (o None)."""
    programa, titulo = (programa or "").strip().lower(), (titulo or "").strip().lower()
    if not programa and not titulo:
        return None
    candidatas = [v for v in listar_ventanas()
                  if (not programa or v["programa"] == programa) and (not titulo or titulo in v["titulo"].lower())]
    candidatas.sort(key=lambda v: (not v["minimizada"], v["ancho"] * v["alto"]), reverse=True)
    return candidatas[0] if candidatas else None


def describir(programa="", titulo=""):
    nombre = (programa or "").removesuffix(".exe").capitalize() or "aplicación"
    return f"Aplicación: {nombre}" + (f" · «{titulo}»" if titulo else "")


class CapturaVentana:
    """Captura el contenido de la ventana de una aplicación (misma interfaz que cv2.VideoCapture)."""

    def __init__(self, programa="", titulo="", fps_maximo=None):
        if not ES_WINDOWS:
            raise RuntimeError("La captura de una aplicación solo está disponible en Windows.")
        if fps_maximo is None:
            from config.settings import FPS_VIDEO as fps_maximo
        self.programa, self.titulo = programa, titulo
        self.intervalo = 1.0 / fps_maximo if fps_maximo else 0.0
        self._ultimo = 0.0
        self._hwnd = None
        self._buscado = 0.0
        self._negros = 0
        self.metodo = "printwindow"
        self._local = threading.local()
        self._abierta = True
        self._resolver(forzar=True)

    def _resolver(self, forzar=False):
        """Busca la ventana al abrir y cada 2 s si se perdió (se cerró, cambió el título…)."""
        valida = self._hwnd is not None and user32.IsWindow(self._hwnd)
        if valida and not forzar:
            return self._hwnd
        if not forzar and time.monotonic() - self._buscado < 2.0:
            return None
        self._buscado = time.monotonic()
        ventana = buscar_ventana(self.programa, self.titulo)
        self._hwnd = ventana["hwnd"] if ventana else None
        return self._hwnd

    def isOpened(self):  # noqa: N802
        return self._abierta and self._hwnd is not None

    def _printwindow(self, hwnd, ancho, alto):
        pantalla = user32.GetDC(None)
        memoria = gdi32.CreateCompatibleDC(pantalla)
        mapa = gdi32.CreateCompatibleBitmap(pantalla, ancho, alto)
        anterior = gdi32.SelectObject(memoria, mapa)
        try:
            if not user32.PrintWindow(hwnd, memoria, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
                return None
            cabecera = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), ancho, -alto, 1, 32, 0, 0, 0, 0, 0, 0)
            imagen = np.empty((alto, ancho, 4), dtype=np.uint8)
            if not gdi32.GetDIBits(memoria, mapa, 0, alto, imagen.ctypes.data, ctypes.byref(cabecera), 0):
                return None
            return np.ascontiguousarray(imagen[:, :, :3])
        finally:
            gdi32.SelectObject(memoria, anterior)
            gdi32.DeleteObject(mapa)
            gdi32.DeleteDC(memoria)
            user32.ReleaseDC(None, pantalla)

    def _pantalla(self, zona):
        import mss

        if getattr(self._local, "mss", None) is None:
            self._local.mss = mss.MSS()
        x, y, ancho, alto = zona
        imagen = np.asarray(self._local.mss.grab({"left": x, "top": y, "width": ancho, "height": alto}))
        return np.ascontiguousarray(imagen[:, :, :3])

    def read(self):
        if not self._abierta:
            return False, None
        espera = self.intervalo - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo = time.monotonic()
        hwnd = self._resolver()
        if hwnd is None or user32.IsIconic(hwnd):
            time.sleep(0.2)
            return False, None  # cerrada o minimizada: FuenteVideo pasa a reconexión / demostración
        zona = _rect_cliente(hwnd)
        if not zona or zona[2] < 32 or zona[3] < 32:
            return False, None
        try:
            if self.metodo == "printwindow":
                imagen = self._printwindow(hwnd, zona[2], zona[3])
                if imagen is not None and int(imagen.max()) < 10:
                    self._negros += 1
                    if self._negros >= 15:  # medio segundo seguido en negro: la app no se deja capturar así
                        self.metodo = "pantalla"
                        print(f"[AVISO] {describir(self.programa, self.titulo)} entrega la imagen en negro; "
                              "se captura su zona de la pantalla (debe quedar visible).")
                else:
                    self._negros = 0
            else:
                imagen = self._pantalla(zona)
        except Exception:
            return False, None
        return (True, imagen) if imagen is not None else (False, None)

    def release(self):
        self._abierta = False
        captura = getattr(self._local, "mss", None)
        if captura is not None:
            captura.close()
            self._local.mss = None

    def set(self, *_):
        return False
