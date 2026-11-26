# Evaluación del clasificador de especies · 2026-11-11 20:24

- Modelo: `modelos\clasificador_aves.onnx` (224 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 863 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **95.4 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 96.5 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 97.7 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Cisne de cuello negro | 86 | 89 | 96.6 % |
| Gaviota de Franklin | 86 | 89 | 96.6 % |
| Huala | 88 | 89 | 98.9 % |
| Martin pescador | 89 | 90 | 98.9 % |
| Pato anteojillo | 59 | 67 | 88.1 % |
| Pato cuchara | 80 | 87 | 92.0 % |
| Pato jergon grande | 84 | 87 | 96.6 % |
| Pato rana de pico delgado | 85 | 88 | 96.6 % |
| Tagua común | 84 | 89 | 94.4 % |
| Yeco | 82 | 88 | 93.2 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Cisne de cuell | Gaviota de Fra | Huala | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua común | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cisne de cuello negro | 86 | 1 | · | · | · | · | · | · | 1 | 1 |
| Gaviota de Franklin | 1 | 86 | · | · | · | 1 | 1 | · | · | · |
| Huala | · | · | 88 | · | · | · | · | · | · | 1 |
| Martin pescador | · | · | · | 89 | · | · | · | · | 1 | · |
| Pato anteojillo | · | 2 | · | 1 | 59 | 1 | 2 | · | 1 | 1 |
| Pato cuchara | 2 | · | 2 | · | · | 80 | 2 | · | · | 1 |
| Pato jergon grande | · | · | 2 | 1 | · | · | 84 | · | · | · |
| Pato rana de pico delgado | · | 1 | · | · | · | · | · | 85 | 1 | 1 |
| Tagua común | · | 1 | · | · | · | 1 | · | · | 84 | 3 |
| Yeco | · | · | 2 | 2 | · | · | · | · | 2 | 82 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Pato rana de pico delgado/inat_163521088.jpg` | Pato rana de pico delgado | Tagua común | 1.00 |
| `Pato anteojillo/inat_243194639_2.jpg` | Pato anteojillo | Yeco | 1.00 |
| `Tagua común/inat_162978592.jpg` | Tagua común | Yeco | 1.00 |
| `Yeco/inat_193164239.jpg` | Yeco | Tagua común | 1.00 |
| `Pato anteojillo/inat_190526845.jpg` | Pato anteojillo | Gaviota de Franklin | 1.00 |
| `Pato rana de pico delgado/inat_405099965.jpg` | Pato rana de pico delgado | Yeco | 0.97 |
| `Pato jergon grande/inat_341032281.jpg` | Pato jergon grande | Huala | 0.93 |
| `Pato anteojillo/inat_179461602.jpg` | Pato anteojillo | Pato cuchara | 0.93 |
| `Pato anteojillo/inat_255960955.jpg` | Pato anteojillo | Pato jergon grande | 0.90 |
| `Gaviota de Franklin/inat_362266725.jpg` | Gaviota de Franklin | Cisne de cuello negro | 0.86 |
| `Gaviota de Franklin/inat_358404236.jpg` | Gaviota de Franklin | Pato cuchara | 0.85 |
| `Pato anteojillo/inat_243194639.jpg` | Pato anteojillo | Martin pescador | 0.85 |
| `Yeco/inat_312992481.jpg` | Yeco | Huala | 0.83 |
| `Cisne de cuello negro/inat_261030589.jpg` | Cisne de cuello negro | Tagua común | 0.81 |
| `Yeco/inat_9901418.jpg` | Yeco | Huala | 0.80 |
