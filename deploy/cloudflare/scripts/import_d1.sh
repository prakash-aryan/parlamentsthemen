#!/bin/bash
cd "$(dirname "$0")/../worker"
D=${1:?usage: import_d1.sh <folder with .sql files>}
DONE=$D/.done
touch $DONE
for f in $(find "$D" -name '*.sql' | sort); do
  b=$(basename $f)
  grep -qx "$b" $DONE && continue
  for i in 1 2 3 4; do
    npx wrangler d1 execute parlamentsthemen --remote --yes --file $f > $D/.last.log 2>&1 && { echo $b >> $DONE; echo "$(date +%T) $b ok"; break; }
    echo "$(date +%T) $b failed try $i: $(grep -m1 -i error $D/.last.log)"; sleep 20
  done
  grep -qx "$b" $DONE || { echo "IMPORT_STOPPED at $b"; exit 1; }
done
echo IMPORT_DONE
