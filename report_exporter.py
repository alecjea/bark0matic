"""Complaint diary report exporter — CSV and PDF.

Generates structured, shareable complaint evidence records for use with
councils, landlords, and strata managers.
"""
import csv
import io
from collections import Counter
from datetime import datetime

# CSV column order as specified in SEN-4.
_CSV_COLUMNS = [
    "incident_id",
    "date",
    "time",
    "day_of_week",
    "event_type",
    "duration_seconds",
    "peak_db",
    "severity_score",
    "quiet_hours_violation",
    "tenant_marked",
    "notes",
]

_DISCLAIMER = (
    "This report was generated automatically by Barkomatic Sentinel. "
    "Timestamps reflect local device time."
)


def _format_date_range(incidents: list[dict]) -> str:
    dates = [inc.get("started_at", "") for inc in incidents if inc.get("started_at")]
    if not dates:
        return "N/A"
    return f"{min(dates)[:10]} to {max(dates)[:10]}"


def _to_csv_row(inc: dict) -> dict:
    """Convert an incident dict to the CSV column mapping."""
    started_at = inc.get("started_at", "")
    try:
        dt = datetime.fromisoformat(started_at)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")
        dow = dt.strftime("%A")
    except (ValueError, TypeError):
        date_str = started_at[:10] if started_at else ""
        time_str = started_at[11:19] if len(started_at) > 10 else ""
        dow = ""
    return {
        "incident_id": inc.get("incident_id", ""),
        "date": date_str,
        "time": time_str,
        "day_of_week": dow,
        "event_type": inc.get("event_type", ""),
        "duration_seconds": inc.get("duration_seconds", ""),
        "peak_db": inc.get("peak_db", ""),
        "severity_score": inc.get("severity_score", ""),
        "quiet_hours_violation": bool(inc.get("quiet_hours_violation")),
        "tenant_marked": bool(inc.get("tenant_marked")),
        "notes": "",
    }


def export_csv(incidents: list[dict]) -> bytes:
    """Return UTF-8 encoded CSV bytes for the given incident list, sorted chronologically."""
    sorted_incidents = sorted(incidents, key=lambda x: x.get("started_at", ""))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for inc in sorted_incidents:
        writer.writerow(_to_csv_row(inc))
    return buf.getvalue().encode("utf-8")


def export_pdf(incidents: list[dict], property_address: str, device_id: str) -> bytes:
    """Return PDF bytes for the complaint diary report.

    Requires reportlab to be installed.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SentinelTitle", parent=styles["Title"], fontSize=22, spaceAfter=4
    )
    sub_style = ParagraphStyle(
        "SentinelSub", parent=styles["Heading1"], fontSize=14, spaceAfter=8
    )
    heading_style = ParagraphStyle(
        "SentinelH2",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=10,
        spaceAfter=3,
    )
    normal_style = styles["Normal"]
    small_style = ParagraphStyle(
        "SentinelSmall",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#6B7280"),
    )
    header_gray = colors.HexColor("#374151")
    row_alt = colors.HexColor("#F9FAFB")

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    date_range = _format_date_range(incidents)
    sorted_incidents = sorted(incidents, key=lambda x: x.get("started_at", ""))

    story = []

    # ── Cover page ──────────────────────────────────────────────────────
    story.append(Paragraph("Barkomatic Sentinel", title_style))
    story.append(Paragraph("Complaint Diary Report", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#D1D5DB")))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"<b>Property:</b> {property_address or 'Not configured'}", normal_style))
    story.append(Paragraph(f"<b>Monitoring period:</b> {date_range}", normal_style))
    story.append(Paragraph(f"<b>Generated:</b> {now_str}", normal_style))
    story.append(Paragraph(f"<b>Device ID:</b> {device_id or 'unknown'}", normal_style))
    story.append(Spacer(1, 10 * mm))

    # ── Summary stats ────────────────────────────────────────────────────
    story.append(Paragraph("Summary", heading_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E5E7EB")))
    story.append(Spacer(1, 3 * mm))

    total = len(incidents)
    qh_count = sum(1 for i in incidents if i.get("quiet_hours_violation"))
    avg_sev = (
        sum(float(i.get("severity_score", 0)) for i in incidents) / total
        if total
        else 0
    )

    day_counts: Counter = Counter()
    hour_counts: Counter = Counter()
    for inc in incidents:
        sa = inc.get("started_at", "")
        try:
            dt = datetime.fromisoformat(sa)
            day_counts[dt.strftime("%A")] += 1
            hour_counts[dt.hour] += 1
        except (ValueError, TypeError):
            pass

    most_active_day = max(day_counts, key=day_counts.get) if day_counts else "N/A"
    most_active_hour = (
        f"{max(hour_counts, key=hour_counts.get):02d}:00" if hour_counts else "N/A"
    )

    summary_data = [
        ["Metric", "Value"],
        ["Total incidents", str(total)],
        ["Quiet hours violations", str(qh_count)],
        ["Average severity score", f"{avg_sev:.3f}"],
        ["Most active day", most_active_day],
        ["Most active hour", most_active_hour],
    ]
    summary_table = Table(summary_data, colWidths=[95 * mm, 75 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_gray),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [row_alt, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 8 * mm))

    # ── Incident log table ───────────────────────────────────────────────
    story.append(Paragraph("Incident Log", heading_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E5E7EB")))
    story.append(Spacer(1, 3 * mm))

    # A4 printable width = 210 - 20 - 20 = 170mm
    log_headers = [
        "Date / Time",
        "Type",
        "Duration",
        "Peak dB",
        "Sev.",
        "QH",
        "Flagged",
        "Notes",
    ]
    col_widths = [38 * mm, 32 * mm, 18 * mm, 16 * mm, 14 * mm, 12 * mm, 16 * mm, 24 * mm]

    log_rows = [log_headers]
    for inc in sorted_incidents:
        row = _to_csv_row(inc)
        log_rows.append(
            [
                f"{row['date']}\n{row['time']}",
                (inc.get("event_type") or "").replace("_", " "),
                f"{row['duration_seconds']}s",
                str(row["peak_db"]),
                str(row["severity_score"]),
                "YES" if row["quiet_hours_violation"] else "",
                "YES" if row["tenant_marked"] else "",
                row["notes"] or "",
            ]
        )

    log_table = Table(log_rows, colWidths=col_widths, repeatRows=1)
    log_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_gray),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [row_alt, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(log_table)
    story.append(Spacer(1, 10 * mm))

    # ── Disclaimer ───────────────────────────────────────────────────────
    story.append(Paragraph("Disclaimer", heading_style))
    story.append(Paragraph(_DISCLAIMER, small_style))

    doc.build(story)
    return buf.getvalue()
