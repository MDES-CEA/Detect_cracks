@echo off
rem ---------------------------------------------------------------
rem Lanceur Windows : cree l'environnement virtuel au premier appel,
rem puis lance l'analyse multi-fissures.
rem
rem   double-clic          -> une fenetre demande l'image a analyser
rem   run.bat mon_image.png -> analyse directement cette image
rem   run.bat mon_image.png --show-cost  -> options transmises au script
rem ---------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creation de l'environnement virtuel .venv ...

    set "PYCMD="
    where py >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3"
    if not defined PYCMD (
        where python >nul 2>&1
        if not errorlevel 1 set "PYCMD=python"
    )
    if not defined PYCMD (
        echo.
        echo ERREUR : Python est introuvable sur cette machine.
        echo Installe Python 3.10 ou plus recent depuis
        echo     https://www.python.org/downloads/
        echo en cochant "Add python.exe to PATH" pendant l'installation,
        echo puis relance ce fichier.
        echo.
        pause
        exit /b 1
    )

    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo ERREUR : la creation de l'environnement virtuel a echoue.
        pause
        exit /b 1
    )

    echo [2/2] Installation des dependances ^(compter quelques minutes^) ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERREUR : l'installation des dependances a echoue.
        pause
        exit /b 1
    )
    echo Installation terminee.
    echo.
)

".venv\Scripts\python.exe" crack_length_analysis_multi.py %*
echo.
pause
