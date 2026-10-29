"""Repeatable, read-only evaluation for the PDF RAG assistant.

Run from the project root with: python -m scripts.evaluate_rag
The cases call the existing answer_question() pipeline. They do not ingest,
update, or delete database records.
"""

import re
import sys
from dataclasses import dataclass

from app.rag import answer_question


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    question: str
    expected_answer_terms: tuple[str, ...] = ()
    expected_citations: tuple[tuple[str, int], ...] = ()
    expects_refusal: bool = False


CASES = (
    EvaluationCase(
        name="prepared statements and SQL injection",
        question="How do prepared statements help prevent SQL injection in PHP?",
        expected_answer_terms=("prepared statement", "sql injection"),
        expected_citations=(
            ("web_development_rag_test_guide.pdf", 12),
            ("web_development_rag_test_guide.pdf", 14),
        ),
    ),
    EvaluationCase(
        name="unsupported Redis question",
        question="How do I configure a Redis cluster for high availability?",
        expects_refusal=True,
    ),
    EvaluationCase(
        name="unsupported Kubernetes question",
        question="How do I deploy a Kubernetes cluster?",
        expects_refusal=True,
    ),
)

REFUSAL_TEXT = "I couldn't find any relevant documents in the knowledge base."
CITATION_PATTERN = re.compile(r"\[Source:\s*(.*?),\s*Page:\s*(\d+)\]")


def evaluate_case(case: EvaluationCase) -> tuple[bool, list[str], str]:
    answer = answer_question(case.question)
    answer_lower = answer.casefold()
    failures: list[str] = []

    if case.expects_refusal:
        if REFUSAL_TEXT.casefold() not in answer_lower:
            failures.append("expected the standard unsupported-question response")
        if CITATION_PATTERN.search(answer):
            failures.append("unsupported answer included a citation")
    else:
        for term in case.expected_answer_terms:
            if term.casefold() not in answer_lower:
                failures.append(f"answer is missing expected term: {term!r}")

        citations = {
            (filename.strip(), int(page))
            for filename, page in CITATION_PATTERN.findall(answer)
        }
        for citation in case.expected_citations:
            if citation not in citations:
                failures.append(
                    f"missing citation [Source: {citation[0]}, Page: {citation[1]}]"
                )

    return not failures, failures, answer


def main() -> int:
    passed = 0
    print("Running PDF RAG evaluation (database is read-only for this script).\n")

    for case in CASES:
        try:
            success, failures, answer = evaluate_case(case)
        except Exception as error:
            success = False
            failures = [f"pipeline raised {type(error).__name__}: {error}"]
            answer = ""

        status = "PASS" if success else "FAIL"
        print(f"[{status}] {case.name}")
        if answer:
            print(f"  Answer: {answer}")
        for failure in failures:
            print(f"  Check failed: {failure}")
        print()
        passed += int(success)

    print(f"Result: {passed}/{len(CASES)} cases passed.")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
