"""
Milestone 5 — Grounded Generation.

Pipeline stages implemented here (see Architecture.png):

    Retrieval  ->  Context Assembly  ->  Grounded Generation (Groq LLM)

This module turns retrieved chunks into a grounded answer:
  - build_context()    formats chunks into a numbered [S1], [S2]... context block
  - generate_answer()  asks the Groq LLM to answer ONLY from that context
  - ask()              the end-to-end entry point: retrieve -> generate -> package

The grounding guard rail lives in SYSTEM_PROMPT and in how the context is
formatted: every chunk is labelled with a source tag the model is told to cite,
and the model is instructed to say it lacks enough information rather than guess.
"""

from groq import Groq

from config import GROQ_API_KEY, LLM_MODEL
from retriever import retrieve

_client = Groq(api_key=GROQ_API_KEY)

# Grounding guard rail. This is the most important design decision in the file:
# it forbids outside knowledge, requires [S#] citations, and demands an honest
# "not enough information" instead of a confident guess.
SYSTEM_PROMPT = (
    "You are an assistant for an unofficial guide to UIUC Industrial "
    "Engineering courses and professors. Answer the question using ONLY the "
    "numbered sources provided in the context. Do not use any outside or prior "
    "knowledge, and do not invent course details, prerequisites, professors, "
    "or reviews.\n\n"
    "Cite the sources you use inline with their tags, e.g. [S1] or [S2]. If the "
    "sources do not contain enough information to answer, reply exactly: "
    "\"I don't have enough information in the provided sources to answer that.\"\n\n"
    "Professor reviews are subjective student opinions, not verified facts — "
    "frame them as what students reported, not as objective truth."
)

# Chunks above this cosine distance are treated as too weakly related to use.
# Calibrated against measured distances for this corpus + all-MiniLM-L6-v2:
#   on-topic matches  -> ~0.29-0.73   (relevant chunks we want to keep)
#   off-topic queries -> ~0.79+        (e.g. "best pizza in Chicago" ~0.795)
# 0.75 sits in the gap: it rejects clearly off-topic queries (returning the
# "not enough information" fallback) while keeping every on-topic chunk that
# matters. The gap is narrow, so the SYSTEM_PROMPT remains the primary grounding
# guard; this threshold is a coarse second line of defense.
RELEVANCE_THRESHOLD = 0.75

# Phrase the model emits when the context can't support an answer.
INSUFFICIENT_INFO = (
    "I don't have enough information in the provided sources to answer that."
)


def build_context(chunks):
    """
    Format retrieved chunks into a numbered context block for the prompt.

    Each chunk is given a stable source label ([S1], [S2], ...) in retrieval
    order, followed by its origin (filename + chunk_id) and its text. The label
    is what the model cites and what source attribution is keyed on.

    Returns a tuple (context_text, labelled_chunks) where labelled_chunks is the
    input list with a "label" added to each chunk, so callers can build the
    source list and evidence view from the same labels the model saw.
    """
    labelled_chunks = []
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        label = f"S{i}"
        labelled = {**chunk, "label": label}
        labelled_chunks.append(labelled)
        blocks.append(
            f"[{label}] (source: {chunk['filename']}, chunk: {chunk['chunk_id']})\n"
            f"{chunk['text']}"
        )

    context_text = "\n\n---\n\n".join(blocks)
    return context_text, labelled_chunks


def _format_sources(labelled_chunks):
    """Build a programmatic source-attribution list from filename + chunk_id."""
    return [
        f"[{c['label']}] {c['filename']} — {c['chunk_id']} "
        f"(distance {c['distance']:.3f})"
        for c in labelled_chunks
    ]


def generate_answer(question, chunks):
    """
    Generate a grounded answer from retrieved chunks using the Groq LLM.

    Filters out weakly-related chunks, builds a [S#]-labelled context block, and
    asks the model to answer only from it. Returns a dict with:
      - "answer"  : the model's grounded answer (str)
      - "sources" : programmatic source labels -> filename/chunk_id (list[str])
      - "chunks"  : the labelled chunks actually sent as context (list[dict])
    """
    # Drop weak matches so they don't pull the answer off-topic. If filtering
    # removes everything, fall back rather than answer from noise.
    relevant = [c for c in chunks if c.get("distance", 0.0) <= RELEVANCE_THRESHOLD]
    if not relevant:
        return {"answer": INSUFFICIENT_INFO, "sources": [], "chunks": []}

    context_text, labelled_chunks = build_context(relevant)

    user_message = (
        f"Question: {question}\n\n"
        f"Context sources:\n{context_text}"
    )

    response = _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,  # low: stay close to the evidence, minimize embellishment
    )
    answer = response.choices[0].message.content.strip()

    return {
        "answer": answer,
        "sources": _format_sources(labelled_chunks),
        "chunks": labelled_chunks,
    }


def ask(question):
    """
    End-to-end entry point: retrieve -> generate -> package the full result.

    Returns a dict with "answer", "sources", and "chunks" (the retrieved
    evidence). Empty/whitespace questions short-circuit with a prompt to ask.
    """
    if not question or not question.strip():
        return {
            "answer": "Please enter a question.",
            "sources": [],
            "chunks": [],
        }

    retrieved = retrieve(question)
    if not retrieved:
        return {"answer": INSUFFICIENT_INFO, "sources": [], "chunks": []}

    return generate_answer(question, retrieved)


if __name__ == "__main__":
    # Smoke test against the Evaluation Plan questions from planning.md.
    test_questions = [
        "What is IE 310 about, and what prerequisite does it require?",
        "What do students say about Chrysafis Vogiatzis for IE 300?",
        "Is IE 421 project-heavy?",
    ]
    for q in test_questions:
        result = ask(q)
        print("\n" + "=" * 80)
        print(f"Q: {q}")
        print("-" * 80)
        print(result["answer"])
        print("\nSources:")
        for s in result["sources"]:
            print(f"  {s}")
