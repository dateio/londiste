#! /bin/bash

set -e
set -x

#cd simple

./test-pgq.sh
./test-sync.sh
./test-fkey.sh
./test-filter.sh
./test-batch-dir.sh
