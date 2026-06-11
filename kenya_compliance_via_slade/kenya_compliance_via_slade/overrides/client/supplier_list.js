const supplierDoctypeName = "Supplier";

frappe.listview_settings[supplierDoctypeName] =
  frappe.listview_settings[supplierDoctypeName] || {};

const existingOnload = frappe.listview_settings[supplierDoctypeName].onload;

frappe.listview_settings[supplierDoctypeName].onload = async function (
  listview,
) {
  if (existingOnload) {
    await existingOnload(listview);
  }

  const { message: data } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_etims_action_data",
    args: { doctype: supplierDoctypeName },
  });

  const allSettings = data?.settings || [];

  if (!allSettings.length) {
    return;
  }

  listview.page.add_action_item(__("Bulk Submit Suppliers"), function () {
    const suppliers = listview.get_checked_items().map((item) => item.name);

    if (!suppliers.length) {
      frappe.msgprint(__("Please select suppliers to submit"));
      return;
    }

    showSettingsModalAndExecute(
      "Bulk Submit Suppliers",
      allSettings,
      (settings_name) => ({
        method: "bulk_submit_suppliers",
        args: {
          docs_list: suppliers,
          settings_name,
        },
        success_msg: "Bulk supplier submission queued",
      }),
    );
  });
};

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  const executeAction = (settingsName) => {
    const { method, args, success_msg } = getCallArgs(settingsName);

    frappe.call({
      method: `kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.${method}`,
      args,
      freeze: true,
      freeze_message: __("Processing..."),
      callback: () => {
        frappe.msgprint(__(success_msg));
      },
      error: (err) => {
        console.error(err);
        frappe.msgprint(__("An error occurred during the request."));
      },
    });
  };

  if (settings.length === 1) {
    executeAction(settings[0].name);
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
      executeAction(settings_name);
    },
  });

  dialog.show();
}
