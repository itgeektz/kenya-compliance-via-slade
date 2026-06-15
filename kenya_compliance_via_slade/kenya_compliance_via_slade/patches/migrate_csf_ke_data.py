import frappe
from frappe.utils import add_years, today

from ..utils import build_verification_url


def execute():
    pass


@frappe.whitelist()
def migrate(from_date=None):
    if not from_date:
        from_date = add_years(today(), -1)

    frappe.cache().set_value(
        "etims_migration_progress",
        {"percent": 1, "description": "Initializing Data Migration..."},
    )
    frappe.enqueue(
        method="kenya_compliance_via_slade.kenya_compliance_via_slade.patches.migrate_csf_ke_data.run_heavy_migrations",
        queue="long",
        timeout=4000,
        now=frappe.flags.in_test,
        from_date=from_date,
    )


@frappe.whitelist()
def get_migration_status():
    status = frappe.cache().get_value("etims_migration_progress")
    if not status:
        return {"percent": 0, "description": "No active migration found."}
    return status


def update_migration_progress(percent, description):
    frappe.cache().set_value(
        "etims_migration_progress", {"percent": percent, "description": description}
    )
    frappe.publish_progress(
        percent,
        title="Migrating Legacy eTims Data",
        description=description,
    )


def run_heavy_migrations(from_date):
    try:
        update_migration_progress(1, "Populating Master Child Table Mapping Records...")
        migrate_master_child_tables(["Item", "Customer", "Supplier"])

        update_migration_progress(20, "Re-mapping Master Target ID Configurations...")
        reconcile_master_id_mappings()

        migrate_doctype_fields(
            "Item",
            {
                "custom_prevent_etims_registration": "etims_prevent_etims_registration",
                "custom_submission_tries": "etims_submission_tries",
                "custom_taxation_type": "etims_taxation_type",
                "custom_taxation_type_name": "etims_taxation_type_name",
                "custom_item_classification": "etims_item_classification",
                "custom_item_classification_code": "etims_item_classification_code",
                "custom_etims_country_of_origin": "etims_country_of_origin",
                "custom_etims_country_of_origin_code": "etims_country_of_origin_code",
                "custom_packaging_unit": "etims_packaging_unit",
                "custom_unit_of_quantity_code": "etims_unit_of_quantity_code",
                "custom_unit_of_quantity": "etims_unit_of_quantity",
                "custom_packaging_unit_code": "etims_packaging_unit_code",
                "custom_item_type": "etims_item_type",
                "custom_product_type": "etims_product_type",
                "custom_item_type_name": "etims_item_type_name",
                "custom_product_type_name": "etims_product_type_name",
            },
            "eTims Item Field Migration Failed",
            start_perc=25,
            end_perc=35,
            main_criterion_field="custom_item_classification_code",
        )

        migrate_doctype_fields(
            "Item Group",
            {
                "custom_prevent_etims_registration": "etims_prevent_etims_registration",
                "custom_taxation_type": "etims_taxation_type",
                "custom_taxation_type_name": "etims_taxation_type_name",
                "custom_item_classification": "etims_item_classification",
                "custom_item_classification_code": "etims_item_classification_code",
                "custom_etims_country_of_origin": "etims_country_of_origin",
                "custom_etims_country_of_origin_code": "etims_country_of_origin_code",
                "custom_packaging_unit": "etims_packaging_unit",
                "custom_unit_of_quantity_code": "etims_unit_of_quantity_code",
                "custom_unit_of_quantity": "etims_unit_of_quantity",
                "custom_packaging_unit_code": "etims_packaging_unit_code",
                "custom_item_type": "etims_item_type",
                "custom_product_type": "etims_product_type",
                "custom_item_type_name": "etims_item_type_name",
                "custom_product_type_name": "etims_product_type_name",
            },
            "eTims Item Group Field Migration Failed",
            start_perc=35,
            end_perc=45,
            main_criterion_field="custom_item_classification_code",
        )

        update_migration_progress(46, "Processing Item Tax Templates...")
        migrate_doctype_fields(
            "Item Tax Template",
            {
                "custom_etims_taxation_type": "etims_taxation_type",
            },
            "eTims Item Tax Template Field Migration Failed",
            start_perc=46,
            end_perc=48,
            main_criterion_field="custom_etims_taxation_type",
        )

        update_migration_progress(49, "Processing Sales Taxes Templates...")
        migrate_doctype_fields(
            "Sales Taxes and Charges Template",
            {
                "custom_etims_taxation_type": "etims_taxation_type",
            },
            "eTims Sales Taxes and Charges Template Field Migration Failed",
            start_perc=49,
            end_perc=52,
            main_criterion_field="custom_etims_taxation_type",
        )

        update_migration_progress(53, "Processing Customer Master Fields...")
        migrate_doctype_fields(
            "Customer",
            {
                "custom_prevent_etims_registration": "etims_prevent_etims_registration",
            },
            "eTims Customer Field Migration Failed",
            start_perc=53,
            end_perc=60,
            main_criterion_field="custom_prevent_etims_registration",
        )

        migrate_doctype_fields_batched(
            "Stock Ledger Entry",
            {
                "custom_submitted_successfully": "sent_to_etims",
                "custom_submission_tries": "etims_submission_attempts",
                "custom_slade_id": "etims_id",
            },
            "eTims Stock Ledger Entry Field Migration Failed",
            60,
            75,
            from_date=from_date,
            date_field="posting_date",
            main_criterion_field="custom_slade_id",
        )

        migrate_doctype_fields_batched(
            "Sales Invoice",
            {
                "custom_successfully_submitted": "sent_to_etims",
                "custom_slade_id": "etims_id",
                "custom_qr_code_url": "etims_qr_code_url",
                "custom_submission_attempts": "etims_submission_attempts",
                "custom_qr_code": "etims_qr_image",
            },
            "eTims Sales Invoice Field Migration Failed",
            75,
            90,
            from_date=from_date,
            date_field="posting_date",
            main_criterion_field="custom_slade_id",
        )

        migrate_doctype_fields_batched(
            "Sales Invoice Item",
            {
                "custom_tax_amount": "etims_tax_amount",
                "custom_base_tax_amount": "etims_base_tax_amount",
                "custom_tax_rate": "etims_tax_rate",
            },
            "eTims Sales Invoice Item Field Migration Failed",
            90,
            95,
            from_date=from_date,
            date_field="creation",
            main_criterion_field="custom_tax_rate",
        )

        generate_invoice_verification_urls(from_date)

        update_migration_progress(98, "Finishing up submission rules settings...")
        set_etims_submission_modes()

        update_migration_progress(100, "Migration successfully finished!")

    except Exception:
        frappe.db.rollback()
        update_migration_progress(0, "Migration stopped due to errors.")


def reconcile_master_id_mappings():
    if not frappe.db.exists("DocType", "eTims ID Mapping"):
        return

    doctypes = ["Customer", "Item", "Supplier"]
    for d_idx, doctype in enumerate(doctypes, start=1):
        if not frappe.db.exists("DocType", doctype):
            continue

        records = frappe.get_all(doctype, fields=["name"], limit_page_length=0)
        total_records = len(records)
        if not total_records:
            continue

        for idx, row in enumerate(records, start=1):
            if idx % 20 == 0 or idx == total_records:
                current_perc = int(((d_idx - 1) / len(doctypes)) * 15) + 20
                update_migration_progress(
                    current_perc,
                    f"Cross-referencing {doctype} configuration structures ({idx}/{total_records})...",
                )

            try:
                doc = frappe.get_doc(doctype, row.name)
                setup_mappings = doc.get("etims_setup_mapping") or []

                existing_global_entries = frappe.get_all(
                    "eTims ID Mapping",
                    filters={"parent": doc.name, "parenttype": doctype},
                    fields=["name", "etims_id", "disabled", "setup_docname"],
                )

                seen_pairs = set()
                for entry in existing_global_entries:
                    pair_key = (entry.setup_docname, entry.etims_id)
                    if pair_key in seen_pairs:
                        frappe.delete_doc(
                            "eTims ID Mapping", entry.name, ignore_permissions=True
                        )
                        continue
                    seen_pairs.add(pair_key)

                existing_global_entries = frappe.get_all(
                    "eTims ID Mapping",
                    filters={"parent": doc.name, "parenttype": doctype},
                    fields=["name", "etims_id", "disabled", "setup_docname"],
                )

                if not setup_mappings:
                    for entry in existing_global_entries:
                        if not entry.disabled:
                            frappe.db.set_value(
                                "eTims ID Mapping",
                                entry.name,
                                "disabled",
                                1,
                                update_modified=False,
                            )
                    continue

                for child in setup_mappings:
                    child_setup = getattr(child, "etims_setup", None) or getattr(
                        child, "setup_docname", None
                    )
                    child_id = getattr(child, "etims_id", None) or getattr(
                        child, "custom_slade_id", None
                    )
                    child_active = not getattr(child, "disabled", 0) and getattr(
                        child, "registered", 1
                    )

                    if not child_setup or not child_id:
                        continue

                    match_found = False
                    for entry in existing_global_entries:
                        if (
                            entry.setup_docname == child_setup
                            and entry.etims_id == child_id
                        ):
                            match_found = True
                            target_disabled = 0 if child_active else 1
                            if entry.disabled != target_disabled:
                                frappe.db.set_value(
                                    "eTims ID Mapping",
                                    entry.name,
                                    "disabled",
                                    target_disabled,
                                    update_modified=False,
                                )
                            break

                    if not match_found:
                        new_mapping = frappe.get_doc(
                            {
                                "doctype": "eTims ID Mapping",
                                "setup_doctype": "Navari KRA eTims Settings",
                                "setup_docname": child_setup,
                                "etims_id": child_id,
                                "disabled": 0 if child_active else 1,
                                "parent": doc.name,
                                "parenttype": doctype,
                                "parentfield": "etims_id_mapping",
                            }
                        )
                        new_mapping.insert(ignore_permissions=True)

                for entry in existing_global_entries:
                    child_match = False
                    for child in setup_mappings:
                        child_setup = getattr(child, "etims_setup", None) or getattr(
                            child, "setup_docname", None
                        )
                        child_id = getattr(child, "etims_id", None) or getattr(
                            child, "custom_slade_id", None
                        )
                        if (
                            child_setup == entry.setup_docname
                            and child_id == entry.etims_id
                        ):
                            child_match = True
                            break

                    if not child_match and not entry.disabled:
                        frappe.db.set_value(
                            "eTims ID Mapping",
                            entry.name,
                            "disabled",
                            1,
                            update_modified=False,
                        )

                if idx % 100 == 0:
                    frappe.db.commit()

            except Exception:
                frappe.db.rollback()
                frappe.log_error(
                    title=f"Mapping Synchronization Broken for {doctype} {row.name}",
                    message=frappe.get_traceback(),
                )
                frappe.db.commit()

        frappe.db.commit()


def migrate_master_child_tables(doctypes):
    for d_idx, doctype in enumerate(doctypes, start=1):
        if not frappe.db.exists("DocType", doctype):
            continue

        meta = frappe.get_meta(doctype)
        if not meta.has_field("etims_setup_mapping"):
            continue

        records = frappe.get_all(
            doctype,
            filters={"custom_item_classification_code": ("is", "set")}
            if doctype == "Item"
            else {},
            fields=["name"],
            limit_page_length=0,
        )
        total_records = len(records)
        if not total_records:
            continue

        for idx, row in enumerate(records, start=1):
            if idx % 10 == 0 or idx == total_records:
                current_perc = int(((d_idx - 1) / len(doctypes)) * 15) + 1
                update_migration_progress(
                    current_perc,
                    f"Mapping {doctype} setups ({idx}/{total_records})...",
                )

            try:
                doc = frappe.get_doc(doctype, row.name)
                has_changes = False

                for child in doc.get("etims_setup_mapping"):
                    if (
                        hasattr(child, "custom_slade_id")
                        and child.custom_slade_id
                        and not child.etims_id
                    ):
                        child.etims_id = child.custom_slade_id
                        has_changes = True

                    if (
                        hasattr(child, "custom_submitted_successfully")
                        and child.custom_submitted_successfully
                        and not child.registered
                    ):
                        child.registered = child.custom_submitted_successfully
                        has_changes = True

                if has_changes:
                    doc.save(ignore_permissions=True, ignore_version=True)

                if idx % 100 == 0:
                    frappe.db.commit()

            except Exception:
                frappe.db.rollback()
                frappe.log_error(
                    title=f"eTims Setup Mapping Child Table Migration Failed for {doctype}",
                    message=frappe.get_traceback(),
                )
                frappe.db.commit()

        frappe.db.commit()


def get_valid_field_map(doctype, field_map):
    if not frappe.db.exists("DocType", doctype):
        return {}

    valid_map = {}
    for src, target in field_map.items():
        if frappe.db.has_column(doctype, src) and frappe.db.has_column(doctype, target):
            valid_map[src] = target
    return valid_map


def migrate_doctype_fields(
    doctype, field_map, error_title, start_perc, end_perc, main_criterion_field=None
):
    valid_field_map = get_valid_field_map(doctype, field_map)
    if not valid_field_map:
        return

    filters = {}
    if main_criterion_field and frappe.db.has_column(doctype, main_criterion_field):
        filters[main_criterion_field] = ("is", "set")

    records = frappe.get_all(
        doctype,
        filters=filters,
        fields=["name"] + list(valid_field_map.keys()),
        limit_page_length=0,
    )
    total_records = len(records)
    if not total_records:
        return

    perc_range = end_perc - start_perc

    for idx, record in enumerate(records, start=1):
        if idx % 25 == 0 or idx == total_records:
            progress_perc = start_perc + int((idx / total_records) * perc_range)
            update_migration_progress(
                progress_perc,
                f"Processing {doctype} metadata registers ({idx}/{total_records})...",
            )

        try:
            update_values = {}
            for src, target in valid_field_map.items():
                value = getattr(record, src, None)
                if value is not None:
                    update_values[target] = value

            if not update_values:
                continue

            frappe.db.set_value(
                doctype,
                record.name,
                update_values,
                update_modified=False,
            )

            if idx % 500 == 0:
                frappe.db.commit()

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title=error_title,
                message=frappe.get_traceback(),
            )
            frappe.db.commit()

    frappe.db.commit()


def migrate_doctype_fields_batched(
    doctype,
    field_map,
    error_title,
    start_perc,
    end_perc,
    from_date=None,
    date_field="posting_date",
    main_criterion_field=None,
):
    valid_field_map = get_valid_field_map(doctype, field_map)
    if not valid_field_map:
        return

    filters = {}
    if from_date and frappe.db.has_column(doctype, date_field):
        filters[date_field] = (">=", from_date)
    if main_criterion_field and frappe.db.has_column(doctype, main_criterion_field):
        filters[main_criterion_field] = ("is", "set")

    records = frappe.get_all(
        doctype,
        filters=filters,
        fields=["name"] + list(valid_field_map.keys()),
        limit_page_length=0,
    )
    total_records = len(records)
    if not total_records:
        return

    perc_range = end_perc - start_perc

    for idx, record in enumerate(records, start=1):
        if idx % 50 == 0 or idx == total_records:
            progress_perc = start_perc + int((idx / total_records) * perc_range)
            update_migration_progress(
                progress_perc,
                f"Updating {doctype} rows ({idx}/{total_records})...",
            )

        try:
            update_values = {}
            for src, target in valid_field_map.items():
                value = getattr(record, src, None)
                if value is not None:
                    update_values[target] = value

            if not update_values:
                continue

            frappe.db.set_value(
                doctype,
                record.name,
                update_values,
                update_modified=False,
            )

            if idx % 1000 == 0:
                frappe.db.commit()

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title=error_title,
                message=frappe.get_traceback(),
            )
            frappe.db.commit()

    frappe.db.commit()


def generate_invoice_verification_urls(from_date=None):
    filters = {
        "docstatus": 1,
        "etims_verification_url": ("is", None),
        "etims_id": ("is", "set"),
    }
    if from_date:
        filters["posting_date"] = (">=", from_date)

    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=["name"],
        limit_page_length=0,
    )
    total_records = len(invoices)
    if not total_records:
        return

    for idx, invoice in enumerate(invoices, start=1):
        if idx % 50 == 0 or idx == total_records:
            progress_perc = 95 + int((idx / total_records) * 3)
            update_migration_progress(
                progress_perc,
                f"Compiling verification URLs ({idx}/{total_records})...",
            )

        try:
            doc = frappe.get_doc("Sales Invoice", invoice.name)
            url = build_verification_url(doc)
            if url:
                frappe.db.set_value(
                    "Sales Invoice",
                    invoice.name,
                    "etims_verification_url",
                    url,
                    update_modified=False,
                )

            if idx % 500 == 0:
                frappe.db.commit()

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title="Invoice Verification URL Generation Failed",
                message=frappe.get_traceback(),
            )
            frappe.db.commit()

    frappe.db.commit()


def set_etims_submission_modes():
    if not frappe.db.exists("DocType", "Navari KRA eTims Settings"):
        return

    settings = frappe.get_all(
        "Navari KRA eTims Settings",
        fields=["name"],
        limit_page_length=0,
    )

    for idx, row in enumerate(settings, start=1):
        try:
            frappe.db.set_value(
                "Navari KRA eTims Settings",
                row.name,
                {
                    "sales_information_submission": "Both",
                    "purchase_information_submission": "Both",
                    "stock_information_submission": "Both",
                },
                update_modified=False,
            )

            if idx % 1000 == 0:
                frappe.db.commit()

        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title="eTims Settings Submission Mode Update Failed",
                message=frappe.get_traceback(),
            )
            frappe.db.commit()

    frappe.db.commit()
