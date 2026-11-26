# Evaluación del clasificador de especies · 2026-11-11 19:23

- Modelo: `laboratorio_ia\runs\classify\B_yolo11m_320\weights\best.onnx` (320 px, CPUExecutionProvider)
- Conjunto: `dataset_aves/test/` · 863 recortes de ave no vistos al entrenar
- Meta del proyecto: exactitud ≥ 90.0 % → **CUMPLE**

| Métrica | Valor |
|---|---|
| Exactitud top-1 | **95.8 %** |
| Cobertura con umbral 0.70 (el kiosco identifica) | 97.9 % |
| Precisión con umbral 0.70 (identificaciones correctas) | 97.2 % |

## Exactitud por especie

| Especie | Aciertos | Total | Exactitud |
|---|---:|---:|---:|
| Cisne de cuello negro | 86 | 89 | 96.6 % |
| Gaviota de Franklin | 85 | 89 | 95.5 % |
| Huala | 87 | 89 | 97.8 % |
| Martin pescador | 88 | 90 | 97.8 % |
| Pato anteojillo | 63 | 67 | 94.0 % |
| Pato cuchara | 81 | 87 | 93.1 % |
| Pato jergon grande | 85 | 87 | 97.7 % |
| Pato rana de pico delgado | 85 | 88 | 96.6 % |
| Tagua común | 85 | 89 | 95.5 % |
| Yeco | 82 | 88 | 93.2 % |

## Matriz de confusión (fila = real, columna = predicha)

| Real \ Predicha | Cisne de cuell | Gaviota de Fra | Huala | Martin pescado | Pato anteojill | Pato cuchara | Pato jergon gr | Pato rana de p | Tagua común | Yeco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cisne de cuello negro | 86 | 2 | · | · | · | · | · | · | · | 1 |
| Gaviota de Franklin | · | 85 | · | · | · | 2 | 1 | · | 1 | · |
| Huala | · | · | 87 | 1 | · | 1 | · | · | · | · |
| Martin pescador | · | · | · | 88 | · | 1 | · | · | · | 1 |
| Pato anteojillo | · | · | · | · | 63 | 2 | 1 | · | · | 1 |
| Pato cuchara | · | · | 3 | · | · | 81 | 1 | · | · | 2 |
| Pato jergon grande | · | · | · | · | · | 1 | 85 | · | · | 1 |
| Pato rana de pico delgado | · | · | · | · | · | · | · | 85 | 2 | 1 |
| Tagua común | · | · | 1 | · | · | · | · | · | 85 | 3 |
| Yeco | · | · | 1 | 2 | · | 1 | · | · | 2 | 82 |

## Errores con mayor confianza (revisar si la foto está mal etiquetada)

| Archivo | Real | Predicha | Confianza |
|---|---|---|---:|
| `Pato rana de pico delgado/inat_163521088.jpg` | Pato rana de pico delgado | Tagua común | 1.00 |
| `Tagua común/inat_162978592.jpg` | Tagua común | Yeco | 1.00 |
| `Gaviota de Franklin/inat_161821744.jpg` | Gaviota de Franklin | Tagua común | 1.00 |
| `Yeco/inat_317652151.jpg` | Yeco | Martin pescador | 0.99 |
| `Pato jergon grande/inat_341032281.jpg` | Pato jergon grande | Yeco | 0.99 |
| `Cisne de cuello negro/inat_373880507.jpg` | Cisne de cuello negro | Gaviota de Franklin | 0.98 |
| `Huala/inat_37564816.jpg` | Huala | Martin pescador | 0.98 |
| `Pato jergon grande/inat_337347027.jpg` | Pato jergon grande | Pato cuchara | 0.97 |
| `Martin pescador/inat_253928527.jpg` | Martin pescador | Pato cuchara | 0.97 |
| `Pato cuchara/inat_97958599.jpg` | Pato cuchara | Huala | 0.97 |
| `Cisne de cuello negro/inat_38073727.jpg` | Cisne de cuello negro | Gaviota de Franklin | 0.93 |
| `Yeco/inat_342093700.jpg` | Yeco | Martin pescador | 0.93 |
| `Gaviota de Franklin/inat_358404236.jpg` | Gaviota de Franklin | Pato cuchara | 0.93 |
| `Tagua común/inat_63189705.jpg` | Tagua común | Yeco | 0.91 |
| `Pato cuchara/inat_149193630.jpg` | Pato cuchara | Huala | 0.90 |
