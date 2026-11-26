# Evaluación del clasificador de especies · 2026-11-12 00:35

- Modelo: `laboratorio_ia\runs\classify\D_yolo11l_384\weights\best.onnx` (384 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 863 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **95.2 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 97.8 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 96.9 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Cisne de cuello negro | 86 | 89 | 96.6 % |
| Gaviota de Franklin | 85 | 89 | 95.5 % |
| Huala | 85 | 89 | 95.5 % |
| Martin pescador | 89 | 90 | 98.9 % |
| Pato anteojillo | 62 | 67 | 92.5 % |
| Pato cuchara | 81 | 87 | 93.1 % |
| Pato jergon grande | 85 | 87 | 97.7 % |
| Pato rana de pico delgado | 86 | 88 | 97.7 % |
| Tagua común | 83 | 89 | 93.3 % |
| Yeco | 80 | 88 | 90.9 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Cisne de cuell | Gaviota de Fra | Huala | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua común | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cisne de cuello negro | 86 | 3 | · | · | · | · | · | · | · | · |
| Gaviota de Franklin | 1 | 85 | · | · | · | · | 1 | · | 1 | 1 |
| Huala | · | · | 85 | 1 | · | · | · | 2 | · | 1 |
| Martin pescador | · | · | · | 89 | · | 1 | · | · | · | · |
| Pato anteojillo | · | 2 | · | · | 62 | 1 | 1 | · | · | 1 |
| Pato cuchara | · | 1 | · | · | · | 81 | 3 | 1 | · | 1 |
| Pato jergon grande | · | · | 1 | · | · | 1 | 85 | · | · | · |
| Pato rana de pico delgado | · | · | · | · | · | · | · | 86 | 2 | · |
| Tagua común | · | · | 2 | · | · | · | · | · | 83 | 4 |
| Yeco | · | · | 1 | 1 | · | 1 | · | 1 | 4 | 80 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Pato cuchara/inat_318629799.jpg` | Pato cuchara | Pato jergon grande | 1.00 |
| `Cisne de cuello negro/229_jpg.rf.a87074dc47ff912cd8a7ee8673783669_0.jpg` | Cisne de cuello negro | Gaviota de Franklin | 1.00 |
| `Cisne de cuello negro/inat_38073727.jpg` | Cisne de cuello negro | Gaviota de Franklin | 1.00 |
| `Pato rana de pico delgado/inat_163521088.jpg` | Pato rana de pico delgado | Tagua común | 1.00 |
| `Cisne de cuello negro/inat_373880507.jpg` | Cisne de cuello negro | Gaviota de Franklin | 1.00 |
| `Yeco/inat_193164239.jpg` | Yeco | Tagua común | 0.99 |
| `Pato cuchara/inat_231339533.jpg` | Pato cuchara | Pato jergon grande | 0.99 |
| `Tagua común/inat_162978592.jpg` | Tagua común | Yeco | 0.98 |
| `Pato anteojillo/inat_179461602.jpg` | Pato anteojillo | Pato cuchara | 0.97 |
| `Gaviota de Franklin/inat_362266725.jpg` | Gaviota de Franklin | Cisne de cuello negro | 0.97 |
| `Pato anteojillo/inat_243194639_2.jpg` | Pato anteojillo | Yeco | 0.97 |
| `Huala/inat_37564816.jpg` | Huala | Martin pescador | 0.97 |
| `Pato cuchara/inat_86412835.jpg` | Pato cuchara | Pato jergon grande | 0.95 |
| `Pato anteojillo/inat_408929235_1.jpg` | Pato anteojillo | Gaviota de Franklin | 0.95 |
| `Yeco/inat_5081515.jpg` | Yeco | Pato cuchara | 0.92 |
