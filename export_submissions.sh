#!/bin/bash

# Export GitHub PR submissions to CSV, sorted by title (descending)
# Usage: ./export_submissions.sh

set -e

REPO="getzep/context-engineering-contest"
OUTPUT_FILE="submissions.csv"

echo "Fetching open PRs from $REPO..."

# Fetch all open PRs, extract title and URL, sort by title descending, format as CSV
echo "PR Title,PR Link,Branch" > "$OUTPUT_FILE"

gh pr list \
    --repo "$REPO" \
    --state open \
    --limit 1000 \
    --json title,url,headRefName \
    --jq '.[] | [.title, .url, .headRefName] | @csv' \
    | sort -r \
    >> "$OUTPUT_FILE"

PR_COUNT=$(tail -n +2 "$OUTPUT_FILE" | wc -l | tr -d ' ')

echo "Done! Exported $PR_COUNT PRs to $OUTPUT_FILE (sorted by title descending)"
