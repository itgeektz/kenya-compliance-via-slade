const itemDoctypName = "Item";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.ui.form.on(itemDoctypName, {
  refresh: async function (frm) {
    const { message: activeSetting } = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_setting",
      args: {
        doctype: settingsDoctypeName,
      },
    });

    if (activeSetting?.length > 0) {
      if (frm.doc.custom_item_registered) {
        frm.toggle_enable("custom_item_classification", false);
        frm.toggle_enable("custom_etims_country_of_origin", false);
        frm.toggle_enable("custom_taxation_type", false);
        frm.toggle_enable("custom_packaging_unit", false);
        frm.toggle_enable("custom_unit_of_quantity", false);
        frm.toggle_enable("custom_product_type", false);
      }

      if (frm.doc.custom_imported_item_submitted) {
        frm.toggle_enable("custom_referenced_imported_item", false);
        frm.toggle_enable("custom_imported_item_status", false);
      }

      if (!frm.is_new()) {
        if (
          !frm.doc.custom_sent_to_slade &&
          frm.doc.custom_item_classification &&
          frm.doc.custom_taxation_type
        ) {
          frm.add_custom_button(
            __("Register Item"),
            function () {
              showCompanySelectionModal(frm, "register_item", activeSetting);
            },
            __("eTims Actions")
          );
        } else if (frm.doc.custom_sent_to_slade && frm.doc.custom_slade_id) {
          frm.add_custom_button(
            __("Fetch Item Details"),
            function () {
              showCompanySelectionModal(
                frm,
                "fetch_item_details",
                activeSetting
              );
            },
            __("eTims Actions")
          );

          frm.add_custom_button(
            __("Update Item"),
            function () {
              showCompanySelectionModal(frm, "update_item", activeSetting);
            },
            __("eTims Actions")
          );
        }

        if (frm.doc.is_stock_item) {
          frm.add_custom_button(
            __("Submit Item Inventory"),
            function () {
              showCompanySelectionModal(frm, "submit_inventory", activeSetting);
            },
            __("eTims Actions")
          );
        }
      }
    }
  },
  custom_product_type_name: function (frm) {
    if (frm.doc.custom_product_type_name === "Service") {
      frm.set_value("is_stock_item", 0);
    } else {
      frm.set_value("is_stock_item", 1);
    }
  },
});

async function showCompanySelectionModal(frm, actionType, activeSettings) {
  if (!activeSettings || activeSettings.length === 0) {
    frappe.msgprint(
      __("No active eTims settings found. Please configure settings first.")
    );
    return;
  }

  const companyOptions = activeSettings.map((setting) => ({
    label: `${setting.company} (${setting.name})`,
    value: setting.name,
    company_name: setting.company,
  }));

  const fields = [
    {
      label: __("Select Company Setup"),
      fieldname: "selected_settings_name",
      fieldtype: "Select",
      options: companyOptions,
      reqd: 1,
      default: companyOptions[0] ? companyOptions[0].value : null,
    },
  ];

  let dialog = new frappe.ui.Dialog({
    title: __("Select Company Setup "),
    fields: fields,
    primary_action_label: __("Proceed"),
    primary_action: (data) => {
      const selectedSettingName = data.selected_settings_name;
      dialog.hide();
      executeItemAction(frm, actionType, selectedSettingName);
    },
  });

  dialog.show();
}

function executeItemAction(frm, actionType, settingName) {
  let method;
  let args = {};

  switch (actionType) {
    case "register_item":
    case "update_item":
      method =
        "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.perform_item_registration";
      args = {
        item_name: frm.doc.name,
        settings_name: settingName,
      };
      break;
    case "fetch_item_details":
      method =
        "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.fetch_item_details";
      args = {
        request_data: {
          document_name: frm.doc.name,
          id: frm.doc.custom_slade_id,
          settings_name: settingName,
        },
      };
      break;
    case "submit_inventory":
      method =
        "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.submit_inventory";
      args = {
        name: frm.doc.name,
        settings_name: settingName,
      };
      break;
    default:
      frappe.msgprint(__("Unknown action type."));
      return;
  }

  frappe.call({
    method: method,
    args: args,
    callback: (response) => {
      let message = "";
      if (actionType === "register_item") {
        message = "Item Registration Queued. Please check in later.";
      } else if (actionType === "fetch_item_details") {
        message = "Item Fetch Request Queued. Please check in later.";
      } else if (actionType === "update_item") {
        message = "Item Update Queued. Please check in later.";
      } else if (actionType === "submit_inventory") {
        message = "Inventory submission queued.";
      }
      frappe.msgprint(message);
    },
    error: (error) => {
      frappe.msgprint(__("An error occurred during the request."));
      console.error(error);
    },
  });
}
