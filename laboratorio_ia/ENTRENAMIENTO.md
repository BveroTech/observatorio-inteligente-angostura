# Entrenamiento del clasificador de especies

Esta guía permite repetir, en cualquier PC con Windows, el entrenamiento del modelo que identifica las 10 especies foco. El modelo desplegado en noviembre de 2026 alcanza un **95,4 % de exactitud** en fotos que nunca vio al entrenar. La meta del proyecto era 90 %.

## 1. Cómo identifica un ave el kiosco

El kiosco trabaja en dos etapas (`src/procesamiento/inferencia_onnx.py`):

1. **Detector** (`modelos/detector_aves.onnx`, YOLOv8n COCO): encuentra la clase "bird" en el cuadro. Las aves de menos de 120 px se descartan.
2. **Clasificador** (`modelos/clasificador_aves.onnx`): recibe el recorte del ave y elige una de las 10 especies. Con una confianza menor que `UMBRAL_CONFIANZA` (0,70, en `config/settings.py`), el kiosco no muestra la especie.

Esta guía trata solo del **clasificador**. El detector COCO ya reconoce aves y no se reentrena.

## 2. Preparar el PC

Requisitos: Python 3.11 (usar `py -3.11`; el `python` de la Microsoft Store no sirve). Se recomienda una GPU NVIDIA. Con solo CPU el entrenamiento tarda días.

```bat
scripts\lanzadores_windows\instalar_windows.bat
laboratorio_ia\scripts_entrenamiento\bat\instalar_entrenamiento.bat
```

- `instalar_windows.bat` crea `.venv` con Python 3.11. Si el `.venv` viene copiado de otro PC y quedó roto, lo recrea.
- `instalar_entrenamiento.bat` instala PyTorch **con CUDA** (índice `cu128`) cuando encuentra `nvidia-smi`. El PyTorch de PyPI para Windows trae solo CPU. Al final muestra si la GPU quedó disponible.

Equipo usado: i7-10700, 32 GB de RAM, RTX 3060 12 GB, PyTorch 2.11 + CUDA 12.8, Ultralytics 8.4.

## 3. Armar el dataset

Las fotos van en `laboratorio_ia/dataset_aves/{train,val,test}/<Especie>/`. Los nombres de las carpetas deben coincidir con `config/clases_modelo.json`.

### 3.1 Descargar fotos de iNaturalist

```bat
laboratorio_ia\scripts_entrenamiento\bat\descargar_fotos.bat --cantidad 600
```

Por cada especie, el script:

- busca observaciones de **grado investigación**, es decir, con la identificación confirmada por la comunidad;
- usa solo fotos con licencia **CC0, CC BY o CC BY-NC**;
- recorta el ave con YOLO, igual que el kiosco con la cámara;
- descarta fotos sin una única ave de tamaño suficiente.

Las fotos se reparten por **observación**: todas las fotos de un mismo avistamiento quedan en la misma división. Así no se filtran datos de train a test. Descarga 8 fotos en paralelo. Si se interrumpe, se vuelve a ejecutar y continúa donde quedó.

El Pato anteojillo tiene pocas observaciones libres, así que se completó con:

```bat
laboratorio_ia\scripts_entrenamiento\bat\descargar_fotos.bat --especies "Pato anteojillo" --cantidad 400 ^
    --fotos-por-observacion 4 --foto-grande --parejas --licencias cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nc-sa
```

Las licencias ND (sin derivados) nunca se usan, porque recortar una foto es una obra derivada.

**Créditos:** el autor y la licencia de cada foto quedan en `dataset_aves/creditos_inaturalist.csv`. Hay que citarlos en el informe. Las fotos CC BY-SA obligan a compartir con la misma licencia solo las imágenes derivadas, no el modelo ni el software.

### 3.2 Ordenar y revisar etiquetas

```bat
laboratorio_ia\scripts_entrenamiento\bat\limpiar_dataset.bat
```

Deja solo las 10 especies foco y elimina duplicados.

iNaturalist tiene errores de etiqueta, y la opción `--parejas` puede colar una segunda especie. Por eso, después de un primer entrenamiento se revisan las etiquetas:

```bat
.venv\Scripts\python.exe -X utf8 laboratorio_ia\scripts_entrenamiento\revisar_etiquetas.py --modelo RUTA\best.pt
```

El script genera `reportes/revision_etiquetas/sospechosas.csv` y hojas de miniaturas `hoja_<especie>.jpg`. Ahí aparecen las fotos que el modelo asigna con confianza ≥ 0,6 a **otra** especie.

**Criterio:** una persona mira cada sospechosa. Se aparta solo si claramente no es la especie de su carpeta: otra especie, algo que no es un ave, o un ave irreconocible. Si el error es del modelo, la foto se queda. Las fotos elegidas se anotan en una lista (`ruta/relativa.jpg  # motivo`) y se apartan con:

```bat
.venv\Scripts\python.exe -X utf8 laboratorio_ia\scripts_entrenamiento\revisar_etiquetas.py --apartar lista.txt
```

Las fotos se **mueven**, no se borran, a `dataset_aves_anterior/mal_etiquetadas/`, y cada una queda registrada con su motivo en `registro.csv`. En esta ronda se apartaron 41 fotos: gaviotas, un águila calva, flamencos, otros patos, etc.

Dataset final: **3.932 train · 855 val · 863 test**, entre 67 y 90 fotos de prueba por especie.

## 4. Entrenar y comparar candidatos

```bat
laboratorio_ia\scripts_entrenamiento\bat\experimentos_clasificador.bat
```

El script entrena varias configuraciones con `--sin-desplegar`, sin tocar el modelo del kiosco. Después evalúa cada una en test con `evaluar_clasificador.py`, que usa exactamente el mismo preprocesamiento que el kiosco. Todas parten de pesos ImageNet de Ultralytics y usan:

- 150 épocas como máximo, con paciencia de 40;
- lote de 32, tasa de aprendizaje coseno y *label smoothing* 0,1;
- semilla fija, para que el entrenamiento sea reproducible.

**Velocidad:** por defecto, 8 procesos de CPU (`--procesos 8`) preparan y aumentan las imágenes en paralelo mientras la GPU entrena. Con un solo proceso, la GPU esperaba a la CPU: estaba al 25–30 % y cada época de YOLO11l tardaba unos 3 minutos. Con 8 procesos sube al 99 % y la época baja a unos 30 segundos. En modo de varios procesos no se usa `cache="ram"`, porque en Windows cada proceso copiaría el dataset completo en memoria. Mientras se entrena conviene no usar el PC para juegos, porque compiten por la GPU.

Antes de entrenar, `entrenar_clasificador.py` se niega a empezar si encuentra una imagen repetida entre divisiones o una observación repartida en dos divisiones.

Para entrenar una sola configuración:

```bat
.venv\Scripts\python.exe -X utf8 laboratorio_ia\scripts_entrenamiento\entrenar_clasificador.py ^
    --base yolo11s-cls.pt --tamano 224 --epocas 150 --paciencia 40 --nombre A_yolo11s_224 --sin-desplegar
```

Si un entrenamiento se corta (reinicio o corte de luz), se retoma desde su último punto guardado con `--reanudar`:

```bat
.venv\Scripts\python.exe -X utf8 laboratorio_ia\scripts_entrenamiento\entrenar_clasificador.py --nombre C_yolo11l_320 --reanudar --sin-desplegar
```

`bat\completar_experimentos.bat` hace esto con C y luego entrena y evalúa D.

### Resultados (test: 863 fotos no vistas, umbral 0,70)

| Modelo | Exactitud test | Cobertura | Precisión | Mejor val | Anteojillo | Kiosco por cuadro 1080p (mediana · p95) |
|---|---:|---:|---:|---:|---:|---:|
| Anterior (YOLOv8n-cls, oct-2026)* | 78,2 % | 77,5 % | — | — | — | 46 · 70 ms |
| **A · YOLO11s 224 px (desplegado)** | **95,4 %** | 96,5 % | **97,7 %** | 96,8 % | 88,1 % | **56 · 84 ms** |
| B · YOLO11m 320 px | 95,8 % | 97,9 % | 97,2 % | 96,6 % | 94,0 % | 80 · 126 ms |
| C · YOLO11l 320 px | 95,0 % | 97,2 % | 96,7 % | 97,1 % | 89,6 % | 88 · 128 ms |
| D · YOLO11l 384 px | 95,2 % | 97,8 % | 96,9 % | 96,6 % | 92,5 % | 106 · 170 ms |

\* El modelo anterior se evaluó sobre las 881 fotos de test antes de la limpieza de etiquetas. Con esas mismas 881 fotos, un YOLO11s de 224 px entrenado igual que A (`exp_yolo11s_224`, antes de la limpieza) obtuvo 94,2 %.

- **Cobertura:** % de aves que el kiosco identifica, es decir, con confianza ≥ 0,70.
- **Precisión:** % de esas identificaciones que son correctas.
- **Kiosco por cuadro:** detector + clasificador sobre 48 cuadros 1080p con un ave, medidos en la misma ejecución en el i7-10700, sin otros programas abiertos. La meta del proyecto es ≤ 90 ms. Las cifras varían unos ±15 ms entre ejecuciones, así que conviene repetir la medición en el PC del kiosco.
- C se cortó por un reinicio del equipo y se retomó con `--reanudar`. Tanto C como D se detuvieron solos por paciencia, en las épocas 148 y 114.

**Por qué se eligió A:**

- Los cuatro modelos quedan entre 95,0 % y 95,8 %. Las diferencias son de unas 3 a 7 fotos de 863, dentro del margen de error, y la mejor nota en validación (C) no fue la mejor en prueba. Con este dataset, un modelo más grande no da más exactitud: el límite son las fotos, sobre todo las del Pato anteojillo.
- A tiene la mayor precisión con el umbral 0,70, es decir, cuando el kiosco nombra una especie es cuando menos se equivoca.
- A es el único que cumple la meta de ≤ 90 ms con margen, incluso en los cuadros lentos (p95). B, C y D la superan en el p95.
- B y D reconocen mejor el Pato anteojillo (94,0 % y 92,5 %, contra 88,1 % de A), pero son bastante más lentos. Son 67 fotos, así que 4 aciertos más ya equivalen a 6 puntos.

**Especie más débil:** Pato anteojillo, con 88,1 % (59 de 67) porque tiene menos fotos. Todas las demás están entre 92 % y 99 %. El detalle por especie y la matriz de confusión están en `reportes/desplegado_A_test.md`.

**Advertencia metodológica:** la limpieza de etiquetas también apartó fotos mal etiquetadas de test. Eso sube un poco la exactitud medida, porque esas fotos habrían contado como errores aunque fuera el modelo el que tenía razón. Antes de la limpieza, la misma configuración ya obtenía 94,2 % (`reportes/exp_yolo11s_224_test.md`).

## 5. Desplegar y verificar

```bat
copy laboratorio_ia\runs\classify\A_yolo11s_224\weights\best.pt modelos\clasificador_aves.pt
laboratorio_ia\scripts_entrenamiento\bat\exportar_modelos.bat --clasificador modelos\clasificador_aves.pt
laboratorio_ia\scripts_entrenamiento\bat\evaluar_clasificador.bat
```

- `exportar_onnx.py` lee del `.pt` el tamaño con que se entrenó (224 px) y exporta con ese tamaño. El kiosco lo toma del ONNX, así que no hay que configurar nada.
- `evaluar_clasificador.bat` evalúa el modelo desplegado y deja un reporte en `laboratorio_ia/reportes/`. Termina con código 2 si la exactitud queda bajo 90 %.
- El modelo anterior está respaldado en `modelos/respaldo/`. Para volver atrás, se copian esos dos archivos como `modelos/clasificador_aves.{onnx,pt}`.

## 6. Archivos que deja el proceso

| Ruta | Contenido |
|---|---|
| `laboratorio_ia/runs/classify/<experimento>/` | Pesos, curvas y `results.csv` de cada entrenamiento |
| `laboratorio_ia/reportes/*_test.md` | Evaluación en test de cada candidato y del modelo desplegado |
| `laboratorio_ia/reportes/revision_etiquetas/` | Sospechosas y hojas de revisión |
| `laboratorio_ia/dataset_aves/creditos_inaturalist.csv` | Autor y licencia de cada foto |
| `laboratorio_ia/dataset_aves_anterior/mal_etiquetadas/` | Fotos apartadas y `registro.csv` |
| `laboratorio_ia/*.log` | Bitácoras de descarga y entrenamiento |

## 7. Aprender de la cámara: aves por identificar

El modelo solo conoce las especies con las que se entrenó. Cuando la cámara ve un ave que no reconoce, el sistema la guarda para que una persona la identifique. Con esas fotos, el siguiente entrenamiento es mejor.

1. **El kiosco guarda el ave.** Esto ocurre cuando se sigue al ave durante al menos 5 cuadros sin reconocerla: confianza bajo 0,70 o especie sin ficha activa. Se guarda **un** recorte por ave, el más grande que se vio, en `data/por_identificar/<fecha>/` y en la tabla `AVE_POR_IDENTIFICAR`. Hay un mínimo de 20 s entre registros y un máximo de 300 por día. Se configura en `config/settings.py` con `GUARDAR_AVES_DESCONOCIDAS`, `SEGUNDOS_ENTRE_DESCONOCIDAS` y `MAXIMO_DESCONOCIDAS_DIA`.
2. **Una persona la identifica en el portal.** Menú **Por identificar** (http://127.0.0.1:5000/por-identificar), donde el número naranjo indica cuántas faltan. Para cada foto hay cuatro opciones:
   - elegir la especie entre todo el catálogo;
   - marcar «No es un ave»;
   - «Descartar», si la foto no sirve;
   - si la especie no está en el catálogo, agregarla desde «Especies».
3. **Las fotos pasan al dataset:**
   ```bat
   laboratorio_ia\scripts_entrenamiento\bat\importar_identificadas.bat
   ```
   - **Especie que el modelo ya conoce:** va a `dataset_aves/` (10 % a test, 10 % a val y el resto a train). Son fotos de la cámara real, así que corrigen justo los casos en que el modelo falla en el humedal.
   - **Especie nueva:** se acumula en `laboratorio_ia/dataset_nuevas/<especie>/` hasta reunir 60 fotos. Entonces se agrega como clase: se reparten sus fotos en `dataset_aves/{train,val,test}/<Nombre común>/`, se completa con iNaturalist si faltan y se entrena con `--forzar`. El nombre común del catálogo basta para vincular la clase con su ficha.
   - **Clase «Otra ave»:** si existe, las especies nuevas también se copian ahí, para que el modelo aprenda a decir «no es ninguna de las que conozco».
   - **Por defecto solo se usan fotos de la cámara real.** `--incluir-simulacion` agrega las del video de demostración y de la captura de pantalla.
4. **Se reentrena, se evalúa y se despliega solo si mejora** (secciones 4 y 5).

**El reentrenamiento no es automático, y es a propósito.** Una etiqueta equivocada, o un modelo que empeora en alguna especie, no deben llegar al kiosco sin que alguien revise la evaluación. Cada reentrenamiento toma de 30 a 60 minutos con GPU.

**Límite actual:** un ave fuera de las 10 especies a veces recibe una confianza alta. En pruebas, un jilguero salió como «Gaviota de Franklin 96 %». Esas aves no llegan a «Por identificar», sino que se registran con la especie equivocada. La solución es entrenar la clase «Otra ave» con fotos de las demás aves de Angostura. Mientras tanto, esos errores se pueden ver en la Bitácora.
