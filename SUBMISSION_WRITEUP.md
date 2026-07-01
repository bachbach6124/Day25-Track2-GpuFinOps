# Lab 25 Submission Write-up

## 1. Baseline vs. Optimized

NimbusAI's monthly GPU cost baseline is **$27,133**. After applying the FinOps levers, optimized spend drops to **$14,626**, saving **$12,507/month** or **46%**.

For inference traffic, the baseline unit cost is **$6.488/1M-token**. The optimized unit cost is **$1.126/1M-token**, a **82.6%** reduction from cascade routing, prompt caching, and batch processing.

## 2. Savings by Lever

| Lever | Monthly savings |
|---|---:|
| Inference cascade/cache/batch | $1,212 |
| Purchasing spot/reserved | $10,040 |
| Right-size util-lies | $655 |
| Kill idle GPUs | $600 |

The largest lever is **purchasing optimization** because multiple long-running or interruptible workloads move away from full on-demand pricing. The fastest reversible lever is **inference optimization**, because cascade/cache/batch directly lowers $/1M-token without changing the infrastructure fleet first.

## 3. GPU-Util Lie

M1 flags `gpu-h100-4` and `gpu-a10g-1` as GPU-Util lies. The clearest case is `gpu-h100-4`: it reports about **98% GPU utilization** but only **0.194 MFU**. This means the GPU is busy from the scheduler's point of view, but it is not converting the paid H100 hour into useful model FLOPs. Likely causes include memory stalls, small inefficient kernels, launch overhead, or decode-style workloads that are bandwidth-bound rather than compute-bound.

The financial impact is that NimbusAI can pay premium GPU-hour rates while getting a fraction of the useful throughput. The report estimates **$655/month** from right-sizing util-lie GPUs and **$600/month** from eliminating idle GPU time.

## 4. Extensions Completed

### Extension 3 - Cache Economics

I added `cache_is_worth_it()` in `finops/pricing.py` and wired its output into M2/M5. The dataset has **2,400 cached requests** and **1,703,990 cached input tokens**. The average cache read-equivalent is **0.32**, and caching is worthwhile under the modeled **$0.05/1M write overhead** with cached reads billed at **10%** of normal input price.

Measured impact: prompt caching saves about **$1.17/day** inside optimized inference.

### Extension 4 - Reasoning Budget

I added reasoning traffic accounting in M2 and surfaced it in the final report. Reasoning traffic is only **8.4% of requests** and **16.5% of tokens**, but it accounts for **16.5% of optimized inference cost** and **94.0% of inference energy** because reasoning requests use the lab's 80x energy multiplier.

Proposed routing rule: cap reasoning to **5% of traffic** for low-risk requests and route the rest through normal generation unless confidence or task complexity requires reasoning. Estimated savings: **$0.20/day** and **11,854 Wh/day**.

## 5. Recommendations for NimbusAI

1. Apply cascade routing, prompt caching, and batch API first because they reduce $/1M-token immediately and are easy to roll back.
2. Move interruptible workloads to spot with checkpointing, and move steady high-duty workloads to reserved capacity only after checking break-even utilization.
3. Track MFU/MBU and idle hours in the platform dashboard so teams optimize useful work, not misleading GPU-Util percentages.

