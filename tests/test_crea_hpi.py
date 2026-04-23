from __future__ import annotations

import zipfile
from io import BytesIO

from crea_hpi import (
    build_market_metric_snapshot,
    derive_appreciation_signal,
    parse_crea_workbook_bytes,
)


def build_minimal_crea_workbook_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
              <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
              <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
            </Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets>
                <sheet name="VICTORIA" sheetId="1" r:id="rId1"/>
              </sheets>
            </workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
            </Relationships>""",
        )
        shared_strings = [
            "Date",
            "Composite_HPI_SA",
            "Single_Family_HPI_SA",
            "One_Storey_HPI_SA",
            "Two_Storey_HPI_SA",
            "Townhouse_HPI_SA",
            "Apartment_HPI_SA",
            "Composite_Benchmark_SA",
            "Single_Family_Benchmark_SA",
            "One_Storey_Benchmark_SA",
            "Two_Storey_Benchmark_SA",
            "Townhouse_Benchmark_SA",
            "Apartment_Benchmark_SA",
        ]
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="13" uniqueCount="13">
              %s
            </sst>"""
            % "".join(f"<si><t>{value}</t></si>" for value in shared_strings),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1">
                  <c r="A1" t="s"><v>0</v></c>
                  <c r="B1" t="s"><v>1</v></c>
                  <c r="C1" t="s"><v>2</v></c>
                  <c r="D1" t="s"><v>3</v></c>
                  <c r="E1" t="s"><v>4</v></c>
                  <c r="F1" t="s"><v>5</v></c>
                  <c r="G1" t="s"><v>6</v></c>
                  <c r="H1" t="s"><v>7</v></c>
                  <c r="I1" t="s"><v>8</v></c>
                  <c r="J1" t="s"><v>9</v></c>
                  <c r="K1" t="s"><v>10</v></c>
                  <c r="L1" t="s"><v>11</v></c>
                  <c r="M1" t="s"><v>12</v></c>
                </row>
                <row r="2">
                  <c r="A2"><v>38353</v></c>
                  <c r="B2"><v>100</v></c>
                  <c r="C2"><v>101</v></c>
                  <c r="D2"><v>102</v></c>
                  <c r="E2"><v>103</v></c>
                  <c r="F2"><v>104</v></c>
                  <c r="G2"><v>105</v></c>
                  <c r="H2"><v>300000</v></c>
                  <c r="I2"><v>350000</v></c>
                  <c r="J2"><v>325000</v></c>
                  <c r="K2"><v>375000</v></c>
                  <c r="L2"><v>280000</v></c>
                  <c r="M2"><v>240000</v></c>
                </row>
              </sheetData>
            </worksheet>""",
        )
    return buffer.getvalue()


def test_parse_crea_workbook_bytes_extracts_market_and_property_rows() -> None:
    observations, profiles, inspection = parse_crea_workbook_bytes(
        build_minimal_crea_workbook_bytes(),
        workbook_name="Seasonally Adjusted (M).xlsx",
        source_file_name="Seasonally Adjusted (M).xlsx",
    )

    assert inspection.sheet_names == ["VICTORIA"]
    assert profiles[0]["market_key"] == "victoria_bc"
    assert profiles[0]["market_name"] == "Victoria"
    assert len(observations) == 6
    composite = next(item for item in observations if item["property_type_slug"] == "composite")
    assert composite["point_date"] == "2005-01-01"
    assert composite["benchmark_price"] == 300000.0


def test_build_market_metric_snapshot_calculates_growth_fields() -> None:
    observations = [
        {"point_date": "2016-01-01", "index_value": 100.0, "benchmark_price": 400000.0},
        {"point_date": "2021-01-01", "index_value": 150.0, "benchmark_price": 600000.0},
        {"point_date": "2025-01-01", "index_value": 180.0, "benchmark_price": 720000.0},
        {"point_date": "2025-12-01", "index_value": 200.0, "benchmark_price": 800000.0},
    ]

    snapshot = build_market_metric_snapshot(
        observations,
        source="crea_hpi",
        market_key="victoria_bc",
        market_name="Victoria",
        province="BC",
        property_type_slug="composite",
        property_type_label="Composite",
    )

    assert snapshot["latest_date"] == "2025-12-01"
    assert snapshot["latest_index_value"] == 200.0
    assert snapshot["latest_benchmark_price"] == 800000.0
    assert round(snapshot["appreciation_5y_total_pct"], 4) == 0.3333
    assert round(snapshot["change_12m_pct"], 4) == 0.1111
    assert snapshot["data_quality_flag"] == "high"


def test_derive_appreciation_signal_returns_recent_cooling() -> None:
    assert (
        derive_appreciation_signal(
            {
                "appreciation_5y_cagr": 0.04,
                "change_12m_pct": -0.05,
                "change_1m_pct": -0.01,
                "data_quality_flag": "high",
            }
        )
        == "recent_cooling"
    )
