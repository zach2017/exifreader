#!/usr/bin/env python3
"""Generate sample PDFs with JSON custom metadata AND embedded images."""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from pypdf import PdfReader, PdfWriter
from PIL import Image as PILImage, ImageDraw, ImageFont
import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
IMAGES_DIR = os.path.join(OUTPUT_DIR, "source_images")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)


def generate_sample_image(path, width, height, bg_color, label, shape="rect"):
    """Create a sample image with a label and shape."""
    img = PILImage.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    cx, cy = width // 2, height // 2
    pad = min(width, height) // 6

    if shape == "circle":
        draw.ellipse([pad, pad, width - pad, height - pad], fill=_lighten(bg_color), outline="white", width=3)
    elif shape == "diamond":
        pts = [(cx, pad), (width - pad, cy), (cx, height - pad), (pad, cy)]
        draw.polygon(pts, fill=_lighten(bg_color), outline="white", width=3)
    else:
        draw.rectangle([pad, pad, width - pad, height - pad], fill=_lighten(bg_color), outline="white", width=3)

    # Grid lines
    for x in range(0, width, width // 8):
        draw.line([(x, 0), (x, height)], fill=_lighten(bg_color, 0.15), width=1)
    for y in range(0, height, height // 8):
        draw.line([(0, y), (width, y)], fill=_lighten(bg_color, 0.15), width=1)

    # Label
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(14, min(width, height) // 12))
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2), label, fill="white", font=font)

    # Dimensions text
    dim_text = f"{width}x{height}"
    try:
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        small_font = ImageFont.load_default()
    dbbox = draw.textbbox((0, 0), dim_text, font=small_font)
    draw.text((cx - (dbbox[2] - dbbox[0]) // 2, cy + th // 2 + 8), dim_text, fill="white", font=small_font)

    img.save(path)
    return path


def _lighten(hex_color, amount=0.25):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def create_pdf_with_images(filename, title, paragraphs, images_spec):
    """Create PDF with text content and embedded images."""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=22, spaceAfter=20)
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 12))

    for para in paragraphs:
        story.append(Paragraph(para, styles["Normal"]))
        story.append(Spacer(1, 8))

    story.append(Spacer(1, 16))

    # Embed images
    for img_spec in images_spec:
        img_path = img_spec["path"]
        display_w = img_spec.get("display_width", 3) * inch
        display_h = img_spec.get("display_height", 2) * inch
        caption = img_spec.get("caption", "")

        if os.path.exists(img_path):
            story.append(RLImage(img_path, width=display_w, height=display_h))
            if caption:
                cap_style = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=9, textColor=HexColor("#666666"), spaceAfter=12)
                story.append(Paragraph(f"<i>{caption}</i>", cap_style))
            story.append(Spacer(1, 12))

    doc.build(story)


def add_custom_metadata(input_path, output_path, standard_meta, custom_fields):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    metadata = {**standard_meta, "/CustomFields": json.dumps(custom_fields)}
    writer.add_metadata(metadata)
    with open(output_path, "wb") as f:
        writer.write(f)


# ── Generate source images ──
source_images = {
    "chart_revenue": generate_sample_image(
        os.path.join(IMAGES_DIR, "chart_revenue.png"), 640, 400, "#2563eb", "Revenue Chart", "rect"
    ),
    "chart_expenses": generate_sample_image(
        os.path.join(IMAGES_DIR, "chart_expenses.png"), 640, 400, "#dc2626", "Expenses Chart", "rect"
    ),
    "logo_company": generate_sample_image(
        os.path.join(IMAGES_DIR, "logo_company.png"), 200, 200, "#059669", "ACME", "circle"
    ),
    "diagram_arch": generate_sample_image(
        os.path.join(IMAGES_DIR, "diagram_arch.png"), 800, 500, "#7c3aed", "System Architecture", "rect"
    ),
    "photo_team": generate_sample_image(
        os.path.join(IMAGES_DIR, "photo_team.png"), 640, 480, "#ea580c", "Team Photo", "rect"
    ),
    "icon_badge": generate_sample_image(
        os.path.join(IMAGES_DIR, "icon_badge.png"), 128, 128, "#0891b2", "Badge", "diamond"
    ),
    "diagram_flow": generate_sample_image(
        os.path.join(IMAGES_DIR, "diagram_flow.png"), 700, 400, "#4f46e5", "Process Flow", "rect"
    ),
    "chart_ml": generate_sample_image(
        os.path.join(IMAGES_DIR, "chart_ml.png"), 600, 400, "#0d9488", "ML Accuracy", "rect"
    ),
    "diagram_neural": generate_sample_image(
        os.path.join(IMAGES_DIR, "diagram_neural.png"), 500, 500, "#8b5cf6", "Neural Network", "circle"
    ),
    "chart_energy": generate_sample_image(
        os.path.join(IMAGES_DIR, "chart_energy.png"), 640, 350, "#16a34a", "Energy Usage", "rect"
    ),
    "photo_office": generate_sample_image(
        os.path.join(IMAGES_DIR, "photo_office.png"), 800, 450, "#f59e0b", "New Office", "rect"
    ),
    "roadmap_timeline": generate_sample_image(
        os.path.join(IMAGES_DIR, "roadmap_timeline.png"), 900, 350, "#6366f1", "2025 Roadmap", "rect"
    ),
}

# ── PDF definitions ──
samples = [
    {
        "filename": "quarterly_report_q4_2024.pdf",
        "title": "Q4 2024 Financial Report",
        "content": [
            "This document contains the quarterly financial results for Q4 2024.",
            "Revenue increased by 15% compared to the previous quarter.",
            "Operating expenses remained stable at $2.3 million.",
            "Net profit margin improved to 12.5% from 10.2% in Q3.",
        ],
        "images": [
            {"path": source_images["logo_company"], "display_width": 1.2, "display_height": 1.2, "caption": "Acme Corporation Logo"},
            {"path": source_images["chart_revenue"], "display_width": 4.5, "display_height": 2.8, "caption": "Figure 1: Revenue growth Q1-Q4 2024"},
            {"path": source_images["chart_expenses"], "display_width": 4.5, "display_height": 2.8, "caption": "Figure 2: Expense breakdown by category"},
        ],
        "standard": {
            "/Title": "Q4 2024 Financial Report", "/Author": "Finance Department",
            "/Subject": "Quarterly Financial Results", "/Keywords": "finance, quarterly, report, Q4, 2024",
            "/Creator": "Acme Corp Financial System", "/Producer": "ReportLab + PyPDF",
        },
        "custom": {
            "classification": "CONFIDENTIAL", "securityLevel": 3, "department": "Finance",
            "documentType": "Financial Report", "retentionPeriod": "7 years",
            "dataSensitivity": "HIGH", "projectCode": "FIN-2024-Q4",
            "compliance": {"category": "SOX", "audited": True, "lastAuditDate": "2024-11-01"},
            "accessControl": {"allowedGroups": ["Finance Team", "Executive", "Audit"], "restrictedCountries": ["CN", "RU"]},
            "workflow": {"status": "Approved", "approvedBy": "Jane Smith", "approvedDate": "2024-12-15"},
            "tags": ["quarterly", "financial", "2024", "Q4"],
        },
    },
    {
        "filename": "employee_handbook_2024.pdf",
        "title": "Employee Handbook 2024",
        "content": [
            "Welcome to Acme Corporation! This handbook outlines company policies.",
            "Chapter 1: Code of Conduct - All employees must maintain professional behavior.",
            "Chapter 2: Benefits - Health insurance, 401k, and PTO policies.",
            "Chapter 3: Remote Work Policy - Guidelines for working from home.",
        ],
        "images": [
            {"path": source_images["logo_company"], "display_width": 1.2, "display_height": 1.2, "caption": "Acme Corporation"},
            {"path": source_images["photo_team"], "display_width": 4.5, "display_height": 3.4, "caption": "Our growing team at the 2024 annual summit"},
        ],
        "standard": {
            "/Title": "Employee Handbook 2024", "/Author": "Human Resources",
            "/Subject": "Company Policies and Procedures", "/Keywords": "HR, handbook, policies, employee",
            "/Creator": "HR Documentation System", "/Producer": "ReportLab + PyPDF",
        },
        "custom": {
            "classification": "INTERNAL", "securityLevel": 1, "department": "Human Resources",
            "documentType": "Policy Document", "retentionPeriod": "Current + 1 year",
            "dataSensitivity": "LOW", "projectCode": "HR-HANDBOOK-2024",
            "compliance": {"category": "HR Compliance", "audited": False},
            "accessControl": {"allowedGroups": ["All Employees"], "public": False},
            "workflow": {"status": "Published", "version": "3.2", "effectiveDate": "2024-01-01"},
            "tags": ["HR", "policy", "handbook", "onboarding"],
            "languages": ["en", "es", "fr"],
        },
    },
    {
        "filename": "product_roadmap_2025.pdf",
        "title": "Product Roadmap 2025",
        "content": [
            "Strategic product development plan for fiscal year 2025.",
            "Q1: Launch of AI-powered analytics dashboard.",
            "Q2: Mobile app redesign with new UX patterns.",
            "Q3: Integration with third-party platforms.",
            "Q4: Enterprise features and security enhancements.",
        ],
        "images": [
            {"path": source_images["roadmap_timeline"], "display_width": 5.5, "display_height": 2.1, "caption": "Figure 1: 2025 Product Roadmap Timeline"},
            {"path": source_images["diagram_arch"], "display_width": 5.0, "display_height": 3.1, "caption": "Figure 2: Target system architecture"},
        ],
        "standard": {
            "/Title": "Product Roadmap 2025", "/Author": "Product Management",
            "/Subject": "Strategic Product Planning", "/Keywords": "roadmap, product, strategy, 2025",
            "/Creator": "Product Planning Tool", "/Producer": "ReportLab + PyPDF",
        },
        "custom": {
            "classification": "TOP SECRET", "securityLevel": 5, "department": "Product",
            "documentType": "Strategic Plan", "retentionPeriod": "5 years",
            "dataSensitivity": "CRITICAL", "projectCode": "PROD-ROADMAP-2025",
            "compliance": {"category": "Trade Secret", "ndaRequired": True, "exportControlled": True},
            "accessControl": {"allowedGroups": ["Executive Team", "Product Leadership"], "mfaRequired": True, "watermarkOnView": True},
            "workflow": {"status": "Draft", "expirationDate": "2025-12-31"},
            "tags": ["roadmap", "strategy", "confidential", "2025"],
        },
    },
    {
        "filename": "research_findings_ai_ml.pdf",
        "title": "AI/ML Research Findings",
        "content": [
            "Summary of machine learning research conducted in 2024.",
            "Key Finding 1: Transformer models showed 23% improvement in accuracy.",
            "Key Finding 2: Training time reduced by 40% with new optimization.",
            "Key Finding 3: Energy consumption decreased through efficient batching.",
        ],
        "images": [
            {"path": source_images["chart_ml"], "display_width": 4.5, "display_height": 3.0, "caption": "Figure 1: Model accuracy comparison across architectures"},
            {"path": source_images["diagram_neural"], "display_width": 3.5, "display_height": 3.5, "caption": "Figure 2: Proposed neural network topology"},
            {"path": source_images["chart_energy"], "display_width": 4.5, "display_height": 2.5, "caption": "Figure 3: Energy consumption per training epoch"},
        ],
        "standard": {
            "/Title": "AI/ML Research Findings 2024", "/Author": "Dr. Jane Smith, Research Team",
            "/Subject": "Machine Learning Research Results", "/Keywords": "AI, ML, research, transformers",
            "/Creator": "Research Documentation System", "/Producer": "ReportLab + PyPDF",
        },
        "custom": {
            "classification": "RESTRICTED", "securityLevel": 4,
            "department": "Research & Development", "documentType": "Research Paper",
            "retentionPeriod": "10 years", "dataSensitivity": "HIGH", "projectCode": "RND-AI-2024-047",
            "compliance": {"category": "IP Protection", "exportControlled": False},
            "accessControl": {"allowedGroups": ["R&D Team", "Patent Office"]},
            "workflow": {"status": "Peer Reviewed", "peerReviewDate": "2024-11-20"},
            "intellectualProperty": {"patentStatus": "Pending", "patentNumber": "US-2024-12345", "embargoUntil": "2025-06-01"},
            "tags": ["AI", "ML", "research", "transformers", "optimization"],
        },
    },
    {
        "filename": "meeting_notes_public.pdf",
        "title": "All-Hands Meeting Notes",
        "content": [
            "Notes from the company all-hands meeting held on December 1, 2024.",
            "CEO presented annual achievements and thanked all teams.",
            "New office locations announced for 2025 expansion.",
            "Q&A session addressed employee questions about benefits.",
        ],
        "images": [
            {"path": source_images["photo_office"], "display_width": 5.0, "display_height": 2.8, "caption": "Our new downtown office opening in Q1 2025"},
            {"path": source_images["icon_badge"], "display_width": 1.0, "display_height": 1.0, "caption": "Employee of the Year badge"},
        ],
        "standard": {
            "/Title": "All-Hands Meeting Notes - December 2024", "/Author": "Communications Team",
            "/Subject": "Company Meeting Summary", "/Keywords": "meeting, all-hands, company, notes",
            "/Creator": "Meeting Notes App", "/Producer": "ReportLab + PyPDF",
        },
        "custom": {
            "classification": "PUBLIC", "securityLevel": 0, "department": "Communications",
            "documentType": "Meeting Notes", "retentionPeriod": "2 years",
            "dataSensitivity": "NONE", "projectCode": "COMM-MTG-2024-12",
            "compliance": {"category": "None", "audited": False},
            "accessControl": {"allowedGroups": ["Public"], "public": True, "shareable": True},
            "workflow": {"status": "Approved for Distribution", "approvedBy": "Communications Director"},
            "meeting": {"date": "2024-12-01", "attendees": "All Employees", "recordingAvailable": True},
            "tags": ["meeting", "all-hands", "company-wide", "december"],
        },
    },
]


if __name__ == "__main__":
    print("Creating sample PDFs with images + JSON custom metadata...\n")

    for sample in samples:
        temp_path = os.path.join(OUTPUT_DIR, f"temp_{sample['filename']}")
        final_path = os.path.join(OUTPUT_DIR, sample['filename'])

        create_pdf_with_images(temp_path, sample["title"], sample["content"], sample["images"])
        add_custom_metadata(temp_path, final_path, sample["standard"], sample["custom"])
        os.remove(temp_path)

        img_count = len(sample["images"])
        print(f"  Created: {sample['filename']}")
        print(f"    Classification : {sample['custom']['classification']}")
        print(f"    Embedded images: {img_count}")
        print()

    print(f"All PDFs saved to: {OUTPUT_DIR}")

    # Quick verification
    print("\n--- Verify: quarterly_report_q4_2024.pdf ---")
    import fitz
    doc = fitz.open(os.path.join(OUTPUT_DIR, "quarterly_report_q4_2024.pdf"))
    total_imgs = sum(len(doc[p].get_images(full=True)) for p in range(doc.page_count))
    print(f"  Pages : {doc.page_count}")
    print(f"  Images: {total_imgs}")
    doc.close()
