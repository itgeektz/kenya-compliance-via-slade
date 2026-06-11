import json

import frappe
import frappe.defaults
from frappe.model.document import Document
from frappe.utils import get_datetime, get_datetime_str

from ..doctype.doctype_names_mapping import (
    COUNTRIES_DOCTYPE_NAME,
    ITEM_CLASSIFICATIONS_DOCTYPE_NAME,
    OPERATION_TYPE_DOCTYPE_NAME,
    PACKAGING_UNIT_DOCTYPE_NAME,
    PAYMENT_TYPE_DOCTYPE_NAME,
    SETTINGS_DOCTYPE_NAME,
    SLADE_ID_MAPPING_DOCTYPE_NAME,
    TAXATION_TYPE_DOCTYPE_NAME,
    UNIT_OF_QUANTITY_DOCTYPE_NAME,
    WORKSTATION_DOCTYPE_NAME,
)
from ..utils import (
    get_company_from_setup_mapping,
    get_link_value,
    update_sales_invoice_etims_details,
)


def send_pos_invoices_information() -> None:
    from ..overrides.server.sales_invoice import on_submit

    all_pending_pos_invoices: list[Document] = frappe.get_all(
        "POS Invoice", {"docstatus": 1, "sent_to_etims": 0}, ["name"]
    )

    if all_pending_pos_invoices:
        for pos_invoice in all_pending_pos_invoices:
            doc = frappe.get_doc(
                "POS Invoice", pos_invoice.name, for_update=False
            )  # Refetch to get the document representation of the record

            try:
                on_submit(
                    doc, method=None
                )  # Delegate to the on_submit method for sales invoices

            except TypeError:
                continue


def update_documents(
    data: dict | list,
    doctype_name: str,
    field_mapping: dict,
    settings_name: str = None,
    is_table: bool = False,
    filter_field: str = "code",
    table_name: str = None,
    separator: str = " - ",
    fixed_values: dict = None,
) -> None:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON string: {data}")

    doc_list = data if isinstance(data, list) else data.get("results", [data])

    def safe_setattr(doc, field, value):
        if isinstance(value, str):
            value = value.replace("\\'", "'")
        setattr(doc, field, value)

    for record in doc_list:
        if isinstance(record, str):
            continue

        temp_doc = frappe.new_doc(doctype_name)

        if fixed_values:
            for field, value in fixed_values.items():
                setattr(temp_doc, field, value)

        for field, value in field_mapping.items():
            if isinstance(value, str):
                safe_setattr(temp_doc, field, record.get(value, ""))

        for field, value in field_mapping.items():
            if isinstance(value, dict) and "doctype" in value:
                linked_doctype = value.get("doctype")
                link_field = value.get("link_field")
                link_filter_field = value.get("filter_field", "etims_id")
                link_extract_field = value.get("extract_field", "name")
                link_filter_value = record.get(link_field)
                if linked_doctype and link_filter_value:
                    linked_value = frappe.db.get_value(
                        linked_doctype,
                        {link_filter_field: link_filter_value},
                        link_extract_field,
                    )
                    setattr(temp_doc, field, linked_value or "")

        for field, value in field_mapping.items():
            if callable(value):
                setattr(temp_doc, field, value(record))
            elif isinstance(value, dict) and "fields" in value:
                parts = []
                for source_field in value["fields"]:
                    part = getattr(temp_doc, source_field, None)
                    if part is None:
                        part = record.get(source_field, "")
                    if part:
                        parts.append(str(part))
                setattr(temp_doc, field, separator.join(parts))

        filter_value = getattr(temp_doc, filter_field, None)
        if not filter_value:
            continue

        filters = {filter_field: filter_value}
        if settings_name:
            if frappe.db.exists(
                "DocField", {"parent": doctype_name, "fieldname": "settings"}
            ):
                filters["settings"] = settings_name
            elif frappe.db.exists(
                "DocField", {"parent": doctype_name, "fieldname": "custom_settings"}
            ):
                filters["custom_settings"] = settings_name

        doc_name = frappe.db.get_value(doctype_name, filters, "name")

        if doc_name:
            doc = frappe.get_doc(doctype_name, doc_name)
            for field in field_mapping.keys():
                setattr(doc, field, getattr(temp_doc, field, ""))
            if fixed_values:
                for field, value in fixed_values.items():
                    setattr(doc, field, value)
        else:
            doc = temp_doc

        if is_table and table_name and hasattr(doc, table_name):
            found = False
            for child_row in getattr(doc, table_name):
                if child_row.setup_docname == settings_name:
                    child_row.etims_id = record.get("id")
                    child_row.is_active = 1
                    found = True
                    break

            if not found and settings_name:
                new_row = doc.append(table_name)
                new_row.setup_docname = settings_name
                new_row.etims_id = record.get("id")
                new_row.is_active = 1

        if settings_name and not is_table:
            if hasattr(doc, "settings"):
                doc.settings = settings_name
            elif hasattr(doc, "custom_settings"):
                doc.custom_settings = settings_name

        try:
            doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error updating {doctype_name}: {str(e)}")
            continue

    frappe.db.commit()


def sync_etims_mappings(
    response: list | dict,
    doctype: str,
    settings_name: str,
    match_field: str,
    response_field: str,
    update_fields: dict | None = None,
    create_missing: bool = False,
) -> None:
    if isinstance(response, str):
        response = json.loads(response)

    records = response if isinstance(response, list) else response.get("results", [])

    if not records:
        return

    match_values = [
        row.get(response_field) for row in records if row.get(response_field)
    ]

    existing_docs = frappe.get_all(
        doctype,
        filters={match_field: ["in", match_values]},
        fields=["name", match_field],
    )

    doc_map = {d[match_field]: d["name"] for d in existing_docs}

    modified = False

    for row in records:
        match_value = row.get(response_field)
        etims_id = row.get("id")

        if not match_value:
            continue

        docname = doc_map.get(match_value)

        if not docname and create_missing:
            doc = frappe.new_doc(doctype)
            doc.set(match_field, match_value)

            if update_fields:
                for target_field, source_field in update_fields.items():
                    value = row.get(source_field)

                    if value is not None:
                        doc.set(target_field, value)

            doc.insert(ignore_permissions=True)

            docname = doc.name
            doc_map[match_value] = docname
            modified = True

        if not docname:
            continue

        if etims_id:
            exists = frappe.db.exists(
                SLADE_ID_MAPPING_DOCTYPE_NAME,
                {
                    "parent": docname,
                    "parenttype": doctype,
                    "parentfield": "etims_id_mapping",
                    "setup_docname": settings_name,
                },
            )

            if not exists:
                frappe.get_doc(
                    {
                        "doctype": SLADE_ID_MAPPING_DOCTYPE_NAME,
                        "parent": docname,
                        "parenttype": doctype,
                        "parentfield": "etims_id_mapping",
                        "setup_doctype": SETTINGS_DOCTYPE_NAME,
                        "setup_docname": settings_name,
                        "etims_id": etims_id,
                    }
                ).insert(ignore_permissions=True)

                modified = True

        if update_fields:
            values = {}

            for target_field, source_field in update_fields.items():
                value = row.get(source_field)

                if value is not None:
                    values[target_field] = value

            if values:
                frappe.db.set_value(
                    doctype,
                    docname,
                    values,
                    update_modified=False,
                )
                modified = True

    if modified:
        frappe.db.commit()


def update_unit_of_quantity(
    response: dict,
    settings_name: str,
    **kwargs,
) -> None:
    sync_etims_mappings(
        response=response,
        doctype=UNIT_OF_QUANTITY_DOCTYPE_NAME,
        settings_name=settings_name,
        match_field="code",
        response_field="code",
        update_fields={
            "code_name": "name",
            "code_description": "description",
            "sort_order": "sort_order",
        },
    )


def update_packaging_units(
    response: dict,
    settings_name: str,
    **kwargs,
) -> None:
    sync_etims_mappings(
        response=response,
        doctype=PACKAGING_UNIT_DOCTYPE_NAME,
        settings_name=settings_name,
        match_field="code",
        response_field="code",
        update_fields={
            "code_name": "name",
            "code_description": "description",
            "sort_order": "sort_order",
        },
    )


def update_payment_methods(response: dict, **kwargs) -> None:
    field_mapping = {
        "slade_id": "id",
        "account_details": "account_details",
        "mobile_money_type": "mobile_money_type",
        "mobile_money_business_number": "mobile_money_business_number",
        "bank_name": "bank_name",
        "bank_branch": "bank_branch",
        "bank_account_number": "bank_account_number",
        "active": lambda x: 1 if x.get("active") else 0,
        "code_name": "name",
        "description": "description",
        "account": "account",
    }
    update_documents(
        response, PAYMENT_TYPE_DOCTYPE_NAME, field_mapping, filter_field="slade_id"
    )


def update_currencies(
    response: dict,
    settings_name: str,
    **kwargs,
) -> None:
    sync_etims_mappings(
        response=response,
        doctype="Currency",
        settings_name=settings_name,
        match_field="name",
        response_field="iso_code",
    )


def update_item_classification_codes(
    response: dict | list,
    settings_name: str,
    **kwargs,
) -> None:
    sync_etims_mappings(
        response=response,
        doctype=ITEM_CLASSIFICATIONS_DOCTYPE_NAME,
        settings_name=settings_name,
        match_field="itemclscd",
        response_field="classification_code",
        update_fields={
            "itemclsnm": "classification_name",
            "itemclslvl": "classification_level",
        },
        create_missing=True,
    )


def update_taxation_type(
    response: list,
    settings_name: str,
    **kwargs,
) -> None:
    sync_etims_mappings(
        response=response,
        doctype=TAXATION_TYPE_DOCTYPE_NAME,
        settings_name=settings_name,
        match_field="cd",
        response_field="tax_code",
        update_fields={
            "cdnm": "name",
            "cddesc": "description",
            "percentage": "percentage",
            "amount_type": "amount_type",
        },
    )


def update_countries(response: list, **kwargs) -> None:
    doc: Document | None = None
    for code, details in response.items():
        country_name = details.get("name", "").strip().lower()
        existing_doc = frappe.get_value(
            COUNTRIES_DOCTYPE_NAME, {"name": ["like", country_name]}
        )

        if existing_doc:
            doc = frappe.get_doc(COUNTRIES_DOCTYPE_NAME, existing_doc)
        else:
            doc = frappe.new_doc(COUNTRIES_DOCTYPE_NAME)

        doc.code = code
        doc.code_name = details.get("name")
        doc.currency_code = details.get("currency_code")
        doc.sort_order = details.get("sort_order", 0)
        doc.code_description = details.get("description", "")

        doc.save(ignore_permissions=True)

    frappe.db.commit()


def update_organisations(response: dict, **kwargs) -> None:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON string: {response}")

    record = (
        response if isinstance(response, list) else response.get("results", response)
    )[0]

    company_name = frappe.defaults.get_user_default("Company") or frappe.get_value(
        "Company", {}, "name"
    )

    doc = frappe.get_doc("Company", company_name)

    if record.get("default_currency"):
        doc.default_currency = (
            get_link_value("Currency", "etims_id", record.get("default_currency"))
            or "KES"
        )
    if record.get("web_address"):
        doc.website = record.get("web_address", "")
    if record.get("phone_number"):
        doc.phone_no = record.get("phone_number", "")
    if record.get("description"):
        doc.company_description = record.get("description", "")
    if record.get("id"):
        doc.etims_id = record.get("id", "")
    if record.get("email_address"):
        doc.email = record.get("email_address", "")
    if record.get("tax_payer_pin"):
        doc.tax_id = record.get("tax_payer_pin", "")
    doc.is_etims_verified = 1 if record.get("is_etims_verified") else 0

    doc.save(ignore_permissions=True)

    frappe.db.commit()


def update_branches(response: dict, settings_name: str, **kwargs) -> None:
    if isinstance(response, str):
        try:
            response = frappe.parse_json(response)
        except ValueError:
            frappe.throw("Invalid JSON string in response")

    results = response.get("results", [response])

    for branch_data in results:
        if not isinstance(branch_data, dict):
            continue

        cluster_id = branch_data.get("parent")
        company = get_company_from_setup_mapping(cluster_id, settings_name)

        if not company:
            # frappe.log_error(
            #     f"No company found for cluster {cluster_id}", "Branch Update Skipped"
            # )
            continue

        original_branch_name = branch_data.get("name", "").strip()
        if not original_branch_name:
            continue

        branch_name = f"eTims - {original_branch_name}"

        branch_filters = {
            "branch": branch_name,
        }
        branch_exists = frappe.db.exists("Branch", branch_filters)

        if branch_exists:
            branch = frappe.get_doc("Branch", branch_filters)
        else:
            branch = frappe.new_doc("Branch")

        branch.update(
            {
                "company": company,
                "branch": branch_name,
                "slade_id": branch_data.get("id"),
                "tax_id": branch_data.get("organisation_tax_pin"),
                "etims_device_serial_no": branch_data.get("etims_device_serial_no"),
                "branch_code": branch_data.get("etims_branch_id"),
                "pin": branch_data.get("organisation_tax_pin"),
                "is_head_office": 1 if branch_data.get("is_headquater") else 0,
                "is_etims_branch": 1 if branch_data.get("branch_status") else 0,
                "is_etims_verified": 1 if branch_data.get("is_etims_verified") else 0,
            }
        )

        branch.save(ignore_permissions=True)
        frappe.db.commit()


def update_departments(response: dict, **kwargs) -> None:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON string: {response}")

    record = (
        response if isinstance(response, list) else response.get("results", [response])
    )[0]

    department_name = "eTims Department"
    existing_department = frappe.db.get_value(
        "Department", {"department_name": department_name}, "name"
    )
    if existing_department:
        doc = frappe.get_doc("Department", existing_department)
    else:
        matching_department = frappe.db.get_value(
            "Department", {"department_name": department_name}, "name"
        )
        if matching_department:
            branch_name = record.get("parent_name", "")
            department_name = (
                f"{department_name} - {branch_name}" if branch_name else department_name
            )

        doc = frappe.new_doc("Department")
        doc.department_name = department_name

    if record.get("organisation"):
        doc.company = (
            get_link_value("Company", "etims_id", record.get("organisation"))
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )
    if record.get("parent"):
        doc.custom_branch = get_link_value("Branch", "slade_id", record.get("parent"))
    if record.get("id"):
        doc.etims_id = record.get("id")
    doc.is_etims_verified = 1 if record.get("is_etims_verified") else 0
    doc.custom_is_etims_department = 1

    doc.save(ignore_permissions=True)

    frappe.db.commit()


def update_workstations(response: dict, settings_name: str, **kwargs) -> None:
    field_mapping = {
        "slade_id": "id",
        "active": lambda x: 1 if x.get("active") else 0,
        "workstation": "name",
        "workstation_type_display": "workstation_type_display",
        "workstation_type": "workstation_type",
        "is_billing_point": lambda x: 1 if x.get("is_billing_point") else 0,
    }
    update_documents(
        response,
        WORKSTATION_DOCTYPE_NAME,
        field_mapping,
        filter_field="slade_id",
        settings_name=settings_name,
    )


def warehouse_search_on_success(response: dict, settings_name: str, **kwargs) -> None:
    from ..apis.process_request import process_request
    from ..utils import get_settings

    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON string: {response}")

    doc_list = (
        response if isinstance(response, list) else response.get("results", [response])
    )

    settings = get_settings(settings_name=settings_name)

    if not settings:
        return

    bhfid_slade_id = frappe.db.get_value("Branch", settings.bhfid, "slade_id")
    selected_record = (
        next((r for r in doc_list if r.get("branch") == bhfid_slade_id), None)
        or next((r for r in doc_list if "Stock" in r.get("name", "")), None)
        or (doc_list[0] if doc_list else None)
    )
    if selected_record:
        existing_warehouse = frappe.db.get_value(
            "Warehouse", {"company": settings.company, "is_group": 1}, "name"
        )
        if existing_warehouse:
            frappe.db.set_value(
                "Warehouse",
                existing_warehouse,
                {
                    "slade_id": selected_record.get("id", ""),
                },
            )
            frappe.db.set_value(
                SETTINGS_DOCTYPE_NAME,
                settings.name,
                {
                    "warehouse": existing_warehouse,
                },
            )
            frappe.enqueue(
                search_customer_supplier_locations, document_name=settings.name
            )

        bhfid_slade_id = frappe.db.get_value("Branch", settings.bhfid, "slade_id")
        if bhfid_slade_id:
            request_data = {
                "branch": bhfid_slade_id,
                "id": selected_record.get("id"),
            }
            frappe.enqueue(
                process_request,
                queue="default",
                is_async=True,
                doctype="Branch",
                request_data=request_data,
                route_key="LocationSearchReq",
                request_method="PATCH",
                settings_name=settings_name,
            )


def search_customer_supplier_locations(document_name: str) -> None:
    from ..apis.process_request import process_request

    process_request(
        {"location_type": "customer", "document_name": document_name},
        "LocationsSearchReq",
        search_customer_supplier_locations_on_success,
        doctype=SETTINGS_DOCTYPE_NAME,
    )

    process_request(
        {"location_type": "supplier", "document_name": document_name},
        "LocationsSearchReq",
        search_customer_supplier_locations_on_success,
        doctype=SETTINGS_DOCTYPE_NAME,
    )


def search_customer_supplier_locations_on_success(
    response: dict, document_name: str, **kwargs
) -> None:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON string: {response}")

    doc_list = (
        response if isinstance(response, list) else response.get("results", [response])
    )
    settings = frappe.get_doc(SETTINGS_DOCTYPE_NAME, document_name)
    bhfid_slade_id = frappe.db.get_value("Branch", settings.bhfid, "slade_id")
    selected_record = next(
        (r for r in doc_list if r.get("branch") == bhfid_slade_id), None
    ) or (doc_list[0] if doc_list else None)

    if selected_record:
        location_type = selected_record.get("location_type", "").lower()
        if location_type == "supplier":
            frappe.db.set_value(
                "Warehouse",
                settings.warehouse,
                "slade_supplier_warehouse",
                selected_record.get("id"),
            )
        elif location_type == "customer":
            frappe.db.set_value(
                "Warehouse",
                settings.warehouse,
                "slade_customer_warehouse",
                selected_record.get("id"),
            )


def operation_types_search_on_success(
    response: dict, document_name: str, **kwargs
) -> None:
    frappe.db.set_value(
        OPERATION_TYPE_DOCTYPE_NAME,
        document_name,
        {
            "slade_id": response.get("id"),
            "operation_name": response.get("operation_name"),
            "source_location": response.get("source_location"),
            "destination_location": response.get("destination_location"),
            "operation_type": response.get("operation_type"),
        },
    )


def update_clusters(response: dict, settings_name: str, **kwargs) -> None:
    pass
    # if isinstance(response, str):
    #     try:
    #         response = json.loads(response)
    #     except json.JSONDecodeError:
    #         raise ValueError(f"Invalid JSON string: {response}")

    # doc_list = response if isinstance(response, list) else response.get("results", [response])

    # modal_data = []
    # for record in doc_list:
    #     if isinstance(record, str):
    #         continue

    #     modal_data.append({
    #         "id": record.get("id"),
    #         "name": record.get("name"),
    #         "organisation": record.get("organisation")
    #     })

    # frappe.publish_realtime('show_cluster_matching_modal', {
    #     "data": modal_data,
    #     "settings_name": settings_name
    # })


def fetch_etims_sales_invoices_on_success(response: dict, **kwargs) -> None:
    data = response.get("results")

    if not data or not isinstance(data, list):
        return

    settings_name = kwargs.get("settings_name")
    if not settings_name:
        frappe.log_error(
            title="eTIMS Fetch Error", message="Settings name not provided in kwargs"
        )
        return

    for invoice_data in data:
        try:
            slade_id = invoice_data.get("id")
            if not slade_id:
                continue

            existing_name = frappe.db.get_value(
                "eTIMS Sales Ledger Entry", {"etims_id": slade_id}
            )

            invoice_date = invoice_data.get("invoice_date")
            if invoice_date:
                try:
                    dt_obj = get_datetime(invoice_date)
                    invoice_date = get_datetime_str(dt_obj)
                except Exception:
                    invoice_date = None

            update_values = {
                "etims_settings": settings_name,
                "type": "Sales Invoice",
                "invoice_date": invoice_date,
                "reference_number": invoice_data.get("reference_number"),
                "document_number": invoice_data.get("document_number"),
                "sales_type": invoice_data.get("sales_type"),
                "workflow_state": invoice_data.get("workflow_state"),
                "customer_name": invoice_data.get("customer_name"),
                "total_vat": invoice_data.get("total_vat", 0),
                "total_amount": invoice_data.get("total_amount", 0),
                "total_gross_amount": invoice_data.get("total_gross_amount", 0),
                "tax_exclusive_amount": invoice_data.get("tax_exclusive_amount", 0),
                "tax_inclusive_amount": invoice_data.get("tax_inclusive_amount", 0),
                "is_signed": 1 if invoice_data.get("is_signed") else 0,
            }

            scu_data = invoice_data.get("scu_data") or {}

            scu_fields = {
                "scu_invoice_number": scu_data.get("scu_invoice_number"),
                "scu_receipt_number": scu_data.get("scu_receipt_number"),
                "scu_id": scu_data.get("scu_id"),
                "scu_receipt_signature": scu_data.get("scu_receipt_signature"),
                "scu_receipt_date": scu_data.get("scu_receipt_date"),
                "scu_receipt_time": scu_data.get("scu_receipt_time"),
                "etims_qr_code_url": scu_data.get("qr_code_url"),
                "scu_internal_data": scu_data.get("scu_internal_data"),
                "scu_mrc_number": scu_data.get("scu_mrc_number"),
            }

            for field, value in scu_fields.items():
                if value is not None:
                    update_values[field] = value

            if existing_name:
                for field, value in update_values.items():
                    if value is not None:
                        frappe.db.set_value(
                            "eTIMS Sales Ledger Entry", existing_name, field, value
                        )
                sales_ledger_name = existing_name

                existing_child_records = frappe.get_all(
                    "eTIMS Sales Ledger Item",
                    filters={"parent": sales_ledger_name},
                    pluck="name",
                )
                for child in existing_child_records:
                    frappe.delete_doc("eTIMS Sales Ledger Item", child, force=True)
            else:
                sales_ledger = frappe.new_doc("eTIMS Sales Ledger Entry")
                sales_ledger.etims_id = slade_id
                for field, value in update_values.items():
                    if value is not None:
                        setattr(sales_ledger, field, value)
                sales_ledger.insert(ignore_permissions=True)
                sales_ledger_name = sales_ledger.name

            lines = invoice_data.get("sales_invoice_lines") or []

            for idx, line in enumerate(lines):
                child_doc = frappe.new_doc("eTIMS Sales Ledger Item")
                child_doc.parent = sales_ledger_name
                child_doc.parenttype = "eTIMS Sales Ledger Entry"
                child_doc.parentfield = "sales_invoice_lines"
                child_doc.idx = idx + 1
                child_doc.product_name = line.get("product_name")
                child_doc.quantity = line.get("quantity", 1)
                child_doc.price_inclusive_tax = line.get("price_inclusive_tax", 0)
                child_doc.price_exclusive_tax = line.get("price_exclusive_tax", 0)
                child_doc.tax_code = line.get("tax_code")
                child_doc.tax_code_description = line.get("tax_code_description")
                child_doc.etims_tax_amount = line.get("tax_amount", 0)
                child_doc.gross_line_amount = line.get("gross_line_amount", 0)
                child_doc.tax_exclusive_amount = line.get("tax_exclusive_amount", 0)
                child_doc.tax_inclusive_amount = line.get("tax_inclusive_amount", 0)
                child_doc.total_net_amount = line.get("total_net_amount", 0)
                child_doc.pricelist_name = line.get("pricelist_name")
                child_doc.insert(ignore_permissions=True)

            frappe.db.commit()

            sales_invoice = frappe.db.get_value(
                "eTIMS Sales Ledger Entry", sales_ledger_name, "sales_invoice"
            )
            if sales_invoice:
                update_sales_invoice_etims_details(sales_invoice)

        except Exception as e:
            doc_ref = invoice_data.get("document_number", "Unknown Document")
            frappe.log_error(
                title=f"eTIMS Sync Error - {doc_ref}",
                message=f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}",
            )


def fetch_etims_credit_notes_on_success(response: dict, **kwargs) -> None:
    data = response.get("results")

    if not data or not isinstance(data, list):
        return

    settings_name = kwargs.get("settings_name")
    if not settings_name:
        frappe.log_error(
            title="eTIMS Fetch Error", message="Settings name not provided in kwargs"
        )
        return

    for invoice_data in data:
        try:
            slade_id = invoice_data.get("id")
            if not slade_id:
                continue

            sales_credit_note_lines = invoice_data.get("sales_credit_note_lines") or []
            if not sales_credit_note_lines:
                continue

            existing_name = frappe.db.get_value(
                "eTIMS Sales Ledger Entry", {"etims_id": slade_id}
            )

            created_at = invoice_data.get("created")
            invoice_date = None
            if created_at:
                try:
                    dt_obj = get_datetime(created_at)
                    invoice_date = get_datetime_str(dt_obj)
                except Exception:
                    invoice_date = None

            update_values = {
                "etims_settings": settings_name,
                "type": "Credit Note",
                "invoice_date": invoice_date,
                "reference_number": invoice_data.get("reference_number"),
                "document_number": invoice_data.get("document_number"),
                "workflow_state": invoice_data.get("workflow_state"),
                "total_vat": -abs(invoice_data.get("total_vat") or 0),
                "total_amount": -abs(invoice_data.get("crn_total_amount") or 0),
                "total_gross_amount": -abs(invoice_data.get("total_gross_amount") or 0),
                "is_signed": 1 if invoice_data.get("is_signed") else 0,
                "original_etims_invoice_counter": invoice_data.get(
                    "original_etims_invoice_counter"
                ),
            }

            customer_details = invoice_data.get("customer_details") or {}
            if customer_details.get("partner_name"):
                update_values["customer_name"] = customer_details.get("partner_name")
            if customer_details.get("customer_tax_pin"):
                update_values["customer_tax_id"] = customer_details.get(
                    "customer_tax_pin"
                )

            scu_data = invoice_data.get("scu_data") or {}

            scu_fields = {
                "scu_invoice_number": scu_data.get("scu_invoice_number"),
                "scu_receipt_number": scu_data.get("scu_receipt_number"),
                "scu_id": scu_data.get("scu_id"),
                "scu_receipt_signature": scu_data.get("scu_receipt_signature"),
                "scu_receipt_date": scu_data.get("scu_receipt_date"),
                "scu_receipt_time": scu_data.get("scu_receipt_time"),
                "etims_qr_code_url": scu_data.get("qr_code_url"),
                "scu_internal_data": scu_data.get("scu_internal_data"),
                "scu_mrc_number": scu_data.get("scu_mrc_number"),
            }

            for field, value in scu_fields.items():
                if value is not None:
                    update_values[field] = value

            if existing_name:
                for field, value in update_values.items():
                    if value is not None:
                        frappe.db.set_value(
                            "eTIMS Sales Ledger Entry", existing_name, field, value
                        )
                sales_ledger_name = existing_name

                existing_child_records = frappe.get_all(
                    "eTIMS Sales Ledger Item",
                    filters={"parent": sales_ledger_name},
                    pluck="name",
                )
                for child in existing_child_records:
                    frappe.delete_doc("eTIMS Sales Ledger Item", child, force=True)
            else:
                sales_ledger = frappe.new_doc("eTIMS Sales Ledger Entry")
                sales_ledger.etims_id = slade_id
                for field, value in update_values.items():
                    if value is not None:
                        setattr(sales_ledger, field, value)
                sales_ledger.insert(ignore_permissions=True)
                sales_ledger_name = sales_ledger.name

            etims_invoice = frappe.db.get_value(
                "eTIMS Sales Ledger Entry",
                {"etims_id": invoice_data.get("invoice")},
                "name",
            )

            if etims_invoice:
                frappe.db.set_value(
                    "eTIMS Sales Ledger Entry",
                    sales_ledger_name,
                    "etims_invoice",
                    etims_invoice,
                )
                sales_invoice = frappe.db.get_value(
                    "eTIMS Sales Ledger Entry",
                    {"etims_id": invoice_data.get("invoice")},
                    "sales_invoice",
                )
                if sales_invoice:
                    frappe.db.set_value(
                        "eTIMS Sales Ledger Entry",
                        sales_ledger_name,
                        "sales_invoice",
                        sales_invoice,
                    )

            for idx, line in enumerate(sales_credit_note_lines):
                quantity = line.get("quantity", 1)
                price_exclusive_tax = line.get("price_exclusive_tax", 0)
                price_inclusive_tax = line.get("price_inclusive_tax", 0)
                tax_amount = line.get("tax_amount", 0)
                gross_line_amount = line.get("gross_line_amount", 0)
                tax_exclusive_amount = line.get("total_tax_exclusive_amount", 0)
                tax_inclusive_amount = line.get("total_amount_line", 0)
                total_net_amount = line.get("total_tax_exclusive_amount", 0)

                child_doc = frappe.new_doc("eTIMS Sales Ledger Item")
                child_doc.parent = sales_ledger_name
                child_doc.parenttype = "eTIMS Sales Ledger Entry"
                child_doc.parentfield = "sales_invoice_lines"
                child_doc.idx = idx + 1
                child_doc.product_name = line.get("product_name")
                child_doc.quantity = quantity
                child_doc.price_inclusive_tax = -abs(price_inclusive_tax)
                child_doc.price_exclusive_tax = -abs(price_exclusive_tax)
                child_doc.tax_code = line.get("tax_code")
                child_doc.tax_code_description = line.get("tax_code_description")
                child_doc.etims_tax_amount = -abs(tax_amount)
                child_doc.gross_line_amount = -abs(gross_line_amount)
                child_doc.tax_exclusive_amount = -abs(tax_exclusive_amount)
                child_doc.tax_inclusive_amount = -abs(tax_inclusive_amount)
                child_doc.total_net_amount = -abs(total_net_amount)
                child_doc.pricelist_name = line.get("pricelist_name")
                child_doc.insert(ignore_permissions=True)

            frappe.db.commit()

        except Exception as e:
            doc_ref = invoice_data.get("document_number", "Unknown Document")
            frappe.log_error(
                title=f"eTIMS Sync Error - {doc_ref}",
                message=f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}",
            )
