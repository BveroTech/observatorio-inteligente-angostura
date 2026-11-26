# Observatorio Inteligente de Aves · Parque Angostura

Prototipo académico (Proyecto de Título INACAP) para el Centro de Visitantes del Parque Angostura. Estructurado en **5 capas desacopladas** con soporte para inferencia en el borde (*Edge Computing*) y empaquetado mediante PyInstaller en dos ejecutables independientes (`Kiosco.exe` y `Admin.exe`).

## Arquitectura de 5 Capas

| Capa | Paquete / Módulo | Responsabilidad |
|---|---|---|
| **1. Adquisición** | `src/adquisicion/captura_rtsp.py` | Captura RTSP/USB en hilo demonio, búfer de último cuadro seguro y *failover* automático a video de demostración (`assets/videos/demo.mp4`). |
| **2. Procesamiento** | `src/procesamiento/inferencia_onnx.py`, `src/procesamiento/seguimiento.py`, `src/procesamiento/motor_vision.py` | Inferencia ONNX en una o dos etapas (detector YOLO + clasificador de especies), filtro de resolución mínima (`120x120 px`), seguimiento IoU y confirmación temporal. |
| **3. Aplicación** | `src/aplicacion/gestor_audio.py`, `src/aplicacion/gestor_monitores.py`, `src/aplicacion/puente_json.py`, `src/aplicacion/servicio_catalogo.py` | Gestión de audio (Pygame/`winsound`), detección de monitores Windows, puente atómico JSON (`data/aves_hoy.json`) y servicio del catálogo interactivo. |
| **4. Presentación** | `src/presentacion/tema_visual.py`, `src/presentacion/ventana_kiosco.py`, `src/presentacion/pantalla_secundaria.py`, `web/` | Kiosco de monitoreo en vivo (Pantalla 1), Segunda Pantalla Táctil de Autoatención (Pantalla 2: Menú de Inicio, Catálogo Público Read-Only con Teclado Virtual y Trivia de Cantos) y Portal Web Administrativo en Flask (`web/auth.py`, `web/admin_crud.py`, `web/dashboard_metricas.py`). |
| **5. Persistencia** | `src/persistencia/repositorio_sqlite.py` | Repositorio SQLite en modo WAL (`data/observatorio.db`) con concurrencia sin bloqueo entre procesos (`Kiosco` + `Admin`) y resolución dinámica de rutas. |
| **Configuración** | `config/settings.py`, `config/clases_modelo.json` | Parámetros globales y resolución de rutas híbrida con soporte para `sys._MEIPASS` (PyInstaller). |

## Puntos de Entrada

- **`main_kiosco.py`** (`Kiosco.exe`): Inicia el Kiosco principal (Pantalla 1), el motor de visión e inferencia ONNX y la Segunda Pantalla interactiva (Pantalla 2).
- **`main_admin.py`** (`Admin.exe`): Inicia el servidor web administrativo local en `http://127.0.0.1:5000`.
- **`scripts/cli_admin/verificar_entorno.py`**: Verifica dependencias, modelos ONNX, catálogo CSV y base de datos SQLite.

## Versión instalable para Windows (ejecutable)

Para construirla, ejecutar `scripts\lanzadores_windows\construir_ejecutable.bat`, que usa `scripts/windows/construir_ejecutable.py` y `observatorio.spec`. Genera tres cosas en `dist\`:

- **`Instalar_Observatorio_<versión>.exe`**: el instalador, armado con Inno Setup 6. Instala por usuario, sin permisos de administrador, y crea accesos directos en el menú Inicio y el escritorio:
  - Observatorio de Aves
  - Portal de administración
  - Crear usuario del portal
  - Ver monitores
  - Configuración
  - Cámara IP

  También ofrece abrir el kiosco al iniciar Windows y permitir el portal en el firewall.
- **`Observatorio_<versión>_portable.zip`**: la misma aplicación sin instalador.
- **`Observatorio\`**: la carpeta con los ejecutables:
  - `Observatorio.exe`: kiosco y pantalla táctil; abre también el portal.
  - `Admin.exe`: el portal.

En la versión instalada, todo lo que se configura sin programar está en `config\observatorio.ini`, que se edita con el Bloc de notas (plantilla: `config/observatorio.ejemplo.ini`):
- la fuente de video;
- los monitores y la pantalla completa;
- el portal en la red;
- el umbral de la IA.

La dirección de la cámara va en `config\camara_local.json`.

Al actualizar o desinstalar se conservan:
- `data\`: base de datos, capturas y registros;
- la configuración y la dirección de la cámara.

Con `--incluir-base-datos`, el instalador lleva el catálogo editado y los usuarios de este PC.

## Idiomas: fichas en español, inglés y alemán

Las fichas se escriben en **español** en el portal. Al guardarlas, se traducen solas al **inglés** y al **alemán**, sin internet. En la pantalla táctil, el visitante elige **Español · English · Deutsch** en el encabezado. La ficha completa se muestra en ese idioma: textos, títulos, medidas y estado de conservación. El catálogo también muestra los nombres en ese idioma. Tras un minuto sin uso, la pantalla vuelve al español.

**Traducciones** (página de cada especie en el portal):
- Se pueden corregir a mano. Lo corregido queda marcado como **revisada** y no se vuelve a traducir solo.
- Si después cambia el texto en español, el portal avisa con **«el español cambió»**.
- Los estados UICN/RCE usan los nombres oficiales de cada categoría, no la traducción automática.
- La traducción automática de los textos largos es útil, pero conviene revisarla, sobre todo los nombres comunes.
- Para traducir todo el catálogo de una vez: `python scripts/cli_admin/traducir_fichas.py`. En la versión instalada: `Admin.exe --traducir-fichas`.

**Leer la ficha en voz alta** (pantalla táctil):
- En cada ficha hay un botón **«Leer ficha»** (*Read aloud* · *Vorlesen*).
- Lee en voz alta, en el idioma elegido: el nombre, el estado de conservación, las medidas y cada sección.
- Usa voces neuronales **Piper**, sin internet, que corren con ONNX Runtime: `es_MX-claude-high`, `en_US-lessac-medium` y `de_DE-thorsten-medium`, guardadas en `modelos/voces`.
- La lectura empieza en uno o dos segundos y se arma por partes. Lo leído queda en `data/cache_voz`, así que la segunda vez empieza al instante.
- Se detiene al tocar «Detener lectura», al tocar «Escuchar canto», al salir de la ficha o al cambiar de idioma.
- Mientras lee, la pantalla no vuelve sola al menú.

**Leer ficha técnica** (portal, al editar o crear una especie):
1. Se elige el idioma del documento (ES/EN/DE) y se sube una foto, un escaneo o un PDF.
2. Tesseract lo lee en ese idioma y rellena los campos que reconoce: nombres, taxonomía, medidas, conservación, hábitat, alimentación…
   - Convierte las unidades (kg→g, m y mm→cm).
   - Si el documento es inglés o alemán, lo traduce al español y guarda el texto original como traducción revisada de ese idioma.
3. Nada se guarda hasta que el administrador revisa y presiona Guardar.

**Requisitos (código fuente):**
- Tesseract: `winget install -e --id UB-Mannheim.TesseractOCR`.
- Los modelos: `python scripts/cli_admin/descargar_modelos_idiomas.py`. Deja en `modelos/tessdata` los idiomas spa/eng/deu y en `modelos/traduccion` los traductores OPUS-MT de Argos Translate (CC-BY 4.0), que corren con CTranslate2.

`instalar_windows.bat` hace ambas cosas. La versión instalada (ejecutable) ya trae Tesseract y los modelos.

## Fuente de video: cámara IP o captura de pantalla

En el portal, el menú **Fuente de video** (solo administradores) permite elegir qué analiza la IA:
- **Cámara IP (RTSP):** la cámara del humedal. La dirección se escribe ahí mismo; la contraseña nunca se muestra.
- **Captura de pantalla:** se elige el monitor. Sirve para probar sin cámara.
- **Captura de una aplicación:** solo la ventana de un programa (navegador, VLC…), que se elige de la lista de aplicaciones abiertas.
  - Funciona aunque la ventana esté detrás de otras o se mueva.
  - Si el programa entrega la imagen en negro, se captura su zona de la pantalla.
  - Solo Windows. Por línea de comandos: `--fuente ventana --ventana "chrome.exe|YouTube"`.
- **Cámara USB** o **video de demostración**.

Al guardar, el kiosco **cambia de fuente en vivo**, en unos segundos y sin reiniciarse. La página muestra qué está usando el kiosco y si recibe imagen.

La elección queda en `config/observatorio.ini` (`[camara]`) y la dirección de la cámara en `config/camara_local.json`. En la versión instalada también hay accesos directos: **«Observatorio (cámara IP)»** y **«Observatorio (captura de pantalla)»**.

## Instalación en otro PC y entrenamiento del modelo

1. Instalar Python 3.11 y ejecutar `scripts\lanzadores_windows\instalar_windows.bat`. Si el `.venv` viene de otro equipo y está roto, el instalador lo recrea con `py -3.11`.
2. Abrir el kiosco con `scripts\lanzadores_windows\ejecutar_observatorio.bat`.
3. Para reentrenar el clasificador de especies, ejecutar `laboratorio_ia\scripts_entrenamiento\bat\instalar_entrenamiento.bat`, que instala PyTorch con CUDA si hay GPU NVIDIA. Después seguir **[laboratorio_ia/ENTRENAMIENTO.md](laboratorio_ia/ENTRENAMIENTO.md)**, que explica la descarga desde iNaturalist, la revisión de etiquetas, los experimentos, la evaluación y el despliegue.

Modelo actual: YOLO11s-cls de 224 px, con **95,4 % de exactitud** en 863 fotos de prueba (meta: 90 %).

## Probar sin cámara (captura de pantalla)

Reproduce un video de aves en un monitor (YouTube, eBird, Macaulay Library…) y ejecuta:

- `scripts\lanzadores_windows\probar_con_pantalla.bat`: ventana de prueba en otro monitor con las **3 especies más probables** de cada ave, el panel de especies agrupadas por parecido y, al cerrar con Q, un informe en `laboratorio_ia/reportes/prueba_pantalla_<fecha>.md`.
- `scripts\lanzadores_windows\ejecutar_observatorio.bat --fuente pantalla --monitor 4 --monitor-kiosco 1 --monitor-tactil 2`: el sistema completo usando el monitor 4 como si fuera la cámara, con el kiosco en el 1 y la pantalla táctil en el 2. En el PC de desarrollo de 4 monitores lo hace `probar_sistema_con_pantalla.bat`. Con un solo monitor, `--region x,y,ancho,alto` limita la captura a la zona del video.

Los números de monitor son los de Windows (Configuración → Pantalla → Identificar). En el Centro de Visitantes, con 2 monitores, no hace falta indicarlos: el kiosco se abre en el principal y la pantalla táctil en el otro (`MONITOR_KIOSCO` y `MONITOR_PANTALLA_2` en `config/settings.py`).

**Velocidad:** el video del kiosco se muestra a `FPS_VIDEO` (30) aunque la IA analice menos cuadros por segundo; los recuadros se actualizan al ritmo de la IA. La IA usa la mitad de los núcleos (`HILOS_IA`) para dejar CPU libre al video. La captura de pantalla usa `dxcam` (DirectX, 30 FPS); `mss` queda como respaldo.

Requiere `mss` y `dxcam` (están en `requirements.txt`; los `.bat` de prueba los instalan si faltan).

## Aves por identificar (el sistema aprende de la cámara)

Cuando el kiosco ve un ave que no reconoce, guarda un recorte de ella. En el portal, el menú **Por identificar** muestra esas fotos para indicar qué especie es (o descartarlas). `laboratorio_ia\scripts_entrenamiento\bat\importar_identificadas.bat` las suma al dataset para el próximo entrenamiento. Detalles en [laboratorio_ia/ENTRENAMIENTO.md](laboratorio_ia/ENTRENAMIENTO.md), sección 7.

## Portal de administración desde otro computador

El PC del kiosco solo muestra el programa. La administración se hace **desde otro computador de la misma red**, con el navegador:

1. En el PC del kiosco, **una sola vez**: `scripts\lanzadores_windows\habilitar_portal_en_red.bat`. Pide permisos de administrador y abre el puerto 5000 en el firewall, solo en redes privadas o de dominio. Al final muestra el enlace.
2. `ejecutar_observatorio.bat` inicia el portal abierto a la red (`PORTAL_EN_RED=si`, al inicio del archivo).
3. Desde otro computador, abrir **`http://NOMBRE-DEL-PC-DEL-KIOSCO:5000`**. `ver_enlace_portal.bat` muestra el nombre y la IP exactos.

- El nombre del PC no cambia. La IP la asigna el router y puede cambiar: si se usa la IP, conviene reservarla en el router.
- Si Windows tiene la red como **pública**, el portal no se ve desde otros equipos. Hay que cambiarla a **privada**.
- El portal usa `waitress` como servidor web y exige usuario y contraseña. Va por HTTP sin cifrar, así que es solo para la red interna del Centro: **nunca se debe publicar en internet**.

## Producción en NVIDIA Jetson Orin Nano

El sistema de producción corre en un **Jetson Orin Nano** (JetPack 6.2.1, Ubuntu 22.04 ARM64, Python 3.10). El código es el mismo que en Windows: detecta la plataforma solo y en el Jetson usa:

- la GPU, con TensorRT → CUDA → CPU;
- GStreamer con decodificación por hardware para el RTSP;
- un hub DisplayPort MST para las dos pantallas;
- systemd para arrancar y reiniciar los servicios.

**Instalador:** `scripts\lanzadores_windows\construir_instalador_jetson.bat` genera `dist\observatorio-angostura_<versión>_arm64.deb`. En el Jetson se instala como una aplicación más con `sudo apt install ./observatorio-angostura_<versión>_arm64.deb`: queda en el menú, el portal arranca como servicio y el kiosco abre al iniciar sesión.

Instalación, pantallas, servicios, modo de energía y pruebas: **[scripts/jetson/LEEME_JETSON.md](scripts/jetson/LEEME_JETSON.md)**. Las dependencias del Jetson están en `requirements-jetson.txt` y la configuración de pantallas en `config/pantallas.conf`.
