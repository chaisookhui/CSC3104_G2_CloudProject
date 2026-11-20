"""Render the integrated results Markdown, including its measured figures, offline."""
from html import escape
from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader, PdfWriter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

from build_instructions import INK, MUTED, STYLES, WIDTH

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
STEM = 'GROUP02_Test_Results_and_Distributed_Concepts_Report'


def markup(value):
    for before, after in {'–': '-', '—': '-', '−': '-', '‑': '-', '≤': '<=',
                          '≥': '>=', 'Δ': 'Delta', '×': 'x', '→': '->'}.items():
        value = value.replace(before, after)
    value = escape(value)
    value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" color="#15656D">\1</a>', value)
    value = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)
    return re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', value)


class Results(BaseDocTemplate):
    def afterFlowable(self, item):
        if isinstance(item, Paragraph) and item.style.name in ('h1', 'h2', 'h3'):
            title = item.getPlainText()
            self.canv.bookmarkPage(title)
            self.canv.addOutlineEntry(title, title, 0, False)


def page(canvas, doc):
    width, height = A4
    canvas.setStrokeColor(INK)
    canvas.line(42, height - 29, width - 42, height - 29)
    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7.3)
    canvas.drawString(42, height - 42, 'CSC3104 / GROUP 02 / TEST RESULTS AND DISTRIBUTED CONCEPTS')
    canvas.drawRightString(width - 42, 22, str(doc.page))


def build(output=None):
    styles = dict(STYLES)
    styles['body'] = STYLES['body'].clone('body', fontSize=9.5, leading=12.8)
    styles['h2'] = STYLES['h2'].clone('h2', fontSize=14, leading=18)
    styles['h4'] = STYLES['h3'].clone('h4', fontSize=10, leading=13)
    def paragraph(text, style='body'):
        return Paragraph(markup(text), styles[style])

    def table(lines):
        rows = [[cell.strip() for cell in line.strip('|').split('|')] for line in lines]
        rows = [row for row in rows if not all(re.fullmatch(r':?-+:?', cell) for cell in row)]
        columns = len(rows[0])
        if any(len(row) != columns for row in rows):
            raise ValueError('Inconsistent table columns')
        widths = [WIDTH / columns] * columns
        if columns == 11:
            widths = [38, 44, 32, 48] + [(WIDTH - 162) / 7] * 7
        elif columns == 2:
            widths = [WIDTH * .4, WIDTH * .6]
        cell = ParagraphStyle('cell', parent=styles['body'], fontSize=6.8 if columns > 7 else 7.8,
                              leading=8.5 if columns > 7 else 10, spaceAfter=0)
        head = ParagraphStyle('head', parent=cell, fontName='Helvetica-Bold', textColor=colors.white)
        result = Table([[Paragraph(markup(text), head if index == 0 else cell) for text in row]
                        for index, row in enumerate(rows)], colWidths=widths, repeatRows=1, hAlign='LEFT')
        result.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), INK), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#D9E0E7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F6F9')]),
        ]))
        return result

    lines = (OUT / (STEM + '.md')).read_text(encoding='utf-8').splitlines()
    story = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line or line.startswith('<!--'):
            continue
        if line == '---':
            if story and not isinstance(story[-1], PageBreak):
                story.append(PageBreak())
        elif line.startswith('|'):
            rows = [line]
            while index < len(lines) and (not lines[index].strip() or lines[index].strip().startswith('|')):
                if lines[index].strip():
                    rows.append(lines[index].strip())
                index += 1
            story.extend([table(rows), Spacer(1, 10)])
        elif line.startswith('!['):
            match = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
            if not match:
                raise ValueError('Invalid image: ' + line)
            image = Image(str((OUT / match[2]).resolve()))
            image._restrictSize(WIDTH, 300)
            story.extend([image, Spacer(1, 8), paragraph(match[1], 'small'), Spacer(1, 8)])
        elif line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            story.append(paragraph(line[level:].strip(), 'h' + str(level)))
        elif line.startswith('```'):
            while index < len(lines) and not lines[index].startswith('```'):
                story.append(paragraph(lines[index], 'code'))
                index += 1
            index += 1
        else:
            block = [line]
            while index < len(lines) and lines[index].strip() and not re.match(r'^(#|\||!\[|```|<!--|---$|- )', lines[index]):
                block.append(lines[index].strip())
                index += 1
            story.append(paragraph(' '.join(block), 'bullet' if line.startswith('- ') else 'body'))
    target = Path(output) if output else OUT / (STEM + '.pdf')
    rendered = BytesIO()
    doc = Results(rendered, pagesize=A4, title='Group 02 - Test Results and Distributed Systems Concepts',
                  author='CSC3104 Group 02', leftMargin=42, rightMargin=42, topMargin=60, bottomMargin=48)
    doc.addPageTemplates(PageTemplate(id='results', frames=[Frame(
        42, 48, WIDTH, A4[1] - 108, leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0)], onPage=page))
    doc.build(story)
    staged = target.with_suffix('.pending.pdf')
    rendered.seek(0)
    writer = PdfWriter()
    reader = PdfReader(rendered)
    writer.clone_document_from_reader(reader)
    writer.metadata = {key: value for key, value in (reader.metadata or {}).items()
                       if key not in ('/CreationDate', '/ModDate')}
    with staged.open('wb') as stream:
        writer.write(stream)
    try:
        staged.replace(target)
    except PermissionError:
        target = target.with_name(target.stem + '_Revised.pdf')
        staged.replace(target)
        print('Original PDF is locked; saved revised copy instead.')
    print('Created:', target)


if __name__ == '__main__':
    build()
