import io
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_pdf(submission):
    # Create a file-like buffer to receive PDF data.
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=30,leftMargin=30,
        topMargin=30,bottomMargin=15
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
            before = submission.form_page.form_field_info_texts[field]["before"]
            for line in before.split('\n'):
                story.append(Paragraph(line, styles["Normal"]))
            story.append(Spacer(1, 5))

        for line in value.split('\n'):
            story.append(Paragraph(line, styles["Response"]))

        if field in submission.form_page.form_field_info_texts:
            story.append(Spacer(1, 5))
            after = submission.form_page.form_field_info_texts[field]["after"]
            for line in after.split('\n'):
                story.append(Paragraph(line, styles["Normal"]))

        story.append(Spacer(1, 10))


    doc.build(story)

    buffer.seek(0)

    return buffer
