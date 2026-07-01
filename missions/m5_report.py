"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
from missions._common import num, catalog_by_type, ROOT
from finops import report, sustainability
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing

DAYS = 30
# one tier down for over-provisioned ("util-lie") GPUs
RIGHTSIZE_MAP = {"H100": "A100", "H200": "H100", "A100": "A10G", "A10G": "L4", "L4": "L4"}


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    cat = catalog_by_type()

    # --- buckets ---
    infer_savings = (r2["baseline_daily"] - r2["optimized_daily"]) * DAYS
    purchasing_savings = r3["on_demand_monthly"] - r3["optimized_monthly"]

    idle_savings = r1["idle_waste_daily"] * DAYS
    rightsize_savings = 0.0
    for lie in r1["lies"]:
        cur = lie["gpu_type"]
        tgt = RIGHTSIZE_MAP.get(cur, cur)
        delta = num(cat[cur]["on_demand_hr"]) - num(cat[tgt]["on_demand_hr"])
        rightsize_savings += max(0.0, delta) * 24 * DAYS

    levers = {
        "Inference (cascade/cache/batch)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size util-lies": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline = r2["baseline_daily"] * DAYS + r3["on_demand_monthly"]
    optimized = baseline - sum(levers.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    median_tokens = 800
    wh = sustainability.wh_per_query(median_tokens)
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get),
    }

    cache = r2["cache_economics"]
    reasoning = r2["reasoning_budget"]
    extensions = [
        {
            "name": "Extension 3 - Cache Economics",
            "points": [
                f"Cached requests: {cache['cached_requests']} with {cache['cached_tokens']:,} cached input tokens.",
                f"Average cache read-equivalent is {cache['avg_cache_reads']:.2f}; cache_is_worth_it() returns {cache['worth_it']} at ${cache['write_cost_per_m']:.2f}/1M write overhead and {cache['read_discount']:.0%} cached-read price.",
                f"Estimated cache savings inside optimized inference: ${cache['estimated_savings_daily']:.2f}/day.",
            ],
        },
        {
            "name": "Extension 4 - Reasoning Budget",
            "points": [
                f"Reasoning traffic is {reasoning['request_share_pct']:.1f}% of requests and {reasoning['token_share_pct']:.1f}% of tokens.",
                f"It accounts for {reasoning['cost_share_pct']:.1f}% of optimized inference cost and {reasoning['wh_share_pct']:.1f}% of inference energy.",
                f"Routing rule: cap reasoning to 5% of traffic for low-risk requests, saving about ${reasoning['cap_cost_savings_daily']:.2f}/day and {reasoning['cap_wh_savings_daily']:.1f} Wh/day.",
            ],
        },
        {
            "name": "Recommended Priority",
            "points": [
                "First apply cascade/cache/batch because it cuts $/1M-token directly and is reversible.",
                "Then move steady workloads to reserved and interruptible jobs to spot with checkpoints.",
                "Finally right-size GPU-Util lies and shut down idle GPUs so utilization metrics match useful work.",
            ],
        },
    ]

    lie_bits = []
    for lie in r1["lies"]:
        lie_bits.append(
            f"{lie['gpu_id']} ({lie['gpu_type']}, util {lie['gpu_util_pct']:.0f}%, MFU {lie['mfu']:.3f})"
        )
    unit_economics = {
        "baseline_per_m": r2["baseline_per_m"],
        "optimized_per_m": r2["optimized_per_m"],
        "savings_pct": r2["savings_pct"],
    }
    efficiency = {
        "lie_summary": ", ".join(lie_bits) if lie_bits else "none",
        "idle_waste_daily": r1["idle_waste_daily"],
        "idle_waste_monthly": r1["idle_waste_daily"] * DAYS,
    }

    md = report.build_report(
        baseline,
        optimized,
        levers,
        sustainability=sust,
        extensions=extensions,
        unit_economics=unit_economics,
        efficiency=efficiency,
    )
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w") as f:
        f.write(md)
    png = report.savings_waterfall(levers, os.path.join(ROOT, "outputs", "savings.png"))

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print(f"\nWritten: outputs/report.md" + (f" + outputs/savings.png" if png else " (matplotlib absent: PNG skipped)"))

    return {"baseline_monthly": round(baseline), "optimized_monthly": round(optimized),
            "levers": levers, "total_savings_pct": round(total_pct, 1)}


if __name__ == "__main__":
    run()
