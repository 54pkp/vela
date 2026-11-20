#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Build the opt-in 4.1.2 Lite K2 shader with the provider's normal shader passes.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
output=${1:-"$source_dir/out/fsr412lite-k2-shared-taps.hpp"}
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
module="k2_shared_taps_${scratch##*.}"
export TOOLS="$source_dir/tools"
export WEIGHTS="$source_dir/../sr4-kernels/tools/weights.bin"
python3 -I "$source_dir/lite/share_k2_taps.py" "$source_dir/lite/k2cl.comp" "$scratch/k2.comp"
COMP="$scratch/k2.comp" MOD="$module" ENTRY=fsr4_model_v07_fp8_no_scale_postpass OUT="$scratch" \
    bash "$TOOLS/p.sh"
mkdir -p -- "$(dirname -- "$output")"
python3 -I "$TOOLS/gen_amd_hpp.py" lite-k2-taps "$output" "$scratch/$module.spv"
