import asyncio
import json

import aiohttp
import frappe
import frappe.defaults
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import chunked

from ..background_tasks.task_response_handlers import (
    operation_types_search_on_success,
)
from ..doctype.doctype_names_mapping import (
    COUNTRIES_DOCTYPE_NAME,
    OPERATION_TYPE_DOCTYPE_NAME,
    REGISTERED_PURCHASES_DOCTYPE_NAME,
    SETTINGS_DOCTYPE_NAME,
    SLADE_ID_MAPPING_DOCTYPE_NAME,
    USER_DOCTYPE_NAME,
)
from ..utils import (
    build_return_invoice_payload,
    generate_custom_item_code_etims,
    get_active_settings,
    get_invoice_reference_number,
    get_link_value,
    get_settings,
    make_get_request,
)
from .api_builder import EndpointsBuilder
from .process_request import process_request
from .remote_response_status_handlers import (
    customer_search_on_success,
    customers_search_on_success,
    fetch_matching_items_on_success,
    fetch_matching_partner_on_success,
    imported_item_submission_on_success,
    imported_items_search_on_success,
    initialize_device_submission_on_success,
    item_composition_submission_on_success,
    item_search_on_success,
    purchase_search_on_success,
    sales_information_submission_on_success,
    submit_inventory_on_success,
    update_invoice_info,
    user_details_fetch_on_success,
    user_details_submission_on_success,
    verify_and_fix_invoice_info,
)

endpoints_builder = EndpointsBuilder()


@frappe.whitelist()
def bulk_submit_sales_invoices(
    docs_list: str = None, settings_name: str = None
) -> None:
    from ..overrides.server.sales_invoice import on_submit

    invoices_to_process = []

    if docs_list:
        data = json.loads(docs_list)
        all_sales_invoices = frappe.db.get_all(
            "Sales Invoice",
            {"docstatus": 1, "custom_successfully_submitted": 0},
            ["name"],
        )

        for record in data:
            for invoice in all_sales_invoices:
                if record == invoice.name:
                    invoices_to_process.append(record)
    else:
        all_invoices = frappe.db.get_all(
            "Sales Invoice",
            {"docstatus": 1, "custom_successfully_submitted": 0},
            ["name"],
        )
        invoices_to_process = [invoice.name for invoice in all_invoices]

    for invoice_name in invoices_to_process:
        doc = frappe.get_doc("Sales Invoice", invoice_name, for_update=False)
        frappe.enqueue(on_submit, doc=doc)


@frappe.whitelist()
def bulk_verify_and_resend_invoices(docs_list: str, settings_name: str = None) -> None:
    invoices_to_process = []

    if docs_list:
        data = json.loads(docs_list)
        all_sales_invoices = frappe.db.get_all(
            "Sales Invoice", {"docstatus": 1}, ["name"]
        )

        for record in data:
            for invoice in all_sales_invoices:
                if record == invoice.name:
                    invoices_to_process.append(record)
    else:
        all_invoices = frappe.db.get_all("Sales Invoice", {"docstatus": 1}, ["name"])
        invoices_to_process = [invoice.name for invoice in all_invoices]

    for invoice_name in invoices_to_process:
        doc = frappe.get_doc("Sales Invoice", invoice_name, for_update=False)
        frappe.enqueue(
            get_invoice_details,
            id=None,
            document_name=doc.name,
            invoice_type="Sales Invoice",
            settings_name=settings_name,
            company=doc.company,
        )


@frappe.whitelist()
def bulk_register_items(docs_list: str, settings_name: str = None) -> None:
    item_names = json.loads(docs_list)
    settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )

    if not item_names or not settings:
        return

    for setting in settings:
        for item_name in item_names:
            frappe.enqueue(
                perform_item_registration,
                item_name=item_name,
                settings_name=setting.name,
            )


@frappe.whitelist()
def update_all_items(settings_name: str = None) -> None:
    settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )

    if not settings:
        return

    for setting in settings:
        Item = DocType("Item")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        items = (
            frappe.qb.from_(Item)
            .inner_join(Mapping)
            .on(
                (Mapping.parent == Item.name)
                & (Mapping.parenttype == "Item")
                & (Mapping.etims_setup == setting.name)
            )
            .select(Item.name)
            .where(Item.custom_sent_to_slade == 1)
            .run(as_dict=True)
        )

        for item in items:
            frappe.enqueue(
                perform_item_registration,
                item_name=item.name,
                settings_name=setting.name,
            )


@frappe.whitelist()
def register_all_items(settings_name: str = None) -> None:
    settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )

    if not settings:
        return

    for setting in settings:
        Item = DocType("Item")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        items = (
            frappe.qb.from_(Item)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Item.name)
                & (Mapping.parenttype == "Item")
                & (Mapping.etims_setup == setting.name)
            )
            .select(Item.name)
            .where((Item.custom_sent_to_slade == 0) & (Mapping.name.isnull()))
            .run(as_dict=True)
        )

        for item in items:
            frappe.enqueue(
                perform_item_registration,
                item_name=item.name,
                settings_name=setting.name,
            )


@frappe.whitelist()
def perform_customer_search(request_data: str) -> None:
    """Search customer details in the eTims Server

    Args:
        request_data (str): Data received from the client
    """
    return process_request(
        request_data,
        "CustSearchReq",
        customer_search_on_success,
        request_method="POST",
        doctype="Customer",
    )


@frappe.whitelist()
def perform_item_registration(item_name: str, settings_name: str) -> dict | None:
    """Main function to handle item registration with SLADE"""
    from ..overrides.server.item import autofill_item_etims_fields

    item = frappe.get_doc("Item", item_name)

    if not is_item_eligible_for_registration(item):
        return None

    defaults = autofill_item_etims_fields(
        item_group=item.item_group,
        settings_name=settings_name,
    )

    updates = {}

    for field in validate_required_fields(item):
        if defaults.get(field):
            updates[field] = defaults.get(field)

    if updates:
        frappe.db.set_value("Item", item.name, updates, update_modified=True)
        for k, v in updates.items():
            item.set(k, v)

    missing_fields = validate_required_fields(item)
    if missing_fields:
        frappe.throw(
            _("Missing required ETIMS fields: {0}").format(
                ", ".join(
                    frappe.bold(field.replace("_", " ").title())
                    for field in missing_fields
                )
            )
        )

    if not item.custom_item_code_etims:
        generate_and_set_etims_code(item)

    frappe.enqueue(
        process_request,
        queue="default",
        is_async=True,
        request_data={"name": item.name, "document_name": item.name},
        route_key="ItemsSearchReq",
        handler_function=fetch_matching_items_on_success,
        request_method="GET",
        doctype="Item",
        settings_name=settings_name,
    )


def is_item_eligible_for_registration(item) -> bool:
    """Check if item meets basic registration criteria"""
    return not (item.custom_prevent_etims_registration or item.disabled)


def validate_required_fields(item) -> list:
    """Validate required fields for item registration"""
    required_fields = [
        "custom_item_classification",
        "custom_product_type",
        "custom_item_type",
        "custom_etims_country_of_origin",
        "custom_packaging_unit",
        "custom_unit_of_quantity",
        "custom_taxation_type",
    ]
    return [field for field in required_fields if not item.get(field)]


def generate_and_set_etims_code(item) -> None:
    """Generate and set ETIMS code for item"""
    item.custom_item_code_etims = generate_custom_item_code_etims(item)
    frappe.db.set_value(
        "Item", item.name, "custom_item_code_etims", item.custom_item_code_etims
    )
    frappe.db.commit()


@frappe.whitelist()
def fetch_item_details(request_data: str, settings_name: str) -> None:
    process_request(
        request_data,
        "ItemSearchReq",
        item_search_on_success,
        doctype="Item",
        settings_name=settings_name,
    )


@frappe.whitelist()
def submit_all_suppliers(settings_name: str = None) -> None:
    active_settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )
    if not active_settings:
        return
    for setting in active_settings:

        Supplier = DocType("Supplier")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        query = (
            frappe.qb.from_(Supplier)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Supplier.name)
                & (Mapping.parenttype == "Supplier")
                & (Mapping.etims_setup == setting.name)
            )
            .select(Supplier.name)
            .where((Mapping.name.isnull()))
        )

        suppliers = query.run(as_dict=True)

        for supplier in suppliers:
            frappe.enqueue(
                send_branch_customer_details,
                settings_name=setting.name,
                name=supplier.name,
                is_customer=False,
            )


@frappe.whitelist()
def bulk_submit_suppliers(docs_list: str, settings_name: str = None) -> None:
    suppliers = json.loads(docs_list)
    settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )
    if not suppliers or not settings:
        return

    for setting in settings:
        for supplier in suppliers:
            frappe.enqueue(
                send_branch_customer_details,
                name=supplier,
                is_customer=False,
                settings_name=setting.name,
            )


@frappe.whitelist()
def bulk_submit_customers(docs_list: str, settings_name: str = None) -> None:
    customers = json.loads(docs_list)
    settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )
    if not customers or not settings:
        return

    for setting in settings:
        customer_names = [c.name for c in customers]

        for batch in chunked(customer_names, 100):
            frappe.enqueue(
                process_customer_batch,
                queue="long",
                settings_name=setting.name,
                customers=batch,
            )


@frappe.whitelist()
def submit_all_customers(settings_name: str = None) -> None:
    active_settings = (
        [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)]
        if settings_name
        else get_active_settings()
    )

    if not active_settings:
        return

    for setting in active_settings:
        Customer = DocType("Customer")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

        query = (
            frappe.qb.from_(Customer)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Customer.name)
                & (Mapping.parenttype == "Customer")
                & (Mapping.etims_setup == setting.name)
            )
            .select(Customer.name)
            .where(Mapping.name.isnull())
        )

        customers = query.run(as_dict=True)

        customer_names = [c.name for c in customers]

        for batch in chunked(customer_names, 100):
            frappe.enqueue(
                process_customer_batch,
                queue="long",
                settings_name=setting.name,
                customers=batch,
            )


def process_customer_batch(settings_name: str, customers: list):
    for customer in customers:
        send_branch_customer_details(
            settings_name=settings_name,
            name=customer,
        )


@frappe.whitelist()
def send_branch_customer_details(
    name: str, settings_name: str, is_customer: bool = True
) -> None:
    doctype = "Customer" if is_customer else "Supplier"
    data = frappe.get_doc(doctype, name)

    if (hasattr(data, "disabled") and data.disabled) or (
        hasattr(data, "custom_prevent_etims_registration")
        and data.custom_prevent_etims_registration
    ):
        return

    request_data = (
        {"customer_tax_pin": data.tax_id, "document_name": name}
        if hasattr(data, "tax_id") and data.tax_id is not None
        else {"partner_name": name, "document_name": name}
    )

    process_request(
        request_data,
        route_key="BhfCustSaveReq",
        handler_function=fetch_matching_partner_on_success,
        request_method="GET",
        doctype=doctype,
        settings_name=settings_name,
    )


@frappe.whitelist()
def search_customers_request(
    request_data: str,
    settings_name: str,
) -> None:
    return process_request(
        request_data,
        "CustomersSearchReq",
        customers_search_on_success,
        settings_name=settings_name,
    )


@frappe.whitelist()
def get_customer_details(
    request_data: str,
    settings_name: str,
) -> None:
    return process_request(
        request_data,
        "CustomerSearchReq",
        customers_search_on_success,
        settings_name=settings_name,
    )


@frappe.whitelist()
def get_my_user_details(request_data: str) -> None:
    return process_request(
        request_data,
        "BhfUserSearchReq",
        user_details_fetch_on_success,
        request_method="GET",
        doctype=USER_DOCTYPE_NAME,
    )


@frappe.whitelist()
def get_branch_user_details(request_data: str) -> None:
    return process_request(
        request_data,
        "BhfUserSaveReq",
        user_details_fetch_on_success,
        request_method="GET",
        doctype=USER_DOCTYPE_NAME,
    )


@frappe.whitelist()
def save_branch_user_details(request_data: str) -> None:
    return process_request(
        request_data,
        "BhfUserSaveReq",
        user_details_submission_on_success,
        request_method="POST",
        doctype=USER_DOCTYPE_NAME,
    )


@frappe.whitelist()
def create_branch_user() -> None:
    # TODO: Implement auto-creation through background tasks
    present_users = frappe.db.get_all(
        "User", {"name": ["not in", ["Administrator", "Guest"]]}, ["name", "email"]
    )

    for user in present_users:
        if not frappe.db.exists(USER_DOCTYPE_NAME, {"email": user.email}):
            doc = frappe.new_doc(USER_DOCTYPE_NAME)

            doc.system_user = user.email
            doc.branch_id = frappe.get_value(
                "Branch",
                {"custom_branch_code": frappe.get_value("Branch", "name")},
                ["name"],
            )  # Created users are assigned to Branch 00

            doc.save(ignore_permissions=True)

    frappe.msgprint("Inspect the Branches to make sure they are mapped correctly")


@frappe.whitelist()
def perform_item_search(request_data: str, settings_name: str) -> None:

    process_request(
        request_data,
        "ItemsSearchReq",
        item_search_on_success,
        doctype="Item",
        settings_name=settings_name,
    )


@frappe.whitelist()
def perform_import_item_search(request_data: str | dict, settings_name: str) -> None:
    process_request(
        request_data,
        "ImportItemSearchReq",
        imported_items_search_on_success,
        doctype="Item",
        settings_name=settings_name,
    )


@frappe.whitelist()
def perform_import_item_search_all_branches() -> None:
    all_credentials = frappe.get_all(
        SETTINGS_DOCTYPE_NAME,
        filters={"is_active": 1},
        fields=["name"],
    )

    for credential in all_credentials:
        perform_import_item_search({}, settings_name=credential.name)


@frappe.whitelist()
def perform_purchases_search(request_data: str | dict, settings_name: str) -> None:
    process_request(
        request_data,
        "TrnsPurchaseSalesReq",
        purchase_search_on_success,
        doctype=REGISTERED_PURCHASES_DOCTYPE_NAME,
        settings_name=settings_name,
    )


@frappe.whitelist()
def perform_purchase_search(request_data: str, settings_name: str) -> None:
    process_request(
        request_data,
        "TrnsPurchaseSearchReq",
        purchase_search_on_success,
        doctype=REGISTERED_PURCHASES_DOCTYPE_NAME,
        settings_name=settings_name,
    )


@frappe.whitelist()
def send_entire_stock_balance(settings_name: str) -> None:
    Item = frappe.qb.DocType("Item")
    Mapping = frappe.qb.DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)

    query = (
        frappe.qb.from_(Item)
        .inner_join(Mapping)
        .on(
            (Mapping.parent == Item.name)
            & (Mapping.parenttype == "Item")
            & (Mapping.etims_setup == settings_name)
        )
        .select(Item.name, Item.item_code, Item.item_name)
        .where((Item.is_stock_item == 1) & (Item.custom_sent_to_slade == 1))
    )

    items = query.run(as_dict=True)

    for item in items:
        frappe.enqueue(submit_inventory, name=item.name, settings_name=settings_name)


@frappe.whitelist()
def submit_inventory(name: str, settings_name: str) -> None:
    # TODO: Redesign this function to work with the new structure for Stock Submission
    # pass
    if not name:
        frappe.throw("Item name is required.")

    settings = get_settings(settings_name=settings_name)

    if not settings:
        return

    request_data = {
        "document_name": name,
        "inventory_reference": name,
        "description": f"{name} Stock Adjustment for {name}",
        "reason": "Opening Stock",
        "source_organisation_unit": get_link_value(
            "Department",
            "name",
            settings.organisation_mapping[0].department,
            "custom_slade_id",
        ),
        "location": get_link_value(
            "Warehouse",
            "name",
            settings.organisation_mapping[0].get("warehouse"),
            "custom_slade_id",
        ),
    }
    process_request(
        request_data,
        route_key="StockMasterSaveReq",
        handler_function=submit_inventory_on_success,
        request_method="POST",
        doctype="Item",
        settings_name=settings_name,
    )


@frappe.whitelist()
def update_stock_quantity(name: str, id: str) -> None:
    if not name:
        frappe.throw("Item name is required.")

    stock_levels = frappe.db.get_all(
        "Bin",
        filters={"item_code": name},
        fields=["actual_qty"],
    )

    if not stock_levels:
        frappe.log_error(
            f"No stock levels found for item {name}.", "Stock Update Error"
        )
    else:
        request_data = {
            "id": id,
            "document_name": name,
            "quantity": sum(
                [float(stock.get("actual_qty", 0)) for stock in stock_levels]
            ),
        }
        process_request(
            request_data,
            route_key="SaveStockBalanceReq",
            # handler_function=submit_inventory_on_success,
            request_method="PATCH",
            doctype="Item",
        )


@frappe.whitelist()
def send_imported_item_request(request_data: str) -> None:
    process_request(
        request_data,
        "ImportItemSearchReq",
        imported_item_submission_on_success,
        request_method="POST",
        doctype="Item",
    )


@frappe.whitelist()
def update_imported_item_request(request_data: str) -> None:
    process_request(
        request_data,
        "ImportItemUpdateReq",
        imported_item_submission_on_success,
        method="PUT",
        doctype="Item",
    )


@frappe.whitelist()
def submit_item_composition(name: str) -> None:
    item = frappe.get_doc("BOM", name)
    request_data = {
        "final_product": get_link_value("Item", "name", item.item, "custom_slade_id"),
        "document_name": name,
    }
    process_request(
        request_data,
        "BOMReq",
        item_composition_submission_on_success,
        request_method="POST",
        doctype="BOM",
    )


@frappe.whitelist()
def create_supplier_from_fetched_registered_purchases(request_data: str) -> Document:
    data: dict = json.loads(request_data)

    new_supplier = create_supplier(data)

    return new_supplier


def create_supplier(supplier_details: dict) -> Document:
    new_supplier = frappe.new_doc("Supplier")

    new_supplier.supplier_name = supplier_details["supplier_name"]
    new_supplier.tax_id = supplier_details["supplier_pin"]
    new_supplier.require_tax_id = 0
    new_supplier.custom_supplier_branch = supplier_details["supplier_branch_id"]

    if "supplier_currency" in supplier_details:
        new_supplier.default_currency = supplier_details["supplier_currency"]

    if "supplier_nation" in supplier_details:
        new_supplier.country = supplier_details["supplier_nation"].capitalize()

    new_supplier.insert(ignore_if_duplicate=True)

    return new_supplier


@frappe.whitelist()
def create_items_from_fetched_registered(request_data: str) -> None:
    data = json.loads(request_data)

    if data.get("items"):
        created = []
        errors = []
        for item in data["items"]:
            try:
                new_item = create_item(item)
                created.append(new_item.name if hasattr(new_item, "name") else new_item)
            except Exception as e:
                frappe.log_error(
                    message=frappe.get_traceback(),
                    title="create_items_from_fetched_registered error",
                )
                errors.append(
                    {
                        "item": item.get("item_code") or item.get("item_name"),
                        "error": str(e),
                    }
                )

        return {"created": created, "errors": errors}


def create_item(item: dict | frappe._dict) -> Document:
    item_code = item.get("item_code", None)

    new_item = frappe.new_doc("Item")
    new_item.is_stock_item = 0  # Default to 0
    new_item.item_code = item["item_code"]
    new_item.item_name = item["item_name"]
    new_item.item_group = "All Item Groups"
    if "item_classification_code" in item:
        new_item.custom_item_classification = item["item_classification_code"]
    new_item.custom_packaging_unit = item["packaging_unit_code"]
    new_item.custom_unit_of_quantity = (
        item.get("quantity_unit_code", None) or item["unit_of_quantity_code"]
    )
    new_item.custom_taxation_type = item["taxation_type_code"]
    new_item.custom_etims_country_of_origin = (
        frappe.get_doc(
            COUNTRIES_DOCTYPE_NAME,
            {"code": item_code[:2]},
            for_update=False,
        ).name
        if item_code
        else None
    )
    new_item.custom_product_type = item_code[2:3] if item_code else None

    if item_code and int(item_code[2:3]) != 3:
        new_item.is_stock_item = 1
    else:
        new_item.is_stock_item = 0

    new_item.custom_item_code_etims = item["item_code"]
    new_item.valuation_rate = item["unit_price"]

    if "imported_item" in item:
        new_item.is_stock_item = 1
        new_item.custom_referenced_imported_item = item["imported_item"]

    new_item.insert(ignore_mandatory=True, ignore_if_duplicate=True)

    return new_item


@frappe.whitelist()
def create_purchase_invoice_from_request(request_data: str) -> Document:
    data = json.loads(request_data)

    if not data.get("company_name"):
        data["company_name"] = frappe.defaults.get_user_default(
            "Company"
        ) or frappe.get_value("Company", {}, "name")

    # Check if supplier exists
    supplier = data.get("supplier", None)
    if not supplier and not frappe.db.exists(
        "Supplier", data["supplier_name"], cache=False
    ):
        supplier = create_supplier(data).name

    set_warehouse = frappe.get_value(
        "Warehouse", {"is_group": 0, "company": data["company_name"]}, "name"
    )  # use first warehouse

    currency = data.get("currency") or frappe.get_value(
        "Company", data["company_name"], "default_currency"
    )

    # Create the Purchase Invoice
    purchase_invoice = frappe.new_doc("Purchase Invoice")
    purchase_invoice.supplier = supplier or data["supplier_name"]
    purchase_invoice.update_stock = 1
    purchase_invoice.set_warehouse = set_warehouse
    purchase_invoice.company = data["company_name"]
    purchase_invoice.bill_no = data["supplier_invoice_no"]
    purchase_invoice.bill_date = data["supplier_invoice_date"]

    if "currency" in data:
        purchase_invoice.currency = currency
        purchase_invoice.custom_source_registered_imported_item = data["name"]
    else:
        purchase_invoice.custom_source_registered_purchase = data["name"]

    if "exchange_rate" in data:
        purchase_invoice.conversion_rate = data["exchange_rate"]

    purchase_invoice.set("items", [])

    expense_account = get_or_create_account(
        account_type="Cost of Goods Sold",
        account_name_template="Cost of Goods Sold",
        company=data["company_name"],
        currency=currency,
    )

    credit_to_account = get_or_create_account(
        account_type="Payable",
        company=data["company_name"],
        account_name_template="Creditors",
        currency=currency,
    )
    purchase_invoice.credit_to = credit_to_account

    for item in data["items"]:
        matching_item = frappe.get_all(
            "Item",
            filters={
                "item_name": item["item_name"],
            },
            fields=["name"],
        )
        item_code = matching_item[0]["name"]

        item_doc = {
            "item_name": item["item_name"],
            "item_code": item_code,
            "qty": item.get("quantity") or 1,
            "rate": item.get("unit_price") or 0,
            "expense_account": expense_account,
        }

        if item.get("discount_amount") not in (None, ""):
            item_doc["discount_amount"] = item["discount_amount"]
        if item.get("total_amount") not in (None, ""):
            item_doc["net_amount"] = item["total_amount"]
        if item.get("tax_amount") not in (None, ""):
            tax_amount = float(item.get("tax_amount") or 0.0)
            total_amount = float(item.get("total_amount") or 0.0) - tax_amount
            net_rate = total_amount / float(item_doc["qty"]) if item_doc["qty"] else 0.0
            custom_tax_rate = (
                (tax_amount / total_amount * 100.0) if total_amount else 0.0
            )
            item_doc["custom_tax_rate"] = custom_tax_rate
            item_doc["net_amount"] = total_amount
            item_doc["rate"] = net_rate

            purchase_invoice.append(
                "taxes",
                {
                    "charge_type": "On Net Total",
                    "account_head": get_link_value(
                        "Account",
                        "name",
                        "VAT - " + data["company_name"],
                        "account_name",
                    ),
                    "description": "Tax for " + item["item_name"],
                    "rate": custom_tax_rate,
                },
            )

        purchase_invoice.append("items", item_doc)

    purchase_invoice.insert(ignore_mandatory=True)

    return purchase_invoice


def get_or_create_account(
    account_type: str, company: str, currency: str, account_name_template: str = None
) -> str:
    if account_name_template:
        account = frappe.db.get_value(
            "Account",
            filters=[
                ["account_type", "=", account_type],
                ["company", "=", company],
                ["account_currency", "=", currency],
                ["account_name", "like", f"%{account_name_template}%"],
            ],
            fieldname="name",
        )
    else:
        account = frappe.db.get_value(
            "Account",
            {
                "account_type": account_type,
                "company": company,
                "account_currency": currency,
            },
            "name",
        )

    if account:
        return account

    template_account = frappe.get_all(
        "Account",
        filters={
            "account_type": account_type,
            "company": company,
            "is_group": 0,
            "account_name": ["like", f"%{account_name_template}%"],
        },
        fields=["name"],
        limit=1,
    )

    if not template_account:
        frappe.throw(
            f"No template account found for type '{account_type}' in company {company}"
        )

    template = frappe.get_doc("Account", template_account[0].name)

    new_account = frappe.new_doc("Account")

    base_name = (
        account_name_template if account_name_template else template.account_name
    )
    new_account.update(
        {
            "account_name": f"{base_name} - {currency}",
            "account_currency": currency,
            "company": company,
            "parent_account": template.parent_account,
            "root_type": template.root_type,
            "report_type": template.report_type,
            "account_type": template.account_type,
            "is_group": template.is_group,
            "freeze_account": template.freeze_account,
            "balance_must_be": template.balance_must_be,
            "account_number": None,
        }
    )

    new_account.insert(ignore_mandatory=True)
    frappe.db.commit()
    return new_account.name


@frappe.whitelist()
def ping_server(request_data: str) -> None:
    data = json.loads(request_data)
    server_url = data.get("server_url")
    auth_url = data.get("auth_url")

    async def check_server(url: str) -> tuple:
        try:
            response = await make_get_request(url)
            return "Online", response
        except aiohttp.client_exceptions.ClientConnectorError:
            return "Offline", None

    async def main() -> None:
        server_status, server_response = await check_server(server_url)
        auth_status, auth_response = await check_server(auth_url)

        if server_response:
            frappe.msgprint(f"Server Status: {server_status}\n{server_response}")
        else:
            frappe.msgprint(f"Server Status: {server_status}")

        frappe.msgprint(f"Auth Server Status: {auth_status}")

    asyncio.run(main())


@frappe.whitelist()
def create_stock_entry_from_stock_movement(request_data: str) -> None:
    data = json.loads(request_data)

    for item in data["items"]:
        if not frappe.db.exists("Item", item["item_name"], cache=False):
            # Create item if item doesn't exist
            create_item(item)

    # Create stock entry
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Material Transfer"

    stock_entry.set("items", [])

    source_warehouse = frappe.get_value(
        "Warehouse",
        {"custom_branch": data["branch_id"]},
        ["name"],
        as_dict=True,
    )

    target_warehouse = frappe.get_value(
        "Warehouse",
        {"custom_branch": "01"},  # TODO: Fix hardcode from 01 to a general solution
        ["name"],
        as_dict=True,
    )

    for item in data["items"]:
        stock_entry.append(
            "items",
            {
                "s_warehouse": source_warehouse.name,
                "t_warehouse": target_warehouse.name,
                "item_code": item["item_name"],
                "qty": item["quantity"],
            },
        )

    stock_entry.save(ignore_permissions=True)

    frappe.msgprint(f"Stock Entry {stock_entry.name} created successfully")


@frappe.whitelist()
def initialize_device(request_data: str) -> None:
    return process_request(
        request_data,
        "DeviceVerificationReq",
        initialize_device_submission_on_success,
        request_method="POST",
        doctype=SETTINGS_DOCTYPE_NAME,
    )


@frappe.whitelist()
def _process_invoice_fetch_request(
    id: str = None,
    document_name: str = None,
    invoice_type: str = "Sales Invoice",
    settings_name: str = None,
    company: str = None,
    handler_function=None,
    reference_number: str = None,
    is_return: bool = False,
    original_invoice_id: str = None,
) -> None:
    """Common helper function to process invoice-related requests."""
    invoice = frappe.get_doc(invoice_type, document_name)

    if is_return and not original_invoice_id:
        frappe.throw("Original invoice ID is required for return processing.")

    request_data = {
        "document_name": document_name,
        "company": company or invoice.company,
    }

    route_key = "TrnsSalesSearchReq"

    if invoice.is_return or is_return:
        route_key = "SalesCreditNoteSaveReq"

    if id:
        request_data["id"] = id
    else:
        if (invoice.is_return and invoice.return_against) or (
            is_return and original_invoice_id
        ):
            route_key = "SalesCreditNoteSaveReq"
            original_invoice_slade_id = (
                original_invoice_id
                if is_return
                else frappe.db.get_value(
                    "Sales Invoice", invoice.return_against, "custom_slade_id"
                )
            )
            request_data["invoice"] = original_invoice_slade_id
        else:
            route_key = "TrnsSalesSaveWrReq"
            request_data["reference_number"] = reference_number

    return process_request(
        request_data,
        route_key,
        handler_function,
        doctype=invoice_type,
        settings_name=settings_name,
        company=company,
    )


@frappe.whitelist()
def get_invoice_details(
    id: str = None,
    document_name: str = None,
    invoice_type: str = "Sales Invoice",
    settings_name: str = None,
    company: str = None,
) -> None:
    invoice = frappe.get_doc(invoice_type, document_name)
    reference_number = get_invoice_reference_number(invoice)
    _process_invoice_fetch_request(
        id=None,
        document_name=document_name,
        invoice_type=invoice_type,
        settings_name=settings_name,
        company=company,
        handler_function=update_invoice_info,
        reference_number=reference_number,
    )


@frappe.whitelist()
def verify_invoice_details(
    id: str = None,
    document_name: str = None,
    invoice_type: str = "Sales Invoice",
    settings_name: str = None,
    company: str = None,
) -> None:
    invoice = frappe.get_doc(invoice_type, document_name)
    reference_number = get_invoice_reference_number(invoice)
    _process_invoice_fetch_request(
        id=id,
        document_name=document_name,
        invoice_type=invoice_type,
        settings_name=settings_name,
        company=company,
        handler_function=verify_and_fix_invoice_info,
        reference_number=reference_number,
    )


@frappe.whitelist()
def save_operation_type(name: str) -> dict | None:
    item = frappe.get_doc(OPERATION_TYPE_DOCTYPE_NAME, name)
    slade_id = item.get("slade_id", None)

    route_key = "OperationTypesReq"
    if item.get("destination_location") and item.get("source_location"):
        request_data = {
            "operation_name": item.get("operation_name"),
            "document_name": item.get("name"),
            "operation_type": item.get("operation_type"),
            "organisation": get_link_value(
                "Company",
                "name",
                item.get("company"),
                "custom_slade_id",
            ),
            "destination_location": item.get("destination_location"),
            "source_location": item.get("source_location"),
            "active": False if item.get("active") == 0 else True,
        }

        if slade_id:
            request_data["id"] = slade_id
            method = "PATCH"
        else:
            method = "POST"

        process_request(
            request_data,
            route_key=route_key,
            handler_function=operation_types_search_on_success,
            request_method=method,
            doctype=OPERATION_TYPE_DOCTYPE_NAME,
        )
    return None


@frappe.whitelist()
def sync_operation_type(request_data: str) -> None:
    process_request(
        request_data,
        "OperationTypeReq",
        operation_types_search_on_success,
        doctype=OPERATION_TYPE_DOCTYPE_NAME,
    )


@frappe.whitelist()
def submit_credit_note(
    response: dict, document_name: str, doctype: str, settings_name: str, **kwargs
) -> None:
    doc = frappe.get_doc(doctype, document_name)
    data = response.get("results", [])[0] if response.get("results") else response
    scu_data = data.get("scu_data")
    if not scu_data:
        return
    payload = build_return_invoice_payload(doc, data)
    frappe.enqueue(
        process_request,
        queue="default",
        is_async=True,
        request_data=payload,
        route_key="CreditNoteSaveReq",
        handler_function=sales_information_submission_on_success,
        request_method="POST",
        doctype=doctype,
        settings_name=settings_name,
        company=doc.company,
    )
