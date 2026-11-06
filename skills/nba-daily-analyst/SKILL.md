---
name: nba-daily-analyst
description: Analiza a diario todos los encuentros NBA publicados, compara rendimiento reciente, jugadores, lesiones y conversación pública con fuentes y genera predicciones independientes de cuotas.
---

# NBA Daily Analyst

## Objetivo
Crear un análisis diario reproducible para cada partido NBA. Publicarlo en el dashboard de GitHub Pages de este proyecto, sin apuestas automáticas.

## Operación
1. Consultar el calendario del día en República Dominicana y los siguientes dos días, con identificador de cada partido.
2. Recopilar hasta ocho encuentros anteriores de cada equipo y hasta cinco box scores recientes por jugador. No usar resultados que hayan ocurrido después del momento de la predicción.
3. Calcular probabilidades separadas de cada equipo mediante `scripts/update.py`. Exigir cuatro partidos previos como mínimo por equipo; en caso contrario mostrar "sin datos".
4. Recuperar bajas como **reportes no confirmados**, con fecha y procedencia; cotejar con el informe oficial NBA antes del inicio si es posible.
5. Extraer titulares recientes de noticias públicas. Separar hechos de especulaciones.
6. Consultar publicaciones de r/nba solamente con acceso Reddit OAuth autorizado; sin permiso, mostrar el enlace al foro y un indicador de "No conectado".
7. **Nunca** convertir volumen de comentarios, votos o rumores en ajuste automático de porcentajes. Utilizarlos únicamente como señales cualitativas para investigación y señalar contradicciones.
8. Mostrar en la web probabilidad de ambos equipos, favorito estadístico, forma reciente, jugadores, descanso, enlaces y advertencias de incertidumbre.
9. Guardar primera estimación emitida antes del partido y compararla con resultados para evaluar Brier score. No corregir retrospectivamente predicciones para aparentar mayor precisión.
10. Si una API falla o faltan estadísticas, conservar el informe anterior, indicar cuándo se generó y no inventar porcentajes.

## Fuentes
- ESPN (calendarios y box scores, endpoint no oficial y sujeto a cambios).
- NBA oficial (informe de lesiones): https://official.nba.com/nba-injury-report-2026-27-season/
- Google News RSS (titulares públicos, como contexto).
- Reddit r/nba OAuth opcional y política de retención restringida.
- Sin datos de Betcris ni uso de cuotas para estimar victorias.

## Horarios
GitHub Actions en America/Santo_Domingo: 09:15, 17:30 y 20:00, sujeto a disponibilidad del servicio. Una ejecución manual se puede iniciar desde Actions.

## Calidad y precauciones
- Datos comprobables y enlaces visibles.
- Predicciones preliminares, no calibradas ni garantías.
- Resultados deportivos influyen en el modelo; foros y noticias se muestran aparte.
- Lesiones reportadas pueden cambiar; no afirmar que una plantilla está sana si la consulta devuelve cero entradas.
- No almacenar autores, comentarios completos ni textos personales de Reddit.
- No automatizar apuestas reales ni ofrecer certezas.
