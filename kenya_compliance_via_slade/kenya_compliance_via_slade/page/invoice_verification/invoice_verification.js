frappe.pages["invoice-verification"].on_page_load = function (wrapper) {
  wrapper.page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Invoice Verification"),
    single_column: true,
    hide_sidebar: true,
  });
};

frappe.pages["invoice-verification"].on_page_show = function (wrapper) {
  hide_desk_ui();
  load_desk_page(wrapper);
};

frappe.pages["invoice-verification"].on_page_hide = function () {
  show_desk_ui();
};

function hide_desk_ui() {
  $(".navbar").hide();
  $("#sidebar").hide();
  $(".layout-side-section").hide();
  $(".page-head").hide();

  $("body").addClass("invoice-verification-page");
}

function show_desk_ui() {
  $(".navbar").show();
  $("#sidebar").show();
  $(".layout-side-section").show();
  $(".page-head").show();

  $("body").removeClass("invoice-verification-page");
}

function load_desk_page(wrapper) {
  const $parent = $(wrapper).find(".layout-main-section");

  $parent.empty();

  frappe.require("invoice_verification.bundle.jsx").then(() => {
    frappe.invoice_verification = new frappe.ui.InvoiceVerification({
      wrapper: $parent,
      page: wrapper.page,
      id: frappe.utils.get_url_arg("id"),
      key: frappe.utils.get_url_arg("key"),
    });
  });
}
