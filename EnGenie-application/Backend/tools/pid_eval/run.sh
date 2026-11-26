#!/bin/bash
# Live digitisation of each drawing, one after another (BROWNFIELD_* env settings pass through):
#   bash tools/pid_eval/run.sh pid13 pid15      -> tools/pid_eval/runs/<pid>_analysis.json
D="$(cd "$(dirname "$0")" && pwd)"
cd "$D/../.."
for n in "$@"; do
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "$D/live_any.py" $n > "$D/runs/$n.log" 2>&1
  grep -E "^$n" "$D/runs/$n.log" | cut -c1-200
done
