from .create_fields_from_json import create_fields_from_json


def execute() -> None:
    create_fields_from_json("./custom_fields/bom_item.json", "BOM Item")
    create_fields_from_json("./custom_fields/bom.json", "BOM")
    create_fields_from_json("./custom_fields/branch.json", "Branch")
    create_fields_from_json("./custom_fields/company.json", "Company")
    create_fields_from_json("./custom_fields/currency.json", "Currency")
    create_fields_from_json("./custom_fields/customer.json", "Customer")
    create_fields_from_json("./custom_fields/department.json", "Department")
    create_fields_from_json("./custom_fields/item_tax_template.json", "Item Tax Template")
    create_fields_from_json("./custom_fields/item.json", "Item")
    create_fields_from_json("./custom_fields/mode_of_payment.json", "Mode of Payment")
    create_fields_from_json("./custom_fields/sales_invoice.json", "Sales Invoice")
    create_fields_from_json("./custom_fields/sales_invoice_item.json", "Sales Invoice Item")
    create_fields_from_json("./custom_fields/purchase_invoice_item.json", "Purchase Invoice Item")
    create_fields_from_json("./custom_fields/purchase_invoice.json", "Purchase Invoice")
    create_fields_from_json("./custom_fields/stock_ledger_entry.json", "Stock Ledger Entry")
    create_fields_from_json("./custom_fields/supplier.json", "Supplier")
    create_fields_from_json("./custom_fields/warehouse.json", "Warehouse")
