const itemDoctypName = "Item";

frappe.ui.form.on(itemDoctypName, {
  refresh: async function (frm) {
    await getEtimsSettings(frm);
    await applyEtimsAutofillFields(frm);
    toggleImportedLocks(frm);
    if (!frm.is_new()) {
      setupButtons(frm);
    }
  },

  item_group: async function (frm) {
    await applyEtimsAutofillFields(frm);
  },

  custom_product_type_name: function (frm) {
    frm.set_value(
      "is_stock_item",
      frm.doc.custom_product_type_name !== "Service" ? 1 : 0
    );
  },
});

async function getEtimsSettings(frm) {
  const { message: data } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_etims_action_data",
    args: {
      doctype: frm.doctype,
      docname: frm.is_new() ? null : frm.doc.name,
    },
  });

  frm.etims = {
    allSettings: data?.settings || [],
    registeredMappings: data?.registered_mappings || [],
    unregisteredSettings: data?.unregistered_settings || [],
  };
}

async function applyEtimsAutofillFields(frm) {
  const fallbackSetting = frm.etims?.allSettings?.length
    ? frm.etims.allSettings[0].name
    : null;

  const { message: values } = await frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.overrides.server.item.autofill_item_etims_fields",
    args: {
      item_group: frm.doc.item_group,
      settings_name: fallbackSetting,
    },
  });

  if (!values) return;

  let changed = false;

  Object.keys(values).forEach((field) => {
    if (values[field] !== null && frm.doc[field] !== values[field]) {
      frm.set_value(field, values[field]);
      changed = true;
    }
  });

  if (changed) frm.refresh_fields();
}

function toggleImportedLocks(frm) {
  if (frm.doc.custom_imported_item_submitted) {
    frm.toggle_enable("custom_referenced_imported_item", false);
    frm.toggle_enable("custom_imported_item_status", false);
  }
}

function setupButtons(frm) {
  const allSettings = frm.etims?.allSettings || [];
  const registeredMappings = frm.etims?.registeredMappings || [];
  const unregisteredSettings = frm.etims?.unregisteredSettings || [];

  if (!allSettings.length || frm.is_new()) return;

  const canRegister =
    frm.doc.custom_item_classification &&
    frm.doc.custom_taxation_type &&
    unregisteredSettings.length;

  if (canRegister) {
    frm.add_custom_button(
      __("Register Item"),
      () =>
        showCompanySelectionModal(frm, "register_item", unregisteredSettings),
      __("eTims Actions")
    );
  }

  if (registeredMappings.length) {
    const registeredSetups = registeredMappings.map((r) => ({
      name: r.etims_setup,
      company: getCompanyName(allSettings, r.etims_setup),
    }));

    frm.add_custom_button(
      __("Fetch Item Details"),
      () =>
        showCompanySelectionModal(frm, "fetch_item_details", registeredSetups),
      __("eTims Actions")
    );

    frm.add_custom_button(
      __("Update Item"),
      () => showCompanySelectionModal(frm, "update_item", registeredSetups),
      __("eTims Actions")
    );
  }

  if (frm.doc.is_stock_item && registeredMappings.length) {
    frm.add_custom_button(
      __("Submit Item Inventory"),
      () =>
        showCompanySelectionModal(
          frm,
          "submit_inventory",
          registeredMappings.map((r) => ({
            name: r.etims_setup,
            company: getCompanyName(allSettings, r.etims_setup),
          }))
        ),
      __("eTims Actions")
    );
  }
}

function showCompanySelectionModal(frm, actionType, availableSettings) {
  if (!availableSettings.length) {
    frappe.msgprint(
      __(
        "No available eTIMS settings for this action. Please check configuration."
      )
    );
    return;
  }

  if (availableSettings.length === 1) {
    executeItemAction(frm, actionType, availableSettings[0].name);
    return;
  }

  const options = availableSettings.map((setting) => ({
    label: `${setting.company} (${setting.name})`,
    value: setting.name,
  }));

  const dialog = new frappe.ui.Dialog({
    title: __("Select Company Setup"),
    fields: [
      {
        label: __("Select Company Setup"),
        fieldname: "selected_settings_name",
        fieldtype: "Select",
        options: options,
        reqd: 1,
        default: options[0].value,
      },
    ],
    primary_action_label: __("Proceed"),
    primary_action(values) {
      dialog.hide();
      executeItemAction(frm, actionType, values.selected_settings_name);
    },
  });

  dialog.show();
}

function executeItemAction(frm, actionType, settingName) {
  let method = "";
  let args = {};
  let sladeId = "";

  if (frm.doc.etims_setup_mapping) {
    const row = frm.doc.etims_setup_mapping.find(
      (r) => r.etims_setup === settingName
    );
    sladeId = row ? row.slade360_id : "";
  }

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
        settings_name: settingName,
        request_data: {
          document_name: frm.doc.name,
          id: sladeId,
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
      frappe.msgprint(__("Invalid action"));
      return;
  }

  frappe.call({
    method,
    args,
    callback() {
      const messages = {
        register_item: "Item Registration Queued.",
        fetch_item_details: "Fetch Request Queued.",
        update_item: "Update Queued.",
        submit_inventory: "Inventory Queued.",
      };
      frappe.msgprint(messages[actionType] || "Request submitted.");
    },
    freeze: true,
    freeze_message: "Processing...",
    error(error) {
      frappe.msgprint(__("Action failed."));
      console.error(error);
    },
  });
}

function getCompanyName(allSettings, settingName) {
  const setting = allSettings.find((s) => s.name === settingName);
  return setting ? setting.company : "Unknown";
}
