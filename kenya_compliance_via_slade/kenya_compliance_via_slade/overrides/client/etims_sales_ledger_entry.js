// Copyright (c) 2026, Navari Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Sales Ledger Entry", {
  refresh(frm) {
    if (!frm.doc.__islocal) {
      frm.add_custom_button(
        __("Refetch eTIMS Invoice"),
        () => {
          frm.call({
            method:
              "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.fetch_etims_ledger_entry",
            args: {
              name: frm.doc.name,
              queue: false,
            },
            freeze: true,
            freeze_message: __("Refetching eTIMS Invoice..."),
            callback: function (r) {
              if (!r.exc) {
                frm.reload_doc();
              }
            },
          });
        },
        __("Actions"),
      );

      if (frm.doc.type === "Sales Invoice") {
        frappe.db
          .get_value(
            "eTIMS Sales Ledger Entry",
            {
              type: "Credit Note",
              etims_invoice: frm.doc.name,
            },
            "name",
          )
          .then((r) => {
            let has_credit_note = r && r.message && r.message.name;

            if (!has_credit_note) {
              frm.add_custom_button(
                __("Create Credit Note"),
                () => {
                  frm.call({
                    method:
                      "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.return_etims_credit_note",
                    args: {
                      name: frm.doc.name,
                      queue: false,
                    },
                    freeze: true,
                    freeze_message: __("Generating Credit Note..."),
                    callback: function (r) {
                      if (!r.exc) {
                        frm.reload_doc();
                      }
                    },
                  });
                },
                __("Actions"),
              );
            }
          });
      }
    }
  },
});
