#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
docker build -f verification/Dockerfile -t nix-workshop-verifier:0.11.1-jvm21 .
echo "Hive verifier image nix-workshop-verifier:0.11.1-jvm21 is ready."
