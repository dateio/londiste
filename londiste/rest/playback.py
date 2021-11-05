#! /usr/bin/env python

"""Basic replication core."""
import json
import os
import sys
import tempfile
import time

import skytools
from londiste.exec_attrs import ExecAttrs
from londiste.handler import *
from londiste.playback import *
from londiste.rest.rest import Rest
from pgq.cascade.worker import CascadedWorker

__all__ = ['ReplicatorRest']

class ReplicatorRest(Replicator):
    """Replication core for REST API.
    """

    def __init__(self, args):
        """Replication init."""

        Replicator.__init__(self, args)

        self.work_dir = None


    def process_remote_batch(self, src_db, tick_id, ev_list, dst_db):
        "All work for a batch.  Entry point from SetConsumer."

        self.current_event = None

        # this part can play freely with transactions

        if not self.code_check_done:
            self.check_code(dst_db)
            self.code_check_done = 1

        self.sync_database_encodings(src_db, dst_db)

        self.cur_tick = self.batch_info['tick_id']
        self.prev_tick = self.batch_info['prev_tick_id']

        self.work_dir = self.cf.get('rest_work_dir')
        if not os.path.isdir(self.work_dir):
            work_dir = tempfile.gettempdir()

        dst_curs = dst_db.cursor()
        self.load_table_state(dst_curs)
        self.sync_tables(src_db, dst_db)

        self.copy_snapshot_cleanup(dst_db)

        # only main thread is allowed to restore fkeys
        if not self.copy_thread:
            self.restore_fkeys(dst_db)

        for p in self.used_plugins.values():
            p.reset()
        self.used_plugins = {}

        # now the actual event processing happens.
        # they must be done all in one tx in dst side
        # and the transaction must be kept open so that
        # the cascade-consumer can save last tick and commit.

        # TODO: tady by se dalo filtrovat ev_list na masteru pomoci SQL na src_db.cursor(),
        # muselo by se ale nacist rovnou vsechny udalosti do pameti a rozdelit po tabulkach,
        # ke kterym mame v event_filter_config filtrovaci SQL.
        # Zatim filtrujeme pythonem pomoci eval().

        with open(os.path.join(self.work_dir, 'batch_'+str(tick_id)), 'w') as batch_json_file:
            self.batch_json_file = batch_json_file
            self.batch_event_count = 0
            CascadedWorker.process_remote_batch(self, src_db, tick_id, ev_list, dst_db)

            # send all the data to the REST API
            # - this is an irreversible operation!
            # - if any error occurs after this, we have a serious problem -> manual recovery needed
            self.send_data()
        #     TODO: ve finally mazat batch_json_file, nebo nechat lezet, pokud to bude nastavene v konfiguraci

        if os.stat(batch_json_file.name).st_size == 0:
            os.remove(batch_json_file.name)

        for p in self.used_plugins.values():
            p.finish_batch(self.batch_info, dst_curs)
        self.used_plugins = {}

        # finalize table changes
        self.save_table_state(dst_curs)

        # store event filter
        # local_only is usually set to false, so the filter is not used at all
        if self.cf.getboolean('local_only', False):            
            # create list of tables
            if self.copy_thread:
                _filterlist = skytools.quote_literal(self.copy_table_name)
            else:
                _filterlist = ','.join(map(skytools.quote_literal, self.table_map.keys()))

            # build filter
            meta = "(ev_type like 'pgq.%' or ev_type like 'londiste.%')"
            if _filterlist:
                self.consumer_filter = "(%s or (ev_extra1 in (%s)))" % (meta, _filterlist)
            else:
                self.consumer_filter = meta
        else:
            # no filter
            self.consumer_filter = None

    def sync_tables(self, src_db, dst_db):
        """Table sync loop.

        Calls appropriate handles, which is expected to
        return one of SYNC_* constants."""

        self.log.debug('Sync tables')

        while 1:
            cnt = Counter(self.table_list)
            if self.copy_thread:
                res = self.sync_from_copy_thread(cnt, src_db, dst_db)
            else:
                res = self.sync_from_main_thread(cnt, src_db, dst_db)

            if res == SYNC_EXIT:
                self.log.debug('Sync tables: exit')
                if self.copy_thread:
                    self.unregister_consumer()
                src_db.commit()
                sys.exit(0)
            elif res == SYNC_OK:
                return
            elif res != SYNC_LOOP:
                raise Exception('Program error')

            self.log.debug('Sync tables: sleeping')
            time.sleep(3)
            dst_db.commit()
            self.load_table_state(dst_db.cursor())
            dst_db.commit()

    dsync_backup = None
    def sync_from_main_thread(self, cnt, src_db, dst_db):
        "Main thread sync logic."

        # This operates on all table, any amount can be in any state

        ret = SYNC_OK

        if cnt.do_sync:
            # wait for copy thread to catch up
            ret = SYNC_LOOP

        # we need to do wanna-sync->do_sync with small batches
        need_dsync = False
        dsync_ok = True
        if self.pgq_min_interval or self.pgq_min_count:
            dsync_ok = False
        elif self.dsync_backup and self.dsync_backup[0] >= self.cur_tick:
            dsync_ok = False

        # now check if do-sync is needed
        for t in self.get_tables_in_state(TABLE_WANNA_SYNC):
            # copy thread wants sync, if not behind, do it
            if self.cur_tick >= t.sync_tick_id:
                if dsync_ok:
                    self.change_table_state(dst_db, t, TABLE_DO_SYNC, self.cur_tick)
                    ret = SYNC_LOOP
                else:
                    need_dsync = True

        # tune batch size if needed
        if need_dsync:
            if self.pgq_min_count or self.pgq_min_interval:
                bak = (self.cur_tick, self.pgq_min_count, self.pgq_min_interval)
                self.dsync_backup = bak
                self.pgq_min_count = None
                self.pgq_min_interval = None
        elif self.dsync_backup:
            self.pgq_min_count = self.dsync_backup[1]
            self.pgq_min_interval = self.dsync_backup[2]
            self.dsync_backup = None

        # now handle new copies
        npossible = self.parallel_copies - cnt.get_copy_count()
        if cnt.missing and npossible > 0:
            pmap = self.get_state_map(src_db.cursor())
            src_db.commit()
            for t in self.get_tables_in_state(TABLE_MISSING):
                if 'copy_node' in t.table_attrs:
                    # should we go and check this node?
                    pass
                else:
                    # regular provider is used
                    if t.name not in pmap:
                        self.log.warning("Table %s not available on provider", t.name)
                        continue
                    pt = pmap[t.name]
                    if pt.state != TABLE_OK: # or pt.custom_snapshot: # FIXME: does snapsnot matter?
                        self.log.info("Table %s not OK on provider, waiting", t.name)
                        continue

                # don't allow more copies than configured
                if npossible == 0:
                    break
                npossible -= 1

                # drop all foreign keys to and from this table
                self.drop_fkeys(dst_db, t.dest_table)

                # change state after fkeys are dropped thus allowing
                # failure inbetween
                self.change_table_state(dst_db, t, TABLE_IN_COPY)

                # the copy _may_ happen immediately
                self.launch_copy(t)

                # there cannot be interesting events in current batch
                # but maybe there's several tables, lets do them in one go
                ret = SYNC_LOOP

        return ret

    def sync_from_copy_thread(self, cnt, src_db, dst_db):
        "Copy thread sync logic."

        # somebody may have done remove-table in the meantime
        if self.copy_table_name not in self.table_map:
            self.log.error("copy_sync: lost table: %s", self.copy_table_name)
            return SYNC_EXIT

        # This operates on single table
        t = self.table_map[self.copy_table_name]

        if t.state == TABLE_DO_SYNC:
            # these settings may cause copy to miss right tick
            self.pgq_min_count = None
            self.pgq_min_interval = None

            # main thread is waiting, catch up, then handle over
            if self.cur_tick == t.sync_tick_id:
                self.change_table_state(dst_db, t, TABLE_OK)
                return SYNC_EXIT
            elif self.cur_tick < t.sync_tick_id:
                return SYNC_OK
            else:
                self.log.error("copy_sync: cur_tick=%d sync_tick=%d",
                                self.cur_tick, t.sync_tick_id)
                raise Exception('Invalid table state')
        elif t.state == TABLE_WANNA_SYNC:
            # wait for main thread to react
            return SYNC_LOOP
        elif t.state == TABLE_CATCHING_UP:

            # partition merging
            if t.copy_role in ('wait-replay', 'lead'):
                return SYNC_LOOP

            # copy just finished
            if t.dropped_ddl:
                self.restore_copy_ddl(t, dst_db)
                return SYNC_OK

            # is there more work?
            if self.work_state:
                return SYNC_OK

            # seems we have catched up
            self.change_table_state(dst_db, t, TABLE_WANNA_SYNC, self.cur_tick)
            return SYNC_LOOP
        elif t.state == TABLE_IN_COPY:
            # table is not copied yet, do it
            self.do_copy(t, src_db, dst_db)

            # forget previous value
            self.work_state = 1

            return SYNC_LOOP
        else:
            # nothing to do
            return SYNC_EXIT

    def restore_copy_ddl(self, ts, dst_db):
        self.log.info("%s: restoring DDL", ts.name)
        dst_curs = dst_db.cursor()
        for ddl in skytools.parse_statements(ts.dropped_ddl):
            self.log.info(ddl)
            dst_curs.execute(ddl)
        q = "select * from londiste.local_set_table_struct(%s, %s, NULL)"
        self.exec_cmd(dst_curs, q, [self.queue_name, ts.name])
        ts.dropped_ddl = None
        dst_db.commit()

        # analyze
        self.log.info("%s: analyze", ts.name)
        dst_curs.execute("analyze " + skytools.quote_fqident(ts.name))
        dst_db.commit()


    def do_copy(self, tbl, src_db, dst_db):
        """Callback for actual copy implementation."""
        raise Exception('do_copy not implemented')

    def process_remote_event(self, src_curs, dst_curs, ev):
        """handle one event"""

        self.log.debug("New event: id=%s / type=%s / data=%s / extra1=%s", ev.id, ev.type, ev.data, ev.extra1)
        
        # set current_event only if processing them one-by-one
        if self.work_state < 0:
            self.current_event = ev

        if ev.type in ('I', 'U', 'D'):
            self.handle_data_event(ev, src_curs, dst_curs)
        elif ev.type[:2] in ('I:', 'U:', 'D:'):
            self.handle_data_event(ev, src_curs, dst_curs)
        elif ev.type == "R":
            self.handle_truncate_event(ev, src_curs, dst_curs)
        elif ev.type == 'EXECUTE':
            self.handle_execute_event(ev, dst_curs)
        elif ev.type == 'londiste.add-table':
            self.add_set_table(dst_curs, ev.data)
        elif ev.type == 'londiste.remove-table':
            self.remove_set_table(dst_curs, ev.data)
        elif ev.type == 'londiste.remove-seq':
            # NOT IMPLEMENTED
            pass
        elif ev.type == 'londiste.update-seq':
            # NOT IMPLEMENTED
            pass
        else:
            CascadedWorker.process_remote_event(self, src_curs, dst_curs, ev)

        # no point keeping it around longer
        self.current_event = None

    def handle_data_event(self, ev, src_curs, dst_curs):
        self.handle_data_event_filter(ev, src_curs, dst_curs, self.apply_data)


    def handle_truncate_event(self, ev, src_curs, dst_curs):
        """handle one truncate event"""
        table_name = ev.extra1
        t = self.get_table_by_name(table_name)
        if not t or not t.interesting(ev, self.cur_tick, self.copy_thread, self.copy_table_name):
            self.stat_increase('ignored_events')
            return

        fqname = skytools.quote_fqident(t.dest_table)

        if table_name in self.used_plugins:
            p = self.used_plugins[table_name]
        else:
            p = t.get_plugin()
            self.used_plugins[table_name] = p
            p.prepare_batch(self.batch_info, src_curs, dst_curs)

        if p.conf.get('ignore_truncate'):
            self.log.info("ignoring truncate for %s", fqname)
            return

        data = {"table": fqname, "op": "R"}

        self.apply_data(data)

    def handle_execute_event(self, ev, dst_curs):
        """handle one EXECUTE event"""

        if self.copy_thread:
            return

        # parse event
        fname = ev.extra1
        s_attrs = ev.extra2
        exec_attrs = ExecAttrs(urlenc = s_attrs)
        sql = ev.data

        # fixme: curs?
        pgver = dst_curs.connection.server_version
        if pgver >= 80300:
            dst_curs.execute("set local session_replication_role = 'local'")

        seq_map = {}
        q = "select seq_name, local from londiste.get_seq_list(%s) where local"
        dst_curs.execute(q, [self.queue_name])
        for row in dst_curs.fetchall():
            seq_map[row['seq_name']] = row['seq_name']

        tbl_map = {}
        for tbl, t in self.table_map.items():
            tbl_map[t.name] = t.dest_table

        q = "select * from londiste.execute_start(%s, %s, %s, false, %s)"
        res = self.exec_cmd(dst_curs, q, [self.queue_name, fname, sql, s_attrs], commit = False)
        ret = res[0]['ret_code']
        if ret > 200:
            self.log.info("Skipping execution of '%s'", fname)
            if pgver >= 80300:
                dst_curs.execute("set local session_replication_role = 'replica'")
            return

        if exec_attrs.need_execute(dst_curs, tbl_map, seq_map):
            self.log.info("%s: executing sql")
            xsql = exec_attrs.process_sql(sql, tbl_map, seq_map)
            for stmt in skytools.parse_statements(xsql):
                dst_curs.execute(stmt)
        else:
            self.log.info("%s: execution not needed on this node")

        q = "select * from londiste.execute_finish(%s, %s)"
        self.exec_cmd(dst_curs, q, [self.queue_name, fname], commit = False)
        if pgver >= 80300:
            dst_curs.execute("set local session_replication_role = 'replica'")

    def apply_data(self, data):
        # REST API: cannot use batch limit - we need to send the whole batch in one API call

        if self.batch_json_file is not None:
            if self.batch_event_count == 0:
                self.batch_json_file.write('{"blocks": [\n')
            else:
                self.batch_json_file.write(',\n')
            self.batch_json_file.write(json.dumps(data))
            self.batch_event_count += 1

    def send_data(self):
        """Send all buffered data to REST API."""

        if self.batch_event_count == 0:
            return

        self.batch_json_file.write('\n]}')
        self.batch_json_file.close()
        self.log.info("Sending data to REST API from %s (%d events)", os.path.realpath(self.batch_json_file.name), self.batch_event_count)

        rest = Rest(self.cf)
        rest.call_api('sync', os.path.realpath(self.batch_json_file.name))

    def add_set_table(self, dst_curs, tbl):
        """There was new table added to root, remember it."""

        q = "select londiste.global_add_table(%s, %s)"
        dst_curs.execute(q, [self.set_name, tbl])

    def remove_set_table(self, dst_curs, tbl):
        """There was table dropped from root, remember it."""
        if tbl in self.table_map:
            t = self.table_map[tbl]
            del self.table_map[tbl]
            self.table_list.remove(t)
        q = "select londiste.global_remove_table(%s, %s)"
        dst_curs.execute(q, [self.set_name, tbl])

    def remove_set_seq(self, dst_curs, seq):
        """There was seq dropped from root, remember it."""

        q = "select londiste.global_remove_seq(%s, %s)"
        dst_curs.execute(q, [self.set_name, seq])


    def get_state_map(self, curs):
        """Get dict of table states."""

        q = "select * from londiste.get_table_list(%s)"
        curs.execute(q, [self.set_name])

        new_map = {}
        for row in curs.fetchall():
            if not row['local']:
                continue
            t = TableState(row['table_name'], self.log)
            t.loaded_state(row)
            new_map[t.name] = t
        return new_map

    def save_table_state(self, curs):
        """Store changed table state in database."""

        for t in self.table_list:
            # backwards compat: move plugin-only dest_table to table_info
            if t.dest_table != t.plugin.dest_table:
                self.log.info("Overwriting .dest_table from plugin: tbl=%s  dst=%s",
                              t.name, t.plugin.dest_table)
                q = "update londiste.table_info set dest_table = %s"\
                    " where queue_name = %s and table_name = %s"
                curs.execute(q, [t.plugin.dest_table, self.set_name, t.name])

            if not t.changed:
                continue
            merge_state = t.render_state()
            self.log.info("storing state of %s: copy:%d new_state:%s",
                            t.name, self.copy_thread, merge_state)
            q = "select londiste.local_set_table_state(%s, %s, %s, %s)"
            curs.execute(q, [self.set_name,
                             t.name, t.str_snapshot, merge_state])
            t.changed = 0

    def change_table_state(self, dst_db, tbl, state, tick_id = None):
        """Chage state for table."""

        tbl.change_state(state, tick_id)
        self.save_table_state(dst_db.cursor())
        dst_db.commit()

        self.log.info("Table %s status changed to '%s'",
                      tbl.name, tbl.render_state())

    def get_tables_in_state(self, state):
        "get all tables with specific state"

        for t in self.table_list:
            if t.state == state:
                yield t

    def get_table_by_name(self, name):
        """Returns cached state object."""
        if name.find('.') < 0:
            name = "public.%s" % name
        if name in self.table_map:
            return self.table_map[name]
        return None

    def launch_copy(self, tbl_stat):
        """Run parallel worker for copy."""
        self.log.info("Launching copy process REST")
        script = sys.argv[0]
        conf = self.cf.filename
        cmd = [script, conf, 'copy-rest', tbl_stat.name]

        self.log.info("CMD" + str(cmd))

        # pass same verbosity options as main script got
        if self.options.quiet:
            cmd.append('-q')
        if self.options.verbose:
            cmd += ['-v'] * self.options.verbose

        # let existing copy finish and clean its pidfile,
        # otherwise new copy will exit immediately.
        # FIXME: should not happen on per-table pidfile ???
        copy_pidfile = "%s.copy.%s" % (self.pidfile, tbl_stat.name)
        while skytools.signal_pidfile(copy_pidfile, 0):
            self.log.warning("Waiting for existing copy to exit")
            time.sleep(2)

        # launch and wait for daemonization result
        self.log.debug("Launch args: %r", cmd)
        if os.name == 'nt':
            cmd.insert(0, '-c')
            # FIXME: launch the command in the same process at least for debug?
            res = os.spawnv(os.P_WAIT, "python.exe", cmd)
        else:
            cmd.append('-d')
            res = os.spawnv(os.P_WAIT, script, cmd)
        self.log.debug("Launch result: %r", res)
        if res != 0:
            self.log.error("Failed to launch copy process, result=%d", res)

    def sync_database_encodings(self, src_db, dst_db):
        """Make sure client_encoding is same on both side."""

        try:
            # psycopg2
            if src_db.encoding != dst_db.encoding:
                dst_db.set_client_encoding(src_db.encoding)
        except AttributeError:
            # psycopg1
            src_curs = src_db.cursor()
            dst_curs = dst_db.cursor()
            src_curs.execute("show client_encoding")
            src_enc = src_curs.fetchone()[0]
            dst_curs.execute("show client_encoding")
            dst_enc = dst_curs.fetchone()[0]
            if src_enc != dst_enc:
                dst_curs.execute("set client_encoding = %s", [src_enc])

    def copy_snapshot_cleanup(self, dst_db):
        """Remove unnecessary snapshot info from tables."""
        no_lag = not self.work_state
        changes = False
        for t in self.table_list:
            t.gc_snapshot(self.copy_thread, self.prev_tick, self.cur_tick, no_lag)
            if t.changed:
                changes = True

        if changes:
            self.save_table_state(dst_db.cursor())
            dst_db.commit()

    def restore_fkeys(self, dst_db):
        """Restore fkeys that have both tables on sync."""
        dst_curs = dst_db.cursor()
        # restore fkeys -- one at a time
        if self.cf.getboolean('restore_all_fkeys', False):
            q = "select * from londiste.pending_fkeys"
        else:
            q = "select * from londiste.get_valid_pending_fkeys(%s)"
        dst_curs.execute(q, [self.set_name])
        fkey_list = dst_curs.fetchall()
        for row in fkey_list:
            self.log.info('Creating fkey: %(fkey_name)s (%(from_table)s --> %(to_table)s)' % row)
            q2 = "select londiste.restore_table_fkey(%(from_table)s, %(fkey_name)s)"
            dst_curs.execute(q2, row)
            dst_db.commit()

    def drop_fkeys(self, dst_db, table_name):
        """Drop all foreign keys to and from this table.

        They need to be dropped one at a time to avoid deadlocks with user code.
        """

        dst_curs = dst_db.cursor()
        q = "select * from londiste.find_table_fkeys(%s)"
        dst_curs.execute(q, [table_name])
        fkey_list = dst_curs.fetchall()
        for row in fkey_list:
            self.log.info('Dropping fkey: %s' % row['fkey_name'])
            q2 = "select londiste.drop_table_fkey(%(from_table)s, %(fkey_name)s)"
            dst_curs.execute(q2, row)
            dst_db.commit()

    def process_root_node(self, dst_db):
        """On root node send seq changes to queue."""

        CascadedWorker.process_root_node(self, dst_db)

        q = "select * from londiste.root_check_seqs(%s)"
        self.exec_cmd(dst_db, q, [self.queue_name])

    def update_seq(self, dst_curs, ev):
        if self.copy_thread:
            return

        val = int(ev.data)
        seq = ev.extra1
        q = "select * from londiste.global_update_seq(%s, %s, %s)"
        self.exec_cmd(dst_curs, q, [self.queue_name, seq, val])

    def copy_event(self, src_curs, dst_curs, ev, filtered_copy):
        # send only data events down (skipping seqs also)
        if filtered_copy:
            if ev.type[:9] in ('londiste.',):
                return
        CascadedWorker.copy_event(self, src_curs, dst_curs, ev, filtered_copy)

    def exception_hook(self, det, emsg):
        # add event info to error message
        if self.current_event:
            ev = self.current_event
            info = "[ev_id=%d,ev_txid=%d] " % (ev.ev_id,ev.ev_txid)
            emsg = info + emsg
        super(ReplicatorRest, self).exception_hook(det, emsg)
        


if __name__ == '__main__':
    script = ReplicatorRest(sys.argv[1:])
    script.start()
