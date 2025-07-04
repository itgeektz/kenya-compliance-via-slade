const doctypeName = "Navari KRA eTims Workstation";
const settingsDoctypeName = "Navari KRA eTims Settings";

frappe.listview_settings[doctypeName] = {
  onload: function (listview) {
    listview.page.add_inner_button(
      __("Get eTims Workstations"),
      async function () {
        const { message: activeSetting } = await frappe.call({
          method:
            "kenya_compliance_via_slade.kenya_compliance_via_slade.utils.get_active_setting",
          args: {
            doctype: settingsDoctypeName,
          },
        });

        if (!activeSetting || activeSetting.length === 0) {
          frappe.msgprint(
            __(
              "No active eTims settings found. Please configure settings first."
            )
          );
          return;
        }

        const companyOptions = activeSetting.map((setting) => ({
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
          title: __("Select Company Setup for Workstation"),
          fields: fields,
          primary_action_label: __("Proceed"),
          primary_action: (data) => {
            const selectedSettingName = data.selected_settings_name;
            dialog.hide();
            frappe.call({
              method:
                "kenya_compliance_via_slade.kenya_compliance_via_slade.background_tasks.tasks.fetch_workstations",
              args: {
                settings_name: selectedSettingName,
              },
              callback: (response) => {
                frappe.msgprint(__("Workstation fetch request queued."));
              },
              error: (error) => {
                frappe.msgprint(
                  __("An error occurred while fetching workstations.")
                );
                console.error(error);
              },
            });
          },
        });

        dialog.show();
      }
    );
  },
};
