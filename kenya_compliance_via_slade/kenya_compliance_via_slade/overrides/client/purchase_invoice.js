const purchaseParentDoctype = "Purchase Invoice";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.ui.form.on(purchaseParentDoctype, {
  refresh: async function (frm) {
    const { message: activeSetting } = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
      args: { doctype: settingsDoctypeName, company: frm.doc.company },
    });

    if (
      activeSetting?.length > 0 &&
      frm.doc.docstatus !== 0 &&
      !frm.doc.prevent_etims_submission
    ) {
      if (!frm.doc.custom_submitted_successfully) {
        frm.add_custom_button(
          __("Send Invoice"),
          function () {
            showSettingsModalAndExecute(
              "Send Purchase Invoice",
              activeSetting,
              (settings_name) => ({
                method:
                  "kenya_compliance_via_slade.kenya_compliance_via_slade.overrides.server.purchase_invoice.send_purchase_details",
                args: {
                  name: frm.doc.name,
                  settings_name: settings_name,
                },
                success_msg: "Purchase invoice submission queued",
              })
            );
          },
          __("eTims Actions")
        );
      }
    }
  },
});

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  if (settings.length === 1) {
    const { method, args, success_msg } = getCallArgs(settings[0].name);
    frappe.call({
      method: method,
      args: args,
      freeze: true,
      freeze_message: "Processing...",
      callback: () => frappe.msgprint(__(success_msg)),
      error: (err) => {
        console.error(err);
        frappe.msgprint(__("An error occurred during the request."));
      },
    });
    return;
  }

  const dialog = new frappe.ui.Dialog({
    title: __(title),
    fields: [
      {
        label: __("Select eTims Settings"),
        fieldname: "settings_name",
        fieldtype: "Select",
        options: settings.map((s) => ({
          label: `${s.company} (${s.name})`,
          value: s.name,
        })),
        reqd: 1,
        default: settings[0]?.name,
      },
    ],
    primary_action_label: __("Proceed"),
    primary_action: ({ settings_name }) => {
      dialog.hide();
      const { method, args, success_msg } = getCallArgs(settings_name);
      frappe.call({
        method: method,
        args: args,
        freeze: true,
        freeze_message: "Processing...",
        callback: () => frappe.msgprint(__(success_msg)),
        error: (err) => {
          console.error(err);
          frappe.msgprint(__("An error occurred during the request."));
        },
      });
    },
  });
  dialog.show();
}
