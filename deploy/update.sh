#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

git pull --ff-only origin main
docker compose up -d --build
docker compose ps
