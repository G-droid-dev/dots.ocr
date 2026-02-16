"""
Table extractor: converts HTML table strings from dots.ocr output
into structured data mapped against a YAML field-mapping configuration.
"""

import os
import re
from io import StringIO
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_tables_from_cells(
    cells_data: List[Dict],
    field_mapping_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Given dots.ocr ``cells_data`` (list of dicts with *category* and *text*),
    extract every element whose category is ``"Table"`` and convert the HTML
    into a structured dict with *headers*, *rows* (list of dicts), and the
    *raw_html*.

    Parameters
    ----------
    cells_data : list[dict]
        Output from ``DotsOCRParser`` — each item has ``bbox``, ``category``,
        ``text``.
    field_mapping_path : str, optional
        Absolute path to a YAML field-mapping file.  If ``None``, uses the
        default at ``field_mappings/default.yaml`` relative to the repo root.

    Returns
    -------
    list[dict]
        One dict per table found: ``{"table_index", "headers", "rows", "raw_html"}``.
    """
    mapping = _load_field_mapping(field_mapping_path)
    tables: List[Dict[str, Any]] = []
    idx = 0

    for cell in cells_data:
        if cell.get("category") != "Table":
            continue
        html = cell.get("text", "")
        if not html.strip():
            continue

        try:
            df = _html_to_dataframe(html)
        except Exception:
            # If pandas cannot parse, fall back to raw HTML only
            tables.append({
                "table_index": idx,
                "headers": [],
                "rows": [],
                "raw_html": html,
            })
            idx += 1
            continue

        headers = list(df.columns)
        mapped_rows = _map_rows(df, mapping) if mapping else _rows_as_dicts(df)

        tables.append({
            "table_index": idx,
            "headers": headers,
            "rows": mapped_rows,
            "raw_html": html,
        })
        idx += 1

    return tables


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_MAPPING_PATH: Optional[str] = None  # resolved lazily


def _resolve_default_mapping() -> Optional[str]:
    global _DEFAULT_MAPPING_PATH
    if _DEFAULT_MAPPING_PATH is not None:
        return _DEFAULT_MAPPING_PATH

    # Walk up from this file to find repo root/field_mappings/default.yaml
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))  # dots.ocr/
    candidate = os.path.join(repo_root, "field_mappings", "default.yaml")
    if os.path.isfile(candidate):
        _DEFAULT_MAPPING_PATH = candidate
    else:
        _DEFAULT_MAPPING_PATH = ""  # empty string → no mapping
    return _DEFAULT_MAPPING_PATH or None


def _load_field_mapping(path: Optional[str] = None) -> Optional[Dict]:
    """Load and cache the YAML field mapping."""
    if path is None:
        path = _resolve_default_mapping()
    if not path or not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("mappings") if data else None


def _html_to_dataframe(html: str) -> pd.DataFrame:
    """
    Parse an HTML ``<table>`` string into a pandas DataFrame.
    Uses the first row as headers.
    """
    # BeautifulSoup normalisation — ensures well-formed HTML for pandas
    soup = BeautifulSoup(html, "html.parser")
    table_tag = soup.find("table")
    if table_tag is None:
        raise ValueError("No <table> element found in HTML")

    clean_html = str(table_tag)
    dfs = pd.read_html(StringIO(clean_html), header=0)
    if not dfs:
        raise ValueError("pandas.read_html returned no tables")

    df = dfs[0]
    # Drop completely empty rows / columns
    df = df.dropna(how="all").dropna(axis=1, how="all")
    # Convert column names to strings
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _map_rows(df: pd.DataFrame, mapping: Dict) -> List[Dict[str, Any]]:
    """
    Map each row of a DataFrame to schema fields using the YAML mapping.

    The mapping dict has the form::

        {
          "model": {"patterns": ["model", "modell", ...], "schema_field": "model"},
          ...
        }

    For each column header, find the first mapping entry whose regex pattern
    matches (case-insensitive), and rename the column to the ``schema_field``.
    """
    col_map = _build_column_map(df.columns.tolist(), mapping)
    rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        mapped: Dict[str, Any] = {}
        for col in df.columns:
            value = row[col]
            # Convert NaN to None
            if pd.isna(value):
                value = None
            elif isinstance(value, float) and value == int(value):
                value = int(value)

            field = col_map.get(col, col)  # fall back to raw column name
            # Handle dotted field paths like "price.value"
            _set_nested(mapped, field, value)

        rows.append(mapped)

    return rows


def _rows_as_dicts(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Simple fallback: rows as plain dicts without field mapping."""
    rows = []
    for _, row in df.iterrows():
        d = {}
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                val = None
            elif isinstance(val, float) and val == int(val):
                val = int(val)
            d[col] = val
        rows.append(d)
    return rows


def _build_column_map(headers: List[str], mapping: Dict) -> Dict[str, str]:
    """
    For each header, find the first matching mapping entry.

    Returns
    -------
    dict
        ``{original_header: schema_field}``
    """
    col_map: Dict[str, str] = {}
    for header in headers:
        for _key, entry in mapping.items():
            patterns = entry.get("patterns", [])
            schema_field = entry.get("schema_field", header)
            for pat in patterns:
                if re.search(pat, header, re.IGNORECASE):
                    col_map[header] = schema_field
                    break
            if header in col_map:
                break
    return col_map


def _set_nested(d: Dict, dotted_key: str, value: Any) -> None:
    """
    Set a value in a nested dict using a dotted key path.
    E.g. ``_set_nested(d, "price.value", 28950)`` →
    ``d["price"]["value"] = 28950``.
    """
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value
