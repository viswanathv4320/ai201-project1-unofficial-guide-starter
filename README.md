# The Unofficial Guide — Project 1

## Demo

Short demo showing the Gradio interface answering course and professor questions with retrieved source citations, including one limitation case from the evaluation.

[Watch the demo](./Demo_The_Unofficial_Guide.mov)

---

## Domain

This project is an unofficial guide to UIUC Industrial Engineering courses and professors. It combines official course descriptions with structured student professor reviews so students can ask questions about course content, prerequisites, workload, teaching style, difficulty, and student experiences in one place. This knowledge is hard to find through official channels because course catalogs explain topics and prerequisites, but they do not capture student-reported experiences like grading style, lecture clarity, workload, accessibility, or whether a course feels project-heavy.

---

## Document Sources

The corpus actually ingested is the three local `.txt` files (rows 1–3). They
were compiled from the official UIUC sources (rows 4–5) and the Rate My
Professors pages (rows 6–15), which are listed here for attribution.

| # | Source | Type | URL or file path |
|---|--------|------|-----------------|
| 1 | IE course descriptions | Local corpus file (ingested) | `documents/ie_courses_desc.txt` |
| 2 | UIUC IE / Engineering professor reviews | Local corpus file (ingested) | `documents/uiuc_ie_professor_reviews.txt` |
| 3 | Course-to-professor mapping | Local corpus file (ingested) | `documents/course_professor_mapping.txt` |
| 4 | UIUC Course Catalog — Industrial Engineering | Official course catalog | https://catalog.illinois.edu/courses-of-instruction/ie/ |
| 5 | UIUC Course Explorer — IE Fall 2026 | Official course schedule | https://courses.illinois.edu/schedule/2026/fall/IE |
| 6 | Rate My Professors — Chrysafis Vogiatzis | Student reviews | https://www.ratemyprofessors.com/professor/2537290 |
| 7 | Rate My Professors — Harrison Kim | Student reviews | https://www.ratemyprofessors.com/professor/1887905 |
| 8 | Rate My Professors — R.S. Sreenivas | Student reviews | https://www.ratemyprofessors.com/professor/778643 |
| 9 | Rate My Professors — Karthekeyan Chandrasekaran | Student reviews | https://www.ratemyprofessors.com/professor/2440361 |
| 10 | Rate My Professors — Lavanya Marla | Student reviews | https://www.ratemyprofessors.com/professor/1836373 |
| 11 | Rate My Professors — David Lariviere | Student reviews | https://www.ratemyprofessors.com/professor/2912372 |
| 12 | Rate My Professors — Carolyn Beck | Student reviews | https://www.ratemyprofessors.com/professor/1836374 |
| 13 | Rate My Professors — Jugal Garg | Student reviews | https://www.ratemyprofessors.com/professor/2266447 |
| 14 | Rate My Professors — Molly Goldstein | Student reviews | https://www.ratemyprofessors.com/professor/2412305 |
| 15 | Rate My Professors — Richard Sowers | Student reviews | https://www.ratemyprofessors.com/professor/257568 |

---

## Chunking Strategy

The system uses **structure-aware recursive chunking**, not a simple fixed-size
split. Each document is first divided on the natural boundaries it already
provides, and only oversized records fall back to a sliding window.

**How documents are split (in `ingest.py`):**

- **`====` separator lines** delimit records in the professor reviews and
  course-professor mapping files — each record becomes its own unit.
- **Course catalog headers** like `IE 310   Deterministic Models in Optimization   credit:`
  start a new record in the course descriptions file.
- **Professor review blocks** are split further: the professor's overview header
  is one record, and each individual `Course:` student review is its own record.
  Every review is kept together with the professor's name so a retrieved chunk
  never loses the context of who and which course it describes.
- **Blank-line paragraphs** are used as a fallback when none of the above apply.

**Sliding-window fallback:** if a single record is longer than `CHUNK_SIZE`, it
is sub-split with a character window using `CHUNK_OVERLAP`, and the record's
header line is prepended to each sub-chunk so context is preserved.

**Config values (`config.py`):**

- `CHUNK_SIZE = 500` characters
- `CHUNK_OVERLAP = 75` characters
- `MIN_CHUNK_LENGTH = 50` characters (chunks shorter than this are dropped)

**Why these choices fit your documents:** Course descriptions and reviews only
make sense when their course/professor context is preserved. A fixed-size
character split could cut a review away from the professor or course it
describes — for example, stranding a course number in one chunk and its
description in the next. Splitting on the documents' own structure keeps each
course description and each student review self-contained, so a retrieved chunk
carries enough context to be interpreted on its own. The 500-character size is
large enough to hold a review's metadata (name, course, rating, difficulty)
together with its text, while the 75-character overlap protects records that
must still be sub-split by the window.

**Final chunk count:** 205 chunks across all four documents
(course_professor_mapping: 15, ie_courses_desc: 88, source_inventory: 16,
uiuc_ie_professor_reviews: 86).

---

## Embedding Model

**Model used:** `all-MiniLM-L6-v2`, run locally through `sentence-transformers`.
It is configured in `config.py` as `EMBEDDING_MODEL = "all-MiniLM-L6-v2"`, and
in `retriever.py` ChromaDB embeds both the stored chunks and incoming queries
with `SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)`. The
resulting vectors are stored in a persistent ChromaDB collection that scores
similarity with **cosine distance** (`metadata={"hnsw:space": "cosine"}`).

This model is a good fit for the project because it runs entirely locally — no
API key and no per-embedding cost — and is fast enough to index and query a
small student-project corpus. It also performs well on semantic similarity over
the short, self-contained text we embed: individual course descriptions and
single student-review chunks.

**Production tradeoff reflection:** If cost were not a constraint, the main
levers would be:

- **Accuracy:** a larger or stronger embedding model could improve retrieval
  quality, especially on domain-specific phrasing (course codes, professor
  names, IE terminology).
- **Context length:** `all-MiniLM-L6-v2` has a short input window, so longer
  reviews or course descriptions get truncated; a longer-context model would
  embed those more faithfully.
- **Multilingual support:** if student reviews ever include languages other than
  English, a multilingual model would represent them more reliably.
- **Local vs. API-hosted:** API-hosted embeddings may be more accurate but add
  cost, network latency, privacy exposure, and an external dependency. Local
  embeddings are cheaper, private, and dependency-free, but may trail larger
  hosted models in accuracy.

For a small, English, locally-run guide, the local model's speed, zero cost, and
privacy outweigh the accuracy gains a hosted model might offer.

---

## Grounded Generation

**System prompt grounding instruction:**

Generation is implemented in `query.py` using the Groq model
`llama-3.3-70b-versatile` (configured as `LLM_MODEL` in `config.py`). For each
question the system first calls `retrieve(question)`, then `build_context()`
formats every retrieved chunk into a numbered context block with source labels
`[S1]`, `[S2]`, and so on. The system prompt explicitly instructs the model to:

- answer using **only** the numbered sources provided in the context;
- not use any outside or prior knowledge;
- not invent course details, prerequisites, professors, or reviews;
- cite the sources it uses inline with their tags, e.g. `[S1]` or `[S2]`;
- reply exactly `I don't have enough information in the provided sources to answer that.`
  when the sources do not contain enough to answer.

The prompt also instructs the model to frame professor reviews as subjective
student reports, not verified facts.

Beyond the prompt, two structural safeguards reinforce grounding. First, the
retrieved chunks are the only material passed to the model, as labeled context.
Second, low-relevance chunks are filtered out before generation using a cosine
`RELEVANCE_THRESHOLD` (0.75) — if every retrieved chunk is above the threshold,
the system returns the "not enough information" response without calling the LLM
at all.

**How source attribution is surfaced in the response:**

Attribution is handled in two complementary ways. The model cites sources
inline in its answer using the `[S1]`/`[S2]` labels it was given. Independently,
the system builds a source list **programmatically** in `query.py` from each
chunk's `filename` and `chunk_id`, so attribution does not rely solely on the
LLM. The Gradio UI (`app.py`) then surfaces three outputs: the **answer**, the
**retrieved sources** (the programmatic list), and the **retrieved evidence**
(the actual chunk text passed to the model), so a user or grader can inspect
exactly what the model was given.

Note that for an unsupported question the retriever may still return its
nearest-neighbor chunks, but the generation step refuses to answer when that
context does not actually support the question. Those retrieved sources are
still shown in the UI for transparency.

---

## Evaluation Report

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What is IE 310 about, and what prerequisite does it require? | IE 310 covers deterministic optimization topics (linear optimization, simplex, duality, sensitivity analysis, transportation/assignment, network optimization, dynamic programming, nonlinear and discrete optimization). Requires credit or concurrent registration in MATH 257 or MATH 415. | Correctly described IE 310 as Deterministic Models in Optimization, listed the optimization topics, and gave the prerequisite as credit or concurrent registration in MATH 257 or MATH 415. | Relevant | Accurate |
| 2 | Which IE courses involve programming? | IE 405 (C++, algorithm design, SQL); IE 421 (programming/data structures); IE 434 (PyTorch); IE 517 (Python, pandas, NumPy, scikit-learn). | Named IE 421 and IE 534 (and IE 434 as IE 534's equivalent) as programming-related, but missed the expected IE 405 and IE 517. Retrieval pulled in some off-topic chunks (a mapping record and a source-inventory line). | Partially relevant | Partially accurate |
| 3 | What do students say about Chrysafis Vogiatzis for IE 300? | Generally very positive; students describe him as caring, accessible, helpful, and strong at explaining concepts, though IE 300 can still be challenging. | Summarized students reporting Vogiatzis as dedicated, helpful, and accessible, holding frequent office hours, grading for understanding, and lecturing well; noted the class is tough but recommended. | Relevant | Accurate |
| 4 | Is IE 421 project-heavy? | Yes. Reviews for David Lariviere's IE 421 mention a semester-long project and that the grade is mostly/almost entirely based on project performance. | Correctly answered yes, citing reviews about a semester-long project and a grade "almost entirely based on your project performance." | Relevant | Accurate |
| 5 | What do students say about Harrison Kim's IE 431 workload? | Reviews mention attendance, weekly review, case studies, quizzes, exams, and keeping up because the course requires significant effort. | Summarized a significant workload: 10–20 page case studies, quizzes, exams, and weekly lecture review, noting it is manageable with regular effort. | Relevant | Accurate |

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

**Question that failed:** Which IE courses involve programming?

**What the system returned:** The system named IE 421 and IE 534 (and IE 434 as
IE 534's equivalent) as programming-related, correctly noting that IE 421
expects programming/data-structures knowledge and coding proficiency. However,
it missed expected programming-related courses IE 405 and IE 517, and retrieval
also pulled in some off-topic chunks (a course-professor mapping record and a
source-inventory line).

**Root cause (tied to a specific pipeline stage):** This is a **retrieval
coverage** limitation, not a generation error. The question asks for a complete
list, but the relevant evidence is spread across many separate course-
description chunks (one course per chunk). The retriever returns only the top
few chunks (`N_RESULTS = 5`), so it surfaces the closest matches rather than
every relevant course. Semantic search optimizes for similarity to the query,
not exhaustive coverage — so "list all X" questions, which need high recall
across the whole corpus, are exactly the case where top-k retrieval falls short.
Generation then faithfully reports only the courses it was given, so the gap is
inherited from retrieval.

**What you would change to fix it:** The fix has to target recall, since the
evidence is real but never reaches the model.

- **Quick mitigation:** raise `N_RESULTS` (e.g. 5 → 10) so more course chunks
  reach the model. This widens coverage with a one-line change, but it also
  admits more noise and still gives no guarantee that *every* relevant course is
  retrieved — so it helps without truly solving the problem.
- **Robust fix (preferred):** add **hybrid retrieval** in `retriever.py` —
  combine the existing semantic search with a keyword pass that scans all course
  chunks for programming signals (e.g. "programming", "Python", "C++", "SQL",
  "PyTorch", "code"), then take the union of both result sets. The keyword pass
  guarantees that any course chunk literally mentioning programming is included
  regardless of its embedding distance, which directly recovers IE 405 and
  IE 517. Because it adds matches rather than relying on threshold tuning, it
  improves recall without sacrificing the precision of the semantic results.

Query expansion (rewriting the question with programming keywords before
embedding) would also help, but like raising top-k it offers no coverage
guarantee, so it is a weaker version of the hybrid approach.

---

## Spec Reflection

**One way the spec helped you during implementation:** The planning.md file helped me give the project a clear structure before I started coding. Instead of treating the RAG system as one large task, the spec broke it into smaller stages: document ingestion, chunking, embedding, vector storage, retrieval, grounded generation, and the user interface. The architecture diagram was especially helpful because it made the full process easier to understand: raw documents become chunks, chunks become embeddings, embeddings are stored in ChromaDB, user queries retrieve relevant chunks, and the LLM generates an answer from those retrieved chunks. That made it easier to decide what each file should do and how the pieces should connect.

**One way your implementation diverged from the spec, and why:** My implementation diverged from a simple fixed-size chunking approach. Once I inspected the documents, I realized that blindly splitting every 500 characters could separate important context, such as a professor name or course number, from the review or course description it belonged to. To avoid that, I implemented structure-aware chunking that first splits on natural document boundaries such as course headers, professor review blocks, individual course review entries, and separator lines. The system only falls back to a 500-character sliding window with overlap when a record is too long. This made the retrieved chunks more self-contained and easier for the generation step to cite accurately.

---

## AI Usage

**Instance 1**

- *What I gave the AI:*  
  I gave Claude my `planning.md` details for the document pipeline, including my document types, chunking strategy, and architecture diagram. I told it that my corpus had course descriptions, professor reviews, and course-professor mapping files, and that chunks needed to keep professor names and course numbers close to the review text.

- *What it produced:*  
  Claude created `config.py` and `ingest.py`. The first version loaded the `.txt` files and used a fixed character sliding window to create chunks.

- *What I changed or overrode:*  
  After I printed random chunks, I noticed the chunks were readable but not always self-contained. Some started in the middle of words or separated professor names from review text. I asked Claude to change the chunking logic to be structure-aware instead of only fixed-size. The final version splits by professor sections, course headers, separators, and review blocks first, then only uses sliding-window splitting when a record is too long.

**Instance 2**

- *What I gave the AI:*  
  I gave Claude my Retrieval Approach section and told it that `build_chunks()` returns chunks with `text`, `source`, `filename`, and `chunk_id`. I asked it to implement only embedding and retrieval using `all-MiniLM-L6-v2` and ChromaDB, without adding generation or UI.

- *What it produced:*  
  Claude created `retriever.py`. It embeds the chunks, stores them in a persistent ChromaDB collection with metadata, and has a `retrieve()` function that returns the top chunks with source information and distance scores.

- *What I changed or overrode:*  
  When I tested retrieval, professor-review questions worked well, but course-code questions were noisy. For example, IE 311 was ranking above IE 310 because it mentioned IE 310 as a prerequisite. I asked Claude to add a small reranking step that gives more weight when the exact course code appears in the course header. I kept the retrieval results and distance scores visible so I could check whether the change actually improved retrieval.
