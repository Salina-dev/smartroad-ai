import os
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

class ReportGenerator:
    def generate_pdf_report(self, meta, output_path):
        c = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4
        styles = getSampleStyleSheet()
        title = styles["Title"]
        normal = styles["Normal"]

        c.setFont("Helvetica-Bold", 18)
        c.drawString(40, height - 60, "ROAD DAMAGE INSPECTION REPORT")
        c.setFont("Helvetica", 11)
        c.drawString(40, height - 90, f"User: {meta['user_name']}")
        c.drawString(40, height - 110, f"Inspection Date: {meta['inspection_date']}")
        c.drawString(40, height - 130, f"Location: {meta['location']['city']}, {meta['location']['state']}, {meta['location']['country']}")
        c.drawString(40, height - 150, f"Road Name: {meta['location']['road_name']}")
        c.drawString(40, height - 170, f"GPS: {meta['location']['latitude']} / {meta['location']['longitude']}")
        c.drawString(40, height - 190, f"File Name: {meta['file_name']}")

        # --- Embed Detection Image ---
        # Assuming meta['full_path'] is provided or use file_name if it exists
        img_path = meta.get('full_path') or meta.get('file_name')
        if img_path and os.path.exists(img_path):
            try:
                # Draw image (resized to fit)
                img_width = 400
                img_height = 300
                c.drawImage(img_path, 40, height - 520, width=img_width, height=img_height, preserveAspectRatio=True)
                table_y = height - 630
            except Exception as e:
                c.drawString(40, height - 210, f"Error embedding image: {str(e)}")
                table_y = height - 300
        else:
            table_y = height - 300

        stats_table = [
            ["Total Potholes", meta['total_potholes']],
            ["Total Cracks", meta['total_cracks']],
            ["Critical Damages", meta['critical_damages']],
            ["Condition Score", f"{meta['condition_score']}%"],
        ]
        table = Table(stats_table, colWidths=[180, 180])
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f77b4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ])
        )
        table.wrapOn(c, width, height)
        table.drawOn(c, 40, table_y)

        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, table_y - 40, "Recommendations")
        recommendations = self.build_recommendations(meta)
        text = c.beginText(40, table_y - 60)
        text.setFont("Helvetica", 11)
        for line in recommendations:
            text.textLine(f"- {line}")
        c.drawText(text)

        c.showPage()
        c.save()

    def generate_excel_report(self, meta, output_path):
        rows = []
        for item in meta['detections']:
            rows.append(
                {
                    "Label": item['label'],
                    "Confidence": item['confidence'],
                    "Severity": item['severity'],
                    "BBox": item['bbox'],
                }
            )
        df = pd.DataFrame(rows)
        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Inspection Details", index=False)
            summary = pd.DataFrame(
                [
                    ["User", meta['user_name']],
                    ["Inspection Date", meta['inspection_date']],
                    ["Location", f"{meta['location']['road_name']}, {meta['location']['city']}, {meta['location']['state']}, {meta['location']['country']}"],
                    ["Latitude", meta['location']['latitude']],
                    ["Longitude", meta['location']['longitude']],
                    ["Total Potholes", meta['total_potholes']],
                    ["Total Cracks", meta['total_cracks']],
                    ["Critical Damages", meta['critical_damages']],
                    ["Condition Score", meta['condition_score']],
                ],
                columns=["Metric", "Value"],
            )
            summary.to_excel(writer, sheet_name="Summary", index=False)

    def build_recommendations(self, meta):
        recommendations = []
        if meta['critical_damages'] > 0:
            recommendations.append("Emergency repair required for critical damage zones.")
        if meta['total_potholes'] > 0:
            recommendations.append("Pothole repair recommended on affected road sections.")
        if meta['total_cracks'] > 5:
            recommendations.append("Minor crack sealing required to prevent worsening.")
        if meta['condition_score'] < 40:
            recommendations.append("Immediate road maintenance required due to low condition score.")
        if not recommendations:
            recommendations.append("No immediate structural maintenance recommended. Continue monitoring.")
        return recommendations
