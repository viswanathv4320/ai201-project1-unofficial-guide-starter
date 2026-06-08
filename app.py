"""
Milestone 5 — Query interface (Gradio).

The final pipeline stage from Architecture.png: "Gradio UI Answer".

This app wires the question box to query.ask(), then shows three outputs:
the grounded answer, the programmatic source attribution, and the raw retrieved
evidence (so a grader can see exactly what the model was given).

Run with:  python app.py
"""

import gradio as gr

from retriever import get_collection, build_index
from query import ask

# Example questions (the Evaluation Plan from planning.md).
EXAMPLE_QUESTIONS = [
    "What is IE 310 about, and what prerequisite does it require?",
    "Which IE courses involve programming?",
    "What do students say about Chrysafis Vogiatzis for IE 300?",
    "Is IE 421 project-heavy?",
    "What do students say about Harrison Kim's IE 431 workload?",
]


def ensure_index():
    """Build the vector store once on startup if it's empty."""
    collection = get_collection()
    if collection.count() == 0:
        print("Vector store is empty — building the index (first run only)...")
        build_index()
    else:
        print(f"Vector store ready ({collection.count()} chunks).")


def _format_evidence(chunks):
    """Render the retrieved chunks into a readable evidence block."""
    if not chunks:
        return "No chunks were retrieved for this question."
    blocks = []
    for c in chunks:
        adjusted = c.get("adjusted_distance", c["distance"])
        blocks.append(
            f"[{c['label']}] {c['filename']} — {c['chunk_id']}\n"
            f"distance={c['distance']:.3f}  adjusted={adjusted:.3f}\n"
            f"{c['text']}"
        )
    return "\n\n----------------------------------------\n\n".join(blocks)


def handle_question(question):
    """
    UI handler: run the full RAG pipeline and return the three output strings
    (answer, sources, retrieved evidence).
    """
    result = ask(question)
    answer = result["answer"]
    sources = "\n".join(result["sources"]) if result["sources"] else "(no sources)"
    evidence = _format_evidence(result["chunks"])
    return answer, sources, evidence


with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue"), title="The Unofficial Guide") as demo:
    gr.Markdown(
        "# 🎓 The Unofficial Guide — UIUC Industrial Engineering\n"
        "Ask about IE courses, prerequisites, professors, and what students say. "
        "Answers are grounded **only** in the retrieved sources; if the sources "
        "don't cover it, the assistant will say so."
    )

    question_box = gr.Textbox(
        label="Your question",
        placeholder="e.g. Is IE 421 project-heavy?",
        lines=2,
    )
    ask_button = gr.Button("Ask", variant="primary")

    answer_box = gr.Textbox(label="Answer", lines=8)
    sources_box = gr.Textbox(label="Retrieved sources", lines=6)
    evidence_box = gr.Textbox(
        label="Retrieved evidence (what the model was given)",
        lines=14,
    )

    gr.Examples(examples=EXAMPLE_QUESTIONS, inputs=question_box)

    outputs = [answer_box, sources_box, evidence_box]
    # Ask button click AND pressing Enter in the question box both submit.
    ask_button.click(fn=handle_question, inputs=question_box, outputs=outputs)
    question_box.submit(fn=handle_question, inputs=question_box, outputs=outputs)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  The Unofficial Guide — starting up")
    print("=" * 50 + "\n")
    ensure_index()
    demo.launch()
