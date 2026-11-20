#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate the experimental Lite K2 shader from Vela's stock K2 source."""

import argparse
import re
from pathlib import Path


def share_taps(source):
    # The existing shader already shares the two horizontal 3x3 windows in each row.
    # Reuse converted taps from the first pair when the second pair has the same
    # rounded X center and its Y center stayed put or advanced by one.
    anchor = "        uint qx1 = uint(qc10.x); uint qy1 = uint(qc10.y);\n"
    if source.count(anchor) != 1:
        raise ValueError("Unexpected K2 lower-row coordinates")
    source = source.replace(anchor, anchor + (
        "        bool sameX = qx1 == qx0;\n"
        "        bool sameY = qy1 == qy0;\n"
        "        bool nextY = qy1 == qy0 + 1u;\n"
    ))

    for row in range(3):
        for column in range(4):
            name = f"qT1_{column}_{row}"
            pattern = rf"^( +vec3 {name} = )(spvNMax\([^\n]+\));$"
            matches = list(re.finditer(pattern, source, re.MULTILINE))
            if len(matches) != 1:
                raise ValueError(f"Expected one stock expression for {name}")
            match = matches[0]
            fallback = match[2]
            if row < 2:
                fallback = f"sameX && nextY ? qT0_{column}_{row + 1} : {fallback}"
            replacement = f"{match[1]}sameX && sameY ? qT0_{column}_{row} : ({fallback});"
            source = source[:match.start()] + replacement + source[match.end():]
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(share_taps(args.stock.read_text(encoding="utf-8")), encoding="utf-8")
