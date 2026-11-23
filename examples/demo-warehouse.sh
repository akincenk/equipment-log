#!/bin/sh
# Builds a made-up demo site: 14 pieces of equipment at a small distribution centre.
# Usage: sh examples/demo-warehouse.sh demo.db
set -eu
DB="${1:-demo.db}"
run() { equipment-log --db "$DB" "$@"; }

run init
run checklists "$(dirname "$0")/checklists.toml"

run add FL-01 "Counterbalance 1" forklift --location "Dock A"
run add FL-02 "Counterbalance 2" forklift --location "Dock A"
run add FL-03 "Reach truck 3" forklift --location "Dock B"
run add FL-04 "Reach truck 4" forklift --location "Aisles 10-20"
run add PJ-01 "Pallet jack 1" pallet-jack --location "Dock A"
run add PJ-02 "Pallet jack 2" pallet-jack --location "Dock B"
run add PJ-03 "Pallet jack 3" pallet-jack --location "Returns"
run add LD-01 "Rolling stair 1" ladder --location "Aisle 4"
run add LD-02 "Rolling stair 2" ladder --location "Aisle 9"
run add LD-03 "Step ladder 3" ladder --location "Office"
run add LD-04 "Rolling stair 4" ladder --location "Mezzanine"
run add SC-01 "Handheld scanner 1" scanner --location "Charging rack"
run add SC-02 "Handheld scanner 2" scanner --location "Charging rack"
run add SC-03 "Handheld scanner 3" scanner --location "Charging rack"

for fl in FL-01 FL-02 FL-03 FL-04; do
  run task "$fl" "Planned service (250 h, about 3 months)" --every 90 --last-done 2026-09-01
done
run task FL-01 "Thorough examination by a competent person" --every 365 --last-done 2025-11-18
run task FL-02 "Thorough examination by a competent person" --every 365 --last-done 2026-03-02
run task FL-03 "Thorough examination by a competent person" --every 365 --last-done 2026-06-15
run task FL-04 "Thorough examination by a competent person" --every 365
for ld in LD-01 LD-02 LD-03 LD-04; do
  run task "$ld" "Monthly ladder inspection" --every 30 --last-done 2026-10-28
done
for pj in PJ-01 PJ-02 PJ-03; do
  run task "$pj" "Grease wheels and check hydraulics" --every 180 --last-done 2026-06-01
done
