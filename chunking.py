def text_chunks(text, chunk_size, overlap):
    wrods = text.split()

    chunks = []
    start = 0
    end = chunk_size

    while start < len(wrods):
        end = start + chunk_size
        chunk = wrods[start:end]
        chunks.append(" ".join(chunk))

        start = end - overlap
    return chunks


text = """
Python is a programming language.
It is widely used for web development.
Python is also popular in data science.
It can be used to build AI applications.
FastAPI is a Python framework for building APIs.
"""

chunks = text_chunks(text, 10, 2)
i = 0;
for chunk in chunks:
    i = i+1
    print(f"Chunk {i}:")
    print(chunk)
    print()


