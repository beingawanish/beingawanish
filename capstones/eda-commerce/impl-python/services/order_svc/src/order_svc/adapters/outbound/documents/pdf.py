"""Invoice PDF rendering with fpdf2 (guide §9)."""

from __future__ import annotations

from fpdf import FPDF

from order_svc.domain.invoice import Invoice


class FpdfInvoiceRenderer:
    def render(self, invoice: Invoice) -> bytes:
        pdf = FPDF(format="A4")
        pdf.set_creator("eda-commerce order-svc")
        pdf.set_title(f"Invoice {invoice.number}")
        pdf.set_creation_date(invoice.issued_at)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Invoice {invoice.number}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 6, f"Order {invoice.order_id}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Issued {invoice.issued_at:%Y-%m-%d %H:%M} UTC", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        for line in invoice.ship_to:
            pdf.cell(0, 5, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        for w, h in ((30, "SKU"), (80, "Product"), (15, "Qty"), (30, "Unit"), (30, "Total")):
            pdf.cell(w, 7, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", size=10)
        for x in invoice.lines:
            name = x.product_name.encode("latin-1", "replace").decode("latin-1")
            for w, v in ((30, x.sku), (80, name), (15, str(x.quantity)), (30, str(x.unit_price)), (30, str(x.line_total))):
                pdf.cell(w, 7, v, border=1)
            pdf.ln()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(155, 8, "Total (VAT included)", border=1)
        pdf.cell(30, 8, str(invoice.total), border=1)
        return bytes(pdf.output())
