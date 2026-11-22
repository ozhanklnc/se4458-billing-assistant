"""Command-line chat for the billing assistant.

    python cli.py                       # interactive chat
    python cli.py -q "What is my October bill?"   # single question (good for screenshots)

Settings come from environment variables or agent/.env (see .env.example).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import signal
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agent import BillingAgent, TurnResult
from clients import DocsClient, GatewayClient

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/mcp")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# low = faster answers; leave empty for providers/models without reasoning support
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")

LOG_DIR = HERE / "logs"


def short(value, limit=400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + " ..."


def print_trace(result: TurnResult) -> None:
    print("\n  ── tool trace " + "─" * 50)
    n = 0
    for step in result.trace:
        if step.kind == "llm":
            print(f"  [LLM] {step.name}: {short(step.output, 300)}  ({step.ms} ms)")
        else:
            n += 1
            print(f"  [{n}] {step.name}  via {step.channel}  ({step.ms} ms)")
            print(f"      input : {short(step.input)}")
            print(f"      result: {short(step.output)}")
    print("  " + "─" * 64)


def save_trace(log_file: Path, question: str, result: TurnResult) -> None:
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "steps": [s.__dict__ for s in result.trace],
        "final_answer": result.answer,
    }
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


async def ask_yes_no(prompt: str) -> bool:
    answer = await asyncio.to_thread(input, f"\n  >>> CONFIRM: {prompt} [yes/no] ")
    return answer.strip().lower() in ("y", "yes", "evet", "e")


async def main():
    # Ctrl+C quits immediately, even while waiting for the LLM or for input()
    asyncio.get_running_loop().add_signal_handler(
        signal.SIGINT, lambda: (print("\nbye"), os._exit(130)))

    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question", help="ask one question and exit")
    ap.add_argument("-u", "--username", default=os.getenv("AGENT_USERNAME"))
    ap.add_argument("--no-trace", action="store_true")
    args = ap.parse_args()

    if not LLM_API_KEY:
        raise SystemExit("LLM_API_KEY is not set (see agent/.env.example)")

    username = args.username or input("username: ")
    password = os.getenv("AGENT_PASSWORD") or getpass.getpass("password: ")

    gateway = GatewayClient(GATEWAY_URL)
    login = await gateway.login(username, password)
    if not login.get("subscriberNo"):
        raise SystemExit("This chat is for subscriber accounts (admin has no subscriber number).")

    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"trace-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    llm = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=40, max_retries=3)

    async with DocsClient(MCP_URL) as docs:
        bot = BillingAgent(llm, LLM_MODEL, gateway, docs, confirm=ask_yes_no,
                           reasoning_effort=LLM_REASONING_EFFORT or None)
        await bot.start()
        print(f"Signed in as {username} (subscriber {gateway.subscriber_no}). "
              f"Gateway: {GATEWAY_URL}  MCP: {MCP_URL}  LLM: {LLM_MODEL}")
        print("Type 'exit' to quit.\n")

        questions = [args.question] if args.question else None
        while True:
            if questions is not None:
                if not questions:
                    break
                q = questions.pop(0)
                print(f"you> {q}")
            else:
                q = (await asyncio.to_thread(input, "you> ")).strip()
                if q.lower() in ("exit", "quit"):
                    break
                if not q:
                    continue

            result = await bot.ask(q)
            if not args.no_trace:
                print_trace(result)
            print(f"\nassistant> {result.answer}\n")
            save_trace(log_file, q, result)

    await gateway.close()
    print(f"Trace saved to {log_file.relative_to(HERE)}")


if __name__ == "__main__":
    asyncio.run(main())
