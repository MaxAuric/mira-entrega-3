# Catálogo de señales de MIRA

| Campo | Valor |
|---|---|
| Código | CAT-SEN |
| Versión | 3 |
| Estado | Vigente |
| Vigencia | Desde el 1 de septiembre de 2026 |
| Responsable | Equipo de Ingeniería de Modelos, DPRIME |

> Documento ficticio elaborado para el Taller de Desarrollo de Software Conducido por Agentes de IA (Universidad de Valparaíso). No corresponde a una política real de DPRIME ni de ninguna organización.

## 1. Qué es una señal

Una señal es el resultado individual que produce un módulo de análisis sobre una pieza de evidencia o sobre el conjunto del caso. Las señales de valor numérico van de 0 a 100, donde un valor mayor indica más confianza. Las señales de fraude son indicadores: están activas o inactivas.

Los mínimos por señal no se definen en este catálogo sino en la política de decisión y umbrales (POL-DEC).

## 2. Señales documentales

| Código | Qué mide | Qué hacer si el valor es bajo |
|---|---|---|
| DOC_AUT | Autenticidad del documento: coherencia de su estructura, timbres, firmas y origen declarado | Revisar el documento original y compararlo con documentos del mismo emisor |
| DOC_ARIT | Coherencia aritmética: que el total corresponda a la suma de sus líneas y los impuestos a su base | Verificar el cálculo; un total que no cuadra es un hallazgo, no un error de lectura |
| DOC_LEG | Legibilidad del archivo: nitidez, encuadre, páginas completas | Bajo 50, solicitar el reenvío del documento |
| DOC_IDIOMA | Indica que el documento está en un idioma distinto del español | Verificar manualmente los campos leídos; la confianza de lectura es menor |

## 3. Señales de metadatos

| Código | Qué mide | Qué hacer si el valor es bajo |
|---|---|---|
| META_FECHA | Coherencia entre la fecha de captura del archivo y la fecha que declara el documento | Revisar si la fotografía es posterior al hecho declarado |
| META_DISP | Coherencia del dispositivo y del software que generaron el archivo | Revisar si el archivo fue reprocesado por un editor |

## 4. Señales biométricas

| Código | Qué mide | Qué hacer si el valor es bajo |
|---|---|---|
| BIO_ROSTRO | Coincidencia entre el rostro de la captura y el del documento de identidad | Comparar manualmente; no decidir solo con el valor |
| BIO_VIDA | Prueba de vida: que la captura corresponda a una persona presente y no a una foto o pantalla | Solicitar una nueva captura |

## 5. Señales de cruce entre fuentes

| Código | Qué mide | Qué hacer si el valor es bajo |
|---|---|---|
| CRUCE_MONTO | Coincidencia de montos entre las distintas piezas del caso | Identificar qué pieza discrepa y por cuánto |
| CRUCE_FECHA | Coincidencia de fechas entre las distintas piezas del caso | Identificar qué pieza discrepa |

## 6. Señales de fraude

Una señal de fraude activa deriva el caso a revisión según POL-DEC.

| Código | Qué indica |
|---|---|
| FRA_EDICION | El archivo muestra rastros de edición posterior a su emisión |
| FRA_MEMORIA | La misma pieza de evidencia, o una casi idéntica, ya fue presentada en otro caso |
| FRA_SINTETICO | La imagen o el documento presenta rasgos de contenido generado artificialmente |
