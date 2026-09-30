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


def test_invoice_descriptions_skip_addresses_and_totals():
    descriptions = [item.lower() for item in collect_descriptions(INVOICE)]
    assert any("sealing compound" in item for item in descriptions)
    assert any("anti seize" in item for item in descriptions)
    assert not any("subtotal" in item or "acme" in item or "invoice" in item for item in descriptions)
