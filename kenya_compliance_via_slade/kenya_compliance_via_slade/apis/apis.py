import asyncio
import json

import aiohttp
import frappe
import frappe.defaults
from frappe.model.document import Document
from frappe.query_builder import DocType

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
def bulk_submit_sales_invoices(docs_list: str = None, settings_name: str = None) -> None:
    from ..overrides.server.sales_invoice import on_submit

    invoices_to_process = []
    
    if docs_list:
        data = json.loads(docs_list)
        all_sales_invoices = frappe.db.get_all(
            "Sales Invoice", {"docstatus": 1, "custom_successfully_submitted": 0}, ["name"]
        )
        
        for record in data:
            for invoice in all_sales_invoices:
                if record == invoice.name:
                    invoices_to_process.append(record)
    else:
        all_invoices = frappe.db.get_all(
            "Sales Invoice", {"docstatus": 1, "custom_successfully_submitted": 0}, ["name"]
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
        all_invoices = frappe.db.get_all(
            "Sales Invoice", {"docstatus": 1}, ["name"]
        )
        invoices_to_process = [invoice.name for invoice in all_invoices]
    
    for invoice_name in invoices_to_process:
        doc = frappe.get_doc("Sales Invoice", invoice_name, for_update=False)
        frappe.enqueue(
            get_invoice_details, 
            id=None,
            document_name=doc.name, 
            invoice_type="Sales Invoice",
            settings_name=settings_name,
            company=doc.company
        )

@frappe.whitelist()
def bulk_register_items(docs_list: str, settings_name: str = None) -> None:
    item_names = json.loads(docs_list)
    settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    
    if not item_names or not settings:
        return
    
    for setting in settings:
        for item_name in item_names:
            frappe.enqueue(
                perform_item_registration,
                item_name=item_name,
                settings_name=setting.name
            )


@frappe.whitelist()
def update_all_items(settings_name: str = None) -> None:
    settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    
    if not settings:
        return
    
    for setting in settings:
        Item = DocType("Item")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)
        
        items = (
            frappe.qb.from_(Item)
            .inner_join(Mapping)
            .on(
                (Mapping.parent == Item.name) &
                (Mapping.parenttype == "Item") &
                (Mapping.etims_setup == setting.name)
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
    settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()

    if not settings:
        return

    for setting in settings:
        Item = DocType("Item")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)
        
        items = (
            frappe.qb.from_(Item)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Item.name) &
                (Mapping.parenttype == "Item") &
                (Mapping.etims_setup == setting.name)
            )
            .select(Item.name)
            .where(
                (Item.custom_sent_to_slade == 0) &
                (Mapping.name.isnull())
            )
            .run(as_dict=True)
        )
        
        for item in items:
            frappe.enqueue(
                perform_item_registration,
                item_name=item.name,
                settings_name=setting.name
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
    item = frappe.get_doc("Item", item_name)

    if not is_item_eligible_for_registration(item):
        return None

    missing_fields = validate_required_fields(item)
    if missing_fields:
        return None

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
        "custom_etims_country_of_origin_code",
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
        request_data, "ItemSearchReq", item_search_on_success, doctype="Item", settings_name=settings_name
    )


@frappe.whitelist()
def submit_all_suppliers(settings_name: str = None) -> None:
    active_settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    if not active_settings:
        return
    for setting in active_settings:
        
        Supplier = DocType("Supplier")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)
        
        query = (
            frappe.qb.from_(Supplier)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Supplier.name) & 
                (Mapping.parenttype == "Supplier") & 
                (Mapping.etims_setup == setting.name)
            )
            .select(Supplier.name)
            .where(
                (Mapping.name.isnull())
            )
        )
        
        suppliers = query.run(as_dict=True)
                
        for supplier in suppliers:
            frappe.enqueue(
                send_branch_customer_details, 
                settings_name=setting.name, 
                name=supplier.name, 
                is_customer=False
            )

            
            
@frappe.whitelist()
def bulk_submit_suppliers(docs_list: str, settings_name: str = None) -> None:
    suppliers = json.loads(docs_list)
    settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    if not suppliers or not settings:
        return
    
    for setting in settings:
        for supplier in suppliers:
            frappe.enqueue(
                send_branch_customer_details,
                name=supplier, 
                is_customer=False,
                settings_name=setting.name
            )
            
            
@frappe.whitelist()
def bulk_submit_customers(docs_list: str, settings_name: str = None) -> None:
    customers = json.loads(docs_list)
    settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    if not customers or not settings:
        return
    
    for setting in settings:
        for customer in customers:
            frappe.enqueue(
                send_branch_customer_details,
                name=customer, 
                is_customer=True,
                settings_name=setting.name
            )

@frappe.whitelist()
def submit_all_customers(settings_name: str = None) -> None:
    active_settings = [frappe.get_doc(SETTINGS_DOCTYPE_NAME, settings_name)] if settings_name else get_active_settings()
    if not active_settings:
        return
    for setting in active_settings:
        
        Customer = DocType("Customer")
        Mapping = DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)
        
        query = (
            frappe.qb.from_(Customer)
            .left_join(Mapping)
            .on(
                (Mapping.parent == Customer.name) & 
                (Mapping.parenttype == "Customer") & 
                (Mapping.etims_setup == setting.name)
            )
            .select(Customer.name)
            .where( 
                (Mapping.name.isnull())
            )
        )
        
        customers = query.run(as_dict=True)
        
        for customer in customers:
            frappe.enqueue(
                send_branch_customer_details, 
                settings_name=setting.name, 
                name=customer.name
            )


@frappe.whitelist()
def send_branch_customer_details(name: str, settings_name: str, is_customer: bool = True) -> None:
    doctype = "Customer" if is_customer else "Supplier"
    data = frappe.get_doc(doctype, name)

    if (hasattr(data, 'disabled') and data.disabled) or (hasattr(data, 'custom_prevent_etims_registration') and data.custom_prevent_etims_registration):
        return
    
    request_data = (
        {"customer_tax_pin": data.tax_id, "document_name": name} 
        if hasattr(data, 'tax_id') and data.tax_id is not None 
        else {"partner_name": name, "document_name": name}
    )

    frappe.enqueue(
        process_request,
        queue="default",
        is_async=True,
        request_data=request_data,
        route_key="BhfCustSaveReq",
        handler_function=fetch_matching_partner_on_success,
        request_method="GET",
        doctype=doctype,
        settings_name=settings_name,
    )
    

@frappe.whitelist()
def search_customers_request(request_data: str, settings_name: str,) -> None:
    return process_request(
        request_data, "CustomersSearchReq", customers_search_on_success, settings_name=settings_name
    )


@frappe.whitelist()
def get_customer_details(request_data: str, settings_name: str,) -> None:
    return process_request(
        request_data, "CustomerSearchReq", customers_search_on_success, settings_name=settings_name
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
        request_data, "ItemsSearchReq", item_search_on_success, doctype="Item", settings_name=settings_name
    )


@frappe.whitelist()
def perform_import_item_search(request_data: str, settings_name: str) -> None:
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
        ["name", "bhfid", "company"],
    )

    for credential in all_credentials:
        request_data = json.dumps(
            {"company_name": credential.company, "branch_code": credential.bhfid}
        )

        perform_import_item_search(request_data, settings_name=credential.name)


@frappe.whitelist()
def perform_purchases_search(request_data: str) -> None:
    process_request(
        request_data,
        "TrnsPurchaseSalesReq",
        purchase_search_on_success,
        doctype=REGISTERED_PURCHASES_DOCTYPE_NAME,
    )


@frappe.whitelist()
def perform_purchase_search(request_data: str) -> None:
    process_request(
        request_data,
        "TrnsPurchaseSearchReq",
        purchase_search_on_success,
        doctype=REGISTERED_PURCHASES_DOCTYPE_NAME,
    )

@frappe.whitelist()
def send_entire_stock_balance(settings_name: str) -> None:
    Item = frappe.qb.DocType("Item")
    Mapping = frappe.qb.DocType(SLADE_ID_MAPPING_DOCTYPE_NAME)
    
    query = (
        frappe.qb.from_(Item)
        .inner_join(Mapping)
        .on(
            (Mapping.parent == Item.name) &
            (Mapping.parenttype == "Item") &
            (Mapping.etims_setup == settings_name)
        )
        .select(Item.name, Item.item_code, Item.item_name)
        .where(
            (Item.is_stock_item == 1) &
            (Item.custom_sent_to_slade == 1)
        )
    )
    
    items = query.run(as_dict=True)
    
    for item in items:
        frappe.enqueue(
            submit_inventory,
            name=item.name,
            settings_name=settings_name
        )


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
def create_supplier_from_fetched_registered_purchases(request_data: str) -> None:
    data: dict = json.loads(request_data)

    new_supplier = create_supplier(data)

    frappe.msgprint(f"Supplier: {new_supplier.name} created")


def create_supplier(supplier_details: dict) -> Document:
    new_supplier = frappe.new_doc("Supplier")

    new_supplier.supplier_name = supplier_details["supplier_name"]
    new_supplier.tax_id = supplier_details["supplier_pin"]
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

    if data["items"]:
        items = data["items"]
        for item in items:
            create_item(item)


def create_item(item: dict | frappe._dict) -> Document:
    item_code = item.get("item_code", None)

    new_item = frappe.new_doc("Item")
    new_item.is_stock_item = 0  # Default to 0
    new_item.item_code = item["product_code"]
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
def create_purchase_invoice_from_request(request_data: str) -> None:
    data = json.loads(request_data)

    if not data.get("company_name"):
        data["company_name"] = frappe.defaults.get_user_default(
            "Company"
        ) or frappe.get_value("Company", {}, "name")

    # Check if supplier exists
    supplier = None
    if not frappe.db.exists("Supplier", data["supplier_name"], cache=False):
        supplier = create_supplier(data).name

    all_items = []
    all_existing_items = {
        item["name"]: item for item in frappe.db.get_all("Item", ["*"])
    }

    for received_item in data["items"]:
        # Check if item exists
        if received_item["item_name"] not in all_existing_items:
            created_item = create_item(received_item)
            all_items.append(created_item)

    set_warehouse = frappe.get_value(
        "Warehouse",
        {"custom_branch": data["branch"]},
        ["name"],
        as_dict=True,
    )

    if not set_warehouse:
        set_warehouse = frappe.get_value(
            "Warehouse", {"is_group": 0, "company": data["company_name"]}, "name"
        )  # use first warehouse match if not available for the branch

    # Create the Purchase Invoice
    purchase_invoice = frappe.new_doc("Purchase Invoice")
    purchase_invoice.supplier = supplier or data["supplier_name"]
    purchase_invoice.supplier = supplier or data["supplier_name"]
    purchase_invoice.update_stock = 1
    purchase_invoice.set_warehouse = set_warehouse
    purchase_invoice.branch = data["branch"]
    purchase_invoice.company = data["company_name"]
    purchase_invoice.custom_slade_organisation = data["organisation"]
    purchase_invoice.bill_no = data["supplier_invoice_no"]
    purchase_invoice.bill_date = data["supplier_invoice_date"]
    purchase_invoice.bill_date = data["supplier_invoice_date"]

    if "currency" in data:
        # The "currency" key is only available when creating from Imported Item
        purchase_invoice.currency = data["currency"]
        purchase_invoice.custom_source_registered_imported_item = data["name"]
    else:
        purchase_invoice.custom_source_registered_purchase = data["name"]

    if "exchange_rate" in data:
        purchase_invoice.conversion_rate = data["exchange_rate"]

    purchase_invoice.set("items", [])

    # TODO: Remove Hard-coded values
    purchase_invoice.custom_purchase_type = "Copy"
    purchase_invoice.custom_receipt_type = "Purchase"
    purchase_invoice.custom_payment_type = "CASH"
    purchase_invoice.custom_purchase_status = "Approved"

    company_abbr = frappe.get_value(
        "Company", {"name": frappe.defaults.get_user_default("Company")}, ["abbr"]
    )
    expense_account = frappe.db.get_value(
        "Account",
        {
            "name": [
                "like",
                f"%Cost of Goods Sold%{company_abbr}",
            ]
        },
        ["name"],
    )

    for item in data["items"]:
        matching_item = frappe.get_all(
            "Item",
            filters={
                "item_name": item["item_name"],
                "custom_item_classification": item["item_classification_code"],
            },
            fields=["name"],
        )
        item_code = matching_item[0]["name"]
        purchase_invoice.append(
            "items",
            {
                "item_name": item["item_name"],
                "item_code": item_code,
                "qty": item["quantity"],
                "rate": item["unit_price"],
                "expense_account": expense_account,
                "custom_item_classification": item["item_classification_code"],
                "custom_packaging_unit": item["packaging_unit_code"],
                "custom_unit_of_quantity": item["quantity_unit_code"],
                "custom_taxation_type": item["taxation_type_code"],
            },
        )

    purchase_invoice.insert(ignore_mandatory=True)

    frappe.msgprint("Purchase Invoices have been created")


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
    handler_function = None,
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
        if (invoice.is_return and invoice.return_against) or (is_return and original_invoice_id):
            route_key = "SalesCreditNoteSaveReq"
            original_invoice_slade_id = original_invoice_id if is_return else frappe.db.get_value("Sales Invoice", invoice.return_against, "custom_slade_id")
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
    id: str = None, document_name: str = None, invoice_type: str = "Sales Invoice", settings_name: str = None, company: str = None
) -> None:
    invoice = frappe.get_doc(invoice_type, document_name)
    reference_number = get_invoice_reference_number(invoice)
    _process_invoice_fetch_request(
        id=id,
        document_name=document_name,
        invoice_type=invoice_type,
        settings_name=settings_name,
        company=company,
        handler_function=update_invoice_info,
        reference_number=reference_number,
    )


@frappe.whitelist()
def verify_invoice_details(
    id: str = None, document_name: str = None, invoice_type: str = "Sales Invoice", settings_name: str = None, company: str = None
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
