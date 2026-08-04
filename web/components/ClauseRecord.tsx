"use client";

import { memo } from "react";
import { CHANGE_STYLE, chipLabel } from "@/lib/change";
import { escapeText, highlight } from "@/lib/highlight";
import type { ClauseComparison, ClauseSide, ComparisonReport } from "@/lib/types";

/**
 * One aligned clause pair.
 *
 * The gutter holds the identifiers, the two panes hold the text. Deletions and
 * insertions arrive already marked up from the comparison service; the only
 * markup added here is the search highlight.
 */

function Pane({
  side,
  clause,
  html,
  versionLabel,
  countryCode,
  absentNote,
  term,
}: {
  side: "v1" | "v2";
  clause: ClauseSide | null;
  html: string;
  versionLabel: string;
  countryCode: string;
  absentNote: string;
  term: string;
}) {
  return (
    <div className="pane">
      <div className="pane-head">
        <span className="pane-label" title={versionLabel}>
          <span className="sigil" style={{ marginRight: 6 }}>
            {countryCode}
          </span>
          {versionLabel}
        </span>
        {clause && <span className="pane-clause">§ {clause.clause_number}</span>}
      </div>

      {clause ? (
        <>
          {clause.title && (
            <div
              className="clause-title"
              dangerouslySetInnerHTML={{ __html: highlight(escapeText(clause.title), term) }}
            />
          )}
          <div
            className="clause-text"
            data-side={side}
            dangerouslySetInnerHTML={{ __html: highlight(html, term) }}
          />
        </>
      ) : (
        <p className="pane-absent">{absentNote}</p>
      )}
    </div>
  );
}

function Record({
  row,
  report,
  term,
}: {
  row: ClauseComparison;
  report: ComparisonReport;
  term: string;
}) {
  const style = CHANGE_STYLE[row.change_type];
  const { redline } = row;
  const section = row.v2?.section ?? row.v1?.section;

  return (
    <article
      className="record"
      id={`clause-${row.index}`}
      data-index={row.index}
      style={{
        ["--change-color" as string]: style.color,
        ["--change-wash" as string]: style.wash,
      }}
    >
      <div className="record-gutter">
        <span className="record-mark" aria-hidden="true" />
        <span className="record-id">{row.label}</span>
        {row.similarity_score !== null && (
          <span className="record-score" title="Semantic similarity">
            {(row.similarity_score * 100).toFixed(0)}% alike
          </span>
        )}
        {row.match_score !== null && report.alignment_method === "semantic" && (
          <span className="record-score" title="How confidently these two clauses were paired">
            {(row.match_score * 100).toFixed(0)}% match
          </span>
        )}
      </div>

      <div>
        <div className="record-head">
          <span className="chip">{chipLabel(row.change_type, report)}</span>
          {section && <span className="record-section">{section}</span>}
          {(redline.words_added > 0 || redline.words_removed > 0) && (
            <span className="wordcount">
              {redline.words_added > 0 && (
                <span className="plus">+{redline.words_added}</span>
              )}
              {redline.words_added > 0 && redline.words_removed > 0 && " / "}
              {redline.words_removed > 0 && (
                <span className="minus">−{redline.words_removed}</span>
              )}
              <span style={{ color: "var(--graphite)" }}> words</span>
            </span>
          )}
        </div>

        <div className="panes">
          <Pane
            side="v1"
            clause={row.v1}
            html={redline.html_v1}
            versionLabel={`${report.v1.document_name} · ${report.v1.version_label}`}
            countryCode={report.v1.country_code}
            absentNote={
              report.is_cross_country
                ? `No counterpart in ${report.v1.country_name}.`
                : `Not present in ${report.v1.version_label}.`
            }
            term={term}
          />
          <Pane
            side="v2"
            clause={row.v2}
            html={redline.html_v2}
            versionLabel={`${report.v2.document_name} · ${report.v2.version_label}`}
            countryCode={report.v2.country_code}
            absentNote={
              report.is_cross_country
                ? `No counterpart in ${report.v2.country_name}.`
                : `Removed in ${report.v2.version_label}.`
            }
            term={term}
          />
        </div>
      </div>
    </article>
  );
}

// Rows are heavy and the list is long; re-render only when the row or the
// search term actually changes.
export const ClauseRecord = memo(Record);
