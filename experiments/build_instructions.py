"""Render the submission Markdown as a bookmarked A4 PDF.

Author/edit output/pdf/GROUP02_INSTRUCTIONS.md, then run this script with
a Python runtime containing reportlab and pypdf. No application services are contacted.
"""
from html import escape
from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
INK = colors.HexColor('#1B2A41')
ACCENT = colors.HexColor('#15656D')
MUTED = colors.HexColor('#566477')
WIDTH = A4[0] - 84
STYLES = {
    'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9.2, leading=12.2,
                           textColor=INK, spaceAfter=6),
    'h1': ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=24, leading=29,
                         textColor=INK, spaceAfter=14),
    'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=18, leading=22,
                         textColor=INK, spaceAfter=12, keepWithNext=True),
    'h3': ParagraphStyle('h3', fontName='Helvetica-Bold', fontSize=11, leading=14,
                         textColor=ACCENT, spaceBefore=8, spaceAfter=5, keepWithNext=True),
    'small': ParagraphStyle('small', fontName='Helvetica', fontSize=7.9, leading=10.3,
                            textColor=INK),
    'table-header': ParagraphStyle('table-header', fontName='Helvetica-Bold',
                                   fontSize=7.9, leading=10.3, textColor=colors.white),
    'fields': ParagraphStyle('fields', fontName='Helvetica', fontSize=9,
                             leading=11.7, textColor=INK, spaceAfter=3),
    'steps-label': ParagraphStyle('steps-label', fontName='Helvetica-Bold', fontSize=9,
                                  leading=11.7, textColor=ACCENT, spaceBefore=3,
                                  spaceAfter=3, keepWithNext=True),
    'code': ParagraphStyle('code', fontName='Courier-Bold', fontSize=8.4, leading=11.2,
                           textColor=INK, backColor=colors.HexColor('#F1F4F7'),
                           borderPadding=5, spaceBefore=4, spaceAfter=6),
    'bullet': ParagraphStyle('bullet', fontName='Helvetica', fontSize=9.2, leading=12.2,
                             textColor=INK, leftIndent=12, firstLineIndent=-10, spaceAfter=5),
}


def markup(text):
    value = escape(text)
    value = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)
    value = re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', value)
    return value


def paragraph(text, style='body'):
    return Paragraph(markup(text), STYLES[style])


class Diagram(Flowable):
    """Vector architecture, with communication and storage edges separated."""
    def __init__(self):
        super().__init__()
        self.width = WIDTH
        self.height = 204

    def draw(self):
        c = self.canv
        c.scale(1, .87)
        def box(x, y, w, title, detail):
            c.setStrokeColor(colors.HexColor('#CBD5DF'))
            c.setFillColor(colors.HexColor('#F7F8FA'))
            c.roundRect(x, y, w, 38, 5, fill=1, stroke=1)
            c.setFillColor(INK)
            c.setFont('Helvetica-Bold', 9)
            c.drawCentredString(x+w/2, y+23, title)
            c.setFont('Helvetica', 7.5)
            c.drawCentredString(x+w/2, y+10, detail)
        def arrow(x, y, xx, yy, dashed=False):
            c.setStrokeColor(MUTED)
            c.setLineWidth(.7)
            c.setDash(3, 2) if dashed else c.setDash()
            c.line(x, y, xx, yy)
            c.setDash()
            import math
            a = math.atan2(yy-y, xx-x)
            for delta in (-.45, .45):
                c.line(xx, yy, xx-5*math.cos(a+delta), yy-5*math.sin(a+delta))
        box(0, 188, 108, 'Browser', 'HTTP / localhost')
        box(144, 188, 142, 'Frontend proxy', 'routes /api/<service>/...')
        arrow(108, 207, 144, 207)
        box(0, 112, 145, 'Waiting room + recovery', 'Redis registration / queue')
        box(181, 112, 145, 'Dispatcher API + worker', 'persisted fixed batches')
        box(362, 112, 145, 'Allocator API + workers', 'policy / leased jobs')
        arrow(180, 188, 72, 150)
        arrow(145, 131, 181, 131)
        arrow(326, 131, 362, 131)
        box(0, 36, 145, 'Redis 7', 'queue / AOF / PVC')
        box(181, 36, 145, 'Payment API + worker', 'mock checkout / reconciliation')
        box(362, 36, 145, 'Seat API + worker', 'atomic holds / expiry / callbacks')
        arrow(72, 112, 72, 74)
        arrow(434, 112, 434, 74)
        arrow(326, 55, 362, 55)
        c.setFont('Helvetica', 7.3)
        c.setFillColor(MUTED)
        c.drawString(188, 86, 'checkout via frontend / waiting room')
        c.setStrokeColor(ACCENT)
        c.line(181, 13, 507, 13)
        for x in (235, 435):
            arrow(x, 36, x, 14, True)
        c.setFillColor(INK)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(186, 0, 'PostgreSQL 17: seats / payment / allocation / dispatcher')
        c.setFont('Helvetica', 7)
        c.setFillColor(MUTED)
        c.drawString(0, 0, 'Dashed: storage (selected edges)')


class Instructions(BaseDocTemplate):
    def afterFlowable(self, item):
        if isinstance(item, Paragraph) and item.style.name in ('h1', 'h2'):
            title = item.getPlainText()
            self.canv.bookmarkPage(title)
            self.canv.addOutlineEntry(title, title, 0, False)


def page(canvas, doc):
    w, h = A4
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(2)
    canvas.line(42, h-29, w-42, h-29)
    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7.3)
    canvas.drawString(42, h-42, 'CSC3104 / GROUP 02 / TESTING INSTRUCTIONS')
    canvas.setStrokeColor(colors.HexColor('#D9E0E7'))
    canvas.setLineWidth(.5)
    canvas.line(42, 34, w-42, 34)
    canvas.drawRightString(w-42, 22, str(doc.page))


def make_table(lines):
    rows = [[part.strip() for part in line.strip().strip('|').split('|')] for line in lines]
    rows = [r for r in rows if not all(re.fullmatch(r':?-+:?', cell) for cell in r)]
    n = len(rows[0])
    fractions = {2: [.29, .71], 3: [.22, .38, .40], 4: [.13, .29, .29, .29],
                 5: [.09, .22, .22, .25, .22]}.get(n, [1/n]*n)
    table = Table([[paragraph(cell, 'table-header' if index == 0 else 'small')
                    for cell in row] for index, row in enumerate(rows)],
                  colWidths=[WIDTH*f for f in fractions], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), INK),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LINEBELOW', (0,0), (-1,0), .7, ACCENT),
        ('LINEBELOW', (0,1), (-1,-1), .3, colors.HexColor('#D9E0E7')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F3F6F9')]),
    ]))
    return table


def build(output=None):
    path = OUT / 'GROUP02_INSTRUCTIONS.md'
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line == '<!-- pagebreak -->':
            story.append(PageBreak())
        elif line == '<!-- architecture -->':
            story.extend([Diagram(), Spacer(1, 12)])
        elif line.startswith('<!--') and line.endswith('-->'):
            continue
        elif line.startswith('```'):
            block = []
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i]); i += 1
            i += 1
            rendered = []
            # Wrap only at whitespace, so copied long identifiers are never split.
            # PDF commands use complete lines in their own paragraph.
            for command in block:
                if not command:
                    continue
                if stringWidth(command, STYLES['code'].fontName, STYLES['code'].fontSize) > WIDTH - 10:
                    raise ValueError('Shorten this command to prevent copy-breaking wraps: ' + command)
                item = paragraph(command, 'code')
                rendered.append(item)
            story.append(KeepTogether(rendered))
        elif line.startswith('|'):
            block = [line]
            while i < len(lines) and lines[i].strip().startswith('|'):
                block.append(lines[i].strip()); i += 1
            story.extend([make_table(block), Spacer(1, 9)])
        elif line.startswith('### '):
            story.append(paragraph(line[4:], 'h3'))
        elif line.startswith('## '):
            story.append(paragraph(line[3:], 'h2'))
        elif line.startswith('# '):
            story.append(paragraph(line[2:], 'h1'))
        elif re.match(r'^\*\*(Objective|Preconditions|Test Data|Expected Result|Verification Method|Evidence|Restore|Duration):\*\*', line):
            fields = [line]
            while i < len(lines) and re.match(
                    r'^\*\*(Objective|Preconditions|Test Data|Expected Result|Verification Method|Evidence|Restore|Duration):\*\*',
                    lines[i].strip()):
                fields.append(lines[i].strip()); i += 1
            story.append(Paragraph('<br/>'.join(markup(field) for field in fields), STYLES['fields']))
        elif line.startswith('**Steps:**'):
            story.append(paragraph('Steps', 'steps-label'))
            inline = line[len('**Steps:**'):].strip()
            if inline:
                story.append(paragraph(inline))
        elif line.startswith('- ') or re.match(r'^\d+\. ', line):
            story.append(paragraph(line, 'bullet'))
        else:
            block = [line]
            while i < len(lines) and lines[i].strip() and not re.match(r'^(#|\||`|<!--|\d+\. |\- |\*\*[^*]+:\*\*)', lines[i]):
                block.append(lines[i].strip()); i += 1
            story.append(paragraph(' '.join(block)))
    output = Path(output) if output else OUT / 'GROUP02_INSTRUCTIONS.pdf'
    rendered = BytesIO()
    doc = Instructions(rendered, pagesize=A4, title='CSC3104 Group 02 - Testing Instructions',
                       author='CSC3104 Group 02', leftMargin=42, rightMargin=42,
                       topMargin=60, bottomMargin=48, allowSplitting=True)
    doc.addPageTemplates([PageTemplate(id='instructions',
                         frames=[Frame(42, 48, WIDTH, A4[1]-108,
                                       leftPadding=0, rightPadding=0,
                                       topPadding=0, bottomPadding=0)], onPage=page)])
    doc.build(story)
    # Keep the public guide undated, including the document properties.
    rendered.seek(0)
    reader = PdfReader(rendered)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.metadata = {key: value for key, value in (reader.metadata or {}).items()
                       if key not in ('/CreationDate', '/ModDate')}
    staged = output.with_suffix('.pending.pdf')
    with staged.open('wb') as stream:
        writer.write(stream)
    try:
        staged.replace(output)
    except PermissionError:
        output = output.with_name(output.stem + '_Revised.pdf')
        staged.replace(output)
        print('Original PDF is locked; saved revised copy instead.')
    print('Created:', output)


if __name__ == '__main__':
    build()

