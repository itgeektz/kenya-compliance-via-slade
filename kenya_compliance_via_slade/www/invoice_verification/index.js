document.addEventListener("DOMContentLoaded", function () {
  document.body.classList.add("invoice-verification-page");

  const loadingState = document.getElementById("state-loading");
  const successState = document.getElementById("state-success");
  const errorState = document.getElementById("state-error");
  const pendingState = document.getElementById("state-pending");
  const errorMessage = document.getElementById("error-message");
  const successBtn = document.getElementById("success-redirect-btn");

  const successMessage = document.getElementById("success-message");
  const miniLoader = document.getElementById("redirect-mini-loader");
  const serverWarning = document.getElementById("etims-server-warning");
  const successLedgerDetails = document.getElementById(
    "success-ledger-details",
  );

  const initialRedirect = document.getElementById("initial_redirect")?.value;
  const initialError = document.getElementById("initial_error")?.value;

  let redirectTimer = null;
  let serverDownTimer = null;

  function handleSuccess(url, ledgerData = null) {
    loadingState.style.display = "none";
    successBtn.href = url;
    successState.style.display = "block";

    if (ledgerData) {
      const currency = ledgerData.currency || "KES";

      document.getElementById("success-scu-type").innerText =
        ledgerData.type || "-";
      document.getElementById("success-scu-invoice").innerText =
        ledgerData.scu_invoice_number || "-";
      document.getElementById("success-scu-receipt").innerText =
        ledgerData.scu_receipt_number || "-";
      document.getElementById("success-scu-customer").innerText =
        ledgerData.customer_name || ledgerData.customer || "-";
      document.getElementById("success-scu-date").innerText =
        ledgerData.invoice_date || ledgerData.posting_date || "-";

      document.getElementById("success-scu-gross").innerText =
        `${currency} ${ledgerData.total_gross_amount || "0.00"}`;
      document.getElementById("success-scu-vat").innerText =
        `${currency} ${ledgerData.total_vat || "0.00"}`;
      document.getElementById("success-scu-amount").innerText =
        `${currency} ${ledgerData.tax_inclusive_amount || "0.00"}`;

      document.getElementById("success-scu-id").innerText =
        ledgerData.scu_id || "-";
      document.getElementById("success-scu-mrc").innerText =
        ledgerData.scu_mrc_number || "-";
      document.getElementById("success-scu-signature").innerText =
        ledgerData.scu_receipt_signature || "-";
      document.getElementById("success-scu-time").innerText =
        `${ledgerData.scu_receipt_date || "-"} ${ledgerData.scu_receipt_time || ""}`.trim();

      const internalField = document.getElementById("success-scu-internal");
      if (internalField && ledgerData.scu_internal_data) {
        internalField.innerText = ledgerData.scu_internal_data;
        internalField.closest(".detail-row").style.display = "flex";
      }

      successLedgerDetails.style.display = "block";
    }

    redirectTimer = setTimeout(function () {
      successMessage.innerText =
        "Attempting connection to KRA eTIMS Gateway servers...";
      miniLoader.style.display = "block";

      serverDownTimer = setTimeout(function () {
        serverWarning.style.display = "block";
        successMessage.innerText =
          "The KRA gateway is unresponsive. Attempting to keep connection alive; you may also try launching manually below:";
      }, 4000);

      window.location.href = url;
    }, 3000);
  }

  if (successBtn) {
    successBtn.addEventListener("click", function () {
      if (redirectTimer) clearTimeout(redirectTimer);
      if (serverDownTimer) clearTimeout(serverDownTimer);
      miniLoader.style.display = "none";
    });
  }

  if (initialRedirect) {
    loadingState.style.display = "none";
    handleSuccess(initialRedirect, null);
    return;
  }

  if (initialError) {
    loadingState.style.display = "none";
    errorMessage.innerText = initialError;
    errorState.style.display = "block";
    return;
  }

  const id = document.getElementById("invoice_id")?.value;
  const key = document.getElementById("verification_key")?.value;

  if (!id || !key) {
    loadingState.style.display = "none";
    errorMessage.innerText = "Invalid verification link.";
    errorState.style.display = "block";
    return;
  }

  frappe.call({
    method:
      "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.check_invoice_submission_status",
    args: { id, key },
    callback: function (r) {
      if (!r.message) {
        loadingState.style.display = "none";
        errorMessage.innerText = "Unable to verify invoice.";
        errorState.style.display = "block";
        return;
      }

      if (r.message.error) {
        loadingState.style.display = "none";
        errorMessage.innerText = r.message.error;
        errorState.style.display = "block";
        return;
      }

      if (r.message.etims_qr_code_url) {
        handleSuccess(r.message.etims_qr_code_url, r.message);
        return;
      }

      loadingState.style.display = "none";

      document.getElementById("detail-name").innerText =
        r.message.name || r.message.scu_invoice_number || "";
      document.getElementById("detail-customer").innerText =
        r.message.customer || r.message.customer_name || "";
      document.getElementById("detail-date").innerText =
        r.message.posting_date || r.message.invoice_date || "";

      if (r.message.grand_total || r.message.tax_inclusive_amount) {
        const amount = r.message.grand_total || r.message.tax_inclusive_amount;
        const currency = r.message.currency || "KES";
        document.getElementById("detail-amount").innerText =
          `${currency} ${amount}`.trim();
        document.getElementById("detail-amount-row").style.display = "flex";
      }

      pendingState.style.display = "block";
    },
    error: function () {
      loadingState.style.display = "none";
      errorMessage.innerText = "Unable to verify invoice.";
      errorState.style.display = "block";
    },
  });
});
