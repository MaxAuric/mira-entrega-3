# Política de decisión y umbrales

| Campo | Valor |
|---|---|
| Código | POL-DEC |
| Versión | 2 |
| Estado | **Vigente** |
| Vigencia | Desde el 1 de septiembre de 2026 |
| Reemplaza a | POL-DEC versión 1 |
| Responsable | Dirección de Producto, DPRIME, con revisión del área de Cumplimiento |

> Documento ficticio elaborado para el Taller de Desarrollo de Software Conducido por Agentes de IA (Universidad de Valparaíso). No corresponde a una política real de DPRIME ni de ninguna organización.

## 1. Propósito

Esta política define cómo MIRA traduce el puntaje de confianza de un caso en una decisión, qué condiciones prevalecen sobre el puntaje y quién puede modificar los valores que gobiernan esa traducción. Aplica a todas las organizaciones que operan en la plataforma.

## 2. Umbrales de referencia

Los valores de esta tabla son de referencia. Cada organización fija los suyos según la sección 5.

| Puntaje de confianza | Decisión |
|---|---|
| 85 o más | Aprobación automática, solo si no hay señales de fraude activas y todas las señales con mínimo propio lo cumplen |
| Entre 60 y 84 | Derivación a revisión asistida por un operador |
| Menos de 60 | Escalamiento a revisión por un analista con rol de supervisor |

Ningún caso se rechaza automáticamente. El rechazo de un caso siempre lo decide y lo firma una persona.

## 3. Mínimos por señal

Algunas señales tienen un mínimo propio. Si una de ellas queda bajo su mínimo, el caso se deriva a revisión aunque el puntaje total alcance el umbral de aprobación.

| Señal | Mínimo |
|---|---|
| DOC_AUT, autenticidad documental | 70 |
| BIO_ROSTRO, coincidencia de rostro | 75 |
| CRUCE_MONTO, cruce de montos entre fuentes | 60 |
| CRUCE_FECHA, cruce de fechas entre fuentes | 60 |

El resto de las señales no tiene mínimo propio y solo aporta al puntaje total.

## 4. Precedencia de las señales de fraude

Una señal de fraude activa deriva el caso a revisión, cualquiera sea su puntaje. Las señales de fraude no restan puntos: prevalecen sobre el puntaje. El catálogo de señales (CAT-SEN) identifica cuáles son señales de fraude.

## 5. Configuración por organización

Cada organización fija sus propios umbrales de aprobación y de revisión. Un cambio de umbral es un cambio de política de riesgo de la organización y no una configuración técnica: requiere la aprobación de dos personas con rol de supervisor de esa organización y queda registrado con su autor, sus aprobadores, la fecha y el valor anterior. Un cambio con una sola aprobación no entra en vigor.

## 6. Señales faltantes

Si un módulo falla o no entrega su señal, el caso no se aprueba con información parcial: se deriva a revisión indicando qué señal faltó. La ausencia de una señal nunca se interpreta como favorable.

## 7. Componentes del puntaje

El puntaje se presenta acompañado de cuatro componentes: autenticidad de los documentos, coherencia biométrica, cruce entre fuentes y presencia de señales de fraude. La interfaz de revisión debe mostrar qué componente empujó el puntaje hacia arriba o hacia abajo.
