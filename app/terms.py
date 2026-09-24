"""字幕专名统一：按“标准写法 + 别名”规则替换字幕正文中的专名。

规则校验（:func:`compile_rules`）：标准写法与别名都不得为空；同一别名不得
指向不同的标准写法（同一别名多次指向同一标准写法时，以先输入的规则为准）。

匹配（:func:`scan_line`）：只扫描字幕正文的各个物理行，逐行独立匹配，
**区分大小写**；从行首到行尾一次扫描，同一位置优先匹配**最长**的别名，
等长时按**规则输入顺序**（同一条规则内再按别名输入顺序）取先出现者；
命中后替换文本不再参与匹配（从命中片段之后继续扫描）。

重写（:func:`unify_srt`）：仅替换正文行内的命中片段，序号、时间轴、
``X1:``/``Position`` 等定位参数、空行、原有换行与开头 BOM 一律保持原样；
没有任何命中时原样返回输入内容。
"""
from __future__ import annotations

from dataclasses import dataclass

from .srt import (
    TextEdit,
    parse_document,
    rewrite_body_srt,
    split_physical_lines,
    strip_eol,
)


class TermError(ValueError):
    """专名规则不合法。"""


@dataclass(frozen=True)
class TermRule:
    """一条专名规则：标准写法及其全部别名（按输入顺序）。"""

    standard: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class CompiledAlias:
    """参与匹配的一条别名（``order`` 为规则输入顺序，从 0 开始）。"""

    text: str
    standard: str
    order: int


@dataclass(frozen=True)
class TermHit:
    """一处命中：字幕输入序号、所在正文物理行、行内位置与替换结果。"""

    cue_order: int
    cue_index: str
    line_no: int
    offset: int
    matched: str
    standard: str


def compile_rules(rules: list[TermRule]) -> list[CompiledAlias]:
    """校验并展开规则为可匹配的别名列表（保持规则输入顺序）。

    :raises TermError: 规则为空、标准写法为空、别名为空，或同一别名指向
        不同的标准写法。
    """
    if not rules:
        raise TermError("至少需要 1 条专名规则。")

    compiled: list[CompiledAlias] = []
    alias_owner: dict[str, tuple[str, int]] = {}
    for order, rule in enumerate(rules):
        label = f"第 {order + 1} 条规则"
        if not rule.standard:
            raise TermError(f"{label}的标准写法不能为空。")
        if not rule.aliases:
            raise TermError(f"{label}（{rule.standard}）至少需要一个别名。")
        for alias in rule.aliases:
            if not alias:
                raise TermError(f"{label}（{rule.standard}）存在空别名。")
            owner = alias_owner.get(alias)
            if owner is not None:
                if owner[0] != rule.standard:
                    raise TermError(
                        f"别名“{alias}”同时指向不同的标准写法"
                        f"“{owner[0]}”（第 {owner[1] + 1} 条规则）与"
                        f"“{rule.standard}”（第 {order + 1} 条规则）。"
                    )
                # 同一别名重复指向同一标准写法：以先输入的规则为准
                continue
            alias_owner[alias] = (rule.standard, order)
            compiled.append(CompiledAlias(text=alias, standard=rule.standard, order=order))
    return compiled


def scan_line(text: str, aliases: list[CompiledAlias]) -> list[tuple[int, int, str, str]]:
    """从左到右一次扫描单行文本，返回 ``(起点, 终点, 原文, 标准写法)`` 列表。

    同一位置优先最长别名，等长按规则输入顺序（``CompiledAlias`` 列表顺序）
    取先出现者；命中片段被跳过后续扫描，替换文本不再参与匹配。
    """
    hits: list[tuple[int, int, str, str]] = []
    pos = 0
    total = len(text)
    while pos < total:
        best: CompiledAlias | None = None
        for alias in aliases:
            if text.startswith(alias.text, pos) and (
                best is None or len(alias.text) > len(best.text)
            ):
                best = alias
        if best is None:
            pos += 1
            continue
        hits.append((pos, pos + len(best.text), best.text, best.standard))
        pos += len(best.text)
    return hits


def unify_srt(
    content: str, rules: list[TermRule]
) -> tuple[str, list[TermHit], dict[int, str]]:
    """按规则统一 SRT 正文中的专名写法。

    :returns: ``(修订后 SRT, 命中列表, 正文物理行号 -> 行内容)``；没有命中时
        修订结果与输入逐字符一致。
    """
    aliases = compile_rules(rules)
    doc = parse_document(content)
    lines = split_physical_lines(content[doc.bom_count :])

    hits: list[TermHit] = []
    edits: list[TextEdit] = []
    body_texts: dict[int, str] = {}
    for order, (cue, line_nos) in enumerate(
        zip(doc.cues, doc.body_line_nos), start=1
    ):
        for line_no in line_nos:
            text = strip_eol(lines[line_no])
            body_texts[line_no] = text
            for start, end, matched, standard in scan_line(text, aliases):
                hits.append(
                    TermHit(
                        cue_order=order,
                        cue_index=cue.index,
                        line_no=line_no,
                        offset=start,
                        matched=matched,
                        standard=standard,
                    )
                )
                edits.append(
                    TextEdit(
                        line_no=line_no,
                        start=start,
                        end=end,
                        replacement=standard,
                    )
                )

    if not edits:
        return content, hits, body_texts
    return rewrite_body_srt(content, edits), hits, body_texts
