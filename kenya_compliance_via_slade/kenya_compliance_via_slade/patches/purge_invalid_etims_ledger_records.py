from ..background_tasks.tasks import purge_invalid_etims_ledger_records


def execute():
    purge_invalid_etims_ledger_records()
