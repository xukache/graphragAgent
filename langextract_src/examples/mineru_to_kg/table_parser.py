"""将 MinerU 的 table_body HTML 转换为 LangExtract 可消费的 Markdown 表格文本。

设计依据：docs/mineru2langextract_handoff-v1.0.md 第 3 节。

为什么转 Markdown：
- HTML 标签消耗 token 但不增加语义信息
- Markdown 表格对 LLM 更友好，结构化抽取准确率更高
- 实测 MinerU 的 table_body 是标准 <table><tr><td> 结构，可靠解析

支持：
- <table> / <tr> / <td> / <th> 基础结构
- rowspan / colspan 单元格合并
- 空单元格保留为空字符串

失败时的 fallback：去除 HTML 标签，保留纯文本（避免阻塞主流程）。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _TableHTMLParser(HTMLParser):
    """解析 <table><tr><td> 结构，处理 rowspan/colspan。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell_text: list[str] = []
        self._in_cell = False
        self._pending_attrs: dict[str, str] = {}
        # 跟踪因 rowspan 占用的下一行单元格：list of dicts {col_idx: (text, remaining_rowspan, colspan)}
        self._rowspan_carry: list[dict[int, tuple[str, int, int]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell_text = []
            self._pending_attrs = {k.lower(): (v or "") for k, v in attrs}

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._in_cell:
            text = "".join(self._current_cell_text).strip()
            text = re.sub(r"\s+", " ", text)

            try:
                rowspan = int(self._pending_attrs.get("rowspan", "1") or 1)
            except ValueError:
                rowspan = 1
            try:
                colspan = int(self._pending_attrs.get("colspan", "1") or 1)
            except ValueError:
                colspan = 1
            rowspan = max(1, rowspan)
            colspan = max(1, colspan)

            if self._current_row is not None:
                # 主单元格内容；colspan 通过重复填充展开
                self._current_row.append(text)
                for _ in range(colspan - 1):
                    self._current_row.append("")
                # 记录 rowspan，影响后续行
                if rowspan > 1:
                    col_start = len(self._current_row) - colspan
                    while len(self._rowspan_carry) < rowspan - 1:
                        self._rowspan_carry.append({})
                    for offset in range(rowspan - 1):
                        for c in range(col_start, col_start + colspan):
                            # 后续行该列填同一文本（仅首格保留文本，其余空）
                            self._rowspan_carry[offset][c] = (
                                text if c == col_start else "",
                                rowspan - 1 - offset,
                                1,
                            )

            self._in_cell = False
            self._current_cell_text = []
            self._pending_attrs = {}

        elif tag == "tr" and self._current_row is not None:
            # 应用本行的 rowspan 占用
            if self._rowspan_carry:
                carry = self._rowspan_carry.pop(0)
                # carry 中按列号填入；合并到当前行
                merged: list[str] = []
                row = self._current_row
                # 简单策略：把 carry 中存在的列插入到对应位置
                # 假定 row 是从左到右添加，carry 提供的是被 rowspan 占用的列号
                final_cols: dict[int, str] = {}
                # 先放入 row 的内容（按顺序填充未被 rowspan 占用的列）
                row_iter = iter(row)
                col = 0
                row_consumed = 0
                target_len = max(
                    len(row) + len(carry),
                    (max(carry.keys()) + 1) if carry else 0,
                )
                while col < target_len:
                    if col in carry:
                        final_cols[col] = carry[col][0]
                    else:
                        try:
                            final_cols[col] = next(row_iter)
                            row_consumed += 1
                        except StopIteration:
                            break
                    col += 1
                # 把剩余未消费的 row 内容追加到末尾
                remaining = list(row_iter)
                merged_row = [final_cols.get(i, "") for i in range(col)]
                merged_row.extend(remaining)
                self.rows.append(merged_row)
            else:
                self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell_text.append(data)


def table_html_to_markdown(html: str) -> str:
    """将 MinerU table_body HTML 转为 Markdown 表格。

    转换失败时（HTML 损坏等）fallback 到去标签纯文本。
    """
    if not html or not html.strip():
        return ""

    try:
        parser = _TableHTMLParser()
        parser.feed(html)
        rows = parser.rows
    except Exception:
        rows = []

    if not rows:
        # Fallback：去标签
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # 对齐列数（取最长行）
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]

    # 渲染 Markdown 表格
    lines = []
    for i, row in enumerate(rows):
        # 空单元格用空格占位，避免 Markdown 表格语法异常
        cells = [c if c else " " for c in row]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            # 表头分隔行
            lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    # 自测
    sample = (
        "<table><tr><td>季度</td><td>营业收入</td><td>净利润</td><td>毛利率(%)</td></tr>"
        "<tr><td>Q1</td><td>1280.50</td><td>210.30</td><td>42.1</td></tr>"
        "<tr><td>Q2</td><td>1395.75</td><td>248.60</td><td>43.8</td></tr>"
        "<tr><td>全年</td><td>5867.35</td><td>1035.45</td><td>43.9</td></tr></table>"
    )
    print(table_html_to_markdown(sample))
