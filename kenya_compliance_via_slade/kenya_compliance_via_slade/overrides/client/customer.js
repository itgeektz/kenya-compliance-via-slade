const doctype = "Customer";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.ui.form.on(doctype, {
  refresh: async function (frm) {
    const companyName = frappe.boot.sysdefaults.company;
    let currency = frm.doc.default_currency || "KES";
    const { message: activeSetting } = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_setting",
      args: {
        doctype: settingsDoctypeName,
      },
    });

    if (activeSetting?.message?.name) {
      frappe.call({
        method: "frappe.client.get_value",
        args: {
          doctype: "Currency",
          fieldname: "name",
          filters: { name: currency },
        },
        callback: function (r) {
          if (r.message) {
            currency = r.message.name;
          }
        },
      });

      if (!frm.is_new()) {
        if (frm.doc.tax_id) {
          frm.add_custom_button(
            __("Perform Customer Search"),
            function () {
              frappe.call({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.perform_customer_search",
                args: {
                  request_data: {
                    doc_name: frm.doc.name,
                    customer_pin: frm.doc.tax_id,
                    company_name: companyName,
                  },
                },
                callback: (response) => {
                  frappe.msgprint("Search queued. Please check in later.");
                },
                error: (r) => {
                  // Error Handling is Defered to the Server
                },
              });
            },
            __("eTims Actions")
          );
        }
        if (!frm.doc.slade_id) {
          frm.add_custom_button(
            __("Send Customer Details"),
            function () {
              frappe.call({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.send_branch_customer_details",
                args: {
                  name: frm.doc.name,
                },
                callback: (response) => {},
                error: (r) => {
                  // Error Handling is Defered to the Server
                },
              });
            },
            __("eTims Actions")
          );
        } else {
          frm.add_custom_button(
            __("Get Customer Detals"),
            function () {
              frappe.call({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.get_customer_details",
                args: {
                  request_data: {
                    doc_name: frm.doc.name,
                    id: frm.doc.slade_id,
                    company_name: companyName,
                  },
                },
                callback: (response) => {
                  frappe.msgprint("Search queued. Please check in later.");
                },
                error: (r) => {
                  // Error Handling is Defered to the Server
                },
              });
            },
            __("eTims Actions")
          );
        }
      }
    }
  },
  require_tax_id: function (frm) {
    if (frm.doc.require_tax_id) {
      frm.set_df_property("tax_id", "reqd", 1);
    } else {
      frm.set_df_property("tax_id", "reqd", 0);
    }
  },
});
