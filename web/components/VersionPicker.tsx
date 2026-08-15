"use client";

import type { Jurisdiction, VersionRecord } from "@/lib/types";

/**
 * One side of a comparison.
 *
 * Options are grouped by jurisdiction and then by document, so picking a
 * Scottish handbook against an English approved document is the same two
 * clicks as picking two editions of the same instrument. Nothing in the
 * control restricts the pairing.
 */
export function VersionPicker({
  side,
  label,
  versions,
  jurisdictions,
  value,
  onChange,
}: {
  side: "baseline" | "revision";
  label: string;
  versions: VersionRecord[];
  jurisdictions: Jurisdiction[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  const selected = versions.find((v) => v.id === value) ?? null;
  const nameFor = (code: string) =>
    jurisdictions.find((j) => j.code === code)?.name ?? code;

  // Group by jurisdiction, keeping the order the API returned.
  const groups = new Map<string, VersionRecord[]>();
  for (const version of versions) {
    const bucket = groups.get(version.country_code) ?? [];
    bucket.push(version);
    groups.set(version.country_code, bucket);
  }

  return (
    <div className="field">
      <span className="field-label">
        {side === "baseline" ? "Version 1 · baseline" : "Version 2 · revision"}
      </span>

      <select
        className="control"
        aria-label={label}
        // Without this the browser restores the previous option on reload,
        // leaving the control showing one edition while the page compares
        // another.
        autoComplete="off"
        value={value ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        <option value="" disabled>
          Choose an edition…
        </option>
        {[...groups.entries()].map(([code, items]) => (
          <optgroup key={code} label={nameFor(code)}>
            {items.map((version) => (
              <option key={version.id} value={version.id}>
                {version.document_name} — {version.version_label} (
                {version.clause_count.toLocaleString()} clauses)
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {selected && (
        <span className="side-tag">
          <span className="sigil">{selected.country_code}</span>
          <span style={{ color: "var(--graphite)" }}>
            {selected.country_name}
            {selected.doc_type ? ` · ${selected.doc_type}` : ""}
          </span>
        </span>
      )}
    </div>
  );
}
