"""Reload every store, run every experiment, print and save all numbers.

    python -m bookloan.run_all

Output: results/results.json (machine readable) and the same text on screen.
The report (report/REPORT.md) quotes numbers from this output; none are typed in by hand.
"""
import json

from . import config, experiments, load_all, vector_bench


def show(title, data):
    print(f"\n===== {title} =====")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def main():
    config.RESULTS_DIR.mkdir(exist_ok=True)
    print("Reloading all five stores from data/ ...")
    load_all.main()                                   # fresh start -> repeatable results

    results = {}
    for name, fn in [
        ("1_eligibility_tests", experiments.eligibility),
        ("2_mongo_validation", experiments.mongo_validation),
        ("3_redis_cache", experiments.redis_cache),
        ("4_neo4j_graph", experiments.graph),
        ("5_concurrency_last_copy", experiments.concurrency),
        ("6_vector_benchmark", vector_bench.run),
        ("7_update_across_stores", experiments.update_across_stores),
    ]:
        results[name] = fn()
        show(name, results[name])

    (config.RESULTS_DIR / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str),
                                                     encoding="utf-8")
    print("\nSaved results/results.json")


if __name__ == "__main__":
    main()
