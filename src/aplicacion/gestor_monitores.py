"""
Detección de monitores en Windows (API Win32) y en Linux / Jetson (xrandr).

En Windows el número de cada monitor es el de Configuración > Pantalla >
Identificar (\\\\.\\DISPLAY1 → 1). En Linux es su posición en
`xrandr --listmonitors` + 1, y también se aceptan nombres de salida
(por ejemplo "DP-1-1"), que es lo que usa config/pantallas.conf.
"""
import platform
import re
import shutil
import subprocess


def listar_monitores(root=None):
    """Rectángulos (x, y, ancho, alto) de los monitores, el principal primero."""
    sistema = platform.system().lower()
    try:
        if sistema == "windows":
            return [rect for _, _, rect in _monitores_windows()]
        if sistema == "linux":
            monitores = _monitores_linux()
            if monitores:
                return [m["rect"] for m in sorted(monitores, key=lambda m: not m["principal"])]
    except Exception:
        pass
    if root is not None:
        return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
    return []


def monitores_numerados():
    """{número: (x, y, ancho, alto)} (Windows: número de Windows; Linux: orden de xrandr + 1)."""
    sistema = platform.system().lower()
    try:
        if sistema == "windows":
            return {numero: rect for _, numero, rect in _monitores_windows() if numero is not None}
        if sistema == "linux":
            return {m["numero"]: m["rect"] for m in _monitores_linux()}
    except Exception:
        pass
    return {}


def rect_monitor(monitor):
    """Rectángulo del monitor indicado por número (1, 2…) o, en Linux, por nombre de salida."""
    if monitor is None or str(monitor).strip() == "":
        return None
    texto = str(monitor).strip()
    if texto.isdigit():
        return monitores_numerados().get(int(texto))
    if platform.system().lower() == "linux":
        for m in _monitores_linux():
            if texto in (m["nombre"], m["salida"]):
                return m["rect"]
    return None


def describir_monitores():
    """[(número, nombre, (x, y, ancho, alto), principal)] para mostrar al usuario."""
    sistema = platform.system().lower()
    if sistema == "windows":
        return [(n, f"DISPLAY{n}", rect, p) for p, n, rect in _monitores_windows()]
    if sistema == "linux":
        return [(m["numero"], m["salida"], m["rect"], m["principal"]) for m in _monitores_linux()]
    return []


# ----------------------------------------------------------
# Linux / Jetson
# ----------------------------------------------------------

_PATRON_XRANDR = re.compile(
    r"^\s*(\d+):\s+\+?(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+?(-?\d+)\+?(-?\d+)\s+(\S+)"
)


def _monitores_linux():
    """Monitores activos según `xrandr --listmonitors` (requiere sesión X11, DISPLAY definido).

    Ejemplo de salida con un hub MST:
         0: +*DP-1-1 1920/527x1080/296+0+0  DP-1-1
         1: +DP-1-2 1920/527x1080/296+1920+0  DP-1-2
    Si xrandr no está, prueba con screeninfo.
    """
    if shutil.which("xrandr"):
        salida = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=5).stdout
        monitores = []
        for linea in salida.splitlines():
            coincidencia = _PATRON_XRANDR.match(linea)
            if not coincidencia:
                continue
            indice, principal, nombre, ancho, alto, x, y, salida_video = coincidencia.groups()
            monitores.append({
                "numero": int(indice) + 1, "nombre": nombre, "salida": salida_video, "principal": bool(principal),
                "rect": (int(x), int(y), int(ancho), int(alto)),
            })
        if monitores:
            return monitores
    try:
        from screeninfo import get_monitors

        return [
            {"numero": i + 1, "nombre": m.name or f"monitor{i + 1}", "salida": m.name or f"monitor{i + 1}",
             "principal": bool(getattr(m, "is_primary", i == 0)), "rect": (m.x, m.y, m.width, m.height)}
            for i, m in enumerate(get_monitors())
        ]
    except Exception:
        return []


# ----------------------------------------------------------
# Windows
# ----------------------------------------------------------

def _monitores_windows():
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    monitores = []
    usuario32 = ctypes.windll.user32

    def al_encontrar(hmonitor, hdc, rect, dato):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        usuario32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
        r = info.rcMonitor
        principal = bool(info.dwFlags & 1)
        coincidencia = re.search(r"DISPLAY(\d+)$", info.szDevice or "")
        numero = int(coincidencia.group(1)) if coincidencia else None
        monitores.append((principal, numero, (r.left, r.top, r.right - r.left, r.bottom - r.top)))
        return 1

    PROTOTIPO = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
    )
    retrollamada = PROTOTIPO(al_encontrar)
    usuario32.EnumDisplayMonitors(None, None, retrollamada, 0)
    monitores.sort(key=lambda m: not m[0])
    return monitores


# ----------------------------------------------------------
# config/pantallas.conf (Linux)
# ----------------------------------------------------------

def leer_configuracion_pantallas(ruta=None):
    """Lee config/pantallas.conf (CLAVE="valor", sintaxis de shell). {} si no existe."""
    if ruta is None:
        from config.settings import ARCHIVO_PANTALLAS as ruta
    valores = {}
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            for linea in archivo:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, _, valor = linea.partition("=")
                valor = valor.split(" #")[0].strip().strip('"').strip("'")
                valores[clave.strip()] = valor
    except OSError:
        pass
    return valores
