# Evaluación del clasificador de especies · 2026-11-11 23:25

- Modelo: `laboratorio_ia\runs\classify\C_yolo11l_320\weights\best.onnx` (320 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 863 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **95.0 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 97.2 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 96.7 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Cisne de cuello negro | 84 | 89 | 94.4 % |
| Gaviota de Franklin | 85 | 89 | 95.5 % |
| Huala | 84 | 89 | 94.4 % |
| Martin pescador | 90 | 90 | 100.0 % |
| Pato anteojillo | 60 | 67 | 89.6 % |
| Pato cuchara | 81 | 87 | 93.1 % |
| Pato jergon grande | 85 | 87 | 97.7 % |
| Pato rana de pico delgado | 84 | 88 | 95.5 % |
| Tagua común | 85 | 89 | 95.5 % |
| Yeco | 82 | 88 | 93.2 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Cisne de cuell | Gaviota de Fra | Huala | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua común | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cisne de cuello negro | 84 | 3 | · | · | · | 1 | · | · | 1 | · |
| Gaviota de Franklin | · | 85 | · | · | · | · | 2 | 1 | 1 | · |
| Huala | · | · | 84 | 1 | · | · | 1 | 1 | 1 | 1 |
| Martin pescador | · | · | · | 90 | · | · | · | · | · | · |
| Pato anteojillo | 1 | · | · | · | 60 | 1 | 2 | 1 | 1 | 1 |
| Pato cuchara | · | 1 | 1 | · | · | 81 | 3 | 1 | · | · |
| Pato jergon grande | · | · | · | · | · | · | 85 | · | 1 | 1 |
| Pato rana de pico delgado | · | 1 | 1 | · | · | · | · | 84 | 1 | 1 |
| Tagua común | · | · | 3 | · | · | · | · | · | 85 | 1 |
| Yeco | · | 1 | · | 2 | · | · | · | · | 3 | 82 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Pato rana de pico delgado/inat_163521088.jpg` | Pato rana de pico delgado | Tagua común | 1.00 |
| `Tagua común/inat_162978592.jpg` | Tagua común | Yeco | 1.00 |
| `Cisne de cuello negro/inat_38073727.jpg` | Cisne de cuello negro | Gaviota de Franklin | 1.00 |
| `Pato anteojillo/inat_255960955.jpg` | Pato anteojillo | Pato jergon grande | 1.00 |
| `Yeco/inat_255017189.jpg` | Yeco | Tagua común | 0.99 |
| `Pato cuchara/inat_66379127.jpg` | Pato cuchara | Pato jergon grande | 0.99 |
| `Tagua común/inat_63189705.jpg` | Tagua común | Huala | 0.99 |
| `Pato rana de pico delgado/inat_405099965.jpg` | Pato rana de pico delgado | Yeco | 0.98 |
| `Gaviota de Franklin/inat_63278290.jpg` | Gaviota de Franklin | Pato jergon grande | 0.98 |
| `Huala/267_jpg.rf.51b313f90cc2e9bf26f39ea185f874bf_0.jpg` | Huala | Tagua común | 0.98 |
| `Huala/inat_37564816.jpg` | Huala | Martin pescador | 0.97 |
| `Pato cuchara/inat_183916116.jpg` | Pato cuchara | Gaviota de Franklin | 0.97 |
| `Pato anteojillo/inat_243194639.jpg` | Pato anteojillo | Cisne de cuello negro | 0.96 |
| `Yeco/inat_237893679.jpg` | Yeco | Tagua común | 0.96 |
| `Yeco/inat_193164239.jpg` | Yeco | Tagua común | 0.93 |
