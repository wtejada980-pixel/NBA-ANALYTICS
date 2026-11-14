# NBA Analytics

Plataforma independiente para consultar partidos NBA, estadísticas y probabilidades experimentales de ganador. No es oficial ni está afiliada a la NBA o ESPN.

**Sitio:** https://wtejada980-pixel.github.io/NBA-ANALYTICS/  
**Repositorio:** https://github.com/wtejada980-pixel/NBA-ANALYTICS

## Qué ofrece

- Agenda y marcadores en vivo, con zona horaria de República Dominicana.
- Probabilidades prepartido de ambos equipos y registro histórico descargable como CSV.
- Estadísticas por jugador, posibles titulares, Team Leaders, forma reciente y descanso.
- Filtros por equipo y favoritos guardados en el navegador.
- Ratings Elo, métricas de validación y gráfico Brier con resultados registrados antes del inicio.
- Aplicación instalable (PWA) que guarda la última agenda para abrirla si no hay conexión.

## Modelos

**V2** es el modelo que publica los pronósticos. Combina Elo de la ventana reciente, margen y porcentaje de victorias, puntos anotados y recibidos, descanso, ventaja de local y tendencia reciente de jugadores. Se abstiene si alguno de los equipos no tiene al menos cuatro partidos verificables; reduce estimaciones cuando la muestra es corta y limita los porcentajes para evitar confianza extrema.

**V3** es un experimento separado que compara una regresión logística cronológica con V2. No sustituye los pronósticos publicados. Las probabilidades son experimentales y no están calibradas para apostar. El sistema no utiliza cuotas de apuestas ni promete resultados. Noticias, disponibilidad y alineaciones pueden mostrarse aparte como contexto; no se convierten automáticamente en variables del porcentaje de V2.

## Actualización de datos

GitHub Actions consulta el calendario, resultados y estadísticas disponibles en ESPN. El proveedor usa endpoints públicos no oficiales que pueden cambiar, limitar consultas o fallar. Si eso ocurre, se conserva el último archivo válido y la página debe indicar que los datos pueden estar desactualizados.

Las actualizaciones están programadas para las **9:15 a. m., 5:30 p. m., 8:17 p. m. y 2:10 a. m.** de República Dominicana. GitHub puede retrasar o saltarse ejecuciones programadas. También se puede ejecutar **Actualizar estadísticas NBA** manualmente desde la pestaña **Actions**.

## Estructura

- `index.html`: estructura y metadatos de la página.
- `assets/app.js`: interfaz, marcadores y filtros.
- `assets/style.css`: presentación.
- `scripts/model_v2.py`, `scripts/model_v3.py`: modelos de predicción.
- `scripts/update.py`: actualización de resultados y estadísticas.
- `data/latest.json`: publicación de datos más reciente.
- `data/history.json`: pronósticos guardados y resultados.
- `service-worker.js`, `manifest.webmanifest`: instalación y caché offline.
- `tests/`: pruebas automatizadas.

## Pruebas

Desde la raíz del repositorio:

```sh
python -m unittest discover -s tests -v
node --check assets/app.js
node tests/ui-smoke.cjs
node tests/v3-ui-smoke.cjs
```

GitHub Actions ejecuta las comprobaciones de calidad y publica la página al actualizar el código. Las puntuaciones y probabilidades son informativas: no constituyen garantía de acierto ni recomendación de apuesta.
