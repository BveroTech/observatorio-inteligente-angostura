@echo off
cd /d "%~dp0..\..\.."
if not exist ".venv\Scripts\python.exe" (
    echo Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
rem En Windows, "pip install torch" instala la version SOLO CPU. Si hay una
rem GPU NVIDIA se instala antes la version con CUDA para entrenar en la GPU.
nvidia-smi >nul 2>nul
if not errorlevel 1 (
    echo GPU NVIDIA detectada: instalando PyTorch con CUDA 12.8...
    ".venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 || goto :error
) else (
    echo No se detecto GPU NVIDIA: se instalara PyTorch para CPU ^(entrenar sera lento^).
)
echo Instalando dependencias para entrenar y exportar modelos...
".venv\Scripts\python.exe" -m pip install -r laboratorio_ia\requirements-entrenamiento.txt || goto :error
".venv\Scripts\python.exe" -c "import torch; print('PyTorch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no (CPU)')"
pause
exit /b 0

:error
echo [ERROR] No se pudo instalar el entorno de entrenamiento.
pause
exit /b 1
