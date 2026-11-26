@echo off
rem Completa los experimentos C y D del clasificador tras un corte (reinicio, corte de luz).
rem C se reanuda desde su last.pt; D se entrena desde cero. Cada uno se evalua en test
rem como lo usa el kiosco. No reemplaza el modelo del kiosco (ver laboratorio_ia\ENTRENAMIENTO.md).
cd /d "%~dp0..\..\.."
set PY=.venv\Scripts\python.exe -X utf8
set ENT=laboratorio_ia\scripts_entrenamiento\entrenar_clasificador.py
set EVA=laboratorio_ia\scripts_entrenamiento\evaluar_clasificador.py
echo ==== C_yolo11l_320 (reanudado) ====
%PY% %ENT% --nombre C_yolo11l_320 --reanudar --sin-desplegar
%PY% %EVA% --modelo laboratorio_ia\runs\classify\C_yolo11l_320\weights\best.pt --salida laboratorio_ia\reportes\C_yolo11l_320_test.md
echo ==== D_yolo11l_384 ====
%PY% %ENT% --base yolo11l-cls.pt --tamano 384 --epocas 150 --paciencia 40 --lote 32 --nombre D_yolo11l_384 --sin-desplegar
%PY% %EVA% --modelo laboratorio_ia\runs\classify\D_yolo11l_384\weights\best.pt --salida laboratorio_ia\reportes\D_yolo11l_384_test.md
