const doctypeName = "Item";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName] =
  frappe.listview_settings[doctypeName] || {};

const existingOnload = frappe.listview_settings[doctypeName].onload;

frappe.listview_settings[doctypeName].onload = async function (listview) {
  if (existingOnload) {
    await existingOnload(listview);
  }

  const { message: data } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_etims_action_data",
    args: {
      doctype: doctypeName,
    },
  });

  const allSettings = data?.settings || [];

  if (!allSettings.length) {
    return;
  }

  addItemListActions(listview, allSettings);

  listview.page.add_action_item(__("Bulk Register Items"), function () {
    const itemsToRegister = listview
      .get_checked_items()
      .map((item) => item.name);

    if (!itemsToRegister.length) {
      frappe.msgprint(__("Please select items to register"));
      return;
    }

    showSettingsModalAndExecute(
      "Bulk Register Items",
      allSettings,
      (settings_name) => ({
        method: "bulk_register_items",
        args: {
          docs_list: itemsToRegister,
          settings_name,
        },
        success_msg: "Bulk registration queued",
      }),
    );
  });
};

function addItemListActions(listview, allSettings) {
  const actions = [
    {
      label: __("Get Imported Items"),
      getCallArgs: (settings_name) => ({
        method: "perform_import_item_search",
        args: {
          settings_name,
          request_data: {},
        },
        success_msg: "Import items search queued",
      }),
    },
  ];

  actions.forEach((action) => {
    listview.page.add_inner_button(
      action.label,
      function () {
        showSettingsModalAndExecute(
          action.label,
          allSettings,
          (settings_name) => action.getCallArgs(settings_name),
        );
      },
      __("eTims Actions"),
    );
  });
}

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
