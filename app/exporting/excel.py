from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any, Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _text_cell(reference: str, value: Any, style: int = 0) -> str:
    text = escape(str(value))
    preserve = ' xml:space="preserve"' if text != text.strip() else ""
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f"<is><t{preserve}>{text}</t></is></c>"
    )


def _number_cell(reference: str, value: Any, style: int = 0) -> str:
    return f'<c r="{reference}" s="{style}"><v>{escape(str(value))}</v></c>'


def _formula_cell(reference: str, formula: str, value: Any, style: int = 0) -> str:
    return (
        f'<c r="{reference}" s="{style}"><f>{escape(formula)}</f>'
        f"<v>{escape(str(value))}</v></c>"
    )


def _excel_date(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def _worksheet_xml(
    rows: Iterable[str],
    *,
    dimensions: str,
    columns: list[float],
    freeze_row: int,
    auto_filter: str | None = None,
    merged_cells: list[str] | None = None,
) -> str:
    column_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(columns, start=1)
    )
    filter_xml = f'<autoFilter ref="{auto_filter}"/>' if auto_filter else ""
    merges = merged_cells or []
    merge_xml = (
        f'<mergeCells count="{len(merges)}">'
        + "".join(f'<mergeCell ref="{reference}"/>' for reference in merges)
        + "</mergeCells>"
        if merges
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimensions}"/>'
        '<sheetViews><sheetView workbookViewId="0" showGridLines="0">'
        f'<pane ySplit="{freeze_row}" topLeftCell="A{freeze_row + 1}" '
        'activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{column_xml}</cols>"
        f"<sheetData>{''.join(rows)}</sheetData>"
        f"{filter_xml}{merge_xml}"
        '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" '
        'header="0.3" footer="0.3"/>'
        "</worksheet>"
    )


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="4">
    <numFmt numFmtId="164" formatCode="yyyy-mm-dd"/>
    <numFmt numFmtId="165" formatCode="[$Rp-421] #,##0;[Red]-[$Rp-421] #,##0;-"/>
    <numFmt numFmtId="166" formatCode="#,##0"/>
    <numFmt numFmtId="167" formatCode="0.00%;[Red]-0.00%;-"/>
  </numFmts>
  <fonts count="5">
    <font><sz val="11"/><name val="Aptos"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="16"/><name val="Aptos Display"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font>
    <font><b/><color rgb="FF0F172A"/><sz val="11"/><name val="Aptos"/></font>
    <font><i/><color rgb="FF475569"/><sz val="10"/><name val="Aptos"/></font>
  </fonts>
  <fills count="6">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0F172A"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0F766E"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE6FFFA"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF1F5F9"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="13">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1"><alignment vertical="center"/></xf>
    <xf numFmtId="165" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="166" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1"><alignment horizontal="right" vertical="center"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def build_ohlcv_workbook(
    source_rows: Iterable[Any], *, generated_at: datetime | None = None
) -> bytes:
    """Build a portable XLSX workbook without adding a heavy runtime dependency."""

    records = list(source_rows)
    generated_at = generated_at or datetime.now(timezone.utc)
    summaries: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        summaries[str(record.symbol)].append(record)

    total_volume = sum(int(record.volume) for record in records)

    summary_rows: list[str] = [
        '<row r="1" ht="26" customHeight="1">'
        + _text_cell("A1", "IDX Daily OHLCV Report", 1)
        + "</row>",
        '<row r="2">'
        + _text_cell(
            "A2",
            f"Validated market data • Currency: IDR • Generated {generated_at.isoformat(timespec='seconds')}",
            8,
        )
        + "</row>",
        '<row r="4">'
        + _text_cell("A4", "Total Candles", 6)
        + _number_cell("B4", len(records), 12)
        + _text_cell("E4", "Jumlah Saham", 6)
        + _number_cell("F4", len(summaries), 12)
        + "</row>",
        '<row r="5">'
        + _text_cell("A5", "Mata Uang", 6)
        + _text_cell("B5", "IDR (Rupiah)", 10)
        + _text_cell("E5", "Total Volume", 6)
        + _number_cell("F5", total_volume, 12)
        + "</row>",
        '<row r="7">'
        + _text_cell("A7", "Symbol", 2)
        + _text_cell("B7", "Candles", 2)
        + _text_cell("C7", "First Date", 2)
        + _text_cell("D7", "Last Date", 2)
        + _text_cell("E7", "First Close", 2)
        + _text_cell("F7", "Last Close", 2)
        + _text_cell("G7", "Change", 2)
        + _text_cell("H7", "Total Volume", 2)
        + "</row>",
    ]
    for row_number, symbol in enumerate(sorted(summaries), start=8):
        symbol_records = sorted(summaries[symbol], key=lambda item: item.trade_date)
        first_record = symbol_records[0]
        last_record = symbol_records[-1]
        first_close = Decimal(first_record.close)
        last_close = Decimal(last_record.close)
        price_change = (last_close - first_close) / first_close if first_close else Decimal(0)
        summary_rows.append(
            f'<row r="{row_number}">'
            + _text_cell(f"A{row_number}", symbol, 9)
            + _number_cell(f"B{row_number}", len(symbol_records), 5)
            + _number_cell(f"C{row_number}", _excel_date(first_record.trade_date), 3)
            + _number_cell(f"D{row_number}", _excel_date(last_record.trade_date), 3)
            + _number_cell(f"E{row_number}", first_close, 4)
            + _number_cell(f"F{row_number}", last_close, 4)
            + _number_cell(f"G{row_number}", price_change, 7)
            + _number_cell(
                f"H{row_number}", sum(int(item.volume) for item in symbol_records), 5
            )
            + "</row>"
        )
    summary_last_row = max(8, 7 + len(summaries))
    summary_xml = _worksheet_xml(
        summary_rows,
        dimensions=f"A1:H{summary_last_row}",
        columns=[14, 13, 15, 15, 18, 18, 14, 20],
        freeze_row=7,
        auto_filter=f"A7:H{summary_last_row}" if summaries else None,
        merged_cells=[
            "A1:H1",
            "A2:H2",
            "B4:D4",
            "F4:H4",
            "B5:D5",
            "F5:H5",
        ],
    )

    data_rows: list[str] = [
        '<row r="1" ht="26" customHeight="1">'
        + _text_cell("A1", "Validated IDX Daily OHLCV", 1)
        + "</row>",
        '<row r="2">'
        + _text_cell(
            "A2",
            "Currency: IDR (Rupiah) • Prices are numeric and Excel-formatted • Incomplete candles are excluded.",
            8,
        )
        + "</row>",
        '<row r="4">'
        + "".join(
            _text_cell(f"{column}4", label, 2)
            for column, label in zip(
                "ABCDEFGHIJ",
                [
                    "Symbol",
                    "Trade Date",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Change vs Open",
                    "Volume",
                    "Source",
                    "Ingested At",
                ],
                strict=True,
            )
        )
        + "</row>",
    ]
    for row_number, record in enumerate(records, start=5):
        ingested_at = getattr(record, "ingested_at", None)
        ingested_text = ingested_at.isoformat() if ingested_at else ""
        open_price = Decimal(record.open)
        close_price = Decimal(record.close)
        intraday_change = (close_price - open_price) / open_price if open_price else Decimal(0)
        values = [
            _text_cell(f"A{row_number}", record.symbol, 9),
            _number_cell(f"B{row_number}", _excel_date(record.trade_date), 3),
            _number_cell(f"C{row_number}", open_price, 4),
            _number_cell(f"D{row_number}", Decimal(record.high), 4),
            _number_cell(f"E{row_number}", Decimal(record.low), 4),
            _number_cell(f"F{row_number}", close_price, 4),
            _formula_cell(
                f"G{row_number}",
                f"IFERROR((F{row_number}-C{row_number})/C{row_number},0)",
                intraday_change,
                7,
            ),
            _number_cell(f"H{row_number}", int(record.volume), 5),
            _text_cell(f"I{row_number}", getattr(record, "source", ""), 9),
            _text_cell(f"J{row_number}", ingested_text, 9),
        ]
        data_rows.append(f'<row r="{row_number}">' + "".join(values) + "</row>")
    data_last_row = max(5, 4 + len(records))
    data_xml = _worksheet_xml(
        data_rows,
        dimensions=f"A1:J{data_last_row}",
        columns=[14, 15, 17, 17, 17, 17, 18, 19, 16, 28],
        freeze_row=4,
        auto_filter=f"A4:J{data_last_row}" if records else None,
        merged_cells=["A1:J1", "A2:J2"],
    )

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView activeTab="0"/></bookViews>
  <sheets><sheet name="Summary" sheetId="1" r:id="rId1"/><sheet name="OHLCV" sheetId="2" r:id="rId2"/></sheets>
  <calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    timestamp = generated_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>IDX OHLCV Export</dc:title><dc:creator>IDX OHLCV Platform</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
</cp:coreProperties>"""
    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>IDX OHLCV Platform</Application>
</Properties>"""

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", _styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", summary_xml)
        archive.writestr("xl/worksheets/sheet2.xml", data_xml)
    return output.getvalue()
