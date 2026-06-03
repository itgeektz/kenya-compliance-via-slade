import * as React from "react";

export function App() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [invoice, setInvoice] = React.useState(null);

  React.useEffect(() => {
    if (!document.getElementById("invoice-verification-css")) {
      const link = document.createElement("link");

      link.id = "invoice-verification-css";
      link.rel = "stylesheet";
      link.href =
        "/assets/kenya_compliance_via_slade/css/invoice_verification.css";

      document.head.appendChild(link);
    }

    document.body.classList.add("invoice-verification-page");

    const params = new URLSearchParams(window.location.search);

    const id = params.get("id");
    const key = params.get("key");

    if (!id || !key) {
      setError("Invalid verification link.");
      setLoading(false);

      return () => {
        document.body.classList.remove("invoice-verification-page");
      };
    }

    frappe.call({
      method:
        "kenya_compliance_via_slade.kenya_compliance_via_slade.apis.apis.check_invoice_submission_status",
      args: {
        id,
        key,
      },
      callback: ({ message }) => {
        setLoading(false);

        if (!message) {
          setError("Unable to verify invoice.");
          return;
        }

        if (message.error) {
          setError(message.error);
          return;
        }

        if (message.qr_code_url) {
          window.location.replace(message.qr_code_url);
          return;
        }

        setInvoice(message);
      },
      error: () => {
        setLoading(false);
        setError("Unable to verify invoice.");
      },
    });

    return () => {
      document.body.classList.remove("invoice-verification-page");
    };
  }, []);

  if (loading) {
    return (
      <div className="invoice-page">
        <div className="invoice-card">
          <div className="loader" />
          <h2>Verifying Invoice</h2>
          <p>Please wait while we verify the invoice and submission status.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="invoice-page">
        <div className="invoice-card error-card">
          <div className="status-icon error">⚠</div>

          <h1>Verification Failed</h1>

          <p>{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="invoice-page">
      <div className="invoice-card">
        <div className="status-icon warning">⏳</div>

        <h1>Invoice Pending Submission</h1>

        <p className="subtitle">
          This invoice has not yet been successfully submitted to KRA eTIMS.
        </p>

        <div className="status-banner">
          <div className="status-banner-title">Submission In Progress</div>

          <div className="status-banner-text">
            The invoice has been generated successfully and is waiting for
            submission processing. Please check again later.
          </div>
        </div>

        <div className="invoice-details">
          <div className="detail-row">
            <span>Invoice Number</span>
            <strong>{invoice.name}</strong>
          </div>

          <div className="detail-row">
            <span>Customer</span>
            <strong>{invoice.customer}</strong>
          </div>

          <div className="detail-row">
            <span>Posting Date</span>
            <strong>{invoice.posting_date}</strong>
          </div>

          {invoice.grand_total && (
            <div className="detail-row">
              <span>Total Amount</span>

              <strong>
                {invoice.currency || ""} {invoice.grand_total}
              </strong>
            </div>
          )}
        </div>

        <button
          className="primary-button"
          onClick={() => window.location.reload()}
        >
          Check Again
        </button>
      </div>
    </div>
  );
}
