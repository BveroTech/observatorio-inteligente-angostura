# Evaluación del clasificador de especies · 2026-11-11 13:42

- Modelo: `modelos\clasificador_aves.onnx` (224 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 881 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **NO CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **78.2 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 77.5 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 92.7 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Becacina común | 0 | 0 | — |
| Chincol | 0 | 0 | — |
| Cisne de cuello negro | 85 | 90 | 94.4 % |
| Garza chica | 0 | 0 | — |
| Garza grande | 0 | 0 | — |
| Gaviota de Franklin | 76 | 90 | 84.4 % |
| Golondrina chilena | 0 | 0 | — |
| Huala | 78 | 90 | 86.7 % |
| Hued-Hued del sur | 0 | 0 | — |
| Martin pescador | 88 | 90 | 97.8 % |
| Pato anteojillo | 58 | 72 | 80.6 % |
| Pato cuchara | 61 | 90 | 67.8 % |
| Pato jergon grande | 78 | 89 | 87.6 % |
| Pato rana de pico delgado | 77 | 90 | 85.6 % |
| Tagua comÃºn | 0 | 0 | — |
| Tagua común | 16 | 90 | 17.8 % |
| Tagua com├║n | 0 | 0 | — |
| Torcaza | 0 | 0 | — |
| Yeco | 72 | 90 | 80.0 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Becacina común | Chincol | Cisne de cuell | Garza chica | Garza grande | Gaviota de Fra | Golondrina chi | Huala | Hued-Hued del  | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua comÃºn | Tagua común | Tagua com├║n | Torcaza | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Becacina común | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Chincol | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Cisne de cuello negro | · | · | 85 | 1 | · | 2 | 1 | 1 | · | · | · | · | · | · | · | · | · | · | · |
| Garza chica | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Garza grande | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Gaviota de Franklin | · | 1 | 6 | · | · | 76 | 2 | · | · | · | 2 | · | 1 | · | · | · | · | 1 | 1 |
| Golondrina chilena | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Huala | · | 2 | · | · | · | · | 1 | 78 | 1 | · | 1 | 1 | · | 1 | 2 | · | 1 | · | 2 |
| Hued-Hued del sur | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Martin pescador | · | · | · | · | · | · | · | · | · | 88 | · | · | · | · | · | · | · | 2 | · |
| Pato anteojillo | · | 1 | 1 | · | · | 1 | · | 1 | · | · | 58 | · | 4 | 1 | · | · | 1 | 1 | 3 |
| Pato cuchara | 2 | · | · | · | · | 1 | · | 2 | 1 | · | 2 | 61 | 8 | 6 | · | 2 | · | 3 | 2 |
| Pato jergon grande | 1 | · | 1 | · | · | · | 1 | · | · | · | 3 | 3 | 78 | · | · | · | · | 1 | 1 |
| Pato rana de pico delgado | 1 | · | · | · | · | · | 1 | 3 | 1 | · | · | · | · | 77 | · | · | 5 | 2 | · |
| Tagua comÃºn | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Tagua común | 1 | · | 1 | · | 1 | 1 | · | · | 2 | · | 1 | · | · | · | 31 | 16 | 31 | 1 | 4 |
| Tagua com├║n | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Torcaza | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| Yeco | · | · | 1 | 1 | · | · | 4 | 1 | 2 | 3 | · | · | 1 | · | 1 | 3 | 1 | · | 72 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Tagua común/inat_152825235.jpg` | Tagua común | Garza grande | 1.00 |
| `Martin pescador/inat_106081810.jpg` | Martin pescador | Torcaza | 1.00 |
| `Gaviota de Franklin/inat_72304210.jpg` | Gaviota de Franklin | Cisne de cuello negro | 1.00 |
| `Cisne de cuello negro/inat_38073727.jpg` | Cisne de cuello negro | Gaviota de Franklin | 0.99 |
| `Pato anteojillo/inat_67570041_1.jpg` | Pato anteojillo | Cisne de cuello negro | 0.99 |
| `Pato anteojillo/inat_366562035_1.jpg` | Pato anteojillo | Yeco | 0.99 |
| `Pato cuchara/inat_126915544.jpg` | Pato cuchara | Pato rana de pico delgado | 0.97 |
| `Pato anteojillo/inat_48648208.jpg` | Pato anteojillo | Pato jergon grande | 0.96 |
| `Gaviota de Franklin/inat_180274063.jpg` | Gaviota de Franklin | Chincol | 0.95 |
| `Pato anteojillo/inat_94535672_1.jpg` | Pato anteojillo | Pato jergon grande | 0.94 |
| `Pato cuchara/inat_252079935.jpg` | Pato cuchara | Becacina común | 0.93 |
| `Gaviota de Franklin/134_jpg.rf.62fc685d1957794dcbd99b00efe9740e_0.jpg` | Gaviota de Franklin | Cisne de cuello negro | 0.93 |
| `Pato cuchara/inat_148642135.jpg` | Pato cuchara | Pato rana de pico delgado | 0.93 |
| `Huala/inat_29344724.jpg` | Huala | Pato cuchara | 0.93 |
| `Huala/inat_69697600.jpg` | Huala | Yeco | 0.93 |
