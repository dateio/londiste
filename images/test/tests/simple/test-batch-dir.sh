#! /bin/bash

# Test whether SQL batch files are created and contain expected queries.
# Batch file directory is configured by batch_save_dir parameter.
# It may be configured by 3 different ways:
# - globaly in londiste.ini configuration (tested here)
# - database-wise through conf.sync_settings table (not tested here and not recommended to use)
# - per-table using "londiste add-table ...  --handler-arg=batch_save_dir=xxxx" (tested here)

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
batch_save_dir = $BATCH_SAVE_DIR/default
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
run sleep 3

msg "See topology"
run londiste $v conf/londiste_db1.ini status

msg "Run londiste daemon for each node"
for db in $db_list; do
  run psql -d $db -c "update pgq.queue set queue_ticker_idle_period='2 secs'"
  run londiste $v -d conf/londiste_$db.ini worker
done

msg "Create table on root node and fill couple of rows"
run psql -d db1 -c "create table taba (id serial primary key, data text)"
run psql -d db1 -c "create table tabb (id serial primary key, data text)"
for n in 1 2 3 4; do
  run psql -d db1 -c "insert into taba (data) values ('row$n')"
  run psql -d db1 -c "insert into tabb (data) values ('row$n')"
done

msg "Register table on root node"
run londiste $v conf/londiste_db1.ini add-table taba
run londiste $v conf/londiste_db1.ini add-table tabb 
run londiste $v conf/londiste_db1.ini add-seq taba_id_seq
run londiste $v conf/londiste_db1.ini add-seq tabb_id_seq

msg "Register table on other node with creation"
for db in db2; do
  run psql -d $db -c "create table taba (id serial primary key, data text)"
  run psql -d $db -c "create table tabb (id serial primary key, data text)"
  run londiste $v conf/londiste_$db.ini add-seq taba_id_seq
  run londiste $v conf/londiste_$db.ini add-seq tabb_id_seq
  run londiste $v conf/londiste_$db.ini add-table taba --handler=column_mapper
  run londiste $v conf/londiste_$db.ini add-table tabb --handler=column_mapper --handler-arg=batch_save_dir=$BATCH_SAVE_DIR/tabb

done

msg "Wait until tables are in sync on db2"

run londiste conf/londiste_db2.ini wait-sync

run londiste conf/londiste_db2.ini status

msg "Insert and update some data in both tables"
run psql -d db1 -f test-batch-dir.sql

msg "Wait until tables in sync and batch files are created"
run londiste conf/londiste_db2.ini wait-sync
run sleep 8 # long, because 3s not enough

msg "Check batch files"
DATA_TABA_LINES=$(cat $BATCH_SAVE_DIR/default/batch*/* | grep -c '')
DATA_TABB_LINES=$(cat $BATCH_SAVE_DIR/tabb/batch*/* | grep -c '')

if [[ $DATA_TABA_LINES -ne 4 ]]; then
    echo "Batch file for table 'taba' is not OK - unexpected line count: $DATA_TABA_LINES"
    exit 1
fi
if [[ $DATA_TABB_LINES -ne 4 ]]; then
    echo "Batch file for table 'tabb' is not OK - unexpected line count: $DATA_TABB_LINES"
    exit 1
fi

echo "OK"

exit 0
