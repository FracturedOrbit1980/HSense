from parsers.line_items import collect_descriptions, parse_document_text, parse_free_text_line


INVOICE = """
ACME INDUSTRIAL SUPPLIES (PTY) LTD
Commercial invoice INV-1044
Date 12 March 2026

Part No          Description                         Qty
CS1900           Sealing compound - TIN              10
ANTI-SEIZE       Anti Seize Compound - 500g          5
GL-750           PVA wood adhesive - 750g            8
10 x Sealing compound - TIN
Subtotal                                          23
"""


def test_free_text_keeps_pack_size_out_of_quantity():
    item = parse_free_text_line("ANTI-SEIZE Anti Seize Compound - 500g 5")
    assert item is not None
    assert item.part_number == "ANTI-SEIZE"
    assert item.quantity == 5
    assert "500g" in item.description


def test_sealing_compound_line():
    item = parse_free_text_line("CS1900 Sealing compound - TIN 10")
    assert item is not None
    assert item.part_number == "CS1900"
    assert item.description == "Sealing compound - TIN"
    assert item.quantity == 10


def test_invoice_text_skips_header_and_total():
    items = parse_document_text(INVOICE)
    descriptions = [item.description for item in items]
    assert descriptions[0] == "Sealing compound - TIN"
    assert any("Anti Seize" in item.description and item.quantity == 5 for item in items)
    assert any(item.quantity == 10 and item.part_number is None for item in items)
    assert not any("subtotal" in item.description.lower() for item in items)
    assert not any("acme" in item.description.lower() for item in items)


def test_multiplied_quantity():
    item = parse_free_text_line("4 x Engine oil 5L")
    assert item is not None
    assert item.quantity == 4
    assert item.description == "Engine oil 5L"


def test_plain_list_keeps_every_description():
    text = """
    Sealing compound - TIN
    Anti Seize Compound - 500g
    Portland cement 50 kg bag
    """
    descriptions = collect_descriptions(text)
    assert descriptions == [
        "Sealing compound - TIN",
        "Anti Seize Compound - 500g",
        "Portland cement 50 kg bag",
    ]


def test_only_the_description_column_below_its_header():
    text = """
    Anti Seize Compound - 500g
    ACME INDUSTRIAL SUPPLIES (PTY) LTD
    Part No          Description                         Qty
    CS1900           Sealing compound - TIN              10
    CEM-50           Portland cement 50 kg bag           20
    Subtotal                                          23
    """
    assert collect_descriptions(text) == [
        "Sealing compound - TIN",
        "Portland cement 50 kg bag",
    ]
    items = parse_document_text(text)
    assert [item.description for item in items] == [
        "Sealing compound - TIN",
        "Portland cement 50 kg bag",
    ]
    assert items[0].part_number == "CS1900"
    assert items[0].quantity == 10


LEONARDO = """
LEONARDO SOUTH AFRICA (PTY) LTD
COMMERCIAL INVOICE JDK27082026
Part nr          Description                         Serial Nr   Qty
CS1900           Sealing compound - TIN              NA          1  3214.90
AC-730           Pro Seal - TIN                      NA          1  "
91V736           Sealant - TUBE                      NA          1  "
CB200-40         Acrylic Adhesive - 40ML             NA          1  3506.10
"""


def test_serial_column_and_ditto_marks():
    items = parse_document_text(LEONARDO)
    assert [item.description for item in items] == [
        "Sealing compound - TIN",
        "Pro Seal - TIN",
        "Sealant - TUBE",
        "Acrylic Adhesive - 40ML",
    ]
    assert items[0].part_number == "CS1900"
    assert items[0].quantity == 1
    assert items[0].noted_code == "3214.90.00"
    assert items[1].same_as_above is True
    assert items[1].noted_code == "3214.90.00"
    assert items[2].noted_code == "3214.90.00"
    assert items[3].noted_code == "3506.10.00"
    assert "NA" not in items[0].description
    assert not any("leonardo" in item.description.lower() for item in items)


def test_na_serial_rows_are_kept_when_the_header_is_missing():
    text = """
    LEONARDO SOUTH AFRICA (PTY) LTD
    Air Charter Botswana t/a KALAHARI AIR SERVICES
    CS1900 Sealing compound - TIN NA 1
    AC-730 Pro Seal - TIN NA 1 "
    91V736 Sealant - TUBE NA 1 "
    """
    items = parse_document_text(text)
    assert [item.description for item in items] == [
        "Sealing compound - TIN",
        "Pro Seal - TIN",
        "Sealant - TUBE",
    ]
    assert items[1].same_as_above is True
    assert not any("kalahari" in item.description.lower() for item in items)


def test_lines_under_a_bare_description_header():
    text = """
    Warehouse note: engine oil 5L is in bay 3
    Description
    Sealing compound - TIN
    PVA wood adhesive - 750g
    """
    assert collect_descriptions(text) == [
        "Sealing compound - TIN",
        "PVA wood adhesive - 750g",
    ]


def test_invoice_descriptions_skip_addresses_and_totals():
    descriptions = [item.lower() for item in collect_descriptions(INVOICE)]
    assert any("sealing compound" in item for item in descriptions)
    assert any("anti seize" in item for item in descriptions)
    assert not any("subtotal" in item or "acme" in item or "invoice" in item for item in descriptions)
