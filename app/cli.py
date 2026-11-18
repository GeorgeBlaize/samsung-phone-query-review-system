"""Terminal client.

    python -m app.cli chat                 # interactive chatbot (keeps conversation context)
    python -m app.cli review "Galaxy S23"  # multi-agent review
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("chat")
    rv = sub.add_parser("review")
    rv.add_argument("phone")
    rv.add_argument("--focus")
    rv.add_argument("--trace", action="store_true", help="print the agent trace")
    args = parser.parse_args()

    from app.db.session import SessionLocal, init_db

    init_db()
    if args.cmd == "chat":
        from app.rag.chatbot import ChatBot

        bot = ChatBot(SessionLocal)
        print(f"Samsung phone assistant (LLM: {bot.llm_name}, {len(bot.phones)} phones). Type 'exit' to quit.\n")
        session = None
        while True:
            try:
                q = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit"}:
                break
            if q:
                r = bot.ask(q, session)
                session = r.session_id
                print(f"\nbot> {r.answer}\n     [intent={r.intent} phones={r.phones}]\n")
    else:
        from app.agents.review_graph import generate_review

        r = generate_review(args.phone, args.focus)
        if r["error"]:
            sys.exit(r["error"])
        print(r["review"])
        if args.trace:
            print("\n--- agent trace ---\n" + json.dumps(r["agent_trace"], indent=2))


if __name__ == "__main__":
    main()
