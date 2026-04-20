import argparse
import csv
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_LIMIT = 10
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 5
RETRY_SLEEP_SECONDS = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run search evaluation queries against the opensearch-connector API."
    )
    parser.add_argument(
        "--input",
        default=os.getenv("SEARCH_EVAL_INPUT", "/workspace/search-evaluation-template.csv"),
        help="Input CSV template with evaluation queries.",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("SEARCH_EVAL_OUTPUT", "/workspace/search-evaluation-results.csv"),
        help="Output CSV file with observed results filled in.",
    )
    parser.add_argument(
        "--html-output",
        default=os.getenv("SEARCH_EVAL_HTML_OUTPUT", "/workspace/search-evaluation-results.html"),
        help="Output HTML report file for inspecting evaluation results.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SEARCH_EVAL_BASE_URL", "http://opensearch-connector:8000"),
        help="Base URL of the opensearch-connector service.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("SEARCH_EVAL_LIMIT", str(DEFAULT_LIMIT))),
        help="Search result limit to request from the connector.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("SEARCH_EVAL_TIMEOUT", str(DEFAULT_TIMEOUT))),
        help="HTTP timeout per request in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("SEARCH_EVAL_RETRIES", str(DEFAULT_RETRIES))),
        help="Number of retries while waiting for the connector.",
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv("SEARCH_EVAL_DATASET", ""),
        help="Optional dataset filter to send with every request, for example 'gnd' or 'aat,gnd'.",
    )
    return parser.parse_args()


def normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def split_candidates(value: str) -> List[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def parse_expected_candidate(value: str) -> Tuple[str, Optional[str]]:
    cleaned = value.strip()
    if not cleaned:
        return "", None

    if cleaned.endswith(")") and " (" in cleaned:
        label, suffix = cleaned.rsplit(" (", 1)
        entity_type = suffix[:-1].strip() or None
        return label.strip(), entity_type

    return cleaned, None


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def build_summary(rows: List[Dict[str, str]]) -> Dict[str, int]:
    summary = {
        "total": len(rows),
        "overall_pass": 0,
        "top_1_correct": 0,
        "top_5_contains_expected": 0,
    }

    for row in rows:
        if row.get("overall_pass") == "TRUE":
            summary["overall_pass"] += 1
        if row.get("top_1_correct") == "TRUE":
            summary["top_1_correct"] += 1
        if row.get("top_5_contains_expected") == "TRUE":
            summary["top_5_contains_expected"] += 1

    return summary


def render_html_report(
    rows: List[Dict[str, str]],
    fieldnames: List[str],
    html_output_path: Path,
    csv_output_path: Path,
) -> None:
    summary = build_summary(rows)
    summary_cards = [
        ("Queries", str(summary["total"])),
        ("Overall Pass", f'{summary["overall_pass"]}/{summary["total"]}'),
        ("Top 1 Correct", f'{summary["top_1_correct"]}/{summary["total"]}'),
        ("Top 5 Match", f'{summary["top_5_contains_expected"]}/{summary["total"]}'),
    ]

    table_headers = "".join(f"<th>{html_escape(name)}</th>" for name in fieldnames)
    table_rows = []
    for row in rows:
        status = row.get("overall_pass", "")
        row_class = "pass" if status == "TRUE" else "fail" if status == "FALSE" else "unknown"
        cells = "".join(
            f"<td data-column=\"{html_escape(name)}\">{html_escape(row.get(name, ''))}</td>"
            for name in fieldnames
        )
        table_rows.append(f"<tr class=\"{row_class}\">{cells}</tr>")

    summary_html = "".join(
        f'<div class="summary-card"><div class="summary-label">{html_escape(label)}</div><div class="summary-value">{html_escape(value)}</div></div>'
        for label, value in summary_cards
    )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Search Evaluation Report</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #d6d3d1;
      --pass: #d1fae5;
      --fail: #fee2e2;
      --unknown: #fef3c7;
      --accent: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(29, 78, 216, 0.08), transparent 28%),
        linear-gradient(180deg, #faf7f2 0%, var(--bg) 100%);
    }}
    .page {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 5vw, 44px);
      line-height: 1.05;
    }}
    p {{
      margin: 0;
      color: var(--muted);
      max-width: 70ch;
    }}
    .meta {{
      margin-top: 12px;
      font-size: 14px;
    }}
    .meta a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 20px;
    }}
    .summary-card {{
      background: #fcfbf8;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
    }}
    .summary-label {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .summary-value {{
      font-size: 28px;
      font-weight: 700;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin: 20px 0 14px;
    }}
    .toolbar input, .toolbar select {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      background: var(--panel);
      font-size: 14px;
    }}
    .table-wrap {{
      border: 1px solid var(--line);
      border-radius: 20px;
      overflow: hidden;
      background: var(--panel);
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
    }}
    .table-scroll {{
      overflow: auto;
      max-height: 70vh;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: #f7f4ee;
      z-index: 1;
      text-align: left;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      vertical-align: top;
      min-width: 140px;
    }}
    tbody tr.pass {{ background: var(--pass); }}
    tbody tr.fail {{ background: var(--fail); }}
    tbody tr.unknown {{ background: var(--unknown); }}
    .legend {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .swatch {{
      width: 14px;
      height: 14px;
      border-radius: 4px;
      border: 1px solid rgba(0, 0, 0, 0.08);
    }}
    .swatch.pass {{ background: var(--pass); }}
    .swatch.fail {{ background: var(--fail); }}
    .swatch.unknown {{ background: var(--unknown); }}
    @media (max-width: 800px) {{
      .page {{ padding: 20px 12px 32px; }}
      th, td {{ min-width: 110px; padding: 8px 10px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Search Evaluation Report</h1>
      <p>Inspect ranking outcomes from the opensearch-connector test run. Use the filters to narrow by query text, scope, or pass status.</p>
      <div class="meta">CSV output: <a href="{html_escape(csv_output_path.name)}">{html_escape(csv_output_path.name)}</a></div>
      <div class="summary">{summary_html}</div>
    </section>

    <div class="toolbar">
      <input id="queryFilter" type="search" placeholder="Filter by query or result text">
      <select id="scopeFilter">
        <option value="">All scopes</option>
        <option value="global">Global</option>
        <option value="type-specific">Type-specific</option>
      </select>
      <select id="statusFilter">
        <option value="">All statuses</option>
        <option value="TRUE">Pass only</option>
        <option value="FALSE">Fail only</option>
      </select>
    </div>

    <div class="legend">
      <span><i class="swatch pass"></i> pass</span>
      <span><i class="swatch fail"></i> fail</span>
      <span><i class="swatch unknown"></i> not fully assessed</span>
    </div>

    <section class="table-wrap">
      <div class="table-scroll">
        <table id="resultsTable">
          <thead>
            <tr>{table_headers}</tr>
          </thead>
          <tbody>
            {''.join(table_rows)}
          </tbody>
        </table>
      </div>
    </section>
  </div>

  <script>
    const queryFilter = document.getElementById('queryFilter');
    const scopeFilter = document.getElementById('scopeFilter');
    const statusFilter = document.getElementById('statusFilter');
    const rows = Array.from(document.querySelectorAll('#resultsTable tbody tr'));

    function applyFilters() {{
      const queryNeedle = queryFilter.value.trim().toLowerCase();
      const scopeValue = scopeFilter.value;
      const statusValue = statusFilter.value;

      for (const row of rows) {{
        const text = row.textContent.toLowerCase();
        const scopeCell = row.querySelector('[data-column="scope"]');
        const statusCell = row.querySelector('[data-column="overall_pass"]');
        const matchesQuery = !queryNeedle || text.includes(queryNeedle);
        const matchesScope = !scopeValue || (scopeCell && scopeCell.textContent === scopeValue);
        const matchesStatus = !statusValue || (statusCell && statusCell.textContent === statusValue);
        row.style.display = matchesQuery && matchesScope && matchesStatus ? '' : 'none';
      }}
    }}

    queryFilter.addEventListener('input', applyFilters);
    scopeFilter.addEventListener('change', applyFilters);
    statusFilter.addEventListener('change', applyFilters);
  </script>
</body>
</html>
"""

    ensure_parent_dir(html_output_path)
    html_output_path.write_text(document, encoding="utf-8")


def request_json(url: str, payload: Dict[str, Any], timeout: float, retries: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url=url, data=data, headers=headers, method="POST")

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                break
            print(
                f"[retry {attempt}/{retries}] request failed for query={payload.get('query')!r}: {exc}",
                file=sys.stderr,
            )
            time.sleep(RETRY_SLEEP_SECONDS)

    raise RuntimeError(f"Request failed after {retries} attempts: {last_error}")


def get_hit_source(hit: Dict[str, Any]) -> Dict[str, Any]:
    source = hit.get("_source")
    return source if isinstance(source, dict) else {}


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()]


def get_score(hit: Dict[str, Any]) -> float:
    raw_score = hit.get("_score", 0)
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return 0.0


def choose_label(source: Dict[str, Any], fallback_id: str) -> str:
    for key in ("prefLabels", "prefLabel", "labels", "label"):
        values = as_list(source.get(key))
        if values:
            return values[0]
    return fallback_id


def choose_type(source: Dict[str, Any]) -> str:
    for key in ("typeClasses", "typeClass", "types"):
        values = as_list(source.get(key))
        if values:
            return values[0]
    return ""


def choose_dataset(source: Dict[str, Any]) -> str:
    values = as_list(source.get("dataset"))
    return values[0] if values else ""


def format_hit(hit: Dict[str, Any]) -> str:
    source = get_hit_source(hit)
    label = choose_label(source, hit.get("_id", "unknown"))
    entity_type = choose_type(source)
    dataset = choose_dataset(source)
    score = get_score(hit)

    parts = [label]
    if entity_type:
        parts.append(f"({entity_type})")
    if dataset:
        parts.append(f"[{dataset}]")
    parts.append(f"score={score:.4f}")
    return " ".join(parts)


def matches_expected(hit: Dict[str, Any], expected: str) -> bool:
    expected_label, expected_type = parse_expected_candidate(expected)
    if not expected_label:
        return False

    source = get_hit_source(hit)
    label_values = []
    for key in ("prefLabels", "prefLabel", "labels", "label"):
        label_values.extend(as_list(source.get(key)))

    expected_label_normalized = normalize_text(expected_label)
    label_match = any(normalize_text(label) == expected_label_normalized for label in label_values)
    if not label_match:
        return False

    if expected_type:
        type_values = []
        for key in ("typeClasses", "typeClass", "types"):
            type_values.extend(as_list(source.get(key)))
        expected_type_normalized = normalize_text(expected_type)
        if not any(normalize_text(value) == expected_type_normalized for value in type_values):
            return False

    return True


def contains_expected(hits: Iterable[Dict[str, Any]], expected_values: List[str]) -> bool:
    return any(matches_expected(hit, expected) for hit in hits for expected in expected_values)


def evaluate_row(
    row: Dict[str, str],
    base_url: str,
    limit: int,
    timeout: float,
    retries: int,
    dataset_override: str,
) -> Dict[str, str]:
    entity_type_filter = row.get("entity_type_filter", "").strip()
    scope = row.get("scope", "").strip()

    payload: Dict[str, Any] = {
        "query": row["query"],
        "limit": limit,
    }

    if scope == "type-specific" and entity_type_filter and entity_type_filter != "All":
        payload["typeclass"] = entity_type_filter
    if dataset_override.strip():
        payload["dataset"] = dataset_override.strip()

    response = request_json(
        url=base_url.rstrip("/") + "/search",
        payload=payload,
        timeout=timeout,
        retries=retries,
    )

    hits = response.get("hits", {}).get("hits", [])
    if not isinstance(hits, list):
        hits = []

    ranked_hits = sorted(
        hits,
        key=lambda hit: (
            -get_score(hit),
            format_hit(hit),
        ),
    )

    top_1_hit = ranked_hits[0] if ranked_hits else None
    top_5_hits = ranked_hits[:5]

    acceptable_alternatives = split_candidates(row.get("acceptable_alternatives", ""))
    expected_top_1_candidates = [row.get("expected_top_1", "").strip(), *acceptable_alternatives]
    expected_top_1_candidates = [candidate for candidate in expected_top_1_candidates if candidate]
    expected_top_5_candidates = split_candidates(row.get("expected_in_top_5", ""))

    top_1_correct = "TRUE" if top_1_hit and contains_expected([top_1_hit], expected_top_1_candidates) else "FALSE"
    top_5_contains_expected = "TRUE" if contains_expected(top_5_hits, expected_top_5_candidates) else "FALSE"

    row["observed_top_1"] = format_hit(top_1_hit) if top_1_hit else ""
    row["observed_top_5"] = " | ".join(format_hit(hit) for hit in top_5_hits)
    row["top_1_correct"] = top_1_correct
    row["top_5_contains_expected"] = top_5_contains_expected

    for field in (
        "type_ranking_ok",
        "grouping_ok",
        "normalization_ok",
        "noise_control_ok",
    ):
        if not row.get(field):
            row[field] = ""

    if top_1_correct == "TRUE" and top_5_contains_expected == "TRUE":
        row["overall_pass"] = row.get("overall_pass") or "TRUE"
    elif not row.get("overall_pass"):
        row["overall_pass"] = "FALSE"

    return row


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    html_output_path = Path(args.html_output)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if not fieldnames:
        print("Input CSV has no header row.", file=sys.stderr)
        return 1

    evaluated_rows: List[Dict[str, str]] = []
    for row in rows:
        print(f"Running query: {row.get('query', '')}", file=sys.stderr)
        try:
            evaluated_rows.append(
                evaluate_row(
                    row=row,
                    base_url=args.base_url,
                    limit=args.limit,
                    timeout=args.timeout,
                    retries=args.retries,
                    dataset_override=args.dataset,
                )
            )
        except Exception as exc:
            row["notes"] = (row.get("notes", "") + f" Request failed: {exc}").strip()
            row["overall_pass"] = "FALSE"
            evaluated_rows.append(row)
            print(f"Query failed: {row.get('query', '')}: {exc}", file=sys.stderr)

    ensure_parent_dir(output_path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(evaluated_rows)

    render_html_report(
        rows=evaluated_rows,
        fieldnames=fieldnames,
        html_output_path=html_output_path,
        csv_output_path=output_path,
    )

    passed = sum(1 for row in evaluated_rows if row.get("overall_pass") == "TRUE")
    print(f"Wrote {len(evaluated_rows)} results to {output_path}")
    print(f"Wrote HTML report to {html_output_path}")
    print(f"Overall pass count: {passed}/{len(evaluated_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
