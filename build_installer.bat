@echo off
setlocal
set "ROOT=%~dp0"
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
  echo Inno Setup compiler not found: "%ISCC%"
  exit /b 1
)

echo [1/3] Building app with PyInstaller...
python -m PyInstaller --noconfirm --clean --windowed --name FarpostFinder --icon "%ROOT%assets\app.ico" --add-data "34.png;." "%ROOT%run_farpost_gui.pyw"
if errorlevel 1 exit /b 1

echo [2/3] Compiling setup with Inno Setup...
"%ISCC%" "%ROOT%installer\FarpostFinder.iss"
if errorlevel 1 exit /b 1

echo [3/3] Done.
echo Installer path: "%ROOT%FarpostFinder_Installer.exe"
endlocal
