@echo off
cd /d "%~dp0"
python herramientas\servidor.py eliminar %*
pause
