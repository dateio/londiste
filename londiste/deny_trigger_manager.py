"""
Manages deny triggers on leaf node. It adds or removes deny triggers from all subscribed tables - configuration is
node wide. Filter conditions are applied.
"""
import logging


class DenyTriggerManager:

    log = logging.getLogger('DenyTriggerManager')

    drop_crud_triggers_query = """
            drop trigger if exists "_londiste_{0}" on {1};
            drop trigger if exists "_londiste_{0}_before" on {1};
            drop trigger if exists "_londiste_{0}_after" on {1};
        """

    drop_truncate_trigger_query = """
            drop trigger if exists "_londiste_{0}_truncate" on {1};
        """

    event_filter_config = {}
    queue_name = None
    dst_db = None

    def __init__(self, dst_db, event_filter_config, queue_name):
        self.event_filter_config = event_filter_config
        self.queue_name = queue_name
        self.dst_db = dst_db

    def create_deny_triggers(self):
        table_infos = self.get_destination_table_infos()
        for table_info in table_infos:
            self.create_deny_trigger_for_table(table_info)

        return

    """
         Create deny filters for subscribed tables.    
    """
    def create_deny_trigger_for_table(self, table_info):
        source_table = table_info['table_name']
        dest_table = table_info['dest_table']

        self.log.debug("Creating triggers for table {0}".format(source_table))
        dst_db = self.dst_db
        dst_curs = dst_db.cursor()

        event_filter = self.event_filter_config.get(source_table, None)
        if event_filter and event_filter['partialSync']:
            # partial sync is enabled for a table, we have to apply filter
            self.log.debug("Partial sync enabled for {0}".format(source_table))

            # we have to take condition for master, because for slave it is in Python format. Condition should have
            # the same result on master and on slave
            filter_condition = event_filter['partialConditionMaster']
            filter_condition_old = filter_condition.replace('_tbl', 'old')
            filter_condition_new = filter_condition.replace('_tbl', 'new')

            q = (self.drop_crud_triggers_query + """
                create trigger "_londiste_{0}_before"
                    after delete or update
                    on {1}
                    for each row
                    when ({2})
                execute procedure pgq.logutriga('{0}', 'deny');

                create trigger "_londiste_{0}_after"
                    after insert or update
                    on {1}
                    for each row
                    when ({3})
                execute procedure pgq.logutriga('{0}', 'deny');
                """).format(self.queue_name, dest_table, filter_condition_old, filter_condition_new)
            dst_curs.execute(q)
        else:
            # partial sync is disabled for a table, just disable edit on all rows
            self.log.debug("Partial sync disabled for {0}".format(dest_table))

            q = (self.drop_crud_triggers_query + """
                create trigger "_londiste_{0}"
                    after insert or update or delete
                    on {1}
                    for each row
                execute procedure pgq.logutriga('{0}', 'deny');
                """).format(self.queue_name, dest_table)
            dst_curs.execute(q)

        # truncate is always disabled on a table
        q = (self.drop_truncate_trigger_query + """			
                create trigger "_londiste_{0}_truncate"
                after truncate
                on {1}
                execute procedure pgq.sqltriga('{0}', 'deny');
        """).format(self.queue_name, dest_table)
        dst_curs.execute(q)

        return

    """
        Drop all deny filters for subscribed tables.
    """
    def drop_deny_triggers(self):
        table_infos = self.get_destination_table_infos()
        for table_info in table_infos:
            dst_db = self.dst_db
            dst_curs = dst_db.cursor()
            q = (self.drop_crud_triggers_query + self.drop_truncate_trigger_query).format(self.queue_name, table_info['dest_name'])
            dst_curs.execute(q)

        return

    def get_destination_table_infos(self):
        dst_db = self.dst_db
        dst_curs = dst_db.cursor()

        q = """select table_name, 
                    coalesce(dest_table, table_name) as dest_table 
                from londiste.get_table_list(%s) 
                where local = true"""
        dst_curs.execute(q, [self.queue_name])

        return dst_curs.fetchall()
