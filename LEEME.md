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

- **`publicar.bat`**: publica lo que haya en `codigo/`. Las apps lo bajan solas (al abrirse o en menos de 1 hora).
- **`eliminar_en_todos.bat`**: desactiva la app. Cada equipo la quita junto con sus datos.
- **`reactivar.bat`**: vuelve a permitirla (necesario antes de reinstalar tras eliminarla).
- **`construir_instalador_windows.bat`**: genera `privado/VigilanteMEC-Setup-Victor.exe`.
- **`crear_instalador_jose.bat`**: genera `privado/instalar_vigilante_jose.sh` (Linux).

`privado/` nunca se sube: los instaladores personales llevan el token del bot.

### Ajustes para todos

En `manifest.json`, `ajustes` pisa la config de cada equipo, por ejemplo:

```json
"ajustes": {"meses_a_vigilar": 5, "intervalo_rapido_segundos": 5, "intervalo_segundos": 60}
```

### Cambios que necesitan reinstalar

Si el código nuevo necesita algo que el lanzador no trae (otra librería), sube
`LANZADOR_VERSION` en `lanzador/lanzador.py`, reconstruye los instaladores y pon
`"lanzador_minimo"` en el manifest: las apps viejas avisarán de que hay que reinstalar.

## Avisos sin repetir

El equipo `principal` avisa siempre y deja cada minuto una señal de vida en el bot.
El `respaldo` solo avisa de cupos si esa señal tiene más de 2,5 minutos.
