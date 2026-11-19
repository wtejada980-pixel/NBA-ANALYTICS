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

El modelo activo es un **híbrido experimental 50/50 de V2 y V3**. V2 aporta sus reglas de Elo, forma, localía, descanso y tendencia reciente de jugadores cuando hay datos; V3 aporta la regresión logística cronológica. Las tres probabilidades se guardan juntas para compararlas en los mismos partidos antes del inicio. Los pesos no cambian automáticamente durante esta evaluación.

Las probabilidades no están calibradas para apostar. El sistema no utiliza cuotas ni promete resultados. Noticias, disponibilidad y alineaciones se muestran como contexto y no cambian directamente el porcentaje. Las versiones anteriores permanecen identificadas en el historial.

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

## Skill de diseño frontend

El proyecto ofrece **Taste Skill (`design-taste-frontend`)** como herramienta opcional para rediseñar o revisar la interfaz. No forma parte de la página publicada. Para instalarla en tu copia local del proyecto:

```sh
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
```

También se puede añadir desde el marketplace de plugins registrado en `.agents/plugins/marketplace.json`. Requiere Node 22 o superior y Chrome, Edge o Chromium para las comprobaciones visuales.
