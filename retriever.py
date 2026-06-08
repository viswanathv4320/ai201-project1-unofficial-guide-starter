"""
Milestone 4 — Embedding and Retrieval.

Pipeline stages implemented here (see Architecture.png):

    Chunking  ->  Embedding (all-MiniLM-L6-v2)  ->  ChromaDB Vector Store  ->  Retrieval

This module takes the chunks produced by ingest.build_chunks(), embeds them
locally with the all-MiniLM-L6-v2 sentence-transformer, stores them in a
persistent ChromaDB collection, and exposes retrieve() for semantic search.

Generation and the UI (Milestone 5) are intentionally NOT implemented here.
"""

import re

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_COLLECTION, CHROMA_PATH, EMBEDDING_MODEL, N_RESULTS
from ingest import build_chunks

# --- Lightweight reranking signals (see retrieve()) -----------------------

# A course code like "IE 310", "IE310", "MATH 257", "GE424", "CS 374".
COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,4}\s*\d{3}[A-Z]?\b")
# A capitalized word that could be (part of) a professor name.
NAME_TOKEN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
# Capitalized words that start questions / are filler — NOT names.
_NAME_STOPWORDS = {
    "What", "Whats", "Is", "Are", "Was", "Were", "Does", "Do", "Did", "How",
    "Which", "Who", "Whom", "Whose", "When", "Where", "Why", "The", "And", "Or",
    "For", "About", "Can", "Could", "Would", "Should", "Tell", "Give", "Course",
    "Professor", "Prof", "Students", "Student", "Review", "Reviews", "Class",
}

# How much to subtract from a candidate's cosine distance on an exact match.
# Distances here run ~0.3-0.7. A code in the chunk HEADER (what the chunk is
# about) earns a strong boost; a code merely mentioned in the body (e.g. as a
# prerequisite cross-reference) earns only a small one.
COURSE_CODE_HEADER_BOOST = 0.30
COURSE_CODE_BODY_BOOST = 0.05
NAME_BOOST = 0.15

# Course-code boosts never apply to the source inventory — it's just a list of
# source URLs/filenames and mentions codes without being "about" them.
_NO_CODE_BOOST_FILES = {"source_inventory.txt"}


def _normalize_code(code):
    """Strip spaces and upper-case a course code so 'IE 310' == 'IE310'."""
    return re.sub(r"\s+", "", code).upper()


def _codes_in(text):
    """Return the set of normalized course codes found in a piece of text."""
    return {_normalize_code(m) for m in COURSE_CODE_RE.findall(text)}


def _header_codes(text):
    """
    Course codes in a chunk's identifying header (its first two lines).

    The header is what the chunk is *about*: the course-title line for catalog
    and mapping chunks, or the 'Professor:' + 'Course:' lines for a review.
    A code that only appears deeper in the body — like a prerequisite or a
    cross-reference — is deliberately NOT counted as a header code.
    """
    header = "\n".join(text.splitlines()[:2])
    return _codes_in(header)


def _name_tokens_in(query):
    """Return capitalized tokens from the query that look like name parts."""
    return {t for t in NAME_TOKEN_RE.findall(query) if t not in _NAME_STOPWORDS}

# --- One-time setup, run when the module is imported ----------------------

# SentenceTransformerEmbeddingFunction wraps SentenceTransformer("all-MiniLM-L6-v2").
# ChromaDB calls it automatically to turn text into vectors — for both the
# documents we store AND the queries we search with — so embedding happens
# locally with the same model on both sides. The model downloads on first use
# (~30-60s once) and is cached locally afterward.
_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
)

# PersistentClient writes the vector store to disk at CHROMA_PATH, so the
# embeddings survive between runs and we don't have to re-embed every time.
_client = chromadb.PersistentClient(path=CHROMA_PATH)

# get_or_create_collection returns the existing collection if it's already on
# disk, otherwise creates it. "hnsw:space": "cosine" tells ChromaDB to score
# similarity with cosine distance, where LOWER distance = MORE similar.
_collection = _client.get_or_create_collection(
    name=CHROMA_COLLECTION,
    embedding_function=_ef,
    metadata={"hnsw:space": "cosine"},
)


def get_collection():
    """Return the ChromaDB collection (handy for later milestones / debugging)."""
    return _collection


def embed_and_store(chunks):
    """
    Embed a list of chunks and store them in the ChromaDB collection.

    _collection.upsert() takes three positionally-aligned lists built from the
    chunk dicts that build_chunks() returns:
      - documents : the raw text strings. ChromaDB runs each through the
                    embedding function above to produce a vector — we never
                    compute embeddings by hand.
      - metadatas : one dict per chunk, stored next to the vector so retrieve()
                    can report where each result came from (source, filename,
                    chunk_id).
      - ids       : the stable chunk_id strings that uniquely identify entries.

    We use upsert (rather than add) so re-running this is safe: a chunk_id that
    already exists is overwritten instead of raising a duplicate-ID error.
    """
    _collection.upsert(
        documents=[c["text"] for c in chunks],
        metadatas=[
            {
                "source": c["source"],
                "filename": c["filename"],
                "chunk_id": c["chunk_id"],
            }
            for c in chunks
        ],
        ids=[c["chunk_id"] for c in chunks],
    )
    print(f"Stored {_collection.count()} total chunks in the vector database.")


def build_index():
    """Load + chunk the documents (Milestone 3) and embed/store them all."""
    chunks = build_chunks()
    embed_and_store(chunks)
    return _collection.count()


def retrieve(query, n_results=N_RESULTS):
    """
    Find the most relevant chunks for a user's question via semantic search,
    then apply a small keyword-aware rerank to fix course-code noise.

    Why rerank? all-MiniLM-L6-v2 treats "IE 310" and "IE 311" as nearly
    identical, so a vector-only search can rank the wrong course first. We pull
    a wider candidate pool, then nudge candidates that contain the EXACT course
    code (or professor name) from the query ahead of near-miss neighbours.

    Steps:
      1. Query ChromaDB for n_results * 4 candidates (a wider net than top-k).
      2. Extract exact course codes and name tokens from the query.
      3. For each candidate, subtract a course-code boost — STRONG if the code
         is in the chunk's header (what it's about), SMALL if it only appears
         in the body (e.g. a prerequisite) — and NAME_BOOST for a queried name.
         The source inventory never receives the course-code boost.
      4. Sort by the adjusted distance and return the top n_results.

    Returns a list of dicts (closest first), each with:
      - "text"              : the chunk text
      - "source"            : the source title (from metadata)
      - "filename"          : the original filename (from metadata)
      - "chunk_id"          : the stable chunk id (from metadata)
      - "distance"          : original cosine distance (LOWER = more similar)
      - "adjusted_distance" : distance after the keyword rerank (used for sort)
    """
    if _collection.count() == 0:
        return []

    # 1) Cast a wider net than the final top-k so a true match that the vector
    #    search ranked 8th still has a chance to be promoted into the top-k.
    candidate_k = min(n_results * 4, _collection.count())
    results = _collection.query(
        query_texts=[query],
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"],
    )

    # 2) Pull the exact signals out of the query once, up front.
    query_codes = _codes_in(query)
    query_names = _name_tokens_in(query)

    # query() returns a list of lists, one per query. We passed a single query,
    # so the real results live at index [0]. The inner lists are aligned by
    # position — index i refers to the same chunk in each list.
    candidates = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        adjusted = dist
        # 3a) Exact course-code overlap (space-normalized). A header match means
        #     the chunk is *about* that course -> strong boost; a body-only
        #     mention (e.g. a prerequisite) -> small boost. Skip the source
        #     inventory entirely.
        if query_codes and meta["filename"] not in _NO_CODE_BOOST_FILES:
            if query_codes & _header_codes(doc):
                adjusted -= COURSE_CODE_HEADER_BOOST
            elif query_codes & _codes_in(doc):
                adjusted -= COURSE_CODE_BODY_BOOST
        # 3b) A queried professor name appears in the chunk -> nudge closer.
        if query_names and any(name in doc for name in query_names):
            adjusted -= NAME_BOOST

        candidates.append({
            "text": doc,
            "source": meta["source"],
            "filename": meta["filename"],
            "chunk_id": meta["chunk_id"],
            "distance": dist,
            "adjusted_distance": adjusted,
        })

    # 4) Sort by the reranked score and keep the original top-k.
    candidates.sort(key=lambda c: c["adjusted_distance"])
    return candidates[:n_results]


if __name__ == "__main__":
    # Build the index on first run (or refresh it via upsert if it already exists).
    if _collection.count() == 0:
        print("Vector store is empty — building the index...\n")
        build_index()
    else:
        print(f"Vector store already has {_collection.count()} chunks. "
              f"Re-embedding to stay in sync...\n")
        build_index()

    # A few smoke-test queries drawn from the Evaluation Plan in planning.md.
    test_queries = [
        "What is IE 310 about, and what prerequisite does it require?",
        "What do students say about Chrysafis Vogiatzis for IE 300?",
        "Is IE 421 project-heavy?",
    ]

    for query in test_queries:
        print("\n" + "=" * 80)
        print(f"QUERY: {query}")
        print("=" * 80)
        for i, chunk in enumerate(retrieve(query), start=1):
            preview = chunk["text"].replace("\n", " ")[:140]
            print(f"\n[{i}] {chunk['chunk_id']}  ({chunk['filename']})  "
                  f"distance={chunk['distance']:.3f}  "
                  f"adjusted={chunk['adjusted_distance']:.3f}")
            print(f"    {preview}...")
