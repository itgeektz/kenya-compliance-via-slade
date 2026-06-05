const doctypeName = "Navari eTims Registered Imported Item";

frappe.ui.form.on(doctypeName, {
  refresh(frm) {
    if (frm.is_new()) return;

    Promise.all([
      frappe.db.get_list("Item", {
        filters: { custom_referenced_imported_item: frm.doc.name },
        fields: ["item_name", "name"],
        limit: 1,
      }),
      frappe.db.get_list("Supplier", {
        filters: { supplier_name: frm.doc.suppliers_name },
        fields: ["name"],
        limit: 1,
      }),
      frappe.db.get_list("Purchase Invoice", {
        filters: [
          ["custom_source_registered_imported_item", "=", frm.doc.name],
          ["docstatus", "in", [0, 1]],
        ],
        fields: ["name"],
        limit: 1,
      }),
    ]).then(([items, suppliers, invoices]) => {
      const itemExists = items.length > 0;
      const supplierExists = suppliers.length > 0;
      const invoiceExists = invoices.length > 0;

      const supplier = suppliers[0]?.name || null;
      const item_name = items[0]?.item_name || null;

      if (!itemExists) {
        frm.add_custom_button(
          __("Create Item"),
          () => {
            frappe.route_options = {
              item_code: frm.doc.product_code || undefined,
              item_name: frm.doc.item_name || undefined,
              item_group: "All Item Groups",
              is_stock_item: frm.doc.task_code !== "3" ? 1 : 0,
              packaging_unit: frm.doc.etims_packaging_unit_code || undefined,
              unit_of_quantity: frm.doc.quantity_unit_code || undefined,
              taxation_type: frm.doc.etims_taxation_type_code || undefined,
              item_classification:
                frm.doc.etims_item_classification_code || undefined,
              custom_item_code_etims: frm.doc.item_code || undefined,
              valuation_rate:
                frm.doc.invoice_foreign_currency_amount && frm.doc.quantity
                  ? parseFloat(frm.doc.invoice_foreign_currency_amount) /
                    parseFloat(frm.doc.quantity)
                  : undefined,
              custom_referenced_imported_item: frm.doc.name,
            };
            frappe.set_route("Form", "Item", "new-item");
          },
          __("eTims Actions"),
        );
      }

      if (!supplierExists) {
        frm.add_custom_button(
          __("Create Supplier"),
          function () {
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.create_supplier_from_fetched_registered_purchases",
              args: {
                request_data: {
                  name: frm.doc.name,
                  supplier_name: frm.doc.suppliers_name,
                  supplier_pin: null,
                  supplier_branch_id: null,
                  supplier_currency: frm.doc.invoice_foreign_currency,
                  supplier_nation: frm.doc.origin_nation_code,
                },
              },
              freeze: true,
              freeze_message: "Creating Supplier...",
              callback: (response) => {
                const newSupplier = response.message;
                if (newSupplier) {
                  frappe.set_route("Form", "Supplier", newSupplier.name);
                } else {
                  frappe.msgprint(
                    __("Failed to create supplier. Please try again."),
                  );
                }
              },
              error: (error) => {
                frappe.msgprint(
                  __(
                    "An error occurred while creating the supplier. Please try again.",
                    error,
                  ),
                );
              },
            });
          },
          __("eTims Actions"),
        );
      }

      if (itemExists && supplierExists && !invoiceExists) {
        frm.add_custom_button(
          __("Create Purchase Invoice"),
          () => {
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.create_purchase_invoice_from_request",
              args: {
                request_data: {
                  name: frm.doc.name,
                  supplier_invoice_no: null,
                  supplier_invoice_date: null,
                  supplier_name: frm.doc.supplier_name,
                  supplier: supplier,
                  exchange_rate: frm.doc.invoice_foreign_currency_rate,
                  currency: frm.doc.invoice_foreign_currency,
                  amount: frm.doc.invoice_foreign_currency_amount,
                  items: [
                    {
                      item_name: item_name,
                      quantity: frm.doc.quantity,
                      unit_price:
                        frm.doc.invoice_foreign_currency_amount &&
                        frm.doc.quantity
                          ? parseFloat(
                              frm.doc.invoice_foreign_currency_amount,
                            ) / parseFloat(frm.doc.quantity)
                          : 0,
                    },
                  ],
                },
              },
              freeze: true,
              freeze_message: "Creating Purchase Invoice...",
              callback: (response) => {
                const newPI = response.message;
                if (newPI) {
                  frappe.set_route("Form", "Purchase Invoice", newPI.name);
                } else {
                  frappe.msgprint(
                    __("Failed to create Purchase Invoice. Please try again."),
                  );
                }
              },
              error: (error) => {
                frappe.msgprint(
                  __(
                    "An error occurred while creating the Purchase Invoice. Please try again.",
                    error,
                  ),
                );
              },
            });
          },
          __("eTims Actions"),
        );
      }
    });
  },
});
