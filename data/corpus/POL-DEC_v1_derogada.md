# Política de decisión y umbrales

| Campo | Valor |
|---|---|
| Código | POL-DEC |
| Versión | 1 |
| Estado | **Derogada**. Reemplazada por la versión 2 desde el 1 de septiembre de 2026 |
| Vigencia | 2 de marzo de 2026 al 31 de agosto de 2026 |
| Responsable | Dirección de Producto, DPRIME |

> Documento ficticio elaborado para el Taller de Desarrollo de Software Conducido por Agentes de IA (Universidad de Valparaíso). No corresponde a una política real de DPRIME ni de ninguna organización.

## 1. Propósito

Esta política define cómo MIRA traduce el puntaje de confianza de un caso en una decisión, y quién puede modificar los valores que gobiernan esa traducción.

## 2. Umbrales de referencia

| Puntaje de confianza | Decisión |
|---|---|
| 85 o más | Aprobación automática, sin intervención humana |
| Entre 60 y 84 | Derivación a revisión asistida por un operador |
| Menos de 60 | Escalamiento o rechazo por riesgo alto |

## 3. Configuración por organización

Los umbrales pueden configurarse por organización y por tipo de proceso desde el diseñador de flujos. Cualquier usuario con rol de diseñador de flujos de la organización puede modificarlos. El cambio queda disponible en producción de inmediato.

## 4. Señales de fraude

Cada señal de fraude activa resta 20 puntos al puntaje total del caso. Después de aplicar el descuento, el caso se decide según la tabla de la sección 2.

## 5. Señales faltantes

Si un módulo de análisis no entrega su señal, el puntaje se calcula con las señales disponibles.
