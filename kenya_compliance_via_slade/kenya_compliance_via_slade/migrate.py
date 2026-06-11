from kenya_compliance_via_slade.kenya_compliance_via_slade.patches.unhide_etims_fields import (
    cleanup_property_setters,
)


def after_migrate():
    cleanup_property_setters()
