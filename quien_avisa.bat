@echo off
cd /d "%~dp0"
echo Quien manda los avisos de cupos?
echo   Victor  = tu PC (si esta apagado, avisa el de Jose)
echo   Jose    = el PC de Jose (si esta apagado, avisa el tuyo)
echo   todos   = los dos a la vez (llegan mensajes repetidos)
echo   auto    = el principal, como al principio
set /p QUIEN=Escribe Victor, Jose, todos o auto: 
python herramientas\servidor.py avisa %QUIEN%
pause
