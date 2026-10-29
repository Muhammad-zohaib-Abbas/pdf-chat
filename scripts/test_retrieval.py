
from uuid import UUID

from app.config import DEFAULT_SITE_ID
from app.rag import retrieve_documents


def main():
    question = input("Enter a question: ").strip()

    if not question:
        print("Please enter a question.")
        return

    if not DEFAULT_SITE_ID:
        print("Set DEFAULT_SITE_ID in .env first.")
        return

    documents = retrieve_documents(question, UUID(DEFAULT_SITE_ID), limit=3)

    if not documents:
        print("No documents retrieved.")
        return

    print(f"\nQuestion: {question}")
    print(f"Retrieved {len(documents)} chunks\n")

    for index, document in enumerate(documents, start=1):
        (
            chunk_id,
            content,
            metadata,
            document_name,
            page_number,
            distance,
        ) = document

        print("=" * 70)
        print(f"Result: {index}")
        print(f"Chunk ID: {chunk_id}")
        print(f"Source: {document_name}")
        print(f"Page: {page_number}")
        print(f"Distance: {distance:.4f}")
        print("\nRetrieved text:")
        print(content)
        print()


if __name__ == "__main__":
    main()
