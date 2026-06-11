const doctypeName = "Sales Invoice";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName] =
  frappe.listview_settings[doctypeName] || {};

const existingOnload = frappe.listview_settings[doctypeName].onload;

frappe.listview_settings[doctypeName].onload = async function (listview) {
  if (existingOnload) {
    await existingOnload(listview);
  }

  const { message: activeSetting } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_settings",
    args: { doctype: settingsDoctypeName },
  });

  if (activeSetting?.length > 0) {
    listview.page.add_action_item(
      __("Bulk Submit to eTims"),
      function () {
        showSettingsModalAndExecute(
          "Bulk Submit to eTims",
          activeSetting,
          (settings_name) => ({
            method: "bulk_submit_sales_invoices",
            args: {
              docs_list: listview.get_checked_items().map((item) => item.name),
              settings_name,
            },
            success_msg: "Bulk submission to eTims queued.",
          }),
        );
      },
      __("eTims Actions"),
    );
  }
};

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  executeWithSingleOrDialog(
    settings,
    (settingsName) => {
      const { method, args, success_msg } = getCallArgs(settingsName);
      executeEtimsAction(method, args, success_msg);
    },
    () => {
      const options = settings.map((s) => ({
        label: `${s.company} (${s.name})`,
        value: s.name,
      }));

      const dialog = new frappe.ui.Dialog({
        title: __(title),
        fields: [
          {
            label: __("Select eTims Settings"),
            fieldname: "settings_name",
            fieldtype: "Select",
            options,
            reqd: 1,
            default: options[0]?.value,
          },
        ],
        primary_action_label: __("Proceed"),
        primary_action: ({ settings_name }) => {
          dialog.hide();

          const { method, args, success_msg } = getCallArgs(settings_name);

          executeEtimsAction(method, args, success_msg);
        },
      });

      dialog.show();
    },
  );
}

function executeWithSingleOrDialog(settings, actionFn, buildDialog) {
  if (settings.length === 1) {
    actionFn(settings[0].name);
    return;
  }

  buildDialog();
}

function executeEtimsAction(method, args, successMsg) {
  frappe.call({
    method: `kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.${method}`,
    args,
    freeze: true,
    freeze_message: __("Processing..."),
    callback: () => {
      frappe.msgprint(__(successMsg));
    },
    error: (err) => {
      console.error(err);
      frappe.msgprint(__("An error occurred during the request."));
    },
  });
}
