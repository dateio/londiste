#! /bin/bash

# Test sync on two tables joined together by foreign key on mytable_rows.main_id.
# Verify FK is respected and preserved when doing basic sync operations like modificatins, resync and so on.

source ../testlib.sh

../zstop.sh

source ./init.sh

v='-q'
v=''
nocheck=1

db_list="db1 db2"

kdb_list=`echo $db_list | sed 's/ /,/g'`

#( cd ../..; make -s install )

do_check() {
  test $nocheck = 1 || ../zcheck.sh
}

title Fkey test

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

run psql -d db1 -c "create table mytable_rows (id serial primary key, main_id int4 references mytable, extra text)"
for n in 1 2 3 4; do
  run psql -d db1 -c "insert into mytable_rows (main_id, extra) values (1, 'row$n')"
done

msg "Register table on root node"
run londiste $v conf/londiste_db1.ini add-table mytable
run londiste $v conf/londiste_db1.ini add-seq mytable_id_seq
run londiste $v conf/londiste_db1.ini add-table mytable_rows
run londiste $v conf/londiste_db1.ini add-seq mytable_rows_id_seq

msg "Register table on other node with creation"
for db in db2; do
  run psql -d $db -c "create table mytable (id serial primary key, data text)"
  run psql -d $db -c "create table mytable_rows (id serial primary key, main_id int4 references mytable, extra text)"
  run londiste $v conf/londiste_$db.ini add-seq mytable_id_seq
  run londiste $v conf/londiste_$db.ini add-seq mytable_rows_id_seq
  run londiste $v conf/londiste_$db.ini add-table mytable
  run londiste $v conf/londiste_$db.ini add-table mytable_rows
done

msg "Wait until tables are in sync on db2"

run londiste conf/londiste_db2.ini wait-sync

run londiste conf/londiste_db2.ini status

run sleep 3

msg "Check FK exists"

ROW_COUNT=$(psql -qtAX -d db2 -c "SELECT count(1) FROM information_schema.table_constraints where table_name='mytable_rows' and constraint_name='mytable_rows_main_id_fkey'")

echo "$ROW_COUNT"

if [[ $ROW_COUNT -ne 1 ]]; then
    echo "FK not exists!"
    exit 1
fi

# Resync mytable (which is referenced by FK)
run londiste conf/londiste_db2.ini resync mytable
run londiste conf/londiste_db2.ini wait-sync
run sleep 3

msg "Check FK still exists"

ROW_COUNT=$(psql -qtAX -d db2 -c "SELECT count(1) FROM information_schema.table_constraints where table_name='mytable_rows' and constraint_name='mytable_rows_main_id_fkey'")
if [[ $ROW_COUNT -ne 1 ]]; then
    echo "FK not exists!"
    exit 1
fi

msg "Verify FK blocks deletion in mytable"

psql -d db2 -c 'delete from mytable where id=1' || EXIT_CODE=$?
if [[ $EXIT_CODE -ne 1 ]]; then
    echo "Deletion not blocked by FK, that's wrong!"
    exit 1
fi
echo "Delete successfully blocked."

echo
echo "Everything is OK"

exit 0
