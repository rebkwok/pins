import io

from django.conf import settings

from html2text import html2text

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import pdfencrypt


def generate_pdf(submission):
    # Create a file-like buffer to receive PDF data.
    buffer = io.BytesIO()
    encryption = pdfencrypt.StandardEncryption(settings.PDF_ENCRYPTION_KEY, canPrint=0)

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=30,leftMargin=30,
        topMargin=30,bottomMargin=15,
        encrypt=encryption,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name='CentreH2', alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=14,
            spaceAfter=6, spaceBefore=12,
    ))
    styles.add(
        ParagraphStyle(
            name='Bold', fontName="Helvetica-Bold", fontSize=10,
    ))

    styles.add(
        ParagraphStyle(
            name='Response', fontSize=10, textColor="#00008B"
    ))

    def normal_paragraph_style_with_indent(spaces):
        if spaces == 0:
            return styles["Normal"]
        style_name = f"n_with_{spaces}_indent"
        if style_name not in styles:
            styles.add(
                ParagraphStyle(
                    style_name, fontSize=10, leftIndent=spaces*5
                )
            )
        return styles[style_name]

    def add_info_text(story_lines, field, info_location):
        info_text = html2text(submission.form_page.form_field_info_texts[field][info_location])
        for line in info_text.split('\n'):
            leading_space = len(line) - len(line.lstrip())
            story_lines.append(
                Paragraph(
                    line, 
                    normal_paragraph_style_with_indent(leading_space)
                )
            )
        story_lines.append(Spacer(1, 5))
        return story_lines
    
    story = []
    title = submission.page.title
    submitted_label = "Submitted"
    if submission.is_draft:
        title += " (NOT SUBMITTED)"
        submitted_label = "Started"
    
    story.append(Paragraph(title, styles["CentreH2"]))
    story.append(Spacer(1, 10))

    for field, value in [
        (submitted_label, submission.submit_time.strftime('%d %b %Y, %H:%M')), 
        ("Name", submission.name), 
        ("Email", submission.email)
    ]:
        story.extend(
            [
                Paragraph(f"{field}: {value}", styles["Bold"]),
                Spacer(1, 10)
            ]
        )

    story.extend([HRFlowable(width="100%"), Spacer(1, 10)])

    for field, value in submission.display_data().items():
        story.extend(
            [Paragraph(field, styles["Bold"]), Spacer(1, 5)]
        )

        if field in submission.form_page.form_field_info_texts:
            story = add_info_text(story, field, "before")

        for line in value.split('\n'):
            story.append(Paragraph(line, styles["Response"]))

        if field in submission.form_page.form_field_info_texts:
            story = add_info_text(story, field, "after")

        story.append(Spacer(1, 10))

    doc.build(story)

    buffer.seek(0)

    return buffer
