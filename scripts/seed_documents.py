from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from app.database import get_connection
from app.embeddings import generate_embedding


DOCUMENTS = [
    "PostgreSQL is a powerful relational database.",
    "PostgreSQL is a relational database.",
    "Python is a popular programming language.",
    "The sun is shining on a beautiful day.",
]


def seed_documents():
    with get_connection() as connection:
        register_vector(connection)
        with connection.cursor() as cursor:
            for page_number, content in enumerate(DOCUMENTS, start=1):
                print(f"Generating embedding: {content}")
                embedding = generate_embedding(
                    content,
                    task_type="RETRIEVAL_DOCUMENT",
                )
                metadata = {
                    "source": "sample_seed_data.txt",
                    "page_number": page_number,
                    "chunk_index": 1,
                }

                cursor.execute(
                    """
                    SELECT id, document_id
                    FROM document_chunks
                    WHERE content = %s
                    LIMIT 1
                    """,
                    (content,),
                )
                existing = cursor.fetchone()

                if existing:
                    chunk_id, document_id = existing
                    if document_id is None:
                        cursor.execute(
                            """
                            INSERT INTO documents (document_name, page_number, content)
                            VALUES (%s, %s, %s)
                            RETURNING id
                            """,
                            ("sample_seed_data.txt", page_number, content),
                        )
                        document_id = cursor.fetchone()[0]
                    else:
                        cursor.execute(
                            """
                            UPDATE documents
                            SET document_name = %s, page_number = %s, content = %s
                            WHERE id = %s
                            """,
                            ("sample_seed_data.txt", page_number, content, document_id),
                        )

                    cursor.execute(
                        """
                        UPDATE document_chunks
                        SET embedding = %s, metadata = %s, document_id = %s
                        WHERE id = %s
                        """,
                        (Vector(embedding), Jsonb(metadata), document_id, chunk_id),
                    )
                    print(f"Updated chunk ID: {chunk_id}")
                else:
                    cursor.execute(
                        """
                        INSERT INTO documents (document_name, page_number, content)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        ("sample_seed_data.txt", page_number, content),
                    )
                    document_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO document_chunks
                            (document_id, content, metadata, embedding)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (document_id, content, Jsonb(metadata), Vector(embedding)),
                    )
                    print(f"Inserted chunk ID: {cursor.fetchone()[0]}")

    print("\nDocument embedding process completed!")


if __name__ == "__main__":
    seed_documents()
