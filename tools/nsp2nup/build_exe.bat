@echo off
setlocal
rem Optional: builds a single nsp2nup.exe so Python isn't needed at runtime.
rem Run once (double-click). Needs Python installed just for this build step.

cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller zstandard
if errorlevel 1 goto fail
py -3 -m PyInstaller --onefile --console --name nsp2nup --paths lib nsp2nup.py
if errorlevel 1 goto fail
copy /y dist\nsp2nup.exe . >nul
rmdir /s /q build dist 2>nul
del nsp2nup.spec 2>nul
echo.
echo Built nsp2nup.exe - drag NSPs onto it the same way as nsp2nup.bat.
goto end

:fail
echo Build failed - see the messages above.

:end
pause
