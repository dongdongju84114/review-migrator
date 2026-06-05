from __future__ import annotations

from html import escape
from pathlib import Path

from review_migrator.schemas import VerificationReport


def render_markdown(report: VerificationReport) -> str:
    lines = [
        f"# CREMA Verification Report: {report.run_id}",
        "",
        f"- checked_at: {report.checked_at.isoformat()}",
        f"- expected_count: {report.expected_count}",
        f"- actual_found_count: {report.actual_found_count}",
        f"- ok_count: {report.ok_count}",
        f"- failed_count: {report.failed_count}",
        "",
        "| code | result | messages |",
        "| --- | --- | --- |",
    ]
    for item in report.items:
        result = "OK" if item.ok else "FAIL"
        messages = "; ".join(item.messages)
        lines.append(f"| `{item.code}` | {result} | {messages} |")
    return "\n".join(lines) + "\n"


def render_html(report: VerificationReport) -> str:
    rows = []
    for item in report.items:
        result = "OK" if item.ok else "FAIL"
        messages = "; ".join(item.messages)
        rows.append(
            "<tr>"
            f"<td><code>{escape(item.code)}</code></td>"
            f"<td>{escape(result)}</td>"
            f"<td>{escape(messages)}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>CREMA Verification Report {escape(report.run_id)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d8dee4; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  </style>
</head>
<body>
  <h1>CREMA Verification Report</h1>
  <p>run_id: <code>{escape(report.run_id)}</code></p>
  <ul>
    <li>checked_at: {escape(report.checked_at.isoformat())}</li>
    <li>expected_count: {report.expected_count}</li>
    <li>actual_found_count: {report.actual_found_count}</li>
    <li>ok_count: {report.ok_count}</li>
    <li>failed_count: {report.failed_count}</li>
  </ul>
  <table>
    <thead><tr><th>code</th><th>result</th><th>messages</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""


def write_report(path: str | Path, report: VerificationReport) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".html":
        output_path.write_text(render_html(report), encoding="utf-8")
    else:
        output_path.write_text(render_markdown(report), encoding="utf-8")

