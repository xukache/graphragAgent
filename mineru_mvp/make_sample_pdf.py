"""生成 MVP 测试用的本地 PDF 文档。

构造一个包含标题、正文段落、数值表格与简单公式的 PDF，
覆盖 MinerU 解析时常见的 text / table / equation 等块类型，
便于验证解析后输出的布局信息与数值提取效果。
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

SAMPLE_PDF_NAME = "sample.pdf"

# 注册 reportlab 内置中日韩字体（无须外部字体文件），否则中文会渲染为方块
CJK_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))


def build_sample_pdf(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="MinerU MVP Sample Document",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CJKTitle", parent=styles["Title"], fontName=CJK_FONT
    )
    h2_style = ParagraphStyle(
        "CJKHeading2", parent=styles["Heading2"], fontName=CJK_FONT
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=CJK_FONT,
        fontSize=11,
        leading=16,
    )

    story = []

    story.append(Paragraph("MinerU MVP 测试样例文档", title_style))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("1. 文档目的", h2_style))
    story.append(
        Paragraph(
            "本文档用于验证 MinerU 精准解析 API（路径 B）的完整解析流程。"
            "它包含标题层级、正文段落、数值型表格以及一个简单公式，"
            "用于检查解析输出中的 text、table、equation 等块类型与布局信息。",
            body_style,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("2. 季度营收数据表", h2_style))
    story.append(
        Paragraph(
            "下表列出 2024 财年各季度的关键经营数值，单位为百万元人民币。",
            body_style,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    table_data = [
        ["季度", "营业收入", "净利润", "毛利率(%)"],
        ["Q1", "1280.50", "210.30", "42.1"],
        ["Q2", "1395.75", "248.60", "43.8"],
        ["Q3", "1502.20", "271.45", "44.5"],
        ["Q4", "1688.90", "305.10", "45.2"],
        ["全年", "5867.35", "1035.45", "43.9"],
    ]
    table = Table(table_data, colWidths=[3 * cm, 4 * cm, 4 * cm, 3 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), CJK_FONT),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dbeafe")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f1f5f9")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("3. 毛利率计算公式", h2_style))
    story.append(
        Paragraph(
            "毛利率的计算方式为：毛利率 = (营业收入 - 营业成本) / 营业收入 x 100%。"
            "例如 Q4 营业收入 1688.90，对应毛利率约 45.2%。",
            body_style,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("4. 结论", h2_style))
    story.append(
        Paragraph(
            "2024 财年四个季度营业收入逐季度增长，全年营业收入合计 5867.35 百万元，"
            "净利润合计 1035.45 百万元，整体毛利率保持在 43.9% 的健康水平。",
            body_style,
        )
    )

    doc.build(story)
    return output_path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / SAMPLE_PDF_NAME
    path = build_sample_pdf(target)
    print(f"已生成样例 PDF: {path}")
