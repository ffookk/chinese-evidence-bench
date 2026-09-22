"""Deterministic fictional datasets and declarations for browser checks only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from evidence_bench import evaluation as ev

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-01-31"


def dataset():
    originals = [json.loads(line) for line in (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
    cases = []
    for index in range(63):
        case = deepcopy(originals[index % len(originals)])
        case["id"] = f"fictional-{index + 1:03d}"
        case["question"] = f"Fictional topic {(index + 9) % 63:03d}: " + case["question"]
        cases.append(case)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fictional-cases.json"
        path.write_text(json.dumps(cases), encoding="utf-8")
        return ev.load_dataset([path], AS_OF)


def seed(session):
    for name in ("fictional-a", "fictional-b"):
        run = ev.prepare_run(session.dataset, run_id=name, model_label="fictional-test-model", created_at="2026-01-31T12:00:00Z")
        run["generation"]["parameters"] = {"large_integer": 9007199254740993, "whole_float": 1.0}
        for index, response in ((0, "Fictional first answer."), (1, "Fictional second reply.")):
            run["records"][index].update(outcome="answered", response_text=response)
            run["records"][index]["judgments"] = {axis: "correct" for axis in ev.AXES}
        run["records"][1]["judgments"].update(citation="incorrect", refusal_decision="unscored")
        session.dispatch("/api/import", {"document": json.dumps(run)})
