from .patches.create_connection_links import update_links_for_doctypes


def after_migrate():
    update_links_for_doctypes()
