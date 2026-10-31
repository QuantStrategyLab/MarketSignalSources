"""Price-proxy research export and consumed-input manifest contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from market_signal_sources.artifacts.research_export import write_research_export_manifest
from market_signal_sources.artifacts.validation import validate_research_export_manifest
from market_signal_sources.cli.export_us_equity_price_proxy_research_csv import (
    main as export_us_equity_price_proxy_main,
)
import market_signal_sources.cli.export_us_equity_price_proxy_research_csv as price_proxy_cli


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_exports_us_equity_price_proxy_research_csv(
    tmp_path,
    capsys,
) -> None:
    nasdaq100_csv = tmp_path / "fred_nasdaq100.csv"
    sp500_csv = tmp_path / "fred_sp500.csv"
    output_csv = tmp_path / "research" / "us_equity_price_proxy.csv"
    manifest_path = tmp_path / "research" / "us_equity_price_proxy.manifest.json"
    pd.DataFrame(
        {
            "DATE": [
                "2025-01-02",
                "2025-01-03",
                "bad-date",
                "2025-01-07",
                "2025-01-08",
            ],
            "NASDAQ100": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    ).to_csv(nasdaq100_csv, index=False)
    pd.DataFrame(
        {
            "DATE": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-06",
                "2025-01-07",
                "2025-01-08",
            ],
            "SP500": [50.0, 51.0, 52.0, 53.0, 54.0],
        }
    ).to_csv(sp500_csv, index=False)

    result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(nasdaq100_csv),
            "--fred-sp500-csv",
            str(sp500_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-01-07",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert summary["artifact_type"] == "us_equity_price_proxy_research_csv"
    assert summary["transform"] == "us_equity.nasdaq_sp500.price_proxy.v1"
    assert summary["row_count"] == 3
    assert summary["last_date"] == "2025-01-07"
    assert list(exported.columns) == [
        "date",
        "QQQ",
        "SPY",
        "provider_timestamp",
    ]
    assert exported["date"].tolist() == [
        "2025-01-02",
        "2025-01-03",
        "2025-01-07",
    ]
    assert exported["QQQ"].tolist() == [100.0, 101.0, 103.0]
    assert exported["SPY"].tolist() == [50.0, 51.0, 53.0]
    assert manifest["artifact_type"] == "us_equity_price_proxy_research_csv"
    assert manifest["transform"] == "us_equity.nasdaq_sp500.price_proxy.v1"
    assert manifest["input_csv"]["sha256"] == _sha256(nasdaq100_csv)
    assert manifest["output_csv"]["sha256"] == _sha256(output_csv)
    assert [record["source_id"] for record in manifest["input_sources"]] == [
        "fred.nasdaq100",
        "fred.sp500",
    ]
    assert manifest["input_sources"][1]["sha256"] == _sha256(sp500_csv)
    assert manifest["transform_parameters"]["price_alignment"] == (
        "exact_date_inner_join"
    )

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="us_equity_price_proxy_research_csv",
        expected_transform="us_equity.nasdaq_sp500.price_proxy.v1",
    )
    assert validation_summary["row_count"] == 3
    assert validation_summary["columns"] == tuple(exported.columns)
    assert validation_summary["output_csv_sha256"] == _sha256(output_csv)


def test_price_proxy_export_rejects_source_replacement_before_writing(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    nasdaq100_csv = tmp_path / "fred_nasdaq100.csv"
    sp500_csv = tmp_path / "fred_sp500.csv"
    output_csv = tmp_path / "research" / "proxy.csv"
    manifest_path = tmp_path / "research" / "proxy.manifest.json"
    nasdaq100_csv.write_text("DATE,NASDAQ100\n2025-01-02,100\n2025-01-03,101\n")
    sp500_csv.write_text("DATE,SP500\n2025-01-02,50\n2025-01-03,51\n")

    original_builder = price_proxy_cli.build_nasdaq_sp500_price_proxy_frame

    def replace_source_after_parse(**kwargs):
        nasdaq100_csv.write_text("DATE,NASDAQ100\n2025-01-02,100\n2025-01-03,999\n")
        return original_builder(**kwargs)

    monkeypatch.setattr(
        price_proxy_cli,
        "build_nasdaq_sp500_price_proxy_frame",
        replace_source_after_parse,
    )
    result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(nasdaq100_csv),
            "--fred-sp500-csv",
            str(sp500_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    assert result == 2
    assert "changed" in capsys.readouterr().err.lower()
    assert not output_csv.exists()
    assert not manifest_path.exists()


def test_price_proxy_export_reads_canonical_same_file_once_and_keeps_path_spelling(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_csv = source_dir / "combined.csv"
    source_csv.write_text(
        "DATE,NASDAQ100,SP500\n2025-01-02,100,50\n2025-01-03,101,51\n"
    )
    source_nested = source_dir / "nested"
    source_nested.mkdir()
    source_link = tmp_path / "combined-link.csv"
    source_link.symlink_to(source_csv)
    original_spelling = tmp_path / "source" / "nested" / ".." / "combined.csv"
    output_csv = tmp_path / "research" / "proxy.csv"
    manifest_path = tmp_path / "research" / "proxy.manifest.json"
    read_bytes = Path.read_bytes
    source_reads = 0

    def count_read_bytes(path):
        nonlocal source_reads
        if path.resolve() == source_csv.resolve():
            source_reads += 1
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_read_bytes)
    result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(original_spelling),
            "--fred-sp500-csv",
            str(source_link),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    assert result == 0
    capsys.readouterr()
    assert source_reads == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["input_csv"]["path"] == str(original_spelling)
    assert [record["source_id"] for record in manifest["input_sources"]] == [
        "fred.nasdaq100",
        "fred.sp500",
    ]
    assert all(record["sha256"] == _sha256(source_csv) for record in manifest["input_sources"])


def test_price_proxy_export_rejects_symlink_retarget_before_writing(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    first_source = tmp_path / "first.csv"
    replacement_source = tmp_path / "replacement.csv"
    sp500_csv = tmp_path / "sp500.csv"
    source_link = tmp_path / "nasdaq.csv"
    source_bytes = b"DATE,NASDAQ100\n2025-01-02,100\n2025-01-03,101\n"
    first_source.write_bytes(source_bytes)
    replacement_source.write_bytes(source_bytes)
    sp500_csv.write_text("DATE,SP500\n2025-01-02,50\n2025-01-03,51\n")
    source_link.symlink_to(first_source)
    output_csv = tmp_path / "research" / "proxy.csv"
    manifest_path = tmp_path / "research" / "proxy.manifest.json"
    original_builder = price_proxy_cli.build_nasdaq_sp500_price_proxy_frame

    def retarget_source_after_parse(**kwargs):
        source_link.unlink()
        source_link.symlink_to(replacement_source)
        return original_builder(**kwargs)

    monkeypatch.setattr(
        price_proxy_cli,
        "build_nasdaq_sp500_price_proxy_frame",
        retarget_source_after_parse,
    )
    result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(source_link),
            "--fred-sp500-csv",
            str(sp500_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    assert result == 2
    assert "changed" in capsys.readouterr().err.lower()
    assert not output_csv.exists()
    assert not manifest_path.exists()


def test_research_export_manifest_can_bind_consumed_input_bytes(tmp_path) -> None:
    input_csv = tmp_path / "input.csv"
    input_csv.write_bytes(b"later file contents")
    output_csv = tmp_path / "output.csv"
    output_csv.write_text("date,value\n2025-01-02,1\n")
    output_frame = pd.DataFrame({"date": ["2025-01-02"], "value": [1]})
    consumed_bytes = b"bytes actually parsed"

    default_manifest = write_research_export_manifest(
        tmp_path / "default-manifest.json",
        output_csv_path=output_csv,
        output_frame=output_frame,
        input_csv_path=input_csv,
        artifact_type="us_equity_price_proxy_research_csv",
        transform="us_equity.nasdaq_sp500.price_proxy.v1",
        source_version="test",
        as_of=None,
        min_history=1,
    )
    assert default_manifest["input_csv"]["sha256"] == _sha256(input_csv)
    assert default_manifest["input_csv"]["size_bytes"] == input_csv.stat().st_size

    manifest = write_research_export_manifest(
        tmp_path / "manifest.json",
        output_csv_path=output_csv,
        output_frame=output_frame,
        input_csv_path=input_csv,
        artifact_type="us_equity_price_proxy_research_csv",
        transform="us_equity.nasdaq_sp500.price_proxy.v1",
        source_version="test",
        as_of=None,
        min_history=1,
        input_csv_bytes=consumed_bytes,
    )

    assert manifest["input_csv"]["sha256"] == hashlib.sha256(consumed_bytes).hexdigest()
    assert manifest["input_csv"]["size_bytes"] == len(consumed_bytes)
