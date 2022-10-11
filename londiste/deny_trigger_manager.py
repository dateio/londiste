
import logging



class DenyTriggerManager:
    """
    Manages deny triggers on leaf node. It adds or removes deny triggers from all subscribed tables - configuration is
    node wide. Filter conditions are applied.
    """

    log = logging.getLogger('DenyTriggerManager')

    type_to_drop_query_dict = {
        'after truncate':                   'drop trigger if exists "_londiste_{0}_truncate" on {1};',
        'after insert or update or delete': 'drop trigger if exists "_londiste_{0}" on {1};',
        'before delete or update':          'drop trigger if exists "_londiste_{0}_before" on {1};',
        'after insert or update':           'drop trigger if exists "_londiste_{0}_after" on {1};',
    }

    event_filter_config = {}
    queue_name = None
    dst_db = None

    def __init__(self, dst_db, event_filter_config, queue_name):
        self.event_filter_config = event_filter_config
        self.queue_name = queue_name
        self.dst_db = dst_db

    def get_triggers_for_type(self, filter_condition, source_table, dest_table):
        triggers = {}

        if filter_condition:
            # partial sync is enabled for a table, we have to apply filter
            self.log.debug("Partial sync enabled for %s", source_table)

            filter_condition_old = filter_condition.replace('_tbl', 'old')
            filter_condition_new = filter_condition.replace('_tbl', 'new')

            # - delete has to be verified before it happens, to still have record in table and record can be found by
            # the partial sync query
            # - update has to be verified before it happens - to prevent change from protected record->not protected
            # record and also after it happens to prevent change in opposite direction
            # - insert, update have to be verified after it happens, so the record is in table and can be found by
            # partial sync query
            triggers['before delete or update'] = \
"""create trigger "_londiste_{0}_before"
    before delete or update
    on {1}
    for each row
    when ({2})
execute procedure pgq.logutriga('{0}', 'deny')""".format(self.queue_name, dest_table, filter_condition_old)
            triggers['after insert or update'] = \
"""create trigger "_londiste_{0}_after"
    after insert or update
    on {1}
    for each row
    when ({2})
execute procedure pgq.logutriga('{0}', 'deny')""".format(self.queue_name, dest_table, filter_condition_new)

        else:
            # partial sync is disabled for a table, just disable edit on all rows
            self.log.debug("Partial sync disabled for %s", dest_table)
            triggers['after insert or update or delete'] = \
"""create trigger "_londiste_{0}"
    after insert or update or delete
    on {1}
    for each row
execute procedure pgq.logutriga('{0}', 'deny')""".format(self.queue_name, dest_table)

        # truncate is always disabled on a table
        triggers['after truncate'] = \
"""create trigger "_londiste_{0}_truncate"
    after truncate
    on {1}
execute procedure pgq.sqltriga('{0}', 'deny')""".format(self.queue_name, dest_table)

        return triggers

    def create_missing_deny_triggers_for_table(self, table_info, only_mark_state):
        """
        (Re)create deny filters for subscribed tables, but only those not yet applied or those that have changed.
        """
        source_table = table_info['table_name']
        dest_table = table_info['dest_table']
        trigger_info = table_info['trigger_info']

        dst_db = self.dst_db
        dst_curs = dst_db.cursor()

        event_filter = self.event_filter_config.get(source_table, None)
        # we have to take condition for master, because for slave it is in Python format. Condition should have
        # the same result on master and on slave
        filter_condition = event_filter['partialConditionMaster'] if event_filter and event_filter['partialSync'] else None

        msg = "Creating triggers for table {0}".format(source_table)
        if filter_condition:
            msg = msg + ", filter condition {0}".format(filter_condition)
        self.log.info(msg)

        triggers = self.get_triggers_for_type(filter_condition, source_table, dest_table)

        if trigger_info is not None:
            # some triggers may not be relevant any more (partialSync added or removed since last time) -> remove old triggers
            types_to_drop = trigger_info.keys() - triggers.keys()
            for type in types_to_drop:
                q = self.type_to_drop_query_dict[type].format(self.queue_name, dest_table)
                self.log.info("Dropping original trigger not used any more: %s", q)
                dst_curs.execute(q)
                dst_curs.execute("""
                    delete from londiste.deny_trigger_info
                    where table_name = %(table_name)s
                        and queue_name = %(queue_name)s
                        and trigger_type = %(type)s;
                """, {'table_name': dest_table, 'queue_name': self.queue_name, 'type': type})

        for type, definition in triggers.items():
            current_definition = trigger_info.get(type) if trigger_info is not None else None
            if current_definition != definition:
                if not only_mark_state:
                    if current_definition is not None:
                        q = self.type_to_drop_query_dict[type].format(self.queue_name, dest_table)
                        self.log.info("Dropping original trigger: %s", q)
                        dst_curs.execute(q)
                    self.log.info("Creating new trigger: %s", definition)
                    dst_curs.execute(definition)
                dst_curs.execute("""
                    delete from londiste.deny_trigger_info
                    where table_name = %(table_name)s
                        and queue_name = %(queue_name)s
                        and trigger_type = %(type)s;
                    insert into londiste.deny_trigger_info(table_name, queue_name, trigger_type, trigger_definition)
                    values (%(table_name)s, %(queue_name)s, %(type)s, %(trigger_definition)s);
                """, {'table_name': dest_table, 'queue_name': self.queue_name, 'type': type, 'trigger_definition': definition})

        dst_db.commit()


    def get_destination_table_infos(self):
        dst_db = self.dst_db
        dst_curs = dst_db.cursor()

        q = """select table_name, 
                    coalesce(dest_table, table_name) as dest_table 
                from londiste.get_table_list(%s) 
                where local = true"""
        dst_curs.execute(q, [self.queue_name])

        table_infos = dst_curs.fetchall()

        q = """create table if not exists londiste.deny_trigger_info
        (
            id                          bigserial primary key,
            table_name                  varchar,
            queue_name                  varchar,
            trigger_type                varchar,
            trigger_definition          varchar
        );
        select * from londiste.deny_trigger_info where queue_name = %s;
        """
        dst_curs.execute(q, [self.queue_name])
        table_trigger_infos = {}
        for row in dst_curs.fetchall():
            table_name = row['table_name']
            trigger_info = table_trigger_infos.get(table_name, {})
            trigger_info[row['trigger_type']] = row['trigger_definition']
            table_trigger_infos[table_name] = trigger_info
        table_infos = [
            {**table_info, 'trigger_info': (table_trigger_infos.get(table_info['dest_table']))}
            for table_info in table_infos
        ]

        return table_infos

    def create_missing_deny_triggers(self, only_mark_state):
        table_infos = self.get_destination_table_infos()
        for table_info in table_infos:
            # self.create_deny_trigger_for_table(table_info)
            self.create_missing_deny_triggers_for_table(table_info, only_mark_state)
