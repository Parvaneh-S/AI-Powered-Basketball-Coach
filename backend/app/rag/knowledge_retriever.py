
from functools import lru_cache
from sentence_transformers import SentenceTransformer
import numpy as np


# -------------------------------------------------------
# Configuration
# -------------------------------------------------------

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# -------------------------------------------------------
# Basketball coaching knowledge base
# -------------------------------------------------------

COACHING_KNOWLEDGE = [
    {
        "id": "nba_knee",
        "topic": "knee bend leg drive balance",
        "text": (
            "Begin shooting with balanced feet and "
            "slightly bent knees. Coordinate lower-body "
            "extension with the upward shooting motion."
        ),
        "source": "Jr. NBA - How to Shoot a Basketball",
        "url": "https://jr.nba.com/shooting/",
    },
    {
        "id": "nba_free_throw",
        "topic": "free throw routine knee consistency stability",
        "text": (
            "A consistent free-throw routine and controlled "
            "knee bend can help maintain stability. "
            "Players should consider their size and strength "
            "when developing their shooting technique."
        ),
        "source": "Jr. NBA - Shooting FAQ",
        "url": "https://jr.nba.com/faq/shooting/",
    },
    {
        "id": "nba_elbow",
        "topic": "elbow alignment shooting arm",
        "text": (
            "Keep the shooting elbow aligned beneath "
            "the ball and coordinate the shooting arm "
            "with the lower body during release."
        ),
        "source": "Jr. NBA - How to Shoot a Basketball",
        "url": "https://jr.nba.com/shooting/",
    },
    {
        "id": "usa_followthrough",
        "topic": "follow through wrist release",
        "text": (
            "Maintain a relaxed shooting wrist and "
            "a consistent follow-through. Coordinate "
            "the legs, core, and shooting arm smoothly."
        ),
        "source": "USA Basketball - Shooting Mechanics",
        "url": (
            "https://www.usab.com/news/2014/01/"
            "7-tips-to-improve-your-shooting-mechanics"
        ),
    },
]


# -------------------------------------------------------
# Load embedding model and encode coaching documents
# -------------------------------------------------------

@lru_cache(maxsize=1)
def load_knowledge_index():
    """
    Load the embedding model and generate document
    embeddings once per Python process.
    """

    print("[Loading semantic search model...]")

    model = SentenceTransformer(
        EMBEDDING_MODEL,
        device="cpu",
    )

    documents = [
        entry["topic"] + ". " + entry["text"]
        for entry in COACHING_KNOWLEDGE
    ]

    document_embeddings = model.encode(
        documents,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    return model, document_embeddings


# -------------------------------------------------------
# Semantic knowledge retrieval
# -------------------------------------------------------

def search_coaching_knowledge(
    query: str,
    top_k: int = 2,
) -> dict:
    """
    Find basketball coaching knowledge semantically.

    Args:
        query: User's basketball coaching question.
        top_k: Maximum number of entries to retrieve.

    Returns:
        A dictionary containing source-backed results
        ranked by cosine similarity.
    """

    if not isinstance(query, str) or not query.strip():
        return {
            "query": query,
            "status": "empty_query",
            "results": [],
        }

    model, document_embeddings = load_knowledge_index()

    # Convert the user's question into an embedding.
    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    # Normalized vector dot product = cosine similarity.
    similarity_scores = (
        document_embeddings @ query_embedding
    )

    # Rank documents by similarity.
    ranked_indices = np.argsort(
        similarity_scores
    )[::-1]

    results = []

    for index in ranked_indices[:max(0, top_k)]:
        entry = COACHING_KNOWLEDGE[int(index)]

        results.append({
            "id": entry["id"],
            "topic": entry["topic"],
            "text": entry["text"],
            "source": entry["source"],
            "url": entry["url"],
            "similarity_score": round(
                float(similarity_scores[index]), 4
            ),
        })

    return {
        "query": query,
        "status": "success",
        "retrieval_method": "semantic_embeddings",
        "embedding_model": EMBEDDING_MODEL,
        "results": results,
    }


# -------------------------------------------------------
# Local testing
# -------------------------------------------------------

if __name__ == "__main__":

    from pprint import pprint

    test_queries = [
        "How does knee bend affect basketball shooting?",
        "How does lower-body flexion help my free throw?",
        "How can I improve my shooting follow-through?",
    ]

    for question in test_queries:

        print("\n" + "=" * 60)
        print("QUESTION:", question)
        print("=" * 60)

        result = search_coaching_knowledge(
            query=question,
            top_k=2,
        )

        pprint(result)
