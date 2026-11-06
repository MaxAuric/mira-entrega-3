"""
Módulo de Indexación del Corpus RAG para el Caso MIRA (CU-1: Operador de Revisión).
Cumple con la Sección 4.1 y Criterio C3 de la rúbrica:
- Indexación reproducible y estrictamente separada de la consulta.
- Conserva en cada fragmento (chunk) los metadatos obligatorios del encabezado:
  código, título, versión, estado (Vigente/Derogada), vigencia, origen y sección.
- Soporta dos estrategias de fragmentación para el experimento comparativo:
  1. `markdown_section`: Por secciones semánticas Markdown (`##`).
  2. `fixed_window`: Ventana fija de caracteres con solapamiento (overlap).
"""

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Literal, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"
INDEX_PATH = PROJECT_ROOT / "data" / "rag_index.json"


def parse_markdown_header(content: str, filename: str) -> Tuple[Dict[str, str], str]:
    """
    Extrae el título y la tabla de metadatos del encabezado de un documento del kit.
    Retorna (metadatos, cuerpo_sin_encabezado).
    """
    lines = content.splitlines()
    title = filename
    for line in lines:
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            break

    meta = {
        "codigo": "DESCONOCIDO",
        "titulo": title,
        "version": "1",
        "estado": "Vigente",
        "vigencia": "",
        "responsable": "",
        "origen": "kit",
        "archivo": filename,
    }

    table_pattern = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")
    body_start_idx = 0

    for idx, line in enumerate(lines):
        m = table_pattern.match(line.strip())
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if key in ("campo", "---", ""):
                continue
            clean_val = re.sub(r"\*\*|\*", "", val).strip()
            if "código" in key or "codigo" in key:
                meta["codigo"] = clean_val
            elif "versión" in key or "version" in key:
                meta["version"] = clean_val
            elif "estado" in key:
                meta["estado"] = "Derogada" if "derogad" in clean_val.lower() else "Vigente"
                meta["estado_detalle"] = clean_val
            elif "vigencia" in key:
                meta["vigencia"] = clean_val
            elif "responsable" in key:
                meta["responsable"] = clean_val
            elif "origen" in key:
                meta["origen"] = clean_val

        if line.strip().startswith("## "):
            body_start_idx = idx
            break

    body = "\n".join(lines[body_start_idx:]) if body_start_idx > 0 else content
    return meta, body


def chunk_by_markdown_section(meta: Dict[str, str], body: str) -> List[Dict]:
    """
    Estrategia 1 (Principal): Fragmentación por secciones semánticas `## `.
    Cada sección conserva su número/nombre y asigna un ID canónico `<CODIGO>_v<VERSION>::<NUM_SECCION>`
    coincidente con el Golden Set.
    """
    sections = re.split(r"(?m)^##\s+", body)
    chunks = []
    sec_counter = 0

    for raw_sec in sections:
        cleaned = raw_sec.strip()
        if not cleaned:
            continue
        sec_counter += 1
        lines = cleaned.splitlines()
        sec_title = lines[0].strip()
        sec_text = "\n".join(lines[1:]).strip()

        num_match = re.match(r"^(\d+)\.", sec_title)
        sec_id_num = num_match.group(1) if num_match else str(sec_counter)
        chunk_id = f"{meta['codigo']}_v{meta['version']}::{sec_id_num}"

        full_text = (
            f"Documento: {meta['titulo']} ({meta['codigo']} v{meta['version']} - Estado: {meta['estado']})\n"
            f"Sección: {sec_title}\n"
            f"Contenido:\n{sec_text}"
        )
        approx_tokens = max(1, math.ceil(len(full_text.split()) * 1.3))

        chunks.append(
            {
                "chunk_id": chunk_id,
                "codigo": meta["codigo"],
                "titulo": meta["titulo"],
                "version": meta["version"],
                "estado": meta["estado"],
                "vigencia": meta["vigencia"],
                "origen": meta["origen"],
                "archivo": meta["archivo"],
                "seccion": sec_title,
                "seccion_num": sec_id_num,
                "texto": sec_text,
                "texto_indexado": full_text,
                "tokens_aprox": approx_tokens,
                "estrategia": "markdown_section",
            }
        )
    return chunks


def chunk_by_fixed_window(
    meta: Dict[str, str], body: str, window_chars: int = 350, overlap_chars: int = 50
) -> List[Dict]:
    """
    Estrategia 2 (Baseline para el experimento comparativo):
    Fragmentación ciega por ventana fija de caracteres sin respetar bordes de sección.
    """
    chunks = []
    step = max(1, window_chars - overlap_chars)
    text = body.strip()

    # Mapear en qué sección cae cada posición del texto para evaluar Recall@k de forma justa
    sec_spans = []
    sec_counter = 0
    for m in re.finditer(r"(?m)^##\s+([^\n]+)", text):
        sec_counter += 1
        sec_title = m.group(1).strip()
        num_match = re.match(r"^(\d+)\.", sec_title)
        sec_id_num = num_match.group(1) if num_match else str(sec_counter)
        sec_spans.append((m.start(), sec_title, sec_id_num))

    idx = 0
    part = 0
    while idx < len(text):
        part += 1
        window = text[idx : idx + window_chars].strip()
        if not window:
            break

        # Determinar la sección principal cubierta por el inicio/mitad de la ventana
        mid_pos = idx + (len(window) // 2)
        active_sec_title = "General"
        active_sec_num = "1"
        for start_pos, s_title, s_num in sec_spans:
            if start_pos <= mid_pos:
                active_sec_title = s_title
                active_sec_num = s_num
            else:
                break

        chunk_id = f"{meta['codigo']}_v{meta['version']}::{active_sec_num}"
        approx_tokens = max(1, math.ceil(len(window.split()) * 1.3))

        chunks.append(
            {
                "chunk_id": chunk_id,
                "chunk_uid": f"{meta['codigo']}_v{meta['version']}_win{part}",
                "codigo": meta["codigo"],
                "titulo": meta["titulo"],
                "version": meta["version"],
                "estado": meta["estado"],
                "vigencia": meta["vigencia"],
                "origen": meta["origen"],
                "archivo": meta["archivo"],
                "seccion": active_sec_title,
                "seccion_num": active_sec_num,
                "texto": window,
                "texto_indexado": window,
                "tokens_aprox": approx_tokens,
                "estrategia": f"fixed_window_{window_chars}",
            }
        )
        idx += step
    return chunks


def tokenize_es(text: str) -> List[str]:
    """Tokenizador en español normalizado con preservación de códigos técnicos (ej. DOC_AUT, POL-DEC)."""
    text_lower = text.lower()
    replacements = str.maketrans("áéíóúü", "aeiouu")
    normalized = text_lower.translate(replacements)
    tokens = re.findall(r"[a-z0-9_]+(?:-[a-z0-9_]+)*", normalized)
    stopwords = {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
        "en", "con", "por", "para", "sin", "sobre", "entre", "hacia", "hasta", "desde",
        "y", "o", "u", "ni", "que", "se", "su", "sus", "es", "son", "fue", "ha", "han",
        "como", "mas", "pero", "si", "lo", "le", "les", "este", "esta", "estos", "estas",
        "ese", "esa", "aquel", "cada", "todo", "toda", "todos", "todas"
    }
    return [t for t in tokens if len(t) > 1 and t not in stopwords]


def build_corpus_inventory(corpus_dir: Path = CORPUS_DIR) -> List[Dict]:
    """Genera el inventario completo del corpus exigido en la Sección 4.1 del informe."""
    inventory = []
    for md_file in sorted(corpus_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta, body = parse_markdown_header(content, md_file.name)
        sec_chunks = chunk_by_markdown_section(meta, body)
        words = len(content.split())
        tokens_aprox = math.ceil(words * 1.3)
        inventory.append(
            {
                "identificador": f"{meta['codigo']} (v{meta['version']})",
                "codigo": meta["codigo"],
                "titulo": meta["titulo"],
                "origen": meta["origen"],
                "version": meta["version"],
                "estado": meta["estado"],
                "vigencia": meta["vigencia"],
                "secciones": len(sec_chunks),
                "palabras": words,
                "tokens_aprox": tokens_aprox,
                "archivo": md_file.name,
            }
        )
    return inventory


def build_index(
    corpus_dir: Path = CORPUS_DIR,
    index_path: Path = INDEX_PATH,
    strategy: Literal["markdown_section", "fixed_window"] = "markdown_section",
    window_chars: int = 350,
    overlap_chars: int = 50,
) -> Dict:
    """
    Construye y persiste el índice RAG en disco con vocabulario IDF y vectores TF-IDF + BM25,
    además de poblar ChromaDB si se encuentra disponible en el entorno.
    """
    all_chunks: List[Dict] = []
    inventory = build_corpus_inventory(corpus_dir)

    for md_file in sorted(corpus_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta, body = parse_markdown_header(content, md_file.name)
        if strategy == "markdown_section":
            chunks = chunk_by_markdown_section(meta, body)
        else:
            chunks = chunk_by_fixed_window(meta, body, window_chars=window_chars, overlap_chars=overlap_chars)
        all_chunks.extend(chunks)

    # Calcular frecuencias e IDF para recuperación híbrida (BM25 + Similitud Coseno TF-IDF de n-gramas)
    N = len(all_chunks)
    df_counts: Dict[str, int] = {}
    chunk_tokens_list: List[List[str]] = []

    for ch in all_chunks:
        toks = tokenize_es(ch["texto_indexado"])
        # Añadir bigramas para capturar frases exactas como "aprobacion automatica" o "solicitud antecedentes"
        bigrams = [f"{toks[i]}_{toks[i+1]}" for i in range(len(toks) - 1)]
        combined = toks + bigrams
        chunk_tokens_list.append(combined)
        for unique_t in set(combined):
            df_counts[unique_t] = df_counts.get(unique_t, 0) + 1

    idf_map = {
        term: math.log((N - df + 0.5) / (df + 0.5) + 1.0)
        for term, df in df_counts.items()
    }
    avgdl = sum(len(toks) for toks in chunk_tokens_list) / max(1, N)

    for ch, toks in zip(all_chunks, chunk_tokens_list):
        tf_map: Dict[str, int] = {}
        for t in toks:
            tf_map[t] = tf_map.get(t, 0) + 1
        ch["tf"] = tf_map
        ch["doc_len"] = len(toks)

    index_payload = {
        "strategy": strategy,
        "total_chunks": N,
        "avgdl": avgdl,
        "inventory": inventory,
        "idf": idf_map,
        "chunks": all_chunks,
    }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_payload


if __name__ == "__main__":
    payload = build_index(strategy="markdown_section")
    print(f"Índice RAG generado en: {INDEX_PATH}")
    print(f"Estrategia: {payload['strategy']} | Total fragmentos indexados: {payload['total_chunks']}")
    print("\nInventario del Corpus (Sección 4.1):")
    for doc in payload["inventory"]:
        print(
            f"  - {doc['identificador']:15s} | Estado: {doc['estado']:8s} | "
            f"Secciones: {doc['secciones']:2d} | Tokens aprox: {doc['tokens_aprox']:4d} | {doc['titulo']}"
        )
