#!/usr/bin/env python3
"""
Measure vLLM inference vs Android step timing from log analysis.

This script analyzes the log file to estimate step timing by correlating
timestamps from health check logs with step counts.

Usage:
    python scripts/measure_step_timing.py <log_file>
"""

import sys
import re
from datetime import datetime
from collections import defaultdict


def parse_timestamp(line: str) -> datetime | None:
    """Extract timestamp from log line like '2026-01-29 09:32:41.963'"""
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})', line)
    if match:
        return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S.%f')
    return None


def parse_step(line: str) -> tuple[int, str] | None:
    """Extract step number and instance from '[AndroidAgent Step X] instance=Y'"""
    match = re.search(r'\[AndroidAgent Step (\d+)\] instance=(\S+)', line)
    if match:
        return int(match.group(1)), match.group(2)
    return None


def analyze_log(log_file: str):
    """Analyze log file to extract timing information."""
    
    # Track timestamps and steps
    timestamps = []
    steps_by_instance = defaultdict(list)
    total_steps = 0
    
    # Key events
    inference_start = None
    inference_end = None
    
    with open(log_file, 'r') as f:
        for line in f:
            # Track health check timestamps (every ~30s)
            if 'Pool Status' in line:
                ts = parse_timestamp(line)
                if ts:
                    timestamps.append(ts)
            
            # Track inference start
            if 'Starting async_fix' in line or 'async_fix_pool_retry dispatch' in line:
                ts = parse_timestamp(line)
                if ts:
                    inference_start = ts
            
            # Track inference end
            if 'Rollout metrics' in line:
                ts = parse_timestamp(line)
                if ts:
                    inference_end = ts
                # Extract avg turns
                match = re.search(r"'avg_turn_assistant': ([\d.]+)", line)
                if match:
                    avg_turns = float(match.group(1))
            
            # Track steps
            step_info = parse_step(line)
            if step_info:
                step_num, instance = step_info
                steps_by_instance[instance].append(step_num)
                total_steps += 1
    
    # Calculate timing
    print("=" * 60)
    print("TIMING ANALYSIS")
    print("=" * 60)
    
    if inference_start and inference_end:
        duration = (inference_end - inference_start).total_seconds()
        print(f"\nInference Duration: {duration:.1f} seconds ({duration/60:.1f} min)")
    else:
        print("\nCould not determine inference duration")
        duration = None
    
    print(f"\nTotal Steps Logged: {total_steps}")
    print(f"Instances: {len(steps_by_instance)}")
    
    # Steps per instance
    print("\nSteps per Instance:")
    max_steps = 0
    for instance, steps in sorted(steps_by_instance.items()):
        max_step = max(steps) if steps else 0
        max_steps = max(max_steps, max_step)
        print(f"  {instance}: {max_step} steps")
    
    avg_steps = sum(max(s) for s in steps_by_instance.values()) / len(steps_by_instance) if steps_by_instance else 0
    print(f"\nAverage Steps per Instance: {avg_steps:.1f}")
    
    if duration and steps_by_instance:
        # Method 1: Total duration / avg steps (assuming parallel execution)
        time_per_step = duration / avg_steps
        print(f"\n--- Timing Estimate (assuming parallel execution) ---")
        print(f"Time per Step: {time_per_step:.1f} seconds")
        print(f"  = vLLM inference + Android step execution")
        
        # Known: Android step is ~5s
        android_step = 5.0
        vllm_estimate = time_per_step - android_step
        print(f"\nIf Android step ≈ 5s:")
        print(f"  vLLM inference ≈ {vllm_estimate:.1f} seconds")
    
    # Analyze Pool Status intervals
    if len(timestamps) >= 2:
        print(f"\n--- Health Check Intervals ---")
        intervals = [(timestamps[i+1] - timestamps[i]).total_seconds() 
                    for i in range(len(timestamps)-1)]
        print(f"Number of health checks: {len(timestamps)}")
        print(f"Average interval: {sum(intervals)/len(intervals):.1f}s")
        print(f"Min/Max interval: {min(intervals):.1f}s / {max(intervals):.1f}s")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <log_file>")
        sys.exit(1)
    
    analyze_log(sys.argv[1])
