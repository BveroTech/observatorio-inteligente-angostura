@echo off
rem Entrena varias configuraciones del clasificador sobre el mismo dataset y
rem evalua cada una en test con evaluar_clasificador.py (como lo usa el kiosco).
rem No reemplaza el modelo del kiosco: el ganador se despliega aparte con
rem exportar_modelos.bat --clasificador RUTA\best.pt (ver laboratorio_ia\ENTRENAMIENTO.md).
cd /d "%~dp0..\..\.."
set PY=.venv\Scripts\python.exe -X utf8
set ENT=laboratorio_ia\scripts_entrenamiento\entrenar_clasificador.py
set EVA=laboratorio_ia\scripts_entrenamiento\evaluar_clasificador.py
for %%E in ("yolo11s-cls.pt 224 A_yolo11s_224" "yolo11m-cls.pt 320 B_yolo11m_320" "yolo11l-cls.pt 320 C_yolo11l_320" "yolo11l-cls.pt 384 D_yolo11l_384") do (
    for /f "tokens=1-3" %%a in (%%E) do (
        echo ==== %%c ====
        %PY% %ENT% --base %%a --tamano %%b --epocas 150 --paciencia 40 --lote 32 --nombre %%c --sin-desplegar
        %PY% %EVA% --modelo laboratorio_ia\runs\classify\%%c\weights\best.pt --salida laboratorio_ia\reportes\%%c_test.md
    )
)
