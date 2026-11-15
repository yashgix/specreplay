#!/bin/sh
# Usage: holdout_sources.sh DEST. Clones the public repository and exports src/ of each hold-out commit into DEST/<commit>/src.
set -eu
dest=$1
git clone --quiet https://github.com/AgentPhone-AI/agentphone-mcp "$dest/repo"
for ref in f86348c^ f86348c f5eb834^ f5eb834 1921eba abfac0b; do
  name=$(git -C "$dest/repo" rev-parse --short "$ref")
  mkdir -p "$dest/$name"
  git -C "$dest/repo" archive "$ref" src | tar -x -C "$dest/$name"
done
