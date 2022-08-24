import json
import os
import tempfile
import time

import skytools

from londiste.compare import Comparator
from londiste.rest.rest import Rest


class ComparatorRest(Comparator):
    """ Compares tables using REST API"""

    def process_sync(self, t1, t2, src_db, dst_db):
        """Actual comparison."""

        src_tbl = t1.dest_table
        dst_tbl = t2.dest_table

        src_curs = src_db.cursor()
        dst_curs = dst_db.cursor()

        self.log.info('Counting %s', dst_tbl)

        # get common cols
        common_cols = self.calc_cols(src_curs, src_tbl, dst_curs, dst_tbl)
        src_q = self.get_compare_query(src_tbl, common_cols)

        f = "%(cnt)d rows"
        if not self.options.count_only:
            f += ", checksum=%(chksum)s"
        f = self.cf.get('compare_fmt', f)

        self.log.debug("srcdb: %s", src_q)
        src_curs.execute(src_q)
        src_row = src_curs.fetchone()
        src_str = f % src_row
        self.log.info("srcdb: %s", src_str)
        src_db.commit()

        with tempfile.NamedTemporaryFile(prefix='compare_' + dst_tbl + '_', suffix='.json', delete=False, mode='w+') as sql_file:
            dst_where = self.get_table_filter_condition(src_tbl)
            compareData = {'table': dst_tbl, 'countOnly': bool(self.options.count_only), 'columns': common_cols, 'condition': dst_where}
            sql_file.write(json.dumps(compareData))
            sql_file.close()
            rest = Rest(self.cf)
            dst_row = rest.call_api('compare', sql_file.name)
            os.remove(sql_file.name)

        dst_str = f % dst_row
        self.log.info("dstdb: %s", dst_str)
        if src_str != dst_str:
            self.log.warning("%s: Results do not match!", dst_tbl)
            return 1
        self.log.info("%s: OK", dst_tbl)
        return 0

    def lock_table_root_and_sync(self, lock_db, setup_db, dst_db, src_tbl, dst_tbl):
        lock_time, tick_id = self.lock_table_root(dst_tbl, lock_db, setup_db, src_tbl)
        dst_curs = dst_db.cursor()
        self.pause_consumer_after_tick(dst_curs, tick_id)

        # now wait
        self.wait_until_tick(dst_db, lock_db, lock_time, tick_id)

    def pause_consumer_after_tick(self, curs, tick_id):
        self.log.info("Pausing consumer after tick %s", tick_id)
        q = "select * from pgq_node.set_node_attrs(%s, %s)"
        self.exec_cmd(curs, q, [self.queue_name, "wait-after=%s" % tick_id])

    def unpause_consumer_after_tick(self, curs):
        q = "select * from pgq_node.set_node_attrs(%s, %s)"
        self.exec_cmd(curs, q, [self.queue_name, None])


    def finalize_sync(self, lock_db, setup_db, dst_db, src_tbl, dst_tbl):
        self.unpause_consumer_after_tick(dst_db.cursor())
        dst_db.commit()