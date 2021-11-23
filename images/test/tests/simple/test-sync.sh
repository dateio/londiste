#! /bin/bash

# Test simple sync on single table.
# Just verify the data from root-node are properly syncing to leaf-node.

source ../testlib.sh

../zstop.sh

source ./init.sh

v='-q'
v=''
nocheck=1

db_list="db1 db2"

kdb_list=`echo $db_list | sed 's/ /,/g'`

do_check() {
  test $nocheck = 1 || ../zcheck.sh
}

title Sync test

# create ticker conf
cat > conf/pgqd.ini <<EOF
[pgqd]
database_list = $kdb_list
logfile = log/pgqd.log
pidfile = pid/pgqd.pid
EOF

# londiste configs
for db in $db_list; do
cat > conf/londiste_$db.ini <<EOF
[londiste]
job_name = londiste_$db
db = dbname=$db
queue_name = replika
logfile = $LOG_DIR/%(job_name)s.log
pidfile = pid/%(job_name)s.pid
batch_save_dir = $BATCH_SAVE_DIR

pgq_autocommit = 1
pgq_lazy_fetch = 0
EOF
done

for db in $db_list; do
  cleardb $db
done

clearlogs

set -e

msg "Basic config"
run cat conf/pgqd.ini
run cat conf/londiste_db1.ini

msg "Install londiste and initialize nodes"
run londiste $v conf/londiste_db1.ini create-root node1 'dbname=db1'
run londiste $v conf/londiste_db2.ini create-leaf node2 'dbname=db2' --provider='dbname=db1'

msg "Run ticker"
run pgqd $v -d conf/pgqd.ini
run sleep 5

msg "See topology"
run londiste $v conf/londiste_db1.ini status

msg "Run londiste daemon for each node"
for db in $db_list; do
  run psql -d $db -c "update pgq.queue set queue_ticker_idle_period='2 secs'"
  run londiste $v -d conf/londiste_$db.ini worker
done

msg "Create table on root node and fill couple of rows"
run psql -d db1 -c "create table mytable (id serial primary key, data text)"
for n in 1 2 3 4; do
  run psql -d db1 -c "insert into mytable (data) values ('row$n')"
done

msg "Register table on root node"
run londiste $v conf/londiste_db1.ini add-table mytable
run londiste $v conf/londiste_db1.ini add-seq mytable_id_seq

msg "Register table on other node with creation"
for db in db2; do
  run psql -d $db -c "create table mytable (id serial primary key, data text)"
  run londiste $v conf/londiste_$db.ini add-seq mytable_id_seq
  run londiste $v conf/londiste_$db.ini add-table mytable
done

msg "Wait until tables are in sync on db3"

run londiste conf/londiste_db2.ini wait-sync

run londiste conf/londiste_db2.ini status

msg "Check the data in db2"

ROW_COUNT=$(psql -qtAX -d db2 -c 'select count(1) from mytable')
if [[ $ROW_COUNT -ne 4 ]]; then
    echo "Unexpected number of lines in mytable: $ROW_COUNT"
    exit 1
fi
echo "OK"

msg "Check db2 afer insert/update/delete in db1"

psql -d db1 -f test-sync.sql

run londiste conf/londiste_db2.ini wait-sync
run sleep 3

ROW_COUNT=$(psql -qtAX -d db2 -c 'select count(1) from mytable')
if [[ $ROW_COUNT -ne 5 ]]; then
    echo "Unexpected number of lines in mytable: $ROW_COUNT"
    exit 1
fi

ROW_COUNT=$(psql -qtAX -d db2 -c "select count(1) from mytable where data='kokos'")
if [[ $ROW_COUNT -ne 1 ]]; then
    echo "Record 'kokos' not found!"
    exit 1
fi

echo "OK"

exit 0
