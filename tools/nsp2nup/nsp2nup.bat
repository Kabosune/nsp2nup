@echo off
setlocal
title nsp2nup

rem Drag .nsp files (base / update / DLC) and optionally prod.keys onto this file.
rem Uses a portable Python in .\python\ if present, otherwise the installed one.

if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" "%~dp0nsp2nup.py" %*
    goto done
)
where py >nul 2>nul && (
    py -3 "%~dp0nsp2nup.py" %*
    goto done
)
where python >nul 2>nul && (
    python "%~dp0nsp2nup.py" %*
    goto done
)
echo Python 3.10+ was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo or unzip the "Windows embeddable package" into a folder named "python" next to this file.

:done
echo.
pause
