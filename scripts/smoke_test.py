r"""End-to-end check against a RUNNING server and your real Gemini key.

    python -m scripts.smoke_test --pdf "C:\path\to\file.pdf" --question "..." ^
        --api-key kb_xxx

(or set KB_API_KEY instead of --api-key). It uploads the PDF, asks a
question, asks a follow-up in the same conversation, lists and then deletes
the document, and prints PASS/FAIL for each step.
"""

import argparse
import os
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.getenv("KB_API_KEY"))
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--follow-up", default="Can you explain that in more detail?")
    parser.add_argument("--keep", action="store_true", help="do not delete the PDF afterwards")
    args = parser.parse_args()

    if not args.api_key:
        print("Provide --api-key or set KB_API_KEY.")
        return 1

    headers = {"X-API-Key": args.api_key}
    base = args.base_url.rstrip("/")
    failures = 0

    def check(label, ok, detail=""):
        nonlocal failures
        print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}")
        failures += 0 if ok else 1
        return ok

    r = requests.get(f"{base}/health", timeout=30)
    check("health", r.status_code == 200)

    r = requests.get(f"{base}/me", headers=headers, timeout=30)
    if not check("api key accepted", r.status_code == 200, f"({r.status_code})"):
        return 1

    with open(args.pdf, "rb") as pdf:
        r = requests.post(
            f"{base}/documents/upload",
            headers=headers,
            files={"file": (os.path.basename(args.pdf), pdf, "application/pdf")},
            timeout=600,
        )
    check("upload", r.status_code == 200, r.text[:200])
    document_id = r.json().get("document_id") if r.status_code == 200 else None

    r = requests.post(f"{base}/ask", headers=headers, json={"question": args.question}, timeout=120)
    check("ask", r.status_code == 200, r.text[:200] if r.status_code != 200 else "")
    if r.status_code == 200:
        body = r.json()
        print("   answer:", body["answer"][:300].replace("\n", " "))
        check("has citations", bool(body["citations"]), str(body["citations"]))

        r = requests.post(
            f"{base}/ask",
            headers=headers,
            json={"question": args.follow_up, "conversation_id": body["conversation_id"]},
            timeout=120,
        )
        check("follow-up", r.status_code == 200, r.text[:200] if r.status_code != 200 else "")

        r = requests.get(f"{base}/conversations/{body['conversation_id']}/messages", headers=headers, timeout=30)
        check("history saved", r.status_code == 200 and len(r.json()) == 4)

    r = requests.get(f"{base}/documents", headers=headers, timeout=30)
    check("list documents", r.status_code == 200 and any(d["document_id"] == document_id for d in r.json()))

    r = requests.post(f"{base}/ask", json={"question": "hi"}, timeout=30)
    check("request without key is rejected", r.status_code == 401)

    if document_id and not args.keep:
        r = requests.delete(f"{base}/documents/{document_id}", headers=headers, timeout=30)
        check("delete document", r.status_code == 200)

    print("\nAll checks passed." if failures == 0 else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
