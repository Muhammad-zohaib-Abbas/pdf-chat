
from app.database import get_connection
from app.embeddings import generate_embedding
from pgvector import Vector
from pgvector.psycopg import register_vector


def search_documents(question: str, limit: int = 3):
    query_embedding = generate_embedding(
        question,
        task_type="RETRIEVAL_QUERY",
    )

    with get_connection() as connection:
        register_vector(connection)

        query_vector = Vector(query_embedding)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, content,
                       embedding <=> %s AS distance
                FROM document_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vector, query_vector, limit),
            )

            return cursor.fetchall()


if __name__ == "__main__":
    question = input("Ask a question: ")

    results = search_documents(question)

    print("\nRelevant documents:")

    for doc_id, content, distance in results:
        print(f"\nID: {doc_id}")
        print(f"Content: {content}")
        print(f"Cosine distance: {distance:.4f}")
