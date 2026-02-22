#!/usr/bin/env python3
"""
vLLM Contention Experiment

Design experiments to identify root causes of vLLM timing outliers:
1. Queueing behind long prefill batch
2. Same slow batch (processed together)
3. Expected contention behavior

Experiments:
-----------
A. Staggered Requests: Add delays between requests to eliminate queueing
B. Single Replica: Use 1 replica to isolate batch effects
C. Batch Size Analysis: Log which requests were batched together
D. Context Length Analysis: Correlate vLLM time with input token count

Usage:
    python vllm_contention_experiment.py --analyze-logs <timing_log_file>
    python vllm_contention_experiment.py --design-experiment
"""

import argparse
import re
from collections import defaultdict
from typing import List, Tuple, Dict


def analyze_timing_logs(log_file: str) -> None:
    """
    Analyze timing logs to identify patterns in vLLM outliers.
    
    Checks:
    1. Are outliers clustered in time? (suggests same batch)
    2. Are outliers at specific steps? (suggests context length)
    3. Distribution of times per replica
    """
    times_by_step: Dict[int, List[float]] = defaultdict(list)
    
    with open(log_file) as f:
        for line in f:
            match = re.search(r'step=(\d+) vLLM=([0-9.]+)s', line)
            if match:
                step = int(match.group(1))
                vllm_time = float(match.group(2))
                times_by_step[step].append(vllm_time)
    
    print("=" * 60)
    print("vLLM TIMING ANALYSIS")
    print("=" * 60)
    
    # Identify outliers (>3x median)
    all_times = []
    for times in times_by_step.values():
        all_times.extend(times)
    
    median_time = sorted(all_times)[len(all_times) // 2]
    outlier_threshold = median_time * 5  # 5x median is an outlier
    
    print(f"\nMedian vLLM time: {median_time:.2f}s")
    print(f"Outlier threshold (5x median): {outlier_threshold:.2f}s")
    
    # Find outliers and their steps
    outliers = []
    for step, times in times_by_step.items():
        for t in times:
            if t > outlier_threshold:
                outliers.append((step, t))
    
    print(f"\nOutliers found: {len(outliers)}")
    for step, t in sorted(outliers, key=lambda x: x[1], reverse=True):
        print(f"  Step {step}: {t:.2f}s")
    
    # Check if outliers are at same step (suggests context length)
    outlier_steps = [s for s, _ in outliers]
    if outlier_steps:
        from collections import Counter
        step_counts = Counter(outlier_steps)
        most_common_step = step_counts.most_common(1)[0]
        print(f"\nMost common outlier step: {most_common_step[0]} ({most_common_step[1]} occurrences)")
        
        if most_common_step[1] == len(outliers):
            print("  → All outliers at same step - likely CONTEXT LENGTH issue")
        else:
            print("  → Outliers at different steps - likely QUEUEING/CONTENTION issue")
    
    # Check time clustering (are outliers close in value?)
    if len(outliers) >= 2:
        outlier_times = [t for _, t in outliers]
        time_range = max(outlier_times) - min(outlier_times)
        avg_time = sum(outlier_times) / len(outlier_times)
        
        print(f"\nOutlier time range: {time_range:.2f}s")
        print(f"Outlier time average: {avg_time:.2f}s")
        
        if time_range < 2.0:  # All within 2s of each other
            print("  → Outliers have similar times - likely SAME BATCH")
        else:
            print("  → Outliers have varied times - likely INDEPENDENT DELAYS")


def design_experiment() -> None:
    """Print experiment design for identifying vLLM outlier root causes."""
    
    print("=" * 60)
    print("EXPERIMENT DESIGN: vLLM Outlier Root Cause Analysis")
    print("=" * 60)
    
    print("""
HYPOTHESIS 1: Queueing Behind Long Prefill
------------------------------------------
Root Cause: 16 agents → 8 replicas, some requests wait in queue
Evidence: 3 outliers at ~25s, while 13 others complete in ~1s

Experiment A: Staggered Requests
  Modify: Add 5s delay between each agent's step 2 request
  Expected: If queueing is the cause, outliers should disappear
  Command:
    # In verl_async_manager.py, add:
    # await asyncio.sleep(agent_id * 0.5)  # Stagger requests


HYPOTHESIS 2: Same Slow Batch
-----------------------------
Root Cause: 3 outliers were in same prefill batch, all waited for slowest
Evidence: All 3 outliers are ~25s (very similar times)

Experiment B: Single Replica Test
  Modify: Set tensor_parallel_size=8 (use all GPUs for 1 replica)
  Expected: All requests sequential, no batching effects
  Command:
    # In verl_android_inference.sh, add:
    # --rollout.tensor_parallel_size=8

Experiment C: Add Request Timestamps
  Modify: Log request start/end times with request_id
  Expected: Can see which requests overlapped
  Code:
    # In async_generate_ids():
    print(f"[vLLM] request_id={request_id} start={time.time():.3f}")
    result = await ...
    print(f"[vLLM] request_id={request_id} end={time.time():.3f} duration={duration:.2f}s")


HYPOTHESIS 3: Context Length Correlation
----------------------------------------
Root Cause: Longer contexts = longer prefill, some agents have more history
Evidence: All outliers at step 2 (first step with 2 images)

Experiment D: Log Token Counts
  Modify: Log input token count before inference
  Expected: Outliers have higher token counts
  Code:
    # In android_agent.py step():
    print(f"[Context] step={step} tokens={len(input_ids)}")


RECOMMENDED EXPERIMENT ORDER:
1. Run Experiment D first (low effort, high signal)
2. If D shows no correlation, run Experiment C
3. If C shows batching, run Experiment A to confirm
""")


def main():
    parser = argparse.ArgumentParser(description="vLLM contention experiment design")
    parser.add_argument("--analyze-logs", type=str, help="Analyze timing logs from a file")
    parser.add_argument("--design-experiment", action="store_true", help="Print experiment design")
    
    args = parser.parse_args()
    
    if args.analyze_logs:
        analyze_timing_logs(args.analyze_logs)
    elif args.design_experiment:
        design_experiment()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
