#!/usr/bin/env bash
set -euo pipefail
system=$(nix eval --impure --raw --expr builtins.currentSystem)
for output in environment release; do
  nix build ".#checks.$system.$output" --no-link
  nix build ".#checks.$system.$output" --no-link --rebuild
 done
