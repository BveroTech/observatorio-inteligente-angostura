# Evaluación del clasificador de especies · 2026-11-11 13:42

- Modelo: `laboratorio_ia\runs\classify\exp_yolo11s_224\weights\best.onnx` (224 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 881 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **94.2 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 97.2 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 96.1 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Cisne de cuello negro | 88 | 90 | 97.8 % |
| Gaviota de Franklin | 86 | 90 | 95.6 % |
| Huala | 86 | 90 | 95.6 % |
| Martin pescador | 90 | 90 | 100.0 % |
| Pato anteojillo | 61 | 72 | 84.7 % |
| Pato cuchara | 81 | 90 | 90.0 % |
| Pato jergon grande | 85 | 89 | 95.5 % |
| Pato rana de pico delgado | 86 | 90 | 95.6 % |
| Tagua común | 84 | 90 | 93.3 % |
| Yeco | 83 | 90 | 92.2 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Cisne de cuell | Gaviota de Fra | Huala | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua común | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cisne de cuello negro | 88 | 2 | · | · | · | · | · | · | · | · |
| Gaviota de Franklin | 1 | 86 | · | · | · | · | · | · | 1 | 2 |
| Huala | · | · | 86 | · | · | 2 | 1 | · | · | 1 |
| Martin pescador | · | · | · | 90 | · | · | · | · | · | · |
| Pato anteojillo | 2 | · | 1 | · | 61 | 4 | · | 1 | · | 3 |
| Pato cuchara | · | 1 | 3 | · | · | 81 | 4 | 1 | · | · |
| Pato jergon grande | · | · | 1 | · | 1 | 2 | 85 | · | · | · |
| Pato rana de pico delgado | · | · | 1 | · | · | · | 1 | 86 | 2 | · |
| Tagua común | · | 1 | 3 | · | · | · | · | · | 84 | 2 |
| Yeco | · | 1 | 1 | · | · | · | · | 1 | 4 | 83 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Pato cuchara/inat_226159056.jpg` | Pato cuchara | Pato jergon grande | 1.00 |
| `Pato anteojillo/inat_67570041_1.jpg` | Pato anteojillo | Cisne de cuello negro | 1.00 |
| `Pato rana de pico delgado/inat_163521088.jpg` | Pato rana de pico delgado | Tagua común | 1.00 |
| `Pato anteojillo/inat_8755558.jpg` | Pato anteojillo | Yeco | 1.00 |
| `Pato cuchara/inat_152681913.jpg` | Pato cuchara | Gaviota de Franklin | 1.00 |
| `Pato anteojillo/inat_366562035_1.jpg` | Pato anteojillo | Yeco | 1.00 |
| `Gaviota de Franklin/inat_362266725.jpg` | Gaviota de Franklin | Cisne de cuello negro | 1.00 |
| `Tagua común/inat_265967895.jpg` | Tagua común | Huala | 0.99 |
| `Pato jergon grande/inat_243444880.jpg` | Pato jergon grande | Pato cuchara | 0.99 |
| `Pato cuchara/inat_86412835.jpg` | Pato cuchara | Pato jergon grande | 0.99 |
| `Gaviota de Franklin/inat_277131303.jpg` | Gaviota de Franklin | Yeco | 0.99 |
| `Huala/inat_319678437.jpg` | Huala | Yeco | 0.98 |
| `Cisne de cuello negro/inat_70893178.jpg` | Cisne de cuello negro | Gaviota de Franklin | 0.98 |
| `Pato anteojillo/inat_337963087.jpg` | Pato anteojillo | Pato cuchara | 0.98 |
| `Yeco/inat_262586237.jpg` | Yeco | Huala | 0.98 |
