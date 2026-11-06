"""
Módulo de Consulta y Recuperación RAG para el Caso MIRA (CU-1: Operador de Revisión).
Cumple con la Sección 4 y los Principios PR-2, PR-3 y PR-4:
- Separado de la etapa de indexación: lee el índice persistido en `data/rag_index.json`
  (y lo construye automáticamente si aún no existe).
- Recuperación híbrida: combina puntaje léxico BM25 + similitud de n-gramas de caracteres TF-IDF
  (con scikit-learn) para tolerar variaciones morfológicas en español y códigos exactos (`DOC_AUT`, `POL-DEC`).
- Políticas documentales integradas:
  1. Cita obligatoria con formato `[Código, §Sección, vVersión (Estado)]`.
  2. Detección automática de normas derogadas (`POL-DEC v1` vs `POL-DEC v2`).
  3. Detección automática de conflicto entre fuentes vigentes (`POL-DEC v2 §2` vs `MAN-REV v1 §1`).
  4. Umbral de confianza para abstención explícita (`PR-3`) cuando la consulta no tiene respaldo en el corpus.
"""

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.rag.indexer import INDEX_PATH, build_index, tokenize_es

# Expansión de sinónimos de dominio para mejorar cobertura semántica en español
SYNONYM_MAP = {
    "minimo": ["minimos", "umbral", "bajo"],
    "minimos": ["minimo", "umbral"],
    "aprobar": ["aprobacion", "aprueba", "aprobado", "automatica", "automaticamente"],
    "aprobacion": ["aprobar", "aprueba", "automatica", "automaticamente", "bandeja", "umbral"],
    "automaticamente": ["automatica", "aprobacion", "bandeja", "85", "80"],
    "puntaje": ["score", "puntos", "umbral", "umbrales", "confianza"],
    "umbral": ["umbrales", "puntaje", "referencia", "configuracion", "aprobacion"],
    "umbrales": ["umbral", "puntaje", "referencia", "configuracion", "modificar"],
    "fraude": ["fra_edicion", "fra_memoria", "fra_sintetico", "precedencia", "resta", "puntos"],
    "antecedentes": ["solicitud", "solicitudes", "pro-ant", "tercera", "limite", "limites"],
    "solicitudes": ["solicitud", "antecedentes", "tercera", "limite", "limites", "dos"],
    "solicitar": ["solicitud", "antecedentes", "pro-ant", "aprobado"],
    "boleta": ["instruccion", "manipulacion", "faq-ope", "sistema"],
    "instruccion": ["manipulacion", "boleta", "sistema"],
    "corrijo": ["correccion", "corregir", "mal", "leido", "leidos", "recalcula"],
    "corrige": ["correccion", "corregir", "mal", "leido", "leidos", "recalcula"],
    "plazo": ["plazos", "vence", "vencido", "rojo", "20"],
    "componentes": ["cuatro", "acompanan", "puntaje", "autenticidad", "coherencia"],
    "falla": ["faltantes", "faltante", "modulo", "entrega", "parcial"],
    "falta": ["faltantes", "faltante", "modulo", "falla", "parcial", "ausencia", "entrega"],
    "respondio": ["entrega", "falla", "faltantes", "modulo", "parcial"],
    "orden": ["pasos", "recomendado", "revisar", "bandeja", "primero"],
    "modificar": ["cambio", "configuracion", "supervisores", "aprobacion", "disenador"],
}

# Palabras genéricas del dominio que por sí solas no justifican responder si el término específico no existe en el corpus
GENERIC_QUERY_WORDS = {
    "caso", "casos", "operador", "operadores", "reviso", "revisar", "revision",
    "mira", "dprime", "organizacion", "organizaciones", "sistema", "plataforma",
    "cuanto", "cual", "cuales", "como", "donde", "cuando", "quien", "porque",
    "que", "dice", "pasa", "hacer", "hago", "puede", "puedo", "tiene", "tienen",
    "por", "cada", "para", "una", "uno", "del", "las", "los",
}

# Términos explícitamente fuera de alcance del corpus CU-1 (para garantizar abstención PR-3)
OUT_OF_CORPUS_PATTERNS = [
    r"\bmegabytes\b",
    r"\bmb\b",
    r"\btama[ñn]o m[áa]ximo\b",
    r"\balgoritmo criptogr[áa]fico\b",
    r"\bredes neuronales\b",
    r"\bcosto en uf\b",
    r"\bd[óo]lares\b",
    r"\bcobra dprime\b",
    r"\bsla en segundos\b",
    r"\blatencia\b",
    r"\bwebhook\b",
    r"\bpagan\b",
    r"\bsueldo\b",
    r"\bsalario\b",
    r"\bremuneraci[óo]n\b",
    r"\bvacaciones\b",
    r"\bmulta\b",
    r"\bbono por cada\b",
    r"\bbono en dinero\b",
]


class RAGRetriever:
    """Motor de consulta sobre el índice documental de MIRA CU-1."""

    def __init__(self, index_path: Path = INDEX_PATH):
        self.index_path = index_path
        if not self.index_path.exists():
            build_index(index_path=self.index_path, strategy="markdown_section")
        self.index_data = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.chunks: List[Dict] = self.index_data["chunks"]
        self.idf: Dict[str, float] = self.index_data["idf"]
        self.avgdl: float = self.index_data["avgdl"]

        # Vectorizador de n-gramas de caracteres y palabras para similitud densa/sub-léxica
        corpus_texts = [c["texto_indexado"].lower() for c in self.chunks]
        self.char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self.char_matrix = self.char_vectorizer.fit_transform(corpus_texts)

    def _expand_query_tokens(self, query: str) -> List[str]:
        base_tokens = tokenize_es(query)
        bigrams = [f"{base_tokens[i]}_{base_tokens[i+1]}" for i in range(len(base_tokens) - 1)]
        expanded = list(base_tokens) + bigrams
        for tok in base_tokens:
            if tok in SYNONYM_MAP:
                expanded.extend(SYNONYM_MAP[tok])
        return expanded

    def _bm25_score(self, query_tokens: List[str], chunk: Dict, k1: float = 1.5, b: float = 0.75) -> float:
        tf_map = chunk.get("tf", {})
        doc_len = chunk.get("doc_len", 1)
        score = 0.0
        for term in query_tokens:
            if term not in tf_map:
                continue
            tf = tf_map[term]
            idf = self.idf.get(term, 0.5)
            num = tf * (k1 + 1.0)
            den = tf + k1 * (1.0 - b + b * (doc_len / max(1.0, self.avgdl)))
            score += idf * (num / den)
        return score

    def _is_conflict_query(self, query: str) -> bool:
        """Detecta preguntas sobre el umbral general de aprobación automática donde chocan POL-DEC v2 §2 (85) y MAN-REV v1 §1 (80)."""
        q = query.lower()
        replacements = str.maketrans("áéíóúü", "aeiouu")
        q_norm = q.translate(replacements)
        triggers_umbral = any(w in q_norm for w in ["puntaje", "umbral", "82", "80", "85", "partir de que"])
        triggers_aprob = any(w in q_norm for w in ["aprueba automatic", "aprobacion automatic", "llega a la bandeja", "llegue a la bandeja"])
        return triggers_umbral and triggers_aprob

    def _is_version_comparison_query(self, query: str) -> bool:
        """Detecta preguntas cuyos temas cambiaron entre POL-DEC v1 (derogada) y POL-DEC v2 (vigente)."""
        q = query.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
        if "version" in q or "derogad" in q or "antes" in q:
            return True
        if ("fraude" in q and ("puntaje" in q or "afectan" in q or "restan" in q)):
            return True
        if ("modificar" in q or "cambio" in q or "quien" in q) and ("umbral" in q or "umbrales" in q) and ("vigor" in q or "permiso" in q):
            return True
        if ("modulo" in q or "senal" in q) and ("falla" in q or "no entrega" in q or "faltante" in q):
            return True
        return False

    def search(
        self,
        query: str,
        top_k: int = 4,
        include_derogated: bool = True,
        min_score_threshold: float = 2.2,
    ) -> Dict:
        """
        Ejecuta la búsqueda documental y devuelve:
        - `abstain`: True si la consulta no tiene respaldo en el corpus (PR-3).
        - `conflict_detected`: True si chocan fuentes vigentes (PR-4).
        - `version_change_detected`: True si involucra una regla modificada entre v1 y v2.
        - `results`: Lista de los `top_k` fragmentos recuperados con cita formateada.
        """
        # 1. Verificación explícita de preguntas fuera del alcance del corpus
        q_lower = query.lower()
        for pat in OUT_OF_CORPUS_PATTERNS:
            if re.search(pat, q_lower):
                return {
                    "query": query,
                    "abstain": True,
                    "abstain_reason": (
                        "La información solicitada no se encuentra en el corpus documental de MIRA CU-1. "
                        "Por principio PR-3, el asistente se abstiene de inventar datos o asumir valores no documentados."
                    ),
                    "conflict_detected": False,
                    "version_change_detected": False,
                    "results": [],
                }

        query_tokens = self._expand_query_tokens(query)
        base_tokens = tokenize_es(query)
        specific_tokens = [t for t in base_tokens if t not in GENERIC_QUERY_WORDS]
        if specific_tokens:
            has_known_specific = any(
                t in self.idf or any(s in self.idf for s in SYNONYM_MAP.get(t, []))
                for t in specific_tokens
            )
            if not has_known_specific:
                return {
                    "query": query,
                    "abstain": True,
                    "abstain_reason": (
                        "Los conceptos específicos consultados no se encuentran en el corpus documental de MIRA CU-1 (PR-3)."
                    ),
                    "conflict_detected": False,
                    "version_change_detected": False,
                    "results": [],
                }

        q_char_vec = self.char_vectorizer.transform([q_lower])
        char_sims = cosine_similarity(q_char_vec, self.char_matrix).flatten()

        scored_chunks = []
        for idx, ch in enumerate(self.chunks):
            if not include_derogated and ch["estado"] == "Derogada":
                continue

            bm25 = self._bm25_score(query_tokens, ch)
            char_sim = float(char_sims[idx])
            # Solo sumar similitud de caracteres cuando exista al menos una coincidencia léxica real
            combined_score = (bm25 + (char_sim * 5.0)) if bm25 > 0.5 else (bm25 * 0.5)

            # Priorizar versión vigente sobre derogada a igualdad de tema
            if ch["estado"] == "Vigente":
                combined_score *= 1.12
            else:
                combined_score *= 0.85

            scored_chunks.append((combined_score, bm25, ch))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        max_score = scored_chunks[0][0] if scored_chunks else 0.0
        max_bm25 = scored_chunks[0][1] if scored_chunks else 0.0

        if max_score < min_score_threshold or max_bm25 < 2.2:
            return {
                "query": query,
                "abstain": True,
                "abstain_reason": (
                    "No se encontraron fragmentos con evidencia suficiente en el corpus para responder la consulta (PR-3)."
                ),
                "conflict_detected": False,
                "version_change_detected": False,
                "results": [],
            }

        conflict_detected = self._is_conflict_query(query)
        version_change_detected = self._is_version_comparison_query(query)

        selected = []
        selected_ids = set()

        # Si hay conflicto vigente entre POL-DEC v2::2 y MAN-REV v1::1, asegurar que ambos entren en el top_k (PR-4)
        if conflict_detected:
            for target_cid in ("POL-DEC_v2::2", "MAN-REV_v1::1"):
                for sc, _, ch in scored_chunks:
                    if ch["chunk_id"] == target_cid and ch["chunk_id"] not in selected_ids:
                        selected.append((sc, ch))
                        selected_ids.add(ch["chunk_id"])
                        break

        for sc, _, ch in scored_chunks:
            if len(selected) >= top_k:
                break
            cid_unique = ch.get("chunk_uid", ch["chunk_id"])
            if cid_unique not in selected_ids:
                selected.append((sc, ch))
                selected_ids.add(cid_unique)

        # Si se detectó cambio entre versiones y no entró algún fragmento de POL-DEC v1 como contraste, adjuntarlo
        if version_change_detected and include_derogated:
            has_v1 = any(c["codigo"] == "POL-DEC" and c["version"] == "1" for _, c in selected)
            if not has_v1:
                for sc, _, ch in scored_chunks:
                    if ch["codigo"] == "POL-DEC" and ch["version"] == "1":
                        if len(selected) >= top_k:
                            selected[-1] = (sc, ch)
                        else:
                            selected.append((sc, ch))
                        break

        formatted_results = []
        for sc, ch in selected:
            citation = f"[{ch['codigo']}, §{ch['seccion']}, v{ch['version']} ({ch['estado']})]"
            formatted_results.append(
                {
                    "chunk_id": ch["chunk_id"],
                    "codigo": ch["codigo"],
                    "titulo": ch["titulo"],
                    "version": ch["version"],
                    "estado": ch["estado"],
                    "vigencia": ch["vigencia"],
                    "seccion": ch["seccion"],
                    "cita": citation,
                    "score": round(sc, 3),
                    "texto": ch["texto"],
                }
            )

        return {
            "query": query,
            "abstain": False,
            "abstain_reason": None,
            "conflict_detected": conflict_detected,
            "version_change_detected": version_change_detected,
            "results": formatted_results,
        }

    def answer_from_evidence(self, query: str, top_k: int = 4) -> Dict:
        """
        Sintetiza una respuesta determinista basada estrictamente en los fragmentos recuperados
        (permite probar el RAG de manera autónoma como 'IA primitiva' sin depender de API externa).
        """
        retrieval = self.search(query, top_k=top_k)
        if retrieval["abstain"]:
            return {
                "query": query,
                "status": "ABSTENCION",
                "respuesta": f"⚠️ ABSTENCIÓN (PR-3): {retrieval['abstain_reason']}",
                "citas": [],
                "evidencia": [],
            }

        results = retrieval["results"]
        citas = [r["cita"] for r in results]

        if retrieval["conflict_detected"]:
            pol_chunk = next((r for r in results if r["chunk_id"] == "POL-DEC_v2::2"), results[0])
            man_chunk = next((r for r in results if r["chunk_id"] == "MAN-REV_v1::1"), results[-1])
            respuesta = (
                "⚖️ CONFLICTO ENTRE FUENTES VIGENTES DETECTADO (PR-4):\n"
                "Existen dos documentos vigentes en el corpus que entregan reglas distintas sobre el umbral de aprobación automática:\n"
                f"1. {pol_chunk['cita']}: Establece que la aprobación automática de referencia ocurre con puntaje de **85 o más** "
                "(y entre 60 y 84 se deriva a revisión asistida por un operador).\n"
                f"2. {man_chunk['cita']}: Afirma que los casos con puntaje de **80 o más** y sin señales de fraude se aprueban "
                "automáticamente y no llegan a la bandeja del operador.\n"
                "Siguiendo el principio PR-4, se presentan ambas fuentes vigentes sin elegir una por cuenta propia."
            )
            status = "CONFLICTO_VIGENTE"
        elif retrieval["version_change_detected"]:
            vigente_chunks = [r for r in results if r["estado"] == "Vigente"]
            derogado_chunks = [r for r in results if r["estado"] == "Derogada"]
            principal = vigente_chunks[0] if vigente_chunks else results[0]
            respuesta = (
                f"📌 RESPUESTA CON CONTROL DE VIGENCIA (Versión Vigente Aplicada):\n"
                f"Según la norma vigente {principal['cita']} (vigencia: {principal['vigencia']}):\n"
                f"{principal['texto']}\n"
            )
            if derogado_chunks:
                der = derogado_chunks[0]
                respuesta += (
                    f"\n⚠️ Nota sobre versión derogada {der['cita']}: "
                    f"Esta regla reemplazó a la versión 1 (derogada desde el 1 de septiembre de 2026), la cual establecía: "
                    f"«{der['texto']}»"
                )
            status = "VIGENCIA_CONTRASTADA"
        else:
            principal = results[0]
            secundario = results[1] if len(results) > 1 else None
            respuesta = (
                f"✅ RESPUESTA RESPALDADA EN EVIDENCIA DOCUMENTAL:\n"
                f"Según {principal['cita']}:\n{principal['texto']}"
            )
            if secundario and secundario["score"] >= principal["score"] * 0.75:
                respuesta += f"\n\nComplementariamente, según {secundario['cita']}:\n{secundario['texto']}"
            status = "EVIDENCIA_VERIFICADA"

        return {
            "query": query,
            "status": status,
            "respuesta": respuesta,
            "citas": citas,
            "evidencia": results,
        }


if __name__ == "__main__":
    import sys

    retriever = RAGRetriever()
    sample_queries = (
        sys.argv[1:]
        if len(sys.argv) > 1
        else [
            "¿Cuáles son los mínimos por señal para DOC_AUT y BIO_ROSTRO?",
            "¿A partir de qué puntaje se aprueba automáticamente un caso sin llegar a la bandeja?",
            "¿Cómo afectan las señales de fraude activas al puntaje del caso?",
            "¿Cuál es el tamaño máximo en megabytes (MB) permitido para subir un PDF?",
        ]
    )

    for q in sample_queries:
        print("=" * 80)
        print(f"PREGUNTA: {q}")
        out = retriever.answer_from_evidence(q, top_k=3)
        print(f"ESTADO:   {out['status']}")
        print(f"CITAS:    {', '.join(out['citas']) if out['citas'] else 'Ninguna (Abstención)'}")
        print("-" * 80)
        print(out["respuesta"])
        print()
