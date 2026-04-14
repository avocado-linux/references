#!/usr/bin/env bash

set -e

echo "Cleaning Elixir build artifacts..."
cd ref-elixir

# Mix compile output (includes platform-pinned esbuild/tailwind binaries
# and compiled BEAM files tied to a specific ERTS).
rm -rf _build

# Fetched Mix dependencies (some contain native NIFs).
rm -rf deps

# npm packages pulled by `mix assets.setup`.
rm -rf assets/node_modules

# Digested static assets produced by `mix assets.deploy`.
rm -rf priv/static/assets

echo "Clean complete"
