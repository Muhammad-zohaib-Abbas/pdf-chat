
from app.rag import answer_question


if __name__ == "__main__":
    while True:
        question = input("\nAsk a question (or type 'exit'): ").strip()

        if question.lower() == "exit":
            print("Goodbye!")
            break

        if not question:
            continue

        try:
            answer = answer_question(question)
            print(f"\nAnswer: {answer}")

        except Exception as error:
            error_message = str(error)

            if "503" in error_message or "UNAVAILABLE" in error_message:
                print(
                    "\nGemini is temporarily unavailable. "
                    "Please wait a little and try again."
                )
            else:
                print(f"\nSomething went wrong: {error}")
