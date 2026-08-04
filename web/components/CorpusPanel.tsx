"use client";

import type { CorpusStatus, Jurisdiction } from "@/lib/types";

/**
 * The reference collection checklist.
 *
 * Tracks the official standards this project validates against and whether
 * each one is actually on disk. British Standards are sold under BSI
 * copyright, so they are listed with a link to the publisher and marked as
 * needing a licensed copy rather than shown as a missing download.
 */
export function CorpusPanel({
  corpus,
  jurisdictions,
}: {
  corpus: CorpusStatus | null;
  jurisdictions: Jurisdiction[];
}) {
  if (!corpus) {
    return (
      <div className="panel">
        <div className="panel-body" style={{ color: "var(--graphite)" }}>
          Loading the collection…
        </div>
      </div>
    );
  }

  const { summary, entries } = corpus;
  const nameFor = (code: string) =>
    jurisdictions.find((j) => j.code === code)?.name ?? code;

  const groups = new Map<string, typeof entries>();
  for (const entry of entries) {
    const bucket = groups.get(entry.jurisdiction) ?? [];
    bucket.push(entry);
    groups.set(entry.jurisdiction, bucket);
  }

  return (
    <div style={{ display: "grid", gap: "1.25rem" }}>
      <div className="panel">
        <div className="panel-head">
          <span className="panel-title">Reference collection</span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: 12, color: "var(--graphite)" }}>
            {summary.downloadable_collected}/{summary.downloadable} published ·{" "}
            {summary.licensed_collected}/{summary.licensed} licensed ·{" "}
            {(summary.bytes / 1024 / 1024).toFixed(0)} MB
          </span>
        </div>
        <div className="panel-body" style={{ display: "grid", gap: "0.9rem" }}>
          <p style={{ margin: 0, fontSize: 13, color: "var(--graphite)" }}>
            Run <code className="mono">python -m corpus.fetch --extract</code> to
            download every openly published standard and build the text corpus,
            then <code className="mono">python -m corpus.load</code> to parse it
            into the database.
          </p>

          {summary.licensed_collected < summary.licensed && (
            <div className="notice" style={{ ["--notice-color" as string]: "var(--sand)" }}>
              <span>
                The BSI standards are sold under copyright and cannot be
                downloaded. Buy or license a copy, save it into{" "}
                <code className="mono">corpus/raw/</code> under the filename
                listed below, and it will appear here as held.
              </span>
            </div>
          )}
        </div>
      </div>

      {[...groups.entries()].map(([code, items]) => (
        <div className="panel" key={code}>
          <div className="panel-head">
            <span className="sigil">{code}</span>
            <span className="panel-title">{nameFor(code)}</span>
            <span className="mono" style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--graphite)" }}>
              {items.filter((e) => e.present).length}/{items.length}
            </span>
          </div>
          <div className="panel-body">
            <div className="checklist">
              {items.map((entry) => (
                <div className="check-row" key={entry.key}>
                  <span
                    className="check-mark"
                    data-state={
                      entry.present
                        ? "held"
                        : entry.access === "licensed"
                          ? "licensed"
                          : "missing"
                    }
                  >
                    {entry.present ? "[x]" : entry.access === "licensed" ? "[$]" : "[ ]"}
                  </span>

                  <span>
                    <span className="check-title">{entry.title}</span>
                    <br />
                    <span className="check-edition">
                      {entry.edition} · {entry.publisher}
                      {entry.kind !== "base" && ` · ${entry.kind}`}
                    </span>
                    {entry.notes && (
                      <>
                        <br />
                        <span className="check-edition" style={{ fontStyle: "italic" }}>
                          {entry.notes}
                        </span>
                      </>
                    )}
                  </span>

                  <span className="check-meta" style={{ textAlign: "right" }}>
                    {entry.present ? (
                      `${(entry.size_bytes / 1024 / 1024).toFixed(1)} MB`
                    ) : (
                      <a href={entry.url} target="_blank" rel="noopener noreferrer">
                        {entry.access === "licensed" ? "publisher" : "source"}
                      </a>
                    )}
                    <br />
                    <span style={{ color: "var(--graphite-light)" }}>{entry.filename}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
