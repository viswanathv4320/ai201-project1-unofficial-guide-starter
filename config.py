import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM (Milestone 5) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"

# --- Embeddings (Milestone 4) ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# --- Vector store (Milestone 4) ---
CHROMA_COLLECTION = "unofficial_guide"
CHROMA_PATH = "./chroma_db"

# --- Retrieval (Milestone 4) ---
N_RESULTS = 5

# --- Documents (Milestone 3) ---
DOCS_PATH = "./documents"

# --- Chunking (Milestone 3) ---
# See "Chunking Strategy" in planning.md for the reasoning behind these values.
# A 500-char window is large enough to keep a professor/course's metadata
# (name, course number, rating, difficulty) together with the review text it
# describes, so a retrieved chunk carries enough context to be meaningful.
CHUNK_SIZE = 500      # characters per chunk
CHUNK_OVERLAP = 75    # characters shared between adjacent chunks
MIN_CHUNK_LENGTH = 50  # drop whitespace/fragment chunks shorter than this
