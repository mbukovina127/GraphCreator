from typing import Set


def _collect_comment_lines(node, lines: Set[int]):
    if node.type == "comment":
        for row in range(node.start_point[0], node.end_point[0] + 1):
            lines.add(row)
    for child in node.children:
        _collect_comment_lines(child, lines)


def calculate_loc(node):
    raw_lines = node.text.split(b'\n')
    total = len(raw_lines)
    blank = sum(1 for l in raw_lines if not l.strip())

    comment_line_rows: Set[int] = set()
    _collect_comment_lines(node, comment_line_rows)
    # remap absolute rows to relative rows within this node's text
    base_row = node.start_point[0]
    commented = len({r - base_row for r in comment_line_rows})

    nonempty = total - blank
    code = max(0, nonempty - commented)
    comment_pct = round(commented / nonempty * 100, 2) if nonempty > 0 else 0.0

    return {
        "total": total,
        "blank": blank,
        "commented": commented,
        "nonempty": nonempty,
        "code": code,
        "comment_pct": comment_pct,
    }


def calculate_loc_agr(node):
    return "loc", calculate_loc(node)