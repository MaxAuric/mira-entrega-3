# Descripción del Proyecto MIRA · Capítulos Pertinentes a Revisión Operativa

| Campo | Valor |
|---|---|
| Código | DOC-MIRA |
| Versión | 1.4 |
| Estado | Vigente |
| Vigencia | Desde el 1 de marzo de 2026 |
| Origen | Descripción |
| Responsable | Arquitectura y Producto, DPRIME SpA |

> Extracto de los capítulos pertinentes al Caso de Uso 1 de la Descripción del Proyecto MIRA v1.4 (DPRIME SpA), elaborado con fines docentes para el Taller de Desarrollo de Software Conducido por Agentes de IA (Universidad de Valparaíso).

## 1. Propósito de la plataforma MIRA y trazabilidad ante terceros

MIRA es la plataforma de inteligencia multimodal para decisiones empresariales desarrollada por DPRIME SpA. Presta servicios a organizaciones cliente de múltiples industrias, incluyendo compañías de seguros, clínicas de salud e instituciones bancarias. El requisito fundacional de MIRA es que toda decisión asistida pueda justificarse de manera auditable ante un tercero o ente regulador: cada afirmación normativa debe contar con fuente documental verificable, cada dato de un caso debe provenir de un registro trazable y ninguna decisión final de rechazo o aprobación recae en un modelo autónomo sin firma humana.

## 2. Arquitectura multimodal y rol del operador de revisión

Cuando una organización envía un caso (por ejemplo, un reembolso médico, un siniestro automotriz, una admisión clínica o una apertura de cuenta bancaria), los módulos multimodales de MIRA analizan documentos, metadatos, biometría y cruces de información, generando señales individuales y un puntaje global de confianza. Los casos que no cumplen las condiciones de aprobación automática son derivados a la bandeja de revisión asistida de la organización cliente, donde un operador humano examina la evidencia y toma la decisión final o solicita nuevos antecedentes.

## 3. Gobernanza multi-organización y seguridad operacional

Dado que MIRA opera bajo un modelo multi-organización (multi-tenant), los datos de casos, señales, evidencias y umbrales están estrictamente aislados por organización cliente. Ningún operador ni asistente puede consultar ni inferir información perteneciente a otra organización. Asimismo, el acceso programático a los datos operacionales se realiza exclusivamente mediante herramientas parametrizadas y auditadas a través del servidor MCP de la plataforma, nunca mediante acceso libre a la base de datos.

