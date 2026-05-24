#!/bin/bash
# Wait for SP1 sw run to finish, then launch SP2-SP7

echo "Waiting for SP1 to complete..."
while [ -f ".claude/.workflow.lock" ]; do
    sleep 30
done
echo "SP1 complete. Adding SP2-SP7 milestones..."

python continue_sp2_sp7.py
git add .claude/workflow.json
git commit -m "chore: add SP2-SP7 milestones for full feature run"

echo "Launching sw run for SP2-SP7..."
sw run
