"""Real CATIA integration regression; creates isolated test documents."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pipeline", ROOT / "cases/glovebox/pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

def main():
    requests = {name:json.loads((ROOT / f"cases/glovebox/{name}.json").read_text()) for name in ("recovery", "no_solution", "default")}
    plan = json.loads(pipeline.PLAN.read_text())
    for invalid in ([], [0], [-1], [True], [float("nan")], [float("inf")], [5]*5):
        try:
            pipeline.validate_request({**requests["default"],"radius_candidates_mm":invalid},plan)
        except ValueError:
            continue
        raise AssertionError("Invalid candidate accepted")
    results = {name:pipeline.run(value) for name,value in requests.items()}
    recovery, clean, no = (results[n] for n in ("recovery", "default", "no_solution"))
    assert [a["passed"] for a in recovery["attempts"]] == [False, True]
    assert recovery["attempts"][0]["restored_checkpoint_sha256"] == recovery["attempts"][1]["restored_checkpoint_sha256"]
    assert no["status"] == "no_solution"
    a,b = recovery["attempts"][-1]["after_reopen"],clean["attempts"][0]["after_reopen"]
    for field in ("volume_mm3", "area_mm2"):
        assert abs(a[field]-b[field]) < 0.001, field
    for field in ("solid_features", "sketches", "limit_mode"):
        assert a[field] == b[field], field
    try:
        pipeline.run({**requests["default"],"minimum_volume_mm3":1000},resume_run=no["run_dir"])
    except ValueError:
        pass
    else:
        raise AssertionError("Changed check conditions accepted on resume")
    resumed = pipeline.run(requests["default"],resume_run=no["run_dir"])
    assert resumed["status"] == "passed"
    assert resumed["run_dir"] == no["run_dir"]
    assert [a["passed"] for a in resumed["attempts"]] == [False,True]
    assert resumed["attempts"][0]["restored_checkpoint_sha256"] == resumed["attempts"][1]["restored_checkpoint_sha256"]
    assert abs(resumed["attempts"][-1]["after_reopen"]["volume_mm3"]-b["volume_mm3"]) < 0.001
    evidence = {"passed":True,"checks":["invalid_inputs", "failure_then_recovery", "same_checkpoint", "clean_build_equivalence", "no_solution", "save_reopen", "resume_same_checkpoint", "reject_changed_checks"],"initial_statuses":{n:r["status"] for n,r in results.items()},"resumed_status":resumed["status"],"runs":{n:r["run_dir"] for n,r in results.items()}}
    pipeline.write_json(Path(clean["run_dir"])/"integration-verification.json",evidence)
    print(json.dumps(evidence),flush=True)
if __name__ == "__main__":
    main()
