"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing, sustainability

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    base_cost = opt_cost = 0.0
    cache_naive_cost = cache_guarded_cost = 0.0
    total_tokens = 0
    cached_requests = 0
    cached_tokens = 0
    cache_read_equiv = 0.0
    reasoning = {
        "requests": 0, "tokens": 0, "optimized_cost": 0.0, "wh": 0.0,
        "capped_wh": 0.0,
    }
    non_reasoning = {"requests": 0, "tokens": 0, "optimized_cost": 0.0, "wh": 0.0}
    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        is_reasoning = bool(int(num(r["is_reasoning"])))
        total_tokens += inp + out
        # BASELINE: naive deployment — everything on the large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        base_cost += pricing.request_cost(inp, out, lin, lout)
        # OPTIMIZED: cascade (route_tier), prompt caching, batch API
        pin, pout = MODEL_PRICES[r["route_tier"]]
        row_cost = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        opt_cost += row_cost

        uncached_cost = pricing.request_cost(inp, out, pin, pout, batch=is_batch)
        cache_naive_cost += row_cost
        if cached > 0:
            cached_requests += 1
            cached_tokens += cached
            cache_read_equiv += cached / max(1, inp)
        cache_guarded_cost += uncached_cost

        row_wh = sustainability.wh_per_query(inp + out, is_reasoning=is_reasoning)
        if is_reasoning:
            reasoning["requests"] += 1
            reasoning["tokens"] += inp + out
            reasoning["optimized_cost"] += row_cost
            reasoning["wh"] += row_wh
            reasoning["capped_wh"] += sustainability.wh_per_query(inp + out, is_reasoning=False)
        else:
            non_reasoning["requests"] += 1
            non_reasoning["tokens"] += inp + out
            non_reasoning["optimized_cost"] += row_cost
            non_reasoning["wh"] += row_wh

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0
    cache_avg_reads = cache_read_equiv / cached_requests if cached_requests else 0.0
    cache_worth_it = pricing.cache_is_worth_it(
        cache_avg_reads, write_cost_per_m=0.05, read_discount=0.10
    )
    cache_savings = cache_guarded_cost - cache_naive_cost

    max_reasoning_share = 0.05
    current_reasoning_share = reasoning["requests"] / len(rows) if rows else 0.0
    reducible_frac = max(0.0, current_reasoning_share - max_reasoning_share) / current_reasoning_share if current_reasoning_share else 0.0
    reasoning_cap = {
        "target_request_share": max_reasoning_share,
        "current_request_share": current_reasoning_share,
        "cost_savings_daily": reasoning["optimized_cost"] * reducible_frac * 0.35,
        "wh_savings_daily": (reasoning["wh"] - reasoning["capped_wh"]) * reducible_frac,
    }

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print("\nExtension: cache economics")
        print(f"cached requests={cached_requests}  cached tokens={cached_tokens:,}  avg read-equivalent={cache_avg_reads:.2f}")
        print(f"cache_is_worth_it(write=$0.05/1M, read=10% price): {cache_worth_it}")
        print("\nExtension: reasoning budget")
        print(f"reasoning requests={reasoning['requests']} ({current_reasoning_share*100:.1f}%)")
        print(f"reasoning optimized cost=${reasoning['optimized_cost']:.2f}/day  energy={reasoning['wh']:.1f} Wh/day")
        print(f"cap reasoning at 5% traffic -> save ${reasoning_cap['cost_savings_daily']:.2f}/day and {reasoning_cap['wh_savings_daily']:.1f} Wh/day")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "total_tokens": total_tokens,
        "cache_economics": {
            "cached_requests": cached_requests,
            "cached_tokens": cached_tokens,
            "avg_cache_reads": round(cache_avg_reads, 3),
            "worth_it": cache_worth_it,
            "write_cost_per_m": 0.05,
            "read_discount": 0.10,
            "estimated_savings_daily": round(cache_savings, 4),
        },
        "reasoning_budget": {
            "requests": reasoning["requests"],
            "request_share_pct": round(current_reasoning_share * 100, 1),
            "token_share_pct": round(reasoning["tokens"] / total_tokens * 100, 1) if total_tokens else 0.0,
            "optimized_cost_daily": round(reasoning["optimized_cost"], 2),
            "cost_share_pct": round(reasoning["optimized_cost"] / opt_cost * 100, 1) if opt_cost else 0.0,
            "wh_daily": round(reasoning["wh"], 1),
            "wh_share_pct": round(reasoning["wh"] / (reasoning["wh"] + non_reasoning["wh"]) * 100, 1) if (reasoning["wh"] + non_reasoning["wh"]) else 0.0,
            "cap_cost_savings_daily": round(reasoning_cap["cost_savings_daily"], 2),
            "cap_wh_savings_daily": round(reasoning_cap["wh_savings_daily"], 1),
        },
    }


if __name__ == "__main__":
    run()
