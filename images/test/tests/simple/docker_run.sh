#! /bin/bash

set -e
set -x

cd simple

# run all simple tests
./_run_all.sh

# run single test - for debug purposes only:
#./test-filter.sh
#./test-batch-dir.sh
#./test-sync.sh
#./test-fkey.sh

# wait forever
tail -f /dev/null
