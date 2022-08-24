"""Compares tables in replication set.

Currently just does count(1) on both sides.
"""

import sys

import skytools
import yaml

from londiste.syncer import Syncer

__all__ = ['Comparator']


class Comparator(Syncer):
    """Simple checker based on Syncer.
    When tables are in sync runs simple SQL query on them.
    """

    def __init__(self, args):
        self.event_filter_config = {}
        super().__init__(args)

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
        dst_q = self.get_compare_query(dst_tbl, common_cols)

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

        self.log.debug("dstdb: %s", dst_q)
        dst_curs.execute(dst_q)
        dst_row = dst_curs.fetchone()
        dst_str = f % dst_row
        self.log.info("dstdb: %s", dst_str)
        dst_db.commit()

        if src_str != dst_str:
            self.log.warning("%s: Results do not match!", dst_tbl)
            return 1
        return 0

    def get_compare_query(self, tbl, common_cols):
        # get sane query
        if self.options.count_only:
            q = "select count(1) as cnt from only _TABLE_"
        else:
            # this way is much faster than the above
            q = "select count(1) as cnt, sum(hashtext(_COLS_::text)::bigint) as chksum from only _TABLE_"

        q = self.cf.get('compare_sql', q)
        q = q.replace("_COLS_", common_cols)

        # replace TABLE placeholder with real table name
        compare_query = q.replace('_TABLE_', skytools.quote_fqident(tbl) + ' _tbl')

        filter_cond = self.get_table_filter_condition(tbl)
        if filter_cond:
            # add filter condition to the query
            if "where" in compare_query.lower():
                # where condition already defined, use "and" to append filter condition
                compare_query = compare_query + " and " + filter_cond
            else:
                compare_query = compare_query + " where " + filter_cond

        # set extra float digits to have same floating point number precision on both DBs
        compare_query = self.set_extra_float_digits_query + compare_query

        return compare_query

    def get_table_filter_condition(self, src_tbl):
        return self.event_filter_config.get(src_tbl, {}).get('partialConditionMaster', '')

    def calc_cols(self, src_curs, src_tbl, dst_curs, dst_tbl):
        cols1 = self.load_cols(src_curs, src_tbl)
        cols2 = self.load_cols(dst_curs, dst_tbl)

        qcols = []
        for c in self.calc_common(cols1, cols2):
            qcols.append(skytools.quote_ident(c))
        return "(%s)" % ",".join(qcols)

    def load_cols(self, curs, tbl):
        schema, table = skytools.fq_name_parts(tbl)
        q = "select column_name from information_schema.columns"\
            " where table_schema = %s and table_name = %s"
        curs.execute(q, [schema, table])
        cols = []
        for row in curs.fetchall():
            cols.append(row[0])
        return cols

    def calc_common(self, cols1, cols2):
        common = []
        map2 = {}
        for c in cols2:
            map2[c] = 1
        for c in cols1:
            if c in map2:
                common.append(c)
        if len(common) == 0:
            raise Exception("no common columns found")

        if len(common) != len(cols1) or len(cols2) != len(cols1):
            self.log.warning("Ignoring some columns")

        return common

    def init_optparse(self, p=None):
        """Initialize cmdline switches."""
        p = super().init_optparse(p)
        p.add_option("--count-only", action="store_true", help="just count rows, do not compare data")
        return p

    def load_config(self):
        cf = super().load_config()
        if cf.has_option('event_filter_config_file'):
            event_filter_config_file = cf.get('event_filter_config_file')
            with open(event_filter_config_file, 'r') as stream:
                self.event_filter_config = yaml.safe_load(stream)
            self.log.info('Filter: ' + str(self.event_filter_config))
        return cf


if __name__ == '__main__':
    script = Comparator(sys.argv[1:])
    script.start()

