"use client";

import { useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Jurisdiction, VersionRecord } from "@/lib/types";

/**
 * Adding a document to the library.
 *
 * The jurisdiction defaults to "detect from the document", because the
 * regulator's own wording identifies it more reliably than a user guessing
 * from a dropdown — but stating it explicitly always wins, since a user who
 * says this is a Scottish handbook knows something page one may not say.
 */
export function UploadPanel({
  jurisdictions,
  versions,
  onIngested,
}: {
  jurisdictions: Jurisdiction[];
  versions: VersionRecord[];
  onIngested: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [documentName, setDocumentName] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [country, setCountry] = useState("AUTO");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const documentNames = [...new Set(versions.map((v) => v.document_name))].sort();
  const ready = Boolean(file && documentName.trim() && versionLabel.trim());

  function take(next: File | null) {
    if (!next) return;
    setFile(next);
    setError(null);
    setResult(null);
    if (!documentName) {
      setDocumentName(next.name.replace(/\.pdf$/i, "").replace(/[_-]+/g, " "));
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || !file) return;

    setBusy(true);
    setError(null);
    setResult(null);

    const form = new FormData();
    form.append("file", file);
    form.append("document_name", documentName.trim());
    form.append("version_label", versionLabel.trim());
    form.append("country_code", country);

    try {
      const { parse } = await api.ingest(form);
      setResult(
        `Stored ${parse.clause_count.toLocaleString()} clauses from ${parse.page_count} pages, ` +
          `read as ${parse.profile_label}.`,
      );
      setFile(null);
      setVersionLabel("");
      if (fileInput.current) fileInput.current.value = "";
      onIngested();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "The upload failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <div className="panel-head">
        <span className="panel-title">Add a regulation</span>
        <span className="eyebrow" style={{ marginLeft: "auto" }}>
          PDF · any jurisdiction
        </span>
      </div>

      <div className="panel-body" style={{ display: "grid", gap: "0.9rem" }}>
        <label
          className="dropzone"
          data-over={dragging}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            take(e.dataTransfer.files?.[0] ?? null);
          }}
        >
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(e) => take(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span>{(file.size / 1024 / 1024).toFixed(1)} MB · click to replace</span>
            </>
          ) : (
            <>
              <strong>Drop a PDF here</strong>
              <span>or click to choose one</span>
            </>
          )}
        </label>

        <div className="grid-3">
          <div className="field">
            <label className="field-label" htmlFor="doc-name">
              Document
            </label>
            <input
              id="doc-name"
              className="control"
              list="known-documents"
              placeholder="Approved Document B — Volume 1"
              value={documentName}
              onChange={(e) => setDocumentName(e.target.value)}
            />
            <datalist id="known-documents">
              {documentNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="version-label">
              Edition
            </label>
            <input
              id="version-label"
              className="control"
              placeholder="2025 amendments"
              value={versionLabel}
              onChange={(e) => setVersionLabel(e.target.value)}
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="country">
              Jurisdiction
            </label>
            <select
              id="country"
              className="control"
              value={country}
              onChange={(e) => setCountry(e.target.value)}
            >
              <option value="AUTO">Detect from the document</option>
              {jurisdictions.map((j) => (
                <option key={j.code} value={j.code}>
                  {j.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <p style={{ margin: 0, fontSize: 12.5, color: "var(--graphite)" }}>
          Give two editions the same document name to compare them as versions.
          Any two stored editions can be compared regardless of name or country.
        </p>

        {busy && <div className="bar bar-indeterminate" role="status" aria-label="Parsing" />}

        {error && (
          <div className="notice" style={{ ["--notice-color" as string]: "var(--del)" }}>
            {error}
          </div>
        )}

        {result && (
          <div className="notice" style={{ ["--notice-color" as string]: "var(--ins)" }}>
            {result}
          </div>
        )}

        <div>
          <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
            {busy ? "Parsing…" : "Add to library"}
          </button>
        </div>
      </div>
    </form>
  );
}
