"""
Column mapping handler.
"""

import skytools
import os, errno
from skytools.dbstruct import TableStruct
from londiste.handler import TableHandler

__all__ = ['ColumnMapperHandler']

class ColumnMapperHandler (TableHandler):
    """Column mapping handler.

Mapping is determined by rows in table conf.sync_mapping

    Parameters:
      batch_save_dir=DIR - Directory to save SQL batch files
    """
    handler_name = 'column_mapper'

    def __init__(self, table_name, args, dest_table):
        # leave field_map empty so that it throws an error if it remains uninitialized in use
        self.field_map = None
        self.batch_save_file = None
        TableHandler.__init__(self, table_name, args, dest_table)
        # self.shard_nr = None    # part number of local node

    def reset(self):
        """Forget config info."""
        # self.shard_nr = None
        TableHandler.reset(self)

    def add(self, trigger_arg_list):
        """Let trigger put hash into extra3"""
        # arg = "ev_extra3='hash='||%s" % self.hashexpr
        # trigger_arg_list.append(arg)
        TableHandler.add(self, trigger_arg_list)

    def load_column_mapping(self, src_curs, dst_curs):
        """Load configuration column mapping from DB (table sync_mapping, schema conf)"""

        rows = None

        if skytools.exists_table(dst_curs, 'conf.sync_mapping'):
            q = "select src_column, dest_column from conf.sync_mapping where table_name = %s"
            dst_curs.execute(q, [self.dest_table])
            rows = dst_curs.fetchall()

        src_pkeys = skytools.get_table_pkeys(src_curs, self.table_name)
        self.field_map = {k:k for k in src_pkeys}

        if rows:
            for row in rows:
                self.field_map[row[0]] = row[1]
        else:
            # default 1:1 mapping on all common (means intersection) columns
            src_cols = skytools.get_table_columns(src_curs, self.table_name)
            dst_cols = skytools.get_table_columns(dst_curs, self.dest_table)
            common_cols = set(src_cols) & set(dst_cols)
            self.field_map = {c:c for c in common_cols}
            self.log.debug('No mapping defined for table %s in conf.sync_mapping, using common columns', self.dest_table)


    def prepare_batch(self, batch_info, src_curs, dst_curs):
        """Called on first event for this table in current batch."""

        # load column mapping configuration from database table
        self.load_column_mapping(src_curs, dst_curs)
        # get SQL batch storage path from local configuration 
        # (may be set either by global configuration or using londiste add-table zzz --handler-arg=batch_save_dir=xxx)
        batch_save_dir = self.conf.get('batch_save_dir')
        # try to load batch_save_dir from database configuration (if available)
        if not batch_save_dir and skytools.exists_table(dst_curs, 'conf.sync_settings'):
            q = "select value from conf.sync_settings where key='batch_save_dir'"
            dst_curs.execute(q)
            row = dst_curs.fetchone()
            if row:
                batch_save_dir = row[0]

        if batch_save_dir:
            path = os.path.join(batch_save_dir, 'batch_{}'.format(batch_info['tick_id']))
            try:
                os.makedirs(path)
                self.log.info('Saving batch SQL files to %s...', path)
            except OSError as exc:
                if not (exc.errno == errno.EEXIST and os.path.isdir(path)):
                    raise
            except:
                raise
            table_name = self.dest_table.split('.', 1)[-1]
            self.batch_save_file = open(os.path.join(path, table_name + '.sql'), 'w')

    def finish_batch(self, batch_info, dst_curs):
        """Called when batch finishes."""
        if self.batch_save_file:
            self.batch_save_file.close()
            self.log.debug('Batch SQL for %s saved.', self.dest_table)

    def parse_row_data(self, ev):
        data = skytools.db_urldecode(ev.data)
        data = self.filter_columns(data)
        return data

    def process_event(self, ev, sql_queue_func, arg):
        row = self.parse_row_data(ev)
        if not row:
            self.log.info('Empty column set, event [%s] ignored (%s)', ev.type, ev.extra1)
            return
        if len(ev.type) == 1:
            # sql event
            fqname = self.fq_dest_table
            fmt = self.sql_command[ev.type]
            sql = fmt % (fqname, row)
        else:
            # urlenc event
            pklist = ev.type[2:].split(',')
            op = ev.type[0]
            tbl = self.dest_table
            if op == 'I':
                sql = skytools.mk_insert_sql(row, tbl, pklist)
            elif op == 'U':
                sql = skytools.mk_update_sql(row, tbl, pklist)
            elif op == 'D':
                sql = skytools.mk_delete_sql(row, tbl, pklist)

        sql_queue_func(sql, arg)
        if self.batch_save_file:
            self.batch_save_file.write(sql+'\n')

    def filter_columns(self, data):
        data = {v: data.get(k) for k, v in self.field_map.items()}
        return data

    def get_config(self):
        """Processes args dict"""
        conf = TableHandler.get_config(self)
        # Take over batch_save_dir value from "--handler-arg" cli argument
        conf.batch_save_dir = self.args.get('batch_save_dir')
        return conf

    def real_copy(self, tablename, src_curs, dst_curs, column_list):
        """do the actual table copy and return tuple with number of bytes and rows copied"""
        self.load_column_mapping(src_curs, dst_curs)
        self.log.info("Copying with mapping: "+ ', '.join('%s -> %s' % (k,v) for k, v in self.field_map.items()))
        _src_cols = self.field_map.keys()
        _dst_cols = self.field_map.values()
        condition = self.get_copy_condition (src_curs, dst_curs)

        if self.encoding_validator:
            def _write_hook(obj, data):
                return self.encoding_validator.validate_copy(data, _src_cols, tablename)
        else:
            _write_hook = None

        return skytools.full_copy(tablename, src_curs, dst_curs,
                                  _src_cols, condition,
                                  dst_tablename = self.dest_table,
                                  dst_column_list = _dst_cols,
                                  write_hook = _write_hook)


    def get_copy_condition(self, src_curs, dst_curs):
        event_filter = self.conf.get('event_filter')
        return event_filter['partialConditionMaster'] if event_filter else None

# register handler class
__londiste_handlers__ = [ColumnMapperHandler]
