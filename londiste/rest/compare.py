import json
import os
import tempfile

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

        dst_where = self.get_table_filter_condition(src_tbl)
        src_where = dst_where

        self.log.info('Counting %s', dst_tbl)

        # get common cols
        cols = self.calc_cols(src_curs, src_tbl, dst_curs, dst_tbl)

        # get sane query
        if self.options.count_only:
            q = "select count(1) as cnt from only _TABLE_"
        else:
            # this way is much faster than the above
            q = "select count(1) as cnt, sum(hashtext(_COLS_::text)::bigint) as chksum from only _TABLE_"

        q = self.cf.get('compare_sql', q)
        q = q.replace("_COLS_", cols)
        src_q = q.replace('_TABLE_', skytools.quote_fqident(src_tbl) + ' _tbl')
        if src_where:
            src_q = src_q + " WHERE " + src_where

        src_q = self.set_extra_float_digits_query + src_q

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
            compareData = {'table': dst_tbl, 'countOnly': bool(self.options.count_only), 'columns': cols, 'condition': dst_where}
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