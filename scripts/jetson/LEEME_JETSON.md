# Observatorio en NVIDIA Jetson Orin Nano

Esta guía instala y opera el Observatorio en la plataforma de producción: **Jetson Orin Nano Developer Kit**, con JetPack 6.2.1 (Jetson Linux 36.4.4, Ubuntu 22.04, ARM64).

El código es el mismo que en Windows, que se sigue usando para desarrollar. El programa detecta la plataforma solo: si la arquitectura es `aarch64` y existe `/etc/nv_tegra_release`, sabe que corre en un Jetson.

## Qué cambia respecto de Windows

| Tema | Windows (desarrollo) | Jetson (producción) | Por qué |
|---|---|---|---|
| Arranque | `.bat` y Programador de tareas | `scripts/jetson/*.sh` y **systemd** (`observatorio-admin`, `observatorio-kiosco`) | Arranque y reinicio automáticos propios de Linux |
| Inferencia | ONNX Runtime en CPU | **onnxruntime-gpu**: TensorRT → CUDA → CPU | Usa la GPU del Orin; el log indica qué proveedor quedó en uso |
| Video RTSP | FFmpeg (CPU) | **GStreamer + `nvv4l2decoder`** (decodificador por hardware) | Libera la CPU para la interfaz y la IA |
| Dos pantallas | 2 salidas de la tarjeta de video | **1 DisplayPort + hub MST** (dos monitores) | El Orin Nano tiene una sola salida de video |
| Monitores | Número de Windows | Nombre de salida en `config/pantallas.conf` (xrandr) | Linux identifica las salidas por nombre |
| Táctil | Windows asigna el panel a su monitor | `xinput map-to-output` (`configurar_pantallas.sh`) | En X11 el toque se reparte sobre todo el escritorio si no se asigna |
| Empaquetado | PyInstaller (`.exe`) | **Paquete `.deb`** (`observatorio-angostura_<versión>_arm64.deb`) | Es el formato de aplicación de Ubuntu: se instala, actualiza y desinstala con `apt` |
| Python | 3.11 | **3.10 del sistema** | Las versiones con GPU de onnxruntime para JetPack 6 se publican para cp310 |

## 0. Instalar con el paquete .deb (recomendado)

**En Windows, construir el instalador:** `scripts\lanzadores_windows\construir_instalador_jetson.bat`. Genera `dist\observatorio-angostura_1.0.1_arm64.deb` (unos 350 MB). Sirve para JetPack 6 (Python 3.10, CUDA 12) y JetPack 7 (Python 3.12, CUDA 13): al instalarse detecta cuál tiene la placa y elige la versión de `onnxruntime-gpu` que corresponde. El paquete incluye:
- el programa, los modelos ONNX, las fotos, los sonidos y el catálogo;
- las librerías de Python para el Jetson, así que no necesita internet para ellas.

No lleva la base de datos, las capturas, las contraseñas ni `camara_local.json` de este equipo.

**En el Jetson** (copiarlo con un pendrive o por la red), ejecutar como el usuario del kiosco:

```bash
sudo apt install ./observatorio-angostura_1.0.1_arm64.deb   # apt resuelve los paquetes del sistema que falten
observatorio-usuario                                         # crea el usuario del portal
```

El paquete deja lo siguiente:

| Qué | Dónde / cómo |
|---|---|
| Programa y datos | `/opt/observatorio-angostura`. Su dueño es el usuario del kiosco: el que ejecutó `sudo`, o el uid 1000. Queda guardado en `/etc/default/observatorio-angostura`. |
| Menú de aplicaciones | **Observatorio de Aves**, **Observatorio · Portal de administración**, **Observatorio · Configurar pantallas** |
| Comandos | `observatorio` (`--fuente video` para pruebas, `--cerrar`), `observatorio-portal`, `observatorio-pantallas` (`--listar`, `--editar`), `observatorio-usuario`, `observatorio-medir` |
| Portal | Servicio `observatorio-admin`, activo desde la instalación en `http://NOMBRE-DEL-JETSON:5000`. Si ufw está activo, abre el puerto 5000. |
| Kiosco | Servicio de usuario `observatorio-kiosco`: abre solo al iniciar la sesión del usuario del kiosco y se reabre si falla. |
| Cámara | `/opt/observatorio-angostura/config/camara_local.json` (`{"rtsp_url": "rtsp://…"}`) |
| Pantallas | `/opt/observatorio-angostura/config/pantallas.conf`. Al actualizar el paquete se conserva lo editado. |

**Actualizar:** construir el paquete con una versión nueva (`construir_instalador_jetson.bat --version 1.0.2`) y repetir `sudo apt install ./…deb`. Se conservan la base de datos, las capturas, las fotos subidas, la cámara y las pantallas.

**Desinstalar:**
- `sudo apt remove observatorio-angostura` conserva los datos en `/opt/observatorio-angostura/data`.
- `sudo apt purge observatorio-angostura` borra todo.

**Llevar la base de datos de Windows:** cerrar el programa en ambos equipos y copiar `data\observatorio.db` a `/opt/observatorio-angostura/data/` con el mismo dueño (`sudo chown $USER: …`). Si no se copia, se crea una base nueva con el catálogo.

Lo que sigue (secciones 1 a 7) es la instalación manual desde la carpeta del proyecto. Sirve para desarrollar en el propio Jetson. Las secciones 2 a 7 (pantallas, energía, medir, pruebas) valen también con el paquete: en vez de `scripts/jetson/…` se usan los comandos de la tabla.

## 1. Instalar (manual, desde la carpeta del proyecto)

```bash
git clone … observatorio   # o copiar la carpeta del proyecto (sin .venv de Windows)
cd observatorio
bash scripts/jetson/instalar.sh
```

El instalador hace lo siguiente:

1. Instala con apt `python3-venv`, `python3-tk`, `xrandr`, `xinput`, `fontconfig` y GStreamer.
2. Comprueba que el **OpenCV de JetPack** tenga GStreamer y que exista `nvv4l2decoder`.
3. Crea `.venv` **con `--system-site-packages`**, para usar el OpenCV y TensorRT de JetPack.
4. Instala `requirements-jetson.txt`. Este archivo trae `onnxruntime-gpu` del índice `https://pypi.jetson-ai-lab.io/jp6/cu126`, verificado para cp310/aarch64 (versiones 1.23.0 y 1.24.0), y deja `numpy` en 1.x porque el OpenCV de JetPack se compiló con numpy 1.
5. Copia las fuentes Montserrat, crea la base de datos y verifica:
   - versiones de Python, SQLite (necesita ≥ 3.35), OpenCV y GStreamer;
   - proveedores de ONNX Runtime, Tk y Pygame.
6. Instala los servicios systemd (con `--sin-servicios` se omite este paso).

Después hay que:

- **Crear el usuario del portal:** `.venv/bin/python scripts/cli_admin/crear_usuario.py`
- **Activar el inicio de sesión automático** del usuario del kiosco, que vive en su sesión gráfica. Se hace en Configuración > Usuarios, o en `/etc/gdm3/custom.conf` con `AutomaticLoginEnable=true` y `AutomaticLogin=<usuario>`.
- **Usar sesión X11 ("Ubuntu on Xorg"), no Wayland.** Se comprueba con `echo $XDG_SESSION_TYPE`.

## 2. Pantallas (hub DisplayPort MST)

```bash
bash scripts/jetson/configurar_pantallas.sh --listar   # salidas de video y paneles táctiles
nano config/pantallas.conf                             # SALIDA_KIOSCO, SALIDA_TACTIL, TACTIL_PANTALLA2…
bash scripts/jetson/configurar_pantallas.sh            # aplica: lado a lado + táctil asignado
```

Con un hub MST, la salida DisplayPort del Jetson debería aparecer como **dos salidas** (por ejemplo `DP-1-1` y `DP-1-2`). **La documentación de NVIDIA no confirma soporte MST: es un supuesto que se prueba en la Fase 2.**

`ejecutar_observatorio.sh` ejecuta `configurar_pantallas.sh` antes de abrir el kiosco.

## 3. Ejecutar

```bash
bash scripts/jetson/ejecutar_observatorio.sh --fuente video   # prueba con el video de demostración
bash scripts/jetson/ejecutar_observatorio.sh                  # cámara configurada en config/settings.py
```

Al inicio del archivo se configuran tres opciones:

- `PANTALLA_COMPLETA`
- `PORTAL_EN_RED`: el portal se abre desde otro computador en `http://NOMBRE-DEL-JETSON:5000`.
- `CONFIGURAR_PANTALLAS`

La cámara IP Dahua se configura en `config/camara_local.json` (`{"rtsp_url": "rtsp://…"}`).

En `config/settings.py`:
- `CODEC_RTSP` debe coincidir con el códec de la cámara (`h264` o `h265`).
- `RTSP_GSTREAMER = "auto"` usa GStreamer en el Jetson y FFmpeg en los demás equipos.
- El respaldo con video de demostración a los 5 s, el reintento cada 10 s y la vuelta tras 5 lecturas correctas no cambian.

## 4. Servicios (arranque automático y reinicio)

| Servicio | Tipo | Qué hace |
|---|---|---|
| `observatorio-admin` | sistema | Portal de administración en la red (`--host 0.0.0.0`). Arranca con el equipo y se reinicia a los 5 s si se cae. |
| `observatorio-kiosco` | usuario | Kiosco y pantalla táctil en la sesión gráfica (`DISPLAY=:0`). Arranca al iniciar sesión y se reabre a los 5 s si falla (si se cierra a propósito, queda cerrado). |
| `observatorio-rendimiento` | sistema, opcional | Fija el modo de energía y `jetson_clocks` al arrancar (`instalar.sh --rendimiento-maximo N`). |

```bash
sudo systemctl status observatorio-admin        journalctl -u observatorio-admin -f
systemctl --user status observatorio-kiosco     journalctl --user -u observatorio-kiosco -f
systemctl --user stop observatorio-kiosco       # mantención: cierra el kiosco (vuelve al reiniciar)
```

En el registro del kiosco (`journalctl --user -u observatorio-kiosco`) aparecen:
- la plataforma detectada;
- el proveedor de ONNX en uso (TensorRT, CUDA o CPU);
- si el RTSP se abrió con GStreamer o volvió a FFmpeg.

## 5. Modo de energía

El Orin Nano tiene modos de potencia configurables, entre 7 y 25 W según la documentación de NVIDIA. **Los números de modo dependen de la versión de JetPack.** No los fijamos de antemano: se consultan en la placa.

```bash
sudo nvpmodel -q                          # modo activo
grep -E "POWER_MODEL" /etc/nvpmodel.conf  # modos disponibles: ID y nombre
sudo nvpmodel -m <ID>                     # cambiar de modo (algunos cambios piden reiniciar)
sudo jetson_clocks                        # fija CPU, GPU y memoria en su máximo dentro del modo activo
sudo jetson_clocks --show                 # muestra las frecuencias actuales
```

Para producción conviene el modo de mayor potencia disponible, que suele llamarse MAXN o MAXN SUPER, junto con `jetson_clocks`. Esto se hace con `bash scripts/jetson/instalar.sh --rendimiento-maximo <ID>`. A cambio sube el consumo y la temperatura, así que hay que revisar la ventilación (la temperatura queda en el CSV de `medir.py`).

## 6. Medir (KPI-02 y KPI-03)

```bash
.venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente video
.venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente rtsp
```

Guarda en `data/mediciones/` un CSV y un resumen. El CSV registra cada 5 s:
- FPS y milisegundos de inferencia (promedio, p95 y máximo);
- proveedor de ONNX;
- RAM y temperaturas, desde `tegrastats`.

El resumen compara con las metas (≥ 15 FPS, ≤ 90 ms). La **primera ejecución con TensorRT compila el motor**, que puede tardar varios minutos, y lo guarda en `data/cache_tensorrt/`. Hay que medir **después** de esa primera vez.

Tras la primera ejecución con TensorRT en FP16, también hay que evaluar de nuevo la exactitud del clasificador en la placa:
`.venv/bin/python laboratorio_ia/scripts_entrenamiento/evaluar_clasificador.py`

## 7. Pruebas en la placa (Fase 2), en orden

```bash
cat /etc/nv_tegra_release; python3 --version; free -h; df -h; sudo nvpmodel -q
echo $XDG_SESSION_TYPE                                   # debe decir x11
xrandr --listmonitors                                    # con hub MST + 2 monitores: ¿aparecen 2?
bash scripts/jetson/configurar_pantallas.sh --listar
xinput list --name-only                                  # nombres de los paneles táctiles
bash scripts/jetson/configurar_pantallas.sh              # tocar cada pantalla: ¿el toque cae en ella?
bash scripts/jetson/ejecutar_observatorio.sh --fuente video
bash scripts/jetson/ejecutar_observatorio.sh --fuente rtsp     # si hay cámara IP
.venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente video
```

**Criterio del hub MST:** si `xrandr --listmonitors` no muestra **dos monitores independientes**, la opción A (hub MST) no funciona. Hay que detenerse y decidir otra opción.

Todos los valores de rendimiento (FPS, ms, RAM y temperatura) están **pendientes de medición** en la placa.
