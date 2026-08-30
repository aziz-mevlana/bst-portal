@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Sanal ortam bulunamadi. Windows kurulumu calistiriliyor...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
    if errorlevel 1 goto :error
)

echo Veritabani guncelleniyor...
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 goto :error

echo.
echo BST Portal: http://127.0.0.1:8000/
echo Durdurmak icin CTRL+C tuslarina basin.
echo.
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Uygulama baslatilamadi. Yukaridaki hata mesajini kontrol edin.
pause
exit /b 1
