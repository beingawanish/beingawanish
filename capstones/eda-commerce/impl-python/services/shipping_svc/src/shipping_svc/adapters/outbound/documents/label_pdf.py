"""Shipping label PDF with fpdf2 (guide §9). The PDF holds the address (it is a label); it lives only
in the ``shipping-labels`` bucket, which expires objects after 30 days."""

from __future__ import annotations

from fpdf import FPDF

from shipping_svc.application.ports import LabelData


def _latin(v: object) -> str:
    return str(v).encode("latin-1", "replace").decode("latin-1")


class FpdfLabelRenderer:
    def render(self, label: LabelData) -> bytes:
        pdf = FPDF(format="A6")
        pdf.set_creator("eda-commerce shipping-svc")
        pdf.set_title(f"Label {label.tracking_number}")
        pdf.set_creation_date(label.booked_at)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, _latin(label.carrier.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", "B", 16)
        pdf.cell(0, 10, label.tracking_number, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        kind = "RETURN to warehouse" if label.direction.value == "RETURN" else f"{label.shipping_method} delivery"
        pdf.cell(0, 5, _latin(kind), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Parcels: {label.parcel_count}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, "FROM" if label.direction.value == "RETURN" else "TO", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        a = label.address
        for key in ("recipientName", "line1", "line2", "postalCode", "city", "countryCode"):
            if a.get(key):
                pdf.cell(0, 5, _latin(a[key]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font("Helvetica", size=7)
        pdf.cell(0, 4, f"Ref {label.shipment_id}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 4, f"Booked {label.booked_at:%Y-%m-%d %H:%M} UTC", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())
