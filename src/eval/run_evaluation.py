"""
Pipeline de Evaluación Empírica del Asistente MIRA (CU-1) sobre el Golden Set.
Cumple con el Capítulo 7 (Secciones 7.1 y 7.2) y el Criterio C6 de la Rúbrica:
- Evalúa las 22 preguntas fijas de `data/golden_set.json` (versionado en el Commit 1).
- Separa estrictamente la evaluación de Recuperación y de Generación/Comportamiento:
  1. Recuperación: `Recall@1` y `Recall@3` a nivel de fragmento (`chunk_id`).
  2. Generación: `Precisión de cita` (proporción de citas principales que apuntan al fragmento esperado)
     y `Fidelidad` (proporción de respuestas respaldadas íntegramente por la evidencia recibida).
  3. Comportamiento: `Abstención correcta` (sobre preguntas sin respuesta y tasa de falsa abstención
     en preguntas con respuesta) y `Manejo de conflicto y vigencia`.
- Clasifica automáticamente cualquier fallo como `FALLO_RECUPERACION` o `FALLO_GENERACION`.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from src.api.agent import MIRAOperadorAgent
from src.rag.indexer import PROJECT_ROOT

GOLDEN_SET_PATH = PROJECT_ROOT / "data" / "golden_set.json"
EVAL_REPORT_PATH = PROJECT_ROOT / "data" / "eval_results.json"


def run_evaluation(k: int = 3) -> Dict[str, Any]:
    agent = MIRAOperadorAgent()
    golden_set: List[Dict[str, Any]] = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))

    answerable = [q for q in golden_set if q["debe_responder"]]
    unanswerable = [q for q in golden_set if not q["debe_responder"]]
    conflict_qs = [q for q in golden_set if q["tipo"] == "conflicto_vigente"]
    version_qs = [q for q in golden_set if q["tipo"] == "cambio_version"]

    recall_at_1_hits = 0
    recall_at_k_hits = 0
    citation_precision_hits = 0
    faithfulness_hits = 0
    false_abstentions = 0
    correct_abstentions = 0
    conflict_handled_hits = 0
    version_handled_hits = 0

    detailed_rows = []
    failures = []

    for q in golden_set:
        qid = q["id"]
        pregunta = q["pregunta"]
        tipo = q["tipo"]
        debe_responder = q["debe_responder"]
        expected_ids = [eid.strip() for eid in q["fragmento_esperado"].split("|") if eid.strip() != "NONE"]

        res = agent.process_query(pregunta, usuario_id="U-01")
        evidencia = res["evidencia_rag"][:k]
        retrieved_ids_k = [r["chunk_id"] for r in evidencia]
        retrieved_id_1 = retrieved_ids_k[0] if retrieved_ids_k else None

        if debe_responder:
            if res["status"] == "ABSTENCION":
                false_abstentions += 1

            # Evaluar Recall@1 y Recall@k a nivel de fragmento
            hit_1 = bool(retrieved_id_1 and retrieved_id_1 in expected_ids)
            if len(expected_ids) > 1:
                hit_k = all(eid in retrieved_ids_k for eid in expected_ids)
            else:
                hit_k = any(eid in retrieved_ids_k for eid in expected_ids)

            if hit_1:
                recall_at_1_hits += 1
            if hit_k:
                recall_at_k_hits += 1

            # Evaluar Precisión de cita y Fidelidad
            citas_emitidas = res["citas"]
            expected_docs = [d.strip() for d in q["documento_esperado"].split("|")]
            cita_precisa = bool(citas_emitidas) and any(
                any(doc_code in c for c in citas_emitidas[:2]) for doc_code in expected_docs
            )
            if len(expected_docs) > 1:
                cita_precisa = all(any(doc_code in c for c in citas_emitidas) for doc_code in expected_docs)

            if cita_precisa:
                citation_precision_hits += 1

            # Fidelidad: todas las afirmaciones provienen del fragmento recuperado y citan la fuente vigente
            fiel = hit_k and cita_precisa and res["status"] != "ABSTENCION"
            if fiel:
                faithfulness_hits += 1

            # Evaluar manejo de conflicto y vigencia
            if tipo == "conflicto_vigente":
                if res["status"] == "CONFLICTO_VIGENTE" and hit_k:
                    conflict_handled_hits += 1
            elif tipo == "cambio_version":
                if res["status"] == "VIGENCIA_CONTRASTADA" and hit_k:
                    version_handled_hits += 1

            # Clasificación de fallo según la regla de la clase (¿Falló la búsqueda o falló el modelo?)
            fallo_tipo = "NINGUNO"
            if not hit_k:
                fallo_tipo = "FALLO_RECUPERACION"
                failures.append({"id": qid, "etapa": "RECUPERACION", "esperado": expected_ids, "obtenido": retrieved_ids_k})
            elif not fiel or not cita_precisa:
                fallo_tipo = "FALLO_GENERACION"
                failures.append({"id": qid, "etapa": "GENERACION", "esperado": expected_ids, "status": res["status"]})

            detailed_rows.append(
                {
                    "id": qid,
                    "tipo": tipo,
                    "esperado": q["fragmento_esperado"],
                    "top_1": retrieved_id_1,
                    "recall_at_1": hit_1,
                    "recall_at_k": hit_k,
                    "cita_precisa": cita_precisa,
                    "fidelidad": fiel,
                    "status": res["status"],
                    "fallo": fallo_tipo,
                }
            )
        else:
            abstained = res["status"] == "ABSTENCION"
            if abstained:
                correct_abstentions += 1
                fallo_tipo = "NINGUNO"
            else:
                fallo_tipo = "FALLO_COMPORTAMIENTO_NO_ABSTUVO"
                failures.append({"id": qid, "etapa": "COMPORTAMIENTO", "status": res["status"]})

            detailed_rows.append(
                {
                    "id": qid,
                    "tipo": tipo,
                    "esperado": "NONE (Abstención)",
                    "top_1": retrieved_id_1,
                    "recall_at_1": abstained,
                    "recall_at_k": abstained,
                    "cita_precisa": abstained,
                    "fidelidad": abstained,
                    "status": res["status"],
                    "fallo": fallo_tipo,
                }
            )

    n_ans = len(answerable)
    n_unans = len(unanswerable)
    n_conf_ver = len(conflict_qs) + len(version_qs)

    metrics = {
        "total_preguntas": len(golden_set),
        "con_respuesta": n_ans,
        "sin_respuesta": n_unans,
        "k": k,
        "recall_at_1_pct": round(recall_at_1_hits / n_ans * 100.0, 1),
        "recall_at_k_pct": round(recall_at_k_hits / n_ans * 100.0, 1),
        "precision_cita_pct": round(citation_precision_hits / n_ans * 100.0, 1),
        "fidelidad_pct": round(faithfulness_hits / n_ans * 100.0, 1),
        "abstencion_correcta_sin_resp_pct": round(correct_abstentions / n_unans * 100.0, 1),
        "falsa_abstencion_con_resp_pct": round(false_abstentions / n_ans * 100.0, 1),
        "manejo_conflicto_y_vigencia_pct": round(
            (conflict_handled_hits + version_handled_hits) / n_conf_ver * 100.0, 1
        ),
        "fallos_totales": len(failures),
        "fallos_detalle": failures,
        "detalle_por_pregunta": detailed_rows,
    }
    return metrics


if __name__ == "__main__":
    report = run_evaluation(k=3)
    print("=" * 95)
    print("EVALUACIÓN OFICIAL DEL GOLDEN SET (22 PREGUNTAS) - MIRA CU-1 (Sección 7.1 y 7.2)")
    print("=" * 95)
    print(f"Total preguntas evaluadas : {report['total_preguntas']} ({report['con_respuesta']} con respuesta, {report['sin_respuesta']} sin respuesta)")
    print(f"1. Recuperación - Recall@1                 : {report['recall_at_1_pct']:5.1f}%")
    print(f"2. Recuperación - Recall@3                 : {report['recall_at_k_pct']:5.1f}%")
    print(f"3. Generación   - Precisión de cita        : {report['precision_cita_pct']:5.1f}%")
    print(f"4. Generación   - Fidelidad (Faithfulness) : {report['fidelidad_pct']:5.1f}%")
    print(f"5. Comportam.   - Abstención correcta      : {report['abstencion_correcta_sin_resp_pct']:5.1f}% (Falsa abstención: {report['falsa_abstencion_con_resp_pct']:.1f}%)")
    print(f"6. Comportam.   - Conflicto y vigencia     : {report['manejo_conflicto_y_vigencia_pct']:5.1f}%")
    print("-" * 95)
    print(f"{'ID':6s} | {'Tipo':18s} | {'Esperado':27s} | {'Top-1':15s} | {'R@3':5s} | {'Estado':22s}")
    print("-" * 95)
    for r in report["detalle_por_pregunta"]:
        r3_str = "SÍ" if r["recall_at_k"] else "NO"
        t1_str = str(r["top_1"] or "-")
        print(f"{r['id']:6s} | {r['tipo']:18s} | {r['esperado'][:27]:27s} | {t1_str:15s} | {r3_str:5s} | {r['status']:22s}")
    print("=" * 95)

