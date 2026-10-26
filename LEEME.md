# Vigilante MEC

App de escritorio (Windows y Linux) que vigila los cupos de la Agenda del trámite
"Inscripción de partidas extranjeras" del MEC y avisa por Telegram. Nunca reserva:
cuando hay cupo deja la ventana de Chrome con el calendario lista para elegir a mano.

Este repositorio es el **servidor de actualizaciones**: las apps instaladas leen
`manifest.json` al abrirse y cada hora.

| Carpeta / archivo | Qué es |
|---|---|
| `codigo/` | Ventana (`app.py`) y vigilante (`motor.py`). Es lo que se actualiza solo. |
| `paquetes/` | Cada versión publicada de `codigo/` en un zip (el manifest lleva su sha256). |
| `manifest.json` | Versión actual, si la app está activa y ajustes para todos los equipos. |
| `lanzador/` | Parte fija de la app instalada e instalador de Windows. |
| `herramientas/` | Publicar, desactivar, construir instaladores. |
| `.github/workflows/linux.yml` | Construye y prueba la versión de Linux (release `lanzador-v1`). |

## Administrador (Windows)

- **`publicar.bat`**: publica lo que haya en `codigo/`. Las apps lo bajan solas (al abrirse o en menos de 5 minutos).
- **`estado_equipos.bat`**: qué equipos están vigilando ahora, esperando sesión del MEC o apagados, y su versión.
- **`quien_avisa.bat`**: elige qué PC manda los avisos de cupos (`Victor`, `Jose`, `todos` o `auto`).
- **`cambiar_ajuste.bat`**: cambia un ajuste para todos o para un solo equipo (`Jose meses_a_vigilar 3`).
- **`mandar_sonido_alarma.bat`**: manda por el bot `herramientas/alarma_mec.mp3` con las instrucciones
  para ponerlo como sonido del chat del bot en el celular.

### Alarma de cupo

Al aparecer un cupo nuevo, además del aviso llegan `alarma_repeticiones` (6) mensajes de alarma, uno cada
`alarma_cada_segundos` (5), a `chats_alarma` (por defecto todos los chats), y el PC hace sonar una sirena.
`alarma_repeticiones 0` la apaga. En Ajustes, «Probar alarma» la prueba solo con el dueño del equipo.
- **`eliminar_en_todos.bat`**: desactiva la app. Cada equipo la quita junto con sus datos.
- **`reactivar.bat`**: vuelve a permitirla (necesario antes de reinstalar tras eliminarla).
- **`construir_instalador_windows.bat`**: genera `privado/VigilanteMEC-Setup-Victor.exe`.
- **`crear_instalador_jose.bat`**: genera `privado/instalar_vigilante_jose.sh` (Linux).

`privado/` nunca se sube: los instaladores personales llevan el token del bot.

### Ajustes desde el servidor

En `manifest.json`, `ajustes` pisa la config de todos los equipos y `equipos` la de uno solo
(por su `nombre`); se aplican sin reiniciar en menos de 5 minutos:

```json
"ajustes": {"meses_a_vigilar": 5, "intervalo_rapido_segundos": 5, "intervalo_segundos": 60, "avisa": "Jose"},
"equipos": {"Jose": {"intervalo_segundos": 90}}
```

`avisos_sistema`: `"todos"` (por defecto, los mensajes de sesión/problemas de cada PC llegan a todos
con `[PC de …]`) o `"dueno"` (solo al dueño de ese PC).

### Cambios que necesitan reinstalar

Si el código nuevo necesita algo que el lanzador no trae (otra librería), sube
`LANZADOR_VERSION` en `lanzador/lanzador.py`, reconstruye los instaladores y pon
`"lanzador_minimo"` en el manifest: las apps viejas avisarán de que hay que reinstalar.

## Avisos sin repetir

Cada equipo deja cada minuto una señal de vida en el bot (vigilando, esperando sesión o
Telegram desactivado). El equipo elegido en `avisa` (por defecto el `principal`) avisa siempre;
los demás solo avisan de cupos si ese equipo no está vigilando o su señal tiene más de 2,5 minutos.
Con `avisa: "todos"` avisan todos a la vez (mensajes repetidos). Los avisos llegan a todos los
chats de `chats_avisos` y dicen qué PC los mandó.

En Linux el vigilante bloquea la suspensión del equipo mientras corre (`systemd-inhibit`).
