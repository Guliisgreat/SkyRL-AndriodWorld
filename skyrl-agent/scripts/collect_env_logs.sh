#!/usr/bin/env bash
# Collect docker logs from all env* containers (env0, env1, ...) for host-network debugging.
# Usage: ./scripts/collect_env_logs.sh [ -o OUTPUT_DIR ]
# Default output dir: ./env_logs (under current dir)

set -e
OUTPUT_DIR="./env_logs"
while getopts "o:" opt; do
  case $opt in
    o) OUTPUT_DIR="$OPTARG" ;;
    *) echo "Usage: $0 [-o OUTPUT_DIR]" >&2; exit 1 ;;
  esac
done

mkdir -p "$OUTPUT_DIR"
echo "Collecting env* container logs into $OUTPUT_DIR"

for name in $(docker ps -a --format '{{.Names}}' | grep -E '^env[0-9]+$' | sort -V); do
  out="$OUTPUT_DIR/${name}.log"
  echo "  $name -> $out"
  docker logs "$name" 2>&1 > "$out" || true
done

echo "Done. Files: $(ls -la "$OUTPUT_DIR" 2>/dev/null | tail -n +2)"
