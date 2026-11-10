# NBA Analytics — versión web actualizable

Un proyecto gratuito para analizar partidos NBA y estimar probabilidades de victoria **de ambos equipos** mediante resultados recientes y algunas estadísticas de jugadores. **No utiliza cuotas de apuestas, no apuesta dinero y no promete aciertos.**

## Qué cambió con respecto al HTML antiguo

- **La página `index.html` no consulta directamente una API externa:** solo lee `data/latest.json` desde su misma web. Así evitamos el problema de CORS `Failed to fetch` que ocurría al abrir un HTML local.
- El actualizador `scripts/update.py` consulta estadísticas de ESPN desde GitHub Actions; el navegador solo muestra el resultado que quedó guardado.
- El resultado vive en una misma dirección web, y puedes modificar el proyecto sin generar otra URL.
- La web compara últimos 8 partidos (hasta donde alcance el historial recuperado), promedios recientes de jugadores, descanso y localía, con **probabilidades experimentales** en las dos columnas.
- Un historial `data/history.json` guarda la primera predicción antes del inicio y luego su resultado para calcular Brier score.
- No se inventan probabilidades si hay menos de cuatro encuentros recientes de cualquiera de los dos equipos.

## Publicarla GRATIS sin instalar Python

**Necesitas una cuenta de GitHub.**

1. Entra a <https://github.com/new> y crea un repositorio **público** llamado `nba-analytics` (sin inicializarlo con archivos extra).
2. Descomprime `NBA_Analytics_Actualizable.zip` en tu computadora.
3. En tu repositorio, usa **Add file → Upload files** y sube el **contenido de la carpeta**, conservando subcarpetas y la carpeta oculta `.github/workflows/` con ambos archivos YAML. Si la web no conserva las carpetas, súbelas por rutas correspondientes o usa GitHub Desktop.
4. Entra a **Settings → Pages → Build and deployment → Source → GitHub Actions**. La publicación es gratis en repositorios públicos de GitHub Free.
5. GitHub publicará la web al subir el código mediante el flujo **Publicar NBA Analytics**. Después ve a **Actions → Actualizar estadísticas NBA → Run workflow → Run workflow** para ejecutar el primer análisis real. Comprueba si termina correctamente.
6. Tu web estará en `https://TU-USUARIO.github.io/nba-analytics/` (sustituye `TU-USUARIO` por tu usuario). GitHub también muestra la URL real en **Settings → Pages**.
7. Después de publicar, abre ese enlace desde el iPhone o la computadora. Cuando actualicemos el código y lo subas al **mismo repositorio**, la dirección de la web no cambia.

**Si GitHub no permite subir carpetas desde el navegador:** instala GitHub Desktop y utiliza **File → Add local repository / Create repository** a partir de esta carpeta, luego publica el repositorio. También se puede usar Git en la terminal, pero no es obligatorio instalar Python.

### Actualización automática

El archivo `.github/workflows/update-nba.yml` configura ejecuciones diarias a las **9:15 a. m. y 6:15 p. m. de República Dominicana**. GitHub puede retrasar las tareas programadas. También puedes ejecutar el flujo manualmente desde **Actions → Run workflow**. En cada ejecución:

1. Se obtienen calendario y resultados de los últimos 35 días usando endpoints no oficiales de ESPN (sin clave).
2. Se consultan los box scores recientes de los equipos que jugarán en los próximos tres días cuando estén disponibles.
3. Se generan probabilidades para partidos que **aún no han empezado** si cada equipo tiene al menos 4 juegos verificables.
4. Se escriben `data/latest.json` y `data/history.json`, se conservan en el repositorio y se publica el sitio.
5. Si falla el proveedor, el proceso **marca error** y la web conserva el último informe válido con aviso de desactualización. Nunca sustituye el dato real por uno inventado.

### Modelo inicial (`forma8-v1`)

- Diferencial medio de puntos ponderado, últimos 8 partidos: coeficiente 0.55.
- Proporción ponderada de victorias recientes: coeficiente 4.5.
- Localía: +2.4 puntos para el equipo local.
- Si se jugó el día anterior: −1.5 puntos de ajuste.
- Tendencia de anotación de hasta 3 jugadores destacados: ajuste limitado a ±0.8 puntos por equipo, solo si hay box scores suficientes.
- Conversión logística suavizada hacia 50/50; la suma de los dos porcentajes es 100%.

**Importante:** esos coeficientes son heurísticos, no aprendidos ni calibrados con un conjunto de validación. No hay ajustes para ausencias confirmadas en tiempo real, fortaleza del rival, trades o cambios en el quinteto inicial. El modelo puede equivocarse. A medida que se guarden pronósticos y resultados, podremos evaluar Brier score y realizar mejoras justificadas por datos.

### Uso local

Si abres `index.html` haciendo doble clic desde la carpeta descomprimida, se muestra un calendario **inicial de referencia, sin porcentajes**, porque los navegadores pueden bloquear la lectura de archivos `.json` desde `file://`. La versión alojada sí carga `data/latest.json` directamente desde la propia web.

Para ver el contenido local actualizado sin publicar podrías ejecutar un servidor HTTP, pero no hace falta para usar la web una vez publicada en GitHub Pages.

### Mantenimiento posterior

- `index.html`: estructura visual.
- `assets/style.css`: colores y presentación.
- `assets/app.js`: tabla y visualizaciones.
- `scripts/update.py`: recopilación, modelo y cálculo de probabilidades.
- `data/latest.json`: información de la última ejecución correcta.
- `data/history.json`: predicciones anteriores y resultados.
- `.github/workflows/update-nba.yml`: horario, generación de estadísticas y publicación automática.
- `.github/workflows/publicar-web.yml`: publicación inicial del sitio aunque ESPN falle.
- `tests/test_update.py`: pruebas unitarias sin Internet.

Podemos trabajar sobre estos archivos en futuras conversaciones. Para hacer cambios **directamente en tu repositorio**, usa ChatGPT Work con el navegador conectado y autoriza el acceso a GitHub cuando se necesite; si no, descarga el nuevo paquete de archivos y súbelo al mismo repositorio. En modo Chat, el acceso al navegador puede ser solo de lectura.

### Límites de las fuentes

`site.api.espn.com` es un endpoint **no oficial y no documentado**, puede cambiar, denegar conexiones desde GitHub o devolver respuestas incompletas. No prometemos disponibilidad permanente. Si falla repetidamente, se necesitará otro proveedor con acceso permitido. No se guardan contraseñas, tokens ni información de Betcris.

### Referencias

- [ESPN NBA Scoreboard](https://www.espn.com/nba/scoreboard)
- [API pública no oficial de ESPN: documentación comunitaria](https://github.com/pseudo-r/Public-ESPN-API)
- [GitHub Pages y GitHub Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

### Si falla la primera actualización

El flujo `Publicar NBA Analytics` mantiene la web disponible, pero sin probabilidades hasta que exista una actualización estadística válida. Comprueba el registro en **Actions → Actualizar estadísticas NBA**. Si ESPN bloquea las peticiones desde los servidores de GitHub, habrá que conectar otra fuente legalmente accesible; no es correcto inventar porcentajes para rellenar la tabla.


## Modelo experimental v2: Elo + forma 10 (noviembre 2026)

- `scripts/model_v2.py` combina rating Elo **reiniciado al comienzo de la ventana recuperada** (no es el Elo completo de la temporada), resultados de hasta diez juegos anteriores, puntos anotados y recibidos, localía, descanso y tendencias de jugadores disponibles.
- El modelo NO utiliza cuotas de casas de apuestas, NO está calibrado y se abstiene si cualquiera de los equipos tiene menos de cuatro partidos previos verificables.
- Las diferencias de anotación y puntos recibidos NO son `OffRtg` y `DefRtg`: esas métricas requieren posesiones. Referencia: https://www.nba.com/stats/help/glossary
- Las lesiones reportadas y los foros aparecen como contexto con fuente, sin alterar porcentajes automáticamente. Reddit requiere credenciales OAuth autorizadas; no se hace scraping sin autorización.
- `scripts/validation.py` calcula Brier, porcentaje de aciertos de favoritos, log loss y rangos de confiabilidad. Guarda la **primera** predicción válida antes del inicio, sin reescribirla después. Un Brier más bajo no demuestra por sí solo que el modelo esté calibrado. Referencia: https://scikit-learn.org/stable/modules/calibration.html
- Los archivos se actualizan mediante GitHub Actions en horario de República Dominicana. Si el proveedor falla, los datos pueden quedar desactualizados y la página debe indicarlo.
- `python -m unittest discover -s tests -v` y `node --check assets/app.js` sirven para comprobar los cambios. GitHub ejecuta estas verificaciones automáticamente.
- GitHub Pages debe habilitarse manualmente en Settings → Pages → Source → GitHub Actions. Un flujo de publicación completado mientras Pages está inactivo solo significa que el proceso evitó fallar, **no** que la página ya esté disponible.

**Limitación esencial:** sin pruebas retrospectivas fuera de muestra y sin una comparación sólida con modelos de referencia, estas probabilidades deben considerarse educativas, no estimaciones con precisión demostrada.


## Laboratorio V3 (experimental, separado de producción)

- `scripts/v3_dataset.py`: recupera **temporadas completas** desde ESPN (API no
  oficial) y guarda solo encuentros finales con tipo regular/playoffs verificable.
  Registra cada fecha consultada, fallos y fecha de extracción en `data/v3/`.
  Los archivos se construyen de forma reanudable y nunca inventan marcadores.
- `scripts/model_v3.py`: genera variables con corte temporal estricto (se excluye
  todo el día del partido), Elo, forma, ataque, defensa y descanso; entrena una
  regresión logística con parámetros ajustados **solo en temporadas antiguas**.
- El penúltimo año sirve para validar y el último para una prueba independiente.
  Se comparan Brier, log loss y precisión con el Elo de referencia en los
  mismos encuentros. Si faltan tres temporadas completas o 100 ejemplos por
  segmento, el informe declara `insufficient_history` y **no crea candidato**.
- En GitHub Actions → **Construir base historica NBA V3** se selecciona una
  temporada por ejecución (2022-23, 2023-24, 2024-25).
- Los resultados de este laboratorio **nunca se muestran como probabilidades
  activas** y no cambian las predicciones guardadas del V2.
- Solo después de comprobar ventaja cronológica, calibración y datos de
  lesiones fiables podrá considerarse una migración del modelo en producción.

La API ESPN es no oficial; backfill no equivale a disponer de todas las
estadísticas avanzadas, alineaciones reales, lesiones históricas ni cuotas.
No se asume ROI ni rentabilidad sin cuotas **reales y fechadas**.
