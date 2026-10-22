@echo off
cd /d "%~dp0"
python herramientas\servidor.py reactivar %*
pause
