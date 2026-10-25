@echo off
cd /d "%~dp0"
echo Ejemplos:  todos meses_a_vigilar 3     Jose intervalo_segundos 90     Jose avisos_sistema dueno
echo Sin valor se quita el ajuste.
set /p AJUSTE=Equipo (o todos), clave y valor: 
python herramientas\servidor.py ajuste %AJUSTE%
pause
