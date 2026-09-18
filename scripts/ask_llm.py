"""Raw LLM smoke test — talk to the configured provider directly.

Bypasses the whole GridWise pipeline (no directives, no guardrails, no
fallback). Proves whether the API key + base_url + model actually work.

Usage (venv active, from repo root):
  python scripts/ask_llm.py "What is 2+2?"
  python scripts/ask_llm.py                      # interactive: type questions
  python scripts/ask_llm.py --secondary "hello"  # test the 2nd provider

Reads credentials from .env via app.config.settings.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Windows consoles default to cp1252; force UTF-8 so LLM replies never crash on print.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from openai import OpenAI  # noqa: E402

from app.config import settings  # noqa: E402


def _pick(secondary: bool):
    if secondary:
        return (settings.llm_secondary_api_key, settings.llm_secondary_base_url,
                settings.llm_secondary_model, "secondary")
    return (settings.llm_primary_api_key, settings.llm_primary_base_url,
            settings.llm_primary_model, "primary")


def ask(client: OpenAI, model: str, question: str) -> None:
    t0 = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
        temperature=0,
    )
    ms = round((time.time() - t0) * 1000)
    answer = resp.choices[0].message.content
    usage = resp.usage
    print(f"\n{answer}\n")
    print(f"[ok] {ms} ms | tokens: "
          f"prompt={getattr(usage, 'prompt_tokens', '?')} "
          f"completion={getattr(usage, 'completion_tokens', '?')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*", help="question to ask; omit for interactive")
    ap.add_argument("--secondary", action="store_true", help="use the secondary provider")
    args = ap.parse_args()

    key, base_url, model, label = _pick(args.secondary)
    if not key:
        print(f"[error] no API key set for the {label} provider in .env "
              f"({'LLM_SECONDARY_API_KEY' if args.secondary else 'LLM_PRIMARY_API_KEY'})")
        return 2

    print(f"provider={label}  base_url={base_url}  model={model}")
    print(f"key={key[:6]}...{key[-4:]}")
    client = OpenAI(api_key=key, base_url=base_url,
                    timeout=settings.llm_timeout_seconds, max_retries=0)

    if args.question:
        try:
            ask(client, model, " ".join(args.question))
        except Exception as exc:
            print(f"\n[FAILED] {type(exc).__name__}: {exc}")
            return 1
        return 0

    print("Interactive mode. Type a question (blank line or Ctrl+C to quit).")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            return 0
        try:
            ask(client, model, q)
        except Exception as exc:
            print(f"\n[FAILED] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
