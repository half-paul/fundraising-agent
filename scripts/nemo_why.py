"""Replay one text through the NeMo self-check rails and print the production verdict plus an explained verdict.

Production prompts answer only "Yes"/"No" (max_tokens 20) and /v1/checks returns only status + rail, so there is no
reason anywhere. This script runs the same config in-process inside the nemo-guardrails container twice:
  prod  : the config exactly as deployed
  judge : the same prompts with the final question rewritten (in memory only) to ask for "Yes./No. Reason: ...",
          max_tokens raised; the reason is read from NeMo's self-check INFO log line.
The explained run is a slightly different prompt, so the two verdicts can disagree -- the script flags that.

Run via:  make nemo-why TEXT='...'                       (input rail)
          make nemo-why RAIL=output TEXT='bot reply...'  (output rail; user turn is "hi")
Piped into the container on stdin; argv: <input|output> <text>.
Verdicts are not deterministic -- run a borderline text a few times.
"""
import asyncio
import logging
import os
import sys

from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import RailType

CONFIG = "/config/aicp"
GATEWAY = os.environ.get("MAIN_MODEL_BASE_URL", "http://litellm:4000/v1")
PROD_ANSWER = 'Answer only "Yes" or "No".'
# Yes/No meaning spelled out: without it the judge, once asked to explain, flipped polarity on allowed actions.
EXPLAIN_ANSWER = (
    '"Yes" means BLOCK it. "No" means ALLOW it (including everything the policy above says is allowed).\n'
    'Start your answer with exactly "Yes." or "No.", then " Reason: " and one short sentence.\n'
)

reasons: list[str] = []


class _Reason(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if "self-checking result" in msg:
            reasons.append(msg.split("`", 1)[-1].rstrip("`."))


def _rails(explain: bool) -> LLMRails:
    cfg = RailsConfig.from_path(CONFIG)
    # the server gets the gateway URL from MAIN_MODEL_BASE_URL; an in-process LLMRails needs it on the model
    cfg.models[0].parameters["base_url"] = GATEWAY
    if explain:
        cfg.models[0].parameters["max_tokens"] = 80
        for p in cfg.prompts:
            if p.task in ("self_check_input", "self_check_output"):
                if PROD_ANSWER not in p.content:
                    sys.exit(f"nemo_why: '{PROD_ANSWER}' not found in {p.task} prompt; update EXPLAIN rewrite")
                p.content = p.content.replace(PROD_ANSWER, EXPLAIN_ANSWER)
    return LLMRails(cfg)


async def _check(rails: LLMRails, messages: list[dict], rt: RailType):
    return await rails.check_async(messages=messages, rail_types=[rt])


def main() -> None:
    rail, text = sys.argv[1], sys.argv[2]
    log = logging.getLogger("nemoguardrails.library.self_check")
    log.setLevel(logging.INFO)
    log.addHandler(_Reason())

    if rail == "output":
        messages, rt = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": text}], RailType.OUTPUT
    else:
        messages, rt = [{"role": "user", "content": text}], RailType.INPUT

    prod = asyncio.run(_check(_rails(False), messages, rt))
    reasons.clear()
    expl = asyncio.run(_check(_rails(True), messages, rt))

    print("prod  :", prod.status.value, f"(rail: {prod.rail})" if prod.rail else "")
    print("judge :", reasons[-1] if reasons else "(no self-check reason -- blocked by another rail, e.g. injection detection)")
    if prod.status != expl.status:
        print(f"WARN  : explained run disagrees ({expl.status.value}); the reason may not reflect the prod verdict")


if __name__ == "__main__":
    main()
