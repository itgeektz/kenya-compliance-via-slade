const doctypeName = "Navari eTims Registered Purchases";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName] = {
  onload: async function (listview) {
    const { message: data } = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_etims_action_data",
      args: { doctype: doctypeName },
    });

    const allSettings = data?.settings || [];
    if (!allSettings.length) return;

    listview.page.add_inner_button(__("Get Raised Purchases"), function () {
      showSettingsModalAndExecute(
        "Get Raised Purchases",
        allSettings,
        (settings_name) => ({
          method: "perform_purchases_search",
          args: {
            request_data: {},
            settings_name: settings_name,
          },
          success_msg: "Purchases search queued",
        })
      );
    });
  },
};

function showSettingsModalAndExecute(title, settings, getCallArgs) {
  executeWithSingleOrDialog(
    settings,
    (settingsName) => {
      const { method, args, success_msg } = getCallArgs(settingsName);
      executeEtimsAction(method, args, success_msg);
    },
    () => {
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
          executeEtimsAction(method, args, success_msg);
        },
      });

      dialog.show();
    }
  );
}

function executeWithSingleOrDialog(settings, actionFn, buildDialog) {
  if (settings.length === 1) {
    actionFn(settings[0].name);
  } else {
    buildDialog();
  }
}

function executeEtimsAction(method, args, successMsg) {
  frappe.call({
    method: `kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.${method}`,
    args: args,
    callback: () => frappe.msgprint(__(successMsg)),
    freeze: true,
    freeze_message: __("Processing..."),
    error: (err) => {
      console.error(err);
      frappe.msgprint(__("An error occurred during the request."));
    },
  });
}
