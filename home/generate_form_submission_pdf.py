import io
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_pdf(submission):
    # Create a file-like buffer to receive PDF data.
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=50,leftMargin=50,
        topMargin=50,bottomMargin=15
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


    story = []
    story.append(Paragraph(submission.page.title, styles["CentreH2"]))
    story.append(Spacer(1, 10))

    for field, value in [
        ("Submitted", submission.submit_time.strftime('%d %b %Y, %H:%M')), 
        ("Name", submission.name), 
        ("Email", submission.email), 
        *submission.display_data().items()
    ]:
        story.append(Paragraph(field, styles["Bold"]))
        for line in value.split('\n'):
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 10))


    doc.build(story)

    buffer.seek(0)

    return buffer