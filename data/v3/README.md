# Datos históricos para V3

Esta carpeta se llena mediante el flujo manual **Construir base historica NBA V3**,
una temporada por ejecución. Las fuentes son los marcadores finales del endpoint
no oficial de ESPN. Los archivos indican qué fechas se consultaron y cuáles
fallaron; **no se rellenan ausencias ni se inventan resultados**.

- `games-YYYY-YY.json`: juegos finales verificables con tipo de temporada 2
  (regular) o 3 (postemporada). Los encuentros de pretemporada se excluyen.
- `evaluation.json`: comparación de V3 con Elo en temporadas posteriores
  estrictamente separadas de las usadas para ajustar parámetros.
- `candidate.json`: pesos experimentales generados solamente cuando hay
  suficientes partidos; **no se cargan ni se publican como pronósticos**.

Para completar tres temporadas, ejecutar por separado 2022-23, 2023-24 y
2024-25 desde GitHub Actions. El proceso se reanuda si ya hay días completados.
El modelo V2 continúa siendo el único de producción. Nunca usar el marcador
de un partido para producir sus propias variables prepartido. Este proyecto
no estima ganancias ni considera probabilidades calibradas sin validación.
