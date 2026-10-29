import psycopg

from app.config import DATABASE_URL


def get_connection():
    connection = psycopg.connect(DATABASE_URL)
    # Supabase installs pgvector in the extensions schema. Keeping public
    # first preserves the app tables while making the vector type discoverable.
    connection.execute("SET search_path TO public, extensions")
    return connection


if __name__ == "__main__":
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            result = cursor.fetchone()
            print("Database connected successfully!")
            print(result[0])
