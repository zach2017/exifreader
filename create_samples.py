#!/usr/bin/env python3
"""Generate sample PDFs with custom metadata including classification fields."""

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from pypdf import PdfReader, PdfWriter
from datetime import datetime
import os

OUTPUT_DIR = "/home/claude/pdf-exif-extractor/samples"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def create_pdf_content(filename, title, content_paragraphs):
    """Create a PDF with reportlab."""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30
    )
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 12))
    
    # Content
    for para in content_paragraphs:
        story.append(Paragraph(para, styles['Normal']))
        story.append(Spacer(1, 12))
    
    doc.build(story)

def add_custom_metadata(input_path, output_path, metadata):
    """Add custom metadata to a PDF including classification fields."""
    reader = PdfReader(input_path)
    writer = PdfWriter()
    
    # Copy all pages
    for page in reader.pages:
        writer.add_page(page)
    
    # Add metadata - pypdf accepts custom fields with / prefix
    writer.add_metadata(metadata)
    
    with open(output_path, "wb") as f:
        writer.write(f)

# Sample PDFs with different classifications
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
        "metadata": {
            "/Title": "Q4 2024 Financial Report",
            "/Author": "Finance Department",
            "/Subject": "Quarterly Financial Results",
            "/Keywords": "finance, quarterly, report, Q4, 2024, revenue",
            "/Creator": "Acme Corp Financial System",
            "/Producer": "ReportLab + PyPDF",
            # Custom classification fields
            "/Classification": "CONFIDENTIAL",
            "/SecurityLevel": "Level 3",
            "/Department": "Finance",
            "/DocumentType": "Financial Report",
            "/RetentionPeriod": "7 years",
            "/ComplianceCategory": "SOX",
            "/AccessControl": "Finance Team, Executive, Audit",
            "/DataSensitivity": "HIGH",
            "/ProjectCode": "FIN-2024-Q4",
            "/ApprovalStatus": "Approved",
            "/ReviewDate": "2024-12-15",
        }
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
        "metadata": {
            "/Title": "Employee Handbook 2024",
            "/Author": "Human Resources",
            "/Subject": "Company Policies and Procedures",
            "/Keywords": "HR, handbook, policies, employee, benefits",
            "/Creator": "HR Documentation System",
            "/Producer": "ReportLab + PyPDF",
            # Custom classification fields
            "/Classification": "INTERNAL",
            "/SecurityLevel": "Level 1",
            "/Department": "Human Resources",
            "/DocumentType": "Policy Document",
            "/RetentionPeriod": "Current + 1 year",
            "/ComplianceCategory": "HR Compliance",
            "/AccessControl": "All Employees",
            "/DataSensitivity": "LOW",
            "/ProjectCode": "HR-HANDBOOK-2024",
            "/ApprovalStatus": "Published",
            "/EffectiveDate": "2024-01-01",
            "/Version": "3.2",
        }
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
        "metadata": {
            "/Title": "Product Roadmap 2025",
            "/Author": "Product Management",
            "/Subject": "Strategic Product Planning",
            "/Keywords": "roadmap, product, strategy, 2025, planning",
            "/Creator": "Product Planning Tool",
            "/Producer": "ReportLab + PyPDF",
            # Custom classification fields
            "/Classification": "TOP SECRET",
            "/SecurityLevel": "Level 5",
            "/Department": "Product",
            "/DocumentType": "Strategic Plan",
            "/RetentionPeriod": "5 years",
            "/ComplianceCategory": "Trade Secret",
            "/AccessControl": "Executive Team, Product Leadership",
            "/DataSensitivity": "CRITICAL",
            "/ProjectCode": "PROD-ROADMAP-2025",
            "/ApprovalStatus": "Draft",
            "/ExpirationDate": "2025-12-31",
            "/DistributionList": "C-Suite, VP Product, Directors",
        }
    },
    {
        "filename": "research_findings_ai_ml.pdf",
        "title": "AI/ML Research Findings",
        "content": [
            "Summary of machine learning research conducted in 2024.",
            "Key Finding 1: Transformer models showed 23% improvement in accuracy.",
            "Key Finding 2: Training time reduced by 40% with new optimization.",
            "Key Finding 3: Energy consumption decreased through efficient batching.",
            "Recommendations for future research directions included.",
        ],
        "metadata": {
            "/Title": "AI/ML Research Findings 2024",
            "/Author": "Dr. Jane Smith, Research Team",
            "/Subject": "Machine Learning Research Results",
            "/Keywords": "AI, ML, research, machine learning, transformers",
            "/Creator": "Research Documentation System",
            "/Producer": "ReportLab + PyPDF",
            # Custom classification fields
            "/Classification": "RESTRICTED",
            "/SecurityLevel": "Level 4",
            "/Department": "Research & Development",
            "/DocumentType": "Research Paper",
            "/RetentionPeriod": "10 years",
            "/ComplianceCategory": "IP Protection",
            "/AccessControl": "R&D Team, Patent Office",
            "/DataSensitivity": "HIGH",
            "/ProjectCode": "RND-AI-2024-047",
            "/ApprovalStatus": "Peer Reviewed",
            "/PatentStatus": "Pending",
            "/PublicationStatus": "Embargoed",
            "/PeerReviewDate": "2024-11-20",
        }
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
        "metadata": {
            "/Title": "All-Hands Meeting Notes - December 2024",
            "/Author": "Communications Team",
            "/Subject": "Company Meeting Summary",
            "/Keywords": "meeting, all-hands, company, notes",
            "/Creator": "Meeting Notes App",
            "/Producer": "ReportLab + PyPDF",
            # Custom classification fields
            "/Classification": "PUBLIC",
            "/SecurityLevel": "Level 0",
            "/Department": "Communications",
            "/DocumentType": "Meeting Notes",
            "/RetentionPeriod": "2 years",
            "/ComplianceCategory": "None",
            "/AccessControl": "Public",
            "/DataSensitivity": "NONE",
            "/ProjectCode": "COMM-MTG-2024-12",
            "/ApprovalStatus": "Approved for Distribution",
            "/MeetingDate": "2024-12-01",
            "/Attendees": "All Employees",
        }
    },
]

print("Creating sample PDFs with custom metadata...\n")

for sample in samples:
    temp_path = os.path.join(OUTPUT_DIR, f"temp_{sample['filename']}")
    final_path = os.path.join(OUTPUT_DIR, sample['filename'])
    
    # Create PDF content
    create_pdf_content(temp_path, sample['title'], sample['content'])
    
    # Add custom metadata
    add_custom_metadata(temp_path, final_path, sample['metadata'])
    
    # Remove temp file
    os.remove(temp_path)
    
    print(f"✓ Created: {sample['filename']}")
    print(f"  Classification: {sample['metadata']['/Classification']}")
    print(f"  Security Level: {sample['metadata']['/SecurityLevel']}")
    print(f"  Department: {sample['metadata']['/Department']}")
    print()

print(f"\nAll PDFs created in: {OUTPUT_DIR}")

# Verify metadata of one file
print("\n--- Verification: Reading metadata from quarterly_report_q4_2024.pdf ---\n")
reader = PdfReader(os.path.join(OUTPUT_DIR, "quarterly_report_q4_2024.pdf"))
meta = reader.metadata
for key, value in meta.items():
    print(f"{key}: {value}")
