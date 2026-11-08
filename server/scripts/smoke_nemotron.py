"""Step 1 smoke test: can each Nemotron model say hi, return JSON and call a tool?

Run from server/:   .venv/bin/python scripts/smoke_nemotron.py [--verbose] [--model super|fast]

Privacy: the only data sent is the synthetic sample fact pack (aliases, ratios, bands),
validated through the FactPack schema first. No transactions, names or amounts.
Every request goes through make_client(), so --verbose shows exactly what left the machine.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.factpack_schema import FactPack  # noqa: E402
from app.http_log import make_client  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]
ENV = dotenv_values(SERVER / ".env")
SAMPLE = SERVER / "app" / "factpack_sample.json"

SIMULATE_TOOL = {
    "type": "function",
    "function": {
        "name": "simulate",
        "description": "Forecast the next 30-90 days with a scenario applied.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["car_loan", "rent_increase", "income_drop", "new_subscription"],
                },
                "payment_ratio_of_income": {"type": "number", "description": "0 to 1"},
                "term_months": {"type": "integer"},
            },
            "required": ["kind", "payment_ratio_of_income", "term_months"],
        },
    },
}


def load_pack() -> FactPack:
    return FactPack.model_validate_json(SAMPLE.read_text())


async def chat(client, model: str, messages: list, **extra) -> tuple[dict, float]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": float(ENV.get("LLM_TEMPERATURE") or 1.0),
        "top_p": float(ENV.get("LLM_TOP_P") or 0.95),
        "max_tokens": 1024,
        **extra,
    }
    started = time.perf_counter()
    r = await client.post("/chat/completions", json=body)
    elapsed = time.perf_counter() - started
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0], elapsed


def strip_think(text: str) -> str:
    return text.split("</think>")[-1].strip()


async def check_hi(client, model, extra):
    choice, secs = await chat(client, model, [{"role": "user", "content": "Say hi in five words."}], **extra)
    text = strip_think(choice["message"].get("content") or "")
    return bool(text), f"{secs:.1f}s -> {text[:80]!r}"


async def check_json(client, model, extra):
    pack = load_pack()
    prompt = (
        "You are a cash-flow assistant. Using ONLY this anonymous fact pack, reply with a JSON object "
        'with exactly two keys: "headline" (one short sentence) and "risk_level" '
        '(one of "low", "medium", "high"). Output JSON only.\n\n' + pack.model_dump_json()
    )
    choice, secs = await chat(
        client, model, [{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, **extra,
    )
    text = strip_think(choice["message"].get("content") or "")
    text = text.removeprefix("```json").removesuffix("```").strip()
    data = json.loads(text)
    ok = set(data) == {"headline", "risk_level"} and data["risk_level"] in {"low", "medium", "high"}
    return ok, f"{secs:.1f}s -> {data}"


async def check_tool(client, model, extra):
    messages = [
        {"role": "system", "content": "Turn the user's request into a simulate tool call. Do not answer in text."},
        {"role": "user", "content": "What if I buy a car with a payment of about 15% of my income for 60 months?"},
    ]
    choice, secs = await chat(client, model, messages, tools=[SIMULATE_TOOL],
        tool_choice={"type": "function", "function": {"name": "simulate"}}, **extra)
    calls = choice["message"].get("tool_calls") or []
    if not calls:
        return False, f"{secs:.1f}s -> no tool call; said {strip_think(choice['message'].get('content') or '')[:80]!r}"
    fn = calls[0]["function"]
    args = json.loads(fn["arguments"])
    ok = fn["name"] == "simulate" and args.get("kind") == "car_loan" and isinstance(args.get("term_months"), int)
    return ok, f"{secs:.1f}s -> {fn['name']}({args})"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="log every outgoing request/response")
    ap.add_argument("--model", choices=["super", "fast"], help="test only one model")
    ap.add_argument("--super-id", help="override NEMOTRON_SUPER_MODEL for this run")
    ap.add_argument("--trials", type=int, default=1, help="repeat the tool-call check N times (small samples lie)")
    ap.add_argument("--think", action="store_true", help="leave thinking mode on (default: off)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")

    key = ENV.get("NVIDIA_API_KEY")
    if not key:
        print("NVIDIA_API_KEY missing in server/.env")
        return 2
    models = {"super": args.super_id or ENV.get("NEMOTRON_SUPER_MODEL"), "fast": ENV.get("NEMOTRON_LIGHTNING_MODEL")}
    models = {k: v for k, v in models.items() if v and (not args.model or args.model == k)}
    if not models:
        print("No model names set (NEMOTRON_SUPER_MODEL / NEMOTRON_LIGHTNING_MODEL)")
        return 2

    extra = {} if args.think else {"chat_template_kwargs": {"enable_thinking": False}}
    failures = 0
    async with make_client(
        base_url=ENV.get("LLM_BASE_URL") or "https://integrate.api.nvidia.com/v1",
        headers={"Authorization": f"Bearer {key}"},
        timeout=float(ENV.get("LLM_TIMEOUT_SECONDS") or 30),
    ) as client:
        for role, model in models.items():
            print(f"\n[{role}] {model}  (thinking {'on' if args.think else 'off'})")
            checks = [("hi", check_hi), ("json", check_json)] + [(f"tool call {i + 1}", check_tool) for i in range(args.trials)]
            for name, check in checks:
                try:
                    ok, detail = await check(client, model, extra)
                except Exception as e:  # report and keep going: one failure shouldn't hide the others
                    ok, detail = False, f"{type(e).__name__}: {e}"
                failures += not ok
                print(f"  {'PASS' if ok else 'FAIL'}  {name:<10} {detail}")
    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
