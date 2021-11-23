#! /bin/sh

# common configuration
BATCH_SAVE_DIR=batches
LOG_DIR=log

# recreate dbs
lst="db1 db2 db3 db4 db5"
for db in $lst; do
  echo dropdb $db
  dropdb --if-exists $db
done
for db in $lst; do
  echo createdb $db
  createdb $db
done

# clean data batch dir
echo "clean batch dir: $BATCH_SAVE_DIR"
rm -rf $BATCH_SAVE_DIR

# print currently running test name
echo "$0" > $LOG_DIR/current_test.txt
