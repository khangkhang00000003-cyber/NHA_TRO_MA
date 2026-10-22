from invoice_pdf import calculate, create_invoice_pdf


def test_invoice_calculation_and_pdf():
    bill = {
        "year": 2026, "month": 10, "room_no": 1,
        "tenant_name": "Nguyễn Thị Ánh", "tenant_phone": "0900000000",
        "tenant_email": "anh@example.com", "rent_price": 2_500_000,
        "electricity_old": 100, "electricity_new": 120,
        "water_old": 20, "water_new": 22,
        "payment_status": "Chưa thanh toán", "note": "Đã nhắc thanh toán",
    }
    settings = {"electric_rate": 3500, "water_rate": 15000, "other_fee": 150000}
    totals = calculate(bill, settings)
    assert totals["used_electricity"] == 20
    assert totals["used_water"] == 2
    assert totals["total"] == 2_750_000
    pdf = create_invoice_pdf(bill, settings, 2026, 10)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 5000
