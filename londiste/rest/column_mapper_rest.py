"""
Column mapping handler.
"""

import skytools
import londiste
import os, errno
from londiste.handlers.column_mapper import ColumnMapperHandler
import londiste.rest.sqltools

__all__ = ['ColumnMapperRestHandler']

class ColumnMapperRestHandler (ColumnMapperHandler):
    """Special column mapping handler for REST API sync.

Mapping is determined by rows in table conf.sync_mapping in the target database.
Mapping is (so far) not determined by calling the REST API to obtain the real column list.

    Parameters:
      batch_save_dir=DIR - Directory to save SQL batch files (useful for debuging and error recovery)
    """

    handler_name = 'column_mapper_rest'

    def __init__(self, table_name, args, dest_table):
        self.field_map = {}
        self.batch_save_file = None
        self.handler_name = 'column_mapper_rest'
        ColumnMapperHandler.__init__(self, table_name, args, dest_table)

    def process_event(self, ev, sql_queue_func, arg):
        row = self.parse_row_data(ev)
        if not row:
            self.log.info('Empty column set, event [%s] ignored (%s)', ev.type, ev.extra1)
            return
        obj = {'table': self.fq_dest_table}
        if len(ev.type) == 1:
            # TODO: co je tohle za vetev, vleze to sem nekdy?
            # sql event
            # fqname = self.fq_dest_table
            # fmt = self.sql_command[ev.type]
            # sql = fmt % (fqname, row)
            obj['op'] = ev.type
        else:
            # napad/optimalizace: udelat si katalog hlavicek tabulek, aby se nemusel posilat stale znovu
            pklist = ev.type[2:].split(',')
            obj['op'] = ev.type[0]
            non_pk_cols = list(set(row.keys()) - set(pklist))
            obj['header'] = header = pklist + non_pk_cols
            pklist_len = len(pklist)
            if pklist_len > 1:
                obj['pks'] = pklist_len
            obj['table'] = self.dest_table
            # TODO: nejak groupovat vic stejnych eventu nad stejnou tabulkou do vic objektu v rows?
            obj['rows'] = [[row[_] for _ in header]]

        sql_queue_func(obj)
        if self.batch_save_file:
            self.batch_save_file.write(str(obj))

    def real_copy(self, tablename, src_curs, dst_curs, column_list, work_dir):
        """do the actual table copy and return tuple with filename, number of bytes and rows copied"""
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

        return londiste.rest.sqltools.full_copy(tablename, src_curs, _src_cols, condition, write_hook = _write_hook, work_dir = work_dir)


# register handler class
__londiste_handlers__ = [ColumnMapperRestHandler]
