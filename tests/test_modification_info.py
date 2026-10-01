"""Last-modified user/timestamp extraction from the <UUID> stamp."""

from lxml import etree

from fm_saxml.parser.extractors._helpers import modification_info


def test_modification_info_reads_uuid_stamp():
    elem = etree.fromstring(
        '<Script id="1"><UUID modifications="3" userName="host" accountName="Jane" '
        'timestamp="2026-05-01T09:58:28">ABC</UUID></Script>'
    )
    assert modification_info(elem) == {
        "user_name": "host", "account_name": "Jane",
        "timestamp": "2026-05-01T09:58:28", "modifications": 3,
    }


def test_modification_info_absent():
    assert modification_info(etree.fromstring('<Script id="1"><UUID>ABC</UUID></Script>')) is None
    assert modification_info(etree.fromstring('<Script id="1"/>')) is None
