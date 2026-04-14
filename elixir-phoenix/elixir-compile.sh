#!/usr/bin/env bash

set -e

echo "Compiling Elixir application"
cd ref-elixir
export MIX_ENV=prod
export MIX_TARGET_INCLUDE_ERTS=false
mix deps.get
mix assets.setup
mix compile
mix assets.deploy
mix release --overwrite
