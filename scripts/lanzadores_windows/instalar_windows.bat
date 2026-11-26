@echo off
setlocal
cd /d "%~dp0..\.."
echo ==========================================================
echo  Instalacion del Observatorio Inteligente de Aves
echo ==========================================================

set "PY="
py -3.11 --version >nul 2>nul && set "PY=py -3.11"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
    echo.
    echo [ERROR] No se encontro Python 3 de 64 bits.
    echo Instalalo con:   winget install -e --id Python.Python.3.11
    echo y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>nul || (
        echo El entorno .venv no funciona en este equipo. Se vuelve a crear...
        rmdir /s /q .venv
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    %PY% -m venv .venv || goto :error
)

echo Actualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
echo Instalando dependencias del kiosco y del portal...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error

echo Descargando los modelos de idiomas (lector de fichas y traductor ES/EN/DE)...
".venv\Scripts\python.exe" scripts\cli_admin\descargar_modelos_idiomas.py || echo [AVISO] No se pudieron descargar: el lector de fichas y la traduccion no estaran disponibles.
if not exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" (
    echo Instalando Tesseract, el lector de fichas tecnicas...
    winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
)


echo Preparando la base de datos...
".venv\Scripts\python.exe" scripts\cli_admin\crear_base_datos.py || goto :error

echo.
".venv\Scripts\python.exe" scripts\cli_admin\verificar_entorno.py
echo.
echo ==========================================================
echo  Instalacion terminada. Pasos siguientes:
echo   1. scripts\lanzadores_windows\crear_usuario.bat
echo   2. scripts\lanzadores_windows\habilitar_portal_en_red.bat  (una vez, como administrador)
echo   3. scripts\lanzadores_windows\ejecutar_observatorio.bat
echo  El portal se abre desde OTRO computador: ver_enlace_portal.bat muestra el enlace.
echo ==========================================================
pause
exit /b 0

:error
echo.
echo [ERROR] La instalacion no pudo completarse. Revisa el mensaje de arriba.
pause
exit /b 1
