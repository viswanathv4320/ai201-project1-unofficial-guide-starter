"""
Milestone 3 — Document Ingestion and Chunking.

Pipeline stages implemented here (see Architecture.png):

    Source Documents  ->  Document Ingestion  ->  Chunking

`load_documents()` reads every source file in DOCS_PATH and returns one record
per document. `chunk_document()` splits a single document into embedding-ready
chunks.

Chunking strategy: STRUCTURE-AWARE RECURSIVE (see planning.md).
Rather than blindly slicing every 500 characters, we first split each document
on the natural record boundaries it already provides:

  - reviews + mapping : "====...====" separator lines between records
  - course catalog    : each "IE 300  Title  credit:..." course header
  - everything else   : blank-line-separated paragraphs

Each whole record becomes one chunk. Only when a single record is larger than
CHUNK_SIZE do we fall back to a sliding window (CHUNK_SIZE / CHUNK_OVERLAP) to
sub-split it, prepending the record's header line so the sub-chunks keep their
context. For professor-review records we also prepend the professor's name to
every individual student review, so a retrieved review always names who it is
about (Anticipated Challenge #2 in planning.md).

The Embedding + ChromaDB stages (Milestone 4) consume the chunks produced here.
"""

import os
import re

from config import DOCS_PATH, CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK_LENGTH

# A run of "=" on its own line separates records in the reviews and mapping files.
RECORD_SEPARATOR_RE = re.compile(r"\n=+\n")
# A course header looks like "IE 300   Analysis of Data   credit: 3 Hours."
COURSE_HEADER_RE = re.compile(r"(?m)^[A-Z]{2,4}\s+\d{3}\b.*credit:")
# "Professor: <name>" line in the reviews file.
PROFESSOR_RE = re.compile(r"(?m)^Professor:\s*(.+)$")


def _title_from_filename(filename):
    """Turn 'uiuc_ie_professor_reviews.txt' into 'Uiuc Ie Professor Reviews'."""
    return filename.replace(".txt", "").replace("_", " ").title()


def load_documents():
    """
    Load every .txt source document from DOCS_PATH.

    Returns a list of dicts, one per document, each with:
      - "source"   : a human-readable source title (str)
      - "filename" : the original filename (str)
      - "text"     : the full document text (str)

    Files are read in sorted order so chunk ids are stable across runs.
    """
    documents = []
    for filename in sorted(os.listdir(DOCS_PATH)):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(DOCS_PATH, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        documents.append({
            "source": _title_from_filename(filename),
            "filename": filename,
            "text": text,
        })

    print(f"Loaded {len(documents)} document(s): {[d['filename'] for d in documents]}")
    return documents


def _split_professor_block(block):
    """
    Split one "====" block from the reviews file into coherent records.

    A block is a single professor: an overview header (name, ratings, etc.)
    followed by many individual "Course: ... Review: ..." student ratings.
    We keep the overview as one record and emit each student review as its own
    record, prefixed with the professor's name so it never loses context.
    """
    prof_match = PROFESSOR_RE.search(block)
    # Only treat this as a professor block if it has a name AND several reviews.
    if not prof_match or len(re.findall(r"(?m)^Course:", block)) <= 1:
        return [block.strip()]

    prof_name = prof_match.group(1).strip()
    # Split before each "Course:" line; parts[0] is the professor overview.
    parts = re.split(r"(?m)^(?=Course:)", block)

    records = [parts[0].strip()]  # overview already begins "Professor: <name>"
    for review in parts[1:]:
        review = review.strip()
        if review:
            records.append(f"Professor: {prof_name}\n{review}")
    return records


def split_into_records(text, filename):
    """
    Split a document into semantically whole records on its natural boundaries.

    Returns a list of record strings. Each record is meant to stand on its own;
    records longer than CHUNK_SIZE are sub-split later in chunk_document().
    """
    text = text.strip()

    # 1) "====" separated records (reviews, mapping).
    if RECORD_SEPARATOR_RE.search(text):
        blocks = [b for b in RECORD_SEPARATOR_RE.split(text) if b.strip()]
        records = []
        for block in blocks:
            records.extend(_split_professor_block(block))
        return [r for r in records if r]

    # 2) Course catalog: one record per course header.
    if COURSE_HEADER_RE.search(text):
        parts = re.split(r"(?m)(?=^[A-Z]{2,4}\s+\d{3}\b.*credit:)", text)
        return [p.strip() for p in parts if p.strip()]

    # 3) Fallback: blank-line-separated paragraphs.
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _window_split(text):
    """Sliding-window fallback for a record that exceeds CHUNK_SIZE."""
    pieces = []
    start = 0
    while start < len(text):
        piece = text[start:start + CHUNK_SIZE].strip()
        if len(piece) >= MIN_CHUNK_LENGTH:
            pieces.append(piece)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return pieces


def chunk_document(text, source, filename):
    """
    Split one document into structure-aware chunks ready for embedding.

    Returns a list of dicts, each with:
      - "text"     : the chunk text (str)
      - "source"   : the source title this chunk came from (str)
      - "filename" : the original filename, for attribution (str)
      - "chunk_id" : a unique, stable identifier, e.g. "ie_courses_desc_0" (str)
    """
    chunks = []
    prefix = filename.replace(".txt", "")
    counter = 0

    for record in split_into_records(text, filename):
        if len(record) <= CHUNK_SIZE:
            # Common case: the whole record fits in one chunk — keep it intact.
            pieces = [record] if len(record) >= MIN_CHUNK_LENGTH else []
        else:
            # Oversized record: sub-split, prepending its header line so every
            # sub-chunk still says which course/professor it belongs to.
            header = record.splitlines()[0].strip()
            pieces = []
            for i, piece in enumerate(_window_split(record)):
                if i > 0 and not piece.startswith(header):
                    piece = f"{header}\n{piece}"
                pieces.append(piece)

        for piece in pieces:
            chunks.append({
                "text": piece,
                "source": source,
                "filename": filename,
                "chunk_id": f"{prefix}_{counter}",
            })
            counter += 1

    return chunks


def build_chunks():
    """Load all documents and chunk each one. Returns a flat list of chunks."""
    documents = load_documents()
    all_chunks = []
    for doc in documents:
        doc_chunks = chunk_document(doc["text"], doc["source"], doc["filename"])
        all_chunks.extend(doc_chunks)
        print(f"  {doc['filename']}: {len(doc_chunks)} chunk(s)")

    print(f"Built {len(all_chunks)} chunk(s) total across all documents.")
    return all_chunks


if __name__ == "__main__":
    # Quick sanity check: load, chunk, and preview the first chunk.
    chunks = build_chunks()
    if chunks:
        first = chunks[0]
        print("\nExample chunk:")
        print(f"  chunk_id : {first['chunk_id']}")
        print(f"  source   : {first['source']}")
        print(f"  filename : {first['filename']}")
        print(f"  text     : {first['text'][:200]!r}...")
