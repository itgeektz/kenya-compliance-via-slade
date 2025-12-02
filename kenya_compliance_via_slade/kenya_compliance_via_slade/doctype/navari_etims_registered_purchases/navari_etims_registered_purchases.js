// Copyright (c) 2024, Navari Ltd and contributors
const doctypeName = "Navari eTims Registered Purchases";

frappe.ui.form.on(doctypeName, {
  refresh: function (frm) {
    let companyName = frappe.boot.sysdefaults.company;

    if (!companyName) {
      frappe.call({
        method: "frappe.client.get_list",
        args: {
          doctype: "Company",
          fields: ["name"],
          limit_page_length: 1,
        },
        async callback(response) {
          if (response.message && response.message.length > 0) {
            companyName = response.message[0].name;
          }
        },
      });
    }

    if (frm.is_new()) return;

    Promise.all([
      frappe.db.get_list("Supplier", {
        filters: { supplier_name: frm.doc.supplier_name },
        fields: ["name"],
        limit: 1,
      }),
      frappe.db.get_list("Purchase Invoice", {
        filters: [
          ["custom_source_registered_purchase", "=", frm.doc.name],
          ["docstatus", "in", [0, 1]],
        ],
        fields: ["name"],
        limit: 1,
      }),
    ]).then(async ([suppliers, invoices]) => {
      const supplierExists = suppliers.length > 0;
      const invoiceExists = invoices.length > 0;

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
                  company_name: companyName,
                  supplier_name: frm.doc.supplier_name,
                  supplier_pin: frm.doc.supplier_pin,
                  supplier_branch_id: frm.doc.supplier_branch_id,
                },
              },
              freeze: true,
              freeze_message: __("Creating Supplier..."),
              callback: (response) => {
                const newSupplier = response.message;
                if (newSupplier) {
                  frappe.set_route("Form", "Supplier", newSupplier.name);
                } else {
                  frappe.msgprint(
                    __("Failed to create supplier. Please try again.")
                  );
                }
              },
              error: (error) => {
                frappe.msgprint(
                  __(
                    "An error occurred while creating the supplier. Please try again.",
                    error
                  )
                );
              },
            });
          },
          __("eTims Actions")
        );
      }

      const itemNames = frm.doc.items.map((i) => i.item_name);
      const existingItems = await frappe.db.get_list("Item", {
        filters: [["item_name", "in", itemNames]],
        fields: ["item_name", "name"],
      });
      const existingItemNames = existingItems.map((i) => i.item_name);

      const missingItems = frm.doc.items.filter(
        (i) => !existingItemNames.includes(i.item_name)
      );

      if (missingItems.length > 0) {
        frm.add_custom_button(
          __("Create Missing Items"),
          function () {
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.create_items_from_fetched_registered",
              args: {
                request_data: {
                  name: frm.doc.name,
                  company_name: companyName,
                  items: missingItems,
                },
              },
              freeze: true,
              freeze_message: __("Creating Missing Items..."),
              callback: (response) => {
                const result = response.message;
                if (result) {
                  const createdItems = result.created || [];
                  const errors = result.errors || [];

                  let msg = "";

                  if (createdItems.length) {
                    msg += "<b>Created Items:</b><br>";
                    createdItems.forEach((itemName) => {
                      const link = frappe.urllib.get_full_url(
                        `/app/item/${encodeURIComponent(itemName)}`
                      );
                      msg += `<a href="${link}" target="_blank">${itemName}</a><br>`;
                    });
                  }

                  if (errors.length) {
                    msg += "<br><b>Errors:</b><br>";
                    errors.forEach((err) => {
                      msg += `${err.item}: ${err.error}<br>`;
                    });
                  }

                  frappe.msgprint(msg);
                  frm.reload_doc();
                } else {
                  frappe.msgprint(
                    __("Failed to create missing items. Please try again.")
                  );
                }
              },
              error: (error) => {
                frappe.msgprint(
                  __(
                    "An error occurred while creating the missing items. Please try again."
                  )
                );
              },
            });
          },
          __("eTims Actions")
        );
      }

      if (
        !invoiceExists &&
        supplierExists &&
        existingItemNames.length === itemNames.length
      ) {
        frm.add_custom_button(
          __("Create Purchase Invoice"),
          function () {
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.create_purchase_invoice_from_request",
              args: {
                request_data: {
                  name: frm.doc.name,
                  company_name: companyName,
                  supplier_name: frm.doc.supplier_name,
                  supplier_pin: frm.doc.supplier_pin,
                  supplier_branch_id: frm.doc.supplier_branch_id,
                  branch: frm.doc.branch,
                  organisation: frm.doc.organisation,
                  supplier_invoice_no: frm.doc.supplier_invoice_number,
                  supplier_invoice_date: frm.doc.sales_date,
                  items: frm.doc.items,
                },
              },
              freeze: true,
              freeze_message: __("Creating Purchase Invoice..."),
              callback: (response) => {
                const newInvoice = response.message;
                if (newInvoice) {
                  frappe.set_route("Form", "Purchase Invoice", newInvoice.name);
                } else {
                  frappe.msgprint(
                    __("Failed to create purchase invoice. Please try again.")
                  );
                }
              },
              error: (error) => {
                frappe.msgprint(
                  __(
                    "An error occurred while creating the purchase invoice. Please try again.",
                    error
                  )
                );
              },
            });
          },
          __("eTims Actions")
        );
      }

      // frm.add_custom_button(
      //   __("Fetch Registered Purchase Details"),
      //   function () {
      //     frappe.call({
      //       method:
      //         "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.perform_purchase_search",
      //       args: {
      //         request_data: {
      //           id: frm.doc.name,
      //           document_name: frm.doc.name,
      //           company_name: companyName,
      //         },
      //       },
      //     });
      //   },
      //   __("eTims Actions")
      // );
    });
  },
});
