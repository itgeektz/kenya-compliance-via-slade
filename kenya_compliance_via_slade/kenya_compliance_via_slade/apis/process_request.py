from typing import Callable

import frappe
import frappe.defaults

from ..doctype.doctype_names_mapping import SETTINGS_DOCTYPE_NAME
from ..utils import (
    get_settings,
    parse_request_data,
)


def process_request(
    request_data: str | dict,
    route_key: str,
    handler_function: Callable,
    request_method: str = "GET",
    doctype: str = SETTINGS_DOCTYPE_NAME,
    error_callback: Callable = None,
    settings_name: str = None,
    company: str = None,
) -> str | None:
    """Create eTims Job Queue entry only. No execution is performed."""

    try:
        if not settings_name and not frappe.db.exists(
            SETTINGS_DOCTYPE_NAME, {"is_active": 1}
        ):
            return

        data = parse_request_data(request_data)

        extracted_company, branch_id, document_name = extract_metadata(data)

        company_name = (
            company
            or extracted_company
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        settings = get_settings(company_name, branch_id, settings_name)

        if not settings or settings.get("is_active") != 1:
            return

        queue_doc = frappe.get_doc(
            {
                "doctype": "eTims Job Queue",
                "route_key": route_key,
                "handler_function": (
                    f"{handler_function.__module__}.{handler_function.__name__}"
                    if handler_function
                    else None
                ),
                "request_method": request_method,
                "status": "Pending",
                "reference_doctype": doctype,
                "reference_docname": document_name
                if document_name and doctype
                else None,
                "company": company_name,
                "settings_name": settings_name or settings.name,
                "request_data": data,
                "retry_count": 0,
                "error_callback": (
                    f"{error_callback.__module__}.{error_callback.__name__}"
                    if error_callback
                    else None
                ),
            }
        )

        queue_doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return queue_doc.name

    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(), title="Error processing request"
        )
        raise


def extract_metadata(data: dict) -> tuple:
    if isinstance(data, list) and data:
        first_entry = data[0]

        company_name = (
            first_entry.get("company")
            or first_entry.get("company_name")
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        branch_id = (
            first_entry.get("branch_id")
            or frappe.defaults.get_user_default("Branch")
            or frappe.get_value("Branch", "name")
        )

        document_name = first_entry.get("document_name", None)

    else:
        company_name = (
            data.pop("company", None)
            or data.pop("company_name", None)
            or frappe.defaults.get_user_default("Company")
            or frappe.get_value("Company", {}, "name")
        )

        branch_id = (
            data.pop("branch_id", None)
            or frappe.defaults.get_user_default("Branch")
            or frappe.get_value("Branch", "name")
        )

        document_name = data.pop("document_name", None)

    return company_name, branch_id, document_name
