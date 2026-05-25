const itemDoctypName = "Item";

frappe.ui.form.on(itemDoctypName, {
  refresh: async function (frm) {
    await getEtimsSettings(frm);

    await applyEtimsAutofillFields(frm);

    let grid = frm.get_field("etims_setup_mapping").grid;

    grid.cannot_add_rows = true;
    grid.cannot_delete_rows = true;
    grid.only_sortable();

    frm.refresh_field("etims_setup_mapping");

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
      frm.doc.custom_product_type_name !== "Service" ? 1 : 0,
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
  if (frm.doc.custom_prevent_etims_registration == 1) return;

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

  if (changed) {
    frm.refresh_fields();
  }
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

  frm.add_custom_button(
    __("AI Classify Item"),
    () => classifyItem(frm),
    __("eTims Actions"),
  );

  const canRegister =
    frm.doc.custom_item_classification &&
    frm.doc.custom_taxation_type &&
    unregisteredSettings.length;

  if (canRegister) {
    frm.add_custom_button(
      __("Register Item"),
      () =>
        showCompanySelectionModal(frm, "register_item", unregisteredSettings),
      __("eTims Actions"),
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
      __("eTims Actions"),
    );

    frm.add_custom_button(
      __("Update Item"),
      () => showCompanySelectionModal(frm, "update_item", registeredSetups),
      __("eTims Actions"),
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
          })),
        ),
      __("eTims Actions"),
    );
  }
}

async function classifyItem(frm) {
  if (frm.is_new()) {
    frappe.msgprint(__("Please save the Item first."));
    return;
  }

  const allSettings = frm.etims?.allSettings || [];

  if (!allSettings.length) {
    frappe.msgprint(__("No eTIMS setup configured."));

    return;
  }

  let settingsName = null;

  if (allSettings.length === 1) {
    settingsName = allSettings[0].name;
  } else {
    const selected = await new Promise((resolve) => {
      const dialog = new frappe.ui.Dialog({
        title: __("Select eTIMS Setup"),
        size: "small",
        fields: [
          {
            label: __("eTIMS Setup"),
            fieldname: "settings_name",
            fieldtype: "Select",
            reqd: 1,
            options: allSettings.map((d) => ({
              label: `${d.company} (${d.name})`,
              value: d.name,
            })),
            default: allSettings[0].name,
          },
        ],
        primary_action_label: __("Continue"),
        primary_action(values) {
          dialog.hide();

          resolve(values.settings_name);
        },
      });

      dialog.show();
    });

    settingsName = selected;
  }

  if (!settingsName) return;

  frappe.dom.freeze(`
    <div style="
      min-width:320px;
      padding:24px;
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:center;
      gap:18px;
      text-align:center;
    ">
      <div style="
        width:68px;
        height:68px;
        border-radius:999px;
        border:5px solid rgba(37,99,235,.15);
        border-top-color:#2563eb;
        animation:spin .9s linear infinite;
      "></div>

      <div>
        <div style="
          font-size:20px;
          font-weight:700;
          color:#0f172a;
          margin-bottom:6px;
        ">
          AI Classification Running
        </div>

        <div style="
          color:#64748b;
          font-size:14px;
          line-height:1.7;
        ">
          Using Item Code, Item Name, Description,
          Item Group and UOMs to predict the
          best eTIMS classification.
        </div>
      </div>
    </div>

    <style>
      @keyframes spin {
        from {
          transform: rotate(0deg);
        }

        to {
          transform: rotate(360deg);
        }
      }
    </style>
  `);

  try {
    const response = await frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.ai.item_classifier.classify_item",
      args: {
        item: frm.doc.name,
        settings_name: settingsName,
      },
    });

    frappe.dom.unfreeze();

    const result = response.message;

    if (!result?.success) {
      frappe.msgprint({
        title: __("Classification Failed"),
        indicator: "red",
        message: result?.message || __("Unable to classify item."),
      });

      return;
    }

    await frm.reload_doc();

    const confidence = cint(result.confidence || 0);

    let indicator = "red";

    if (confidence >= 90) {
      indicator = "green";
    } else if (confidence >= 70) {
      indicator = "orange";
    }

    const confidenceColor =
      confidence >= 90 ? "#22c55e" : confidence >= 70 ? "#f59e0b" : "#ef4444";

    const alternatives = (result.alternative_codes || [])
      .map(
        (d) => `
          <div style="
            padding:10px 14px;
            border-radius:10px;
            background:#f8fafc;
            border:1px solid #e2e8f0;
            font-size:13px;
            font-weight:600;
          ">
            ${d}
          </div>
        `,
      )
      .join("");

    const reasoning = frappe.utils.escape_html(result.reasoning || "");

    const html = `
      <div style="
        padding:6px;
      ">
        <div style="
          background:
            linear-gradient(
              135deg,
              #2563eb,
              #7c3aed
            );
          border-radius:24px;
          padding:28px;
          color:white;
          margin-bottom:18px;
          position:relative;
          overflow:hidden;
        ">
          <div style="
            position:absolute;
            right:-40px;
            top:-40px;
            width:160px;
            height:160px;
            border-radius:999px;
            background:
              rgba(255,255,255,.08);
          "></div>

          <div style="
            position:relative;
            z-index:2;
          ">
            <div style="
              display:inline-flex;
              align-items:center;
              gap:8px;
              padding:6px 12px;
              border-radius:999px;
              background:
                rgba(255,255,255,.12);
              font-size:12px;
              font-weight:700;
              margin-bottom:20px;
              letter-spacing:.4px;
            ">
              AI eTIMS Classification
            </div>

            <div style="
              font-size:38px;
              font-weight:800;
              line-height:1.1;
              margin-bottom:8px;
            ">
              ${result.classification_code}
            </div>

            <div style="
              font-size:18px;
              line-height:1.6;
              font-weight:600;
              opacity:.95;
              margin-bottom:26px;
            ">
              ${result.classification_name}
            </div>

            <div style="
              display:flex;
              align-items:center;
              gap:14px;
            ">
              <div style="
                width:14px;
                height:14px;
                border-radius:999px;
                background:${confidenceColor};
                box-shadow:
                  0 0 18px ${confidenceColor};
              "></div>

              <div style="
                font-size:15px;
                font-weight:700;
              ">
                Confidence ${confidence}%
              </div>
            </div>
          </div>
        </div>

        <div style="
          border:1px solid #e2e8f0;
          border-radius:20px;
          background:white;
          padding:22px;
          margin-bottom:18px;
        ">
          <div style="
            font-size:13px;
            font-weight:800;
            color:#475569;
            margin-bottom:14px;
            letter-spacing:.4px;
            text-transform:uppercase;
          ">
            AI Reasoning
          </div>

          <div style="
            font-size:14px;
            color:#0f172a;
            line-height:1.9;
            white-space:pre-wrap;
          ">
            ${reasoning}
          </div>
        </div>

        ${
          alternatives
            ? `
          <div style="
            border:1px solid #e2e8f0;
            border-radius:20px;
            background:white;
            padding:22px;
          ">
            <div style="
              font-size:13px;
              font-weight:800;
              color:#475569;
              margin-bottom:14px;
              letter-spacing:.4px;
              text-transform:uppercase;
            ">
              Alternative Matches
            </div>

            <div style="
              display:grid;
              grid-template-columns:
                repeat(
                  auto-fit,
                  minmax(180px,1fr)
                );
              gap:10px;
            ">
              ${alternatives}
            </div>
          </div>
        `
            : ""
        }
      </div>
    `;

    frappe.msgprint({
      title: __("AI Classification Complete"),
      indicator,
      wide: true,
      message: html,
    });

    frappe.show_alert({
      message: __("Item classified successfully"),
      indicator,
    });
  } catch (e) {
    frappe.dom.unfreeze();

    frappe.msgprint({
      title: __("Classification Failed"),
      indicator: "red",
      message: e?.message || __("Unexpected error during classification."),
    });

    console.error(e);
  }
}

function showCompanySelectionModal(frm, actionType, availableSettings) {
  if (!availableSettings.length) {
    frappe.msgprint(
      __(
        "No available eTIMS settings for this action. Please check configuration.",
      ),
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
      (r) => r.etims_setup === settingName,
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
