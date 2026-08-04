"use client";

import { useMemo } from "react";
import { CHANGE_ORDER, CHANGE_STYLE } from "@/lib/change";
import type { ChangeType, ClauseComparison } from "@/lib/types";

/**
 * The change spine.
 *
 * A one-column map of the whole comparison, in document order, coloured by
 * what happened at each point. It answers the question an auditor asks before
 * any other — where are the changes concentrated? — and doubles as the
 * navigation for getting there.
 *
 * Long comparisons are bucketed so every segment stays clickable; a bucket
 * takes the colour of the most significant change inside it, because a single
 * rewritten clause matters more than the fifty unchanged ones around it.
 */

const SEVERITY = new Map<ChangeType, number>(
  CHANGE_ORDER.map((type, index) => [type, index]),
);

const MAX_SEGMENTS = 220;

interface Segment {
  index: number;
  type: ChangeType;
  count: number;
}

export function ChangeSpine({
  rows,
  activeIndex,
  onJump,
}: {
  rows: ClauseComparison[];
  activeIndex: number | null;
  onJump: (rowIndex: number) => void;
}) {
  const segments = useMemo<Segment[]>(() => {
    if (rows.length === 0) return [];
    if (rows.length <= MAX_SEGMENTS) {
      return rows.map((row, index) => ({
        index,
        type: row.change_type,
        count: 1,
      }));
    }

    const size = Math.ceil(rows.length / MAX_SEGMENTS);
    const buckets: Segment[] = [];

    for (let start = 0; start < rows.length; start += size) {
      const slice = rows.slice(start, start + size);
      const worst = slice.reduce((current, row) =>
        (SEVERITY.get(row.change_type) ?? 9) < (SEVERITY.get(current.change_type) ?? 9)
          ? row
          : current,
      );
      buckets.push({ index: start, type: worst.change_type, count: slice.length });
    }

    return buckets;
  }, [rows]);

  if (segments.length === 0) return null;

  // The segment covering the row currently in view: the last one that starts
  // at or before it.
  let activeStart = -1;
  if (activeIndex !== null) {
    for (const segment of segments) {
      if (segment.index <= activeIndex) activeStart = segment.index;
      else break;
    }
  }

  return (
    <nav className="spine" aria-label="Jump to a change">
      {segments.map((segment) => {
        const description =
          segment.count === 1
            ? `${rows[segment.index]?.label ?? ""} — ${segment.type}`
            : `${segment.count} clauses from ${rows[segment.index]?.label ?? ""}, most significant: ${segment.type}`;

        return (
          <button
            key={segment.index}
            type="button"
            className="spine-seg"
            data-active={activeStart === segment.index}
            style={{ ["--seg-color" as string]: CHANGE_STYLE[segment.type].color }}
            onClick={() => onJump(segment.index)}
            title={description}
            aria-label={`Jump to ${description}`}
          />
        );
      })}
    </nav>
  );
}
