"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChangeSpine } from "@/components/ChangeSpine";
import { ClauseRecord } from "@/components/ClauseRecord";
import { CorpusPanel } from "@/components/CorpusPanel";
import { Masthead, type Tab } from "@/components/Masthead";
import { ModelDownload } from "@/components/ModelDownload";
import { ModelPicker } from "@/components/ModelPicker";
import { UploadPanel } from "@/components/UploadPanel";
import { VersionPicker } from "@/components/VersionPicker";
import { ApiError, api } from "@/lib/api";
import { tallies } from "@/lib/change";
import { matches } from "@/lib/highlight";
import type {
  ChangeType,
  ComparisonReport,
  CorpusStatus,
  DownloadStatus,
  Meta,
  ModelInfo,
  SearchHit,
  VersionRecord,
} from "@/lib/types";

const PAGE_SIZE = 40;
const SEARCH_SCOPES = ["comparison", "library"] as const;
type SearchScope = (typeof SEARCH_SCOPES)[number];

export default function Page() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null);
  const [tab, setTab] = useState<Tab>("compare");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [baselineId, setBaselineId] = useState<number | null>(null);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [strategy, setStrategy] = useState("auto");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelKey, setModelKey] = useState("");
  const [download, setDownload] = useState<DownloadStatus | null>(null);

  const [report, setReport] = useState<ComparisonReport | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  const [term, setTerm] = useState("");
  const [scope, setScope] = useState<SearchScope>("comparison");
  const [libraryHits, setLibraryHits] = useState<SearchHit[] | null>(null);
  const [excluded, setExcluded] = useState<Set<ChangeType>>(new Set());

  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [pendingJump, setPendingJump] = useState<number | null>(null);

  const searchInput = useRef<HTMLInputElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);

  // Deferring the term keeps typing responsive when a comparison holds a
  // thousand clauses: keystrokes land immediately, filtering catches up.
  const deferredTerm = useDeferredValue(term);

  // ── Loading ──────────────────────────────────────────────────────

  const loadLibrary = useCallback(async () => {
    try {
      const [nextMeta, nextVersions] = await Promise.all([
        api.meta(),
        api.versions(),
      ]);
      setMeta(nextMeta);
      setVersions(nextVersions);
      setLoadError(null);
    } catch (caught) {
      setLoadError(
        caught instanceof ApiError ? caught.message : "Could not load the library.",
      );
    }
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const { models: available } = await api.models();
      setModels(available);
      setModelKey((current) => {
        if (current && available.some((m) => m.key === current)) return current;
        return (available.find((m) => m.is_default) ?? available[0])?.key ?? "";
      });
    } catch {
      setModels([]);
    }
  }, []);

  useEffect(() => {
    void loadLibrary();
    void loadModels();
    api.corpus().then(setCorpus).catch(() => setCorpus(null));
  }, [loadLibrary, loadModels]);

  // Open on a comparison worth looking at: the largest instrument that has
  // more than one edition, oldest against newest.
  useEffect(() => {
    if (versions.length === 0 || baselineId !== null) return;

    const byDocument = new Map<number, VersionRecord[]>();
    for (const version of versions) {
      const bucket = byDocument.get(version.document_id) ?? [];
      bucket.push(version);
      byDocument.set(version.document_id, bucket);
    }

    const candidates = [...byDocument.values()].filter((group) => group.length >= 2);
    const weight = (group: VersionRecord[]) =>
      group.reduce((total, version) => total + version.clause_count, 0);

    if (candidates.length > 0) {
      const pair = candidates.reduce((best, group) =>
        weight(group) > weight(best) ? group : best,
      );
      // The API returns newest first within a document.
      setBaselineId(pair[pair.length - 1].id);
      setRevisionId(pair[0].id);
    } else {
      setBaselineId(versions[0].id);
      setRevisionId(versions[1]?.id ?? null);
    }
  }, [versions, baselineId]);

  // ── Comparison ───────────────────────────────────────────────────

  /**
   * Make sure the chosen model is on disk and loaded before comparing.
   *
   * Downloading inside the comparison request would give one long silence, so
   * it runs as its own tracked job and the progress is shown while it works.
   * Resolves true when the model is ready to use.
   */
  const ensureModelReady = useCallback(async (): Promise<boolean> => {
    const chosen = models.find((m) => m.key === modelKey);
    if (!chosen || (chosen.downloaded && chosen.loaded)) return true;

    setDownload({
      model: chosen.id,
      state: "resolving",
      percent: 0,
      done_bytes: 0,
      total_bytes: 0,
      message: "Checking what needs downloading…",
      error: "",
      elapsed_seconds: 0,
    });

    try {
      let status = await api.startModelDownload(modelKey);
      setDownload(status);

      while (status.state !== "ready" && status.state !== "error") {
        await new Promise((resolve) => setTimeout(resolve, 600));
        status = await api.modelStatus(modelKey);
        setDownload(status);
      }

      if (status.state === "error") {
        setCompareError(`Could not prepare ${chosen.key}: ${status.error}`);
        return false;
      }

      await loadModels();
      return true;
    } catch (caught) {
      setCompareError(
        caught instanceof ApiError ? caught.message : "The model download failed.",
      );
      return false;
    } finally {
      // Leave the panel up briefly on success so the finished state is seen.
      setTimeout(() => setDownload(null), 900);
    }
  }, [models, modelKey, loadModels]);

  const runComparison = useCallback(async () => {
    if (!baselineId || !revisionId || baselineId === revisionId) return;

    setComparing(true);
    setCompareError(null);

    const ready = await ensureModelReady();
    if (!ready) {
      setComparing(false);
      return;
    }

    try {
      const next = await api.compare(baselineId, revisionId, strategy, modelKey);
      setReport(next);
      setExcluded(new Set());
      setVisibleCount(PAGE_SIZE);
      setActiveIndex(null);
      window.scrollTo({ top: 0, behavior: "smooth" });
      // The chosen model is now downloaded and resident; refresh the labels.
      void loadModels();
    } catch (caught) {
      setCompareError(
        caught instanceof ApiError ? caught.message : "The comparison failed.",
      );
      setReport(null);
    } finally {
      setComparing(false);
    }
  }, [baselineId, revisionId, strategy, modelKey, loadModels, ensureModelReady]);

  function swapSides() {
    setBaselineId(revisionId);
    setRevisionId(baselineId);
  }

  // ── Filtering ────────────────────────────────────────────────────

  const rows = useMemo(() => {
    if (!report) return [];

    return report.comparisons.filter((row) => {
      if (excluded.has(row.change_type)) return false;
      if (scope !== "comparison" || deferredTerm.trim().length < 2) return true;

      return matches(
        [
          row.v1?.content,
          row.v2?.content,
          row.v1?.title,
          row.v2?.title,
          row.v1?.section,
          row.v2?.section,
          row.label,
        ],
        deferredTerm,
      );
    });
  }, [report, excluded, deferredTerm, scope]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [deferredTerm, excluded, scope]);

  // Library-wide search runs on the server; the comparison filter does not.
  useEffect(() => {
    if (scope !== "library" || deferredTerm.trim().length < 2) {
      setLibraryHits(null);
      return;
    }
    let cancelled = false;
    api
      .search(deferredTerm.trim(), country || undefined)
      .then((hits) => {
        if (!cancelled) setLibraryHits(hits);
      })
      .catch(() => {
        if (!cancelled) setLibraryHits([]);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, deferredTerm, country]);

  function toggleTypes(types: ChangeType[]) {
    if (types.length === 0) {
      setExcluded(new Set());
      return;
    }
    setExcluded((current) => {
      const next = new Set(current);
      const hidingNow = types.every((type) => !next.has(type));
      // Clicking a tally isolates it; clicking again restores everything.
      if (hidingNow && next.size === 0) {
        for (const type of allChangeTypes) {
          if (!types.includes(type)) next.add(type);
        }
      } else {
        next.clear();
      }
      return next;
    });
  }

  // ── Scroll behaviour ─────────────────────────────────────────────

  const jumpTo = useCallback(
    (rowIndex: number) => {
      const position = rows.findIndex((row) => row.index === rowIndex);
      if (position < 0) return;
      if (position >= visibleCount) setVisibleCount(position + PAGE_SIZE);
      setPendingJump(rowIndex);
    },
    [rows, visibleCount],
  );

  useEffect(() => {
    if (pendingJump === null) return;
    const target = document.getElementById(`clause-${pendingJump}`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveIndex(pendingJump);
      setPendingJump(null);
    }
  }, [pendingJump, visibleCount]);

  // Grow the list as the reader reaches the end of what is rendered.
  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisibleCount((current) => Math.min(current + PAGE_SIZE, rows.length));
        }
      },
      { rootMargin: "800px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [rows.length]);

  // Keep the spine's marker on whichever clause is at the top of the viewport.
  useEffect(() => {
    const records = document.querySelectorAll<HTMLElement>(".record");
    if (records.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActiveIndex(Number(top.target.getAttribute("data-index")));
      },
      { rootMargin: "-130px 0px -70% 0px" },
    );

    records.forEach((record) => observer.observe(record));
    return () => observer.disconnect();
  }, [rows, visibleCount]);

  // "/" focuses search, the way a reader expects in a document tool.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT";
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchInput.current?.focus();
      }
      if (event.key === "Escape" && target === searchInput.current) {
        setTerm("");
        searchInput.current?.blur();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── Render ───────────────────────────────────────────────────────

  const jurisdictions = meta?.jurisdictions ?? [];
  const visibleVersions = country
    ? versions.filter((v) => v.country_code === country)
    : versions;

  const filtering = deferredTerm.trim().length >= 2 || excluded.size > 0;

  const selectedModel = models.find((m) => m.key === modelKey) ?? null;
  // Scores from different encoders are not comparable, so a report produced by
  // one must not be read as if it came from another.
  const modelChanged = Boolean(
    report && selectedModel && report.model !== selectedModel.id,
  );

  return (
    <>
      <Masthead stats={meta?.stats ?? null} tab={tab} onTab={setTab} />

      <main className="shell">
        {loadError && (
          <div
            className="notice"
            style={{ ["--notice-color" as string]: "var(--del)", marginTop: "1.25rem" }}
          >
            {loadError}
          </div>
        )}

        {tab === "library" && (
          <div style={{ padding: "1.5rem 0", display: "grid", gap: "1.25rem" }}>
            <UploadPanel
              jurisdictions={jurisdictions}
              versions={versions}
              onIngested={loadLibrary}
            />
            <StoredVersions
              versions={versions}
              onDeleted={loadLibrary}
            />
          </div>
        )}

        {tab === "collection" && (
          <div style={{ padding: "1.5rem 0" }}>
            <CorpusPanel corpus={corpus} jurisdictions={jurisdictions} />
          </div>
        )}

        {tab === "compare" && (
          <>
            <section className="compare-bar">
              <VersionPicker
                side="baseline"
                label="Baseline version"
                versions={visibleVersions}
                jurisdictions={jurisdictions}
                value={baselineId}
                onChange={setBaselineId}
              />

              <button
                type="button"
                className="compare-swap"
                onClick={swapSides}
                aria-label="Swap the two versions"
                title="Swap"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M3 6h10M3 6l2.5-2.5M3 6l2.5 2.5M13 10H3M13 10l-2.5-2.5M13 10l-2.5 2.5"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>

              <VersionPicker
                side="revision"
                label="Revised version"
                versions={visibleVersions}
                jurisdictions={jurisdictions}
                value={revisionId}
                onChange={setRevisionId}
              />

              <div className="compare-actions">
                <div className="field" style={{ minWidth: 150 }}>
                  <label className="field-label" htmlFor="jurisdiction-filter">
                    Jurisdiction
                  </label>
                  <select
                    id="jurisdiction-filter"
                    className="control"
                    autoComplete="off"
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                  >
                    <option value="">All jurisdictions</option>
                    {jurisdictions.map((j) => (
                      <option key={j.code} value={j.code}>
                        {j.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field" style={{ minWidth: 165 }}>
                  <label className="field-label" htmlFor="alignment">
                    Clause matching
                  </label>
                  <select
                    id="alignment"
                    className="control"
                    autoComplete="off"
                    value={strategy}
                    onChange={(e) => setStrategy(e.target.value)}
                  >
                    <option value="auto">Automatic</option>
                    <option value="identifier">By clause number</option>
                    <option value="semantic">By meaning</option>
                  </select>
                </div>

                <ModelPicker
                  models={models}
                  value={modelKey}
                  onChange={setModelKey}
                  disabled={comparing}
                />

                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={runComparison}
                  disabled={comparing || !baselineId || !revisionId || baselineId === revisionId}
                >
                  {download
                    ? "Preparing model…"
                    : comparing
                      ? "Comparing…"
                      : "Compare"}
                </button>

                {report && (
                  <a
                    className="btn"
                    href={api.exportUrl(
                      report.v1.version_id!,
                      report.v2.version_id!,
                      strategy,
                      modelKey,
                    )}
                  >
                    Export CSV
                  </a>
                )}
              </div>
            </section>

            {download && <ModelDownload status={download} model={selectedModel} />}

            {comparing && !download && (
              <div className="bar bar-indeterminate" role="status" aria-label="Comparing" />
            )}

            {report && modelChanged && !comparing && (
              <div
                className="notice"
                style={{ ["--notice-color" as string]: "var(--sand)", marginTop: "1rem" }}
              >
                <span>
                  These results came from <b>{report.model}</b>. Similarity scores are
                  not comparable across models — run the comparison again to see them
                  under {modelKey}.
                </span>
              </div>
            )}

            {compareError && (
              <div
                className="notice"
                style={{ ["--notice-color" as string]: "var(--del)", marginTop: "1rem" }}
              >
                {compareError}
              </div>
            )}

            {!report && !comparing && !compareError && (
              <Welcome hasVersions={versions.length > 0} onAdd={() => setTab("library")} />
            )}

            {report && (
              <>
                <Summary report={report} excluded={excluded} onToggle={toggleTypes} />

                <div className="searchbar">
                  <div className="search-input-wrap">
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.3" />
                      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                    </svg>
                    <input
                      ref={searchInput}
                      className="search-input"
                      type="search"
                      placeholder={
                        scope === "comparison"
                          ? "Find a term in this comparison — try door, sprinkler, travel distance"
                          : "Search every stored edition"
                      }
                      value={term}
                      onChange={(e) => setTerm(e.target.value)}
                    />
                  </div>

                  <div className="tabs" role="tablist" aria-label="Search scope">
                    {SEARCH_SCOPES.map((option) => (
                      <button
                        key={option}
                        type="button"
                        role="tab"
                        className="tab"
                        aria-selected={scope === option}
                        onClick={() => setScope(option)}
                      >
                        {option === "comparison" ? "This comparison" : "Whole library"}
                      </button>
                    ))}
                  </div>

                  <span className="search-meta">
                    {scope === "library"
                      ? libraryHits
                        ? `${libraryHits.length} clauses`
                        : "type to search"
                      : filtering
                        ? `${rows.length} of ${report.comparisons.length} clauses`
                        : `${report.comparisons.length} clauses`}
                  </span>

                  {!term && (
                    <span className="search-meta" aria-hidden="true">
                      <span className="kbd">/</span>
                    </span>
                  )}
                </div>

                {scope === "library" ? (
                  <LibraryResults hits={libraryHits} term={deferredTerm} />
                ) : (
                  <div className="ledger">
                    <ChangeSpine rows={rows} activeIndex={activeIndex} onJump={jumpTo} />

                    <div className="records">
                      {rows.length === 0 ? (
                        <div className="empty">
                          <span className="empty-title">Nothing matches</span>
                          <p>
                            No clause in this comparison mentions “{deferredTerm}”.
                            Try the whole library instead.
                          </p>
                        </div>
                      ) : (
                        <>
                          {rows.slice(0, visibleCount).map((row) => (
                            <ClauseRecord
                              key={row.index}
                              row={row}
                              report={report}
                              term={deferredTerm}
                            />
                          ))}
                          <div ref={sentinel} style={{ height: 1 }} />
                          {visibleCount < rows.length && (
                            <p
                              className="mono"
                              style={{
                                padding: "1.5rem 0",
                                textAlign: "center",
                                fontSize: 12,
                                color: "var(--graphite)",
                              }}
                            >
                              {rows.length - visibleCount} more clauses below
                            </p>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>

      <footer className="shell" style={{ padding: "3rem 0 2.5rem", color: "var(--graphite)", fontSize: 12 }}>
        <span className="eyebrow">
          {selectedModel
            ? `Embedding model ${selectedModel.id} · ${selectedModel.window}-token window`
            : meta
              ? `Embedding model ${meta.model}`
              : ""}
        </span>
      </footer>
    </>
  );
}

const allChangeTypes: ChangeType[] = [
  "Unchanged",
  "Minor Edit",
  "Significant Change",
  "Added",
  "Removed",
];

function Summary({
  report,
  excluded,
  onToggle,
}: {
  report: ComparisonReport;
  excluded: Set<ChangeType>;
  onToggle: (types: ChangeType[]) => void;
}) {
  const items = tallies(report);

  return (
    <section className="summary">
      {items.map((item) => {
        const isolated =
          item.types.length > 0 && item.types.every((type) => !excluded.has(type)) && excluded.size > 0;

        return (
          <button
            key={item.key}
            type="button"
            className="tally"
            aria-pressed={isolated}
            style={{
              ["--tally-color" as string]: item.color,
              ["--tally-wash" as string]: item.wash,
            }}
            onClick={() => onToggle(item.types)}
            title={item.types.length ? `Show only ${item.label.toLowerCase()}` : "Show everything"}
          >
            <span className="tally-value">{item.value.toLocaleString()}</span>
            <span className="tally-label">{item.label}</span>
          </button>
        );
      })}

      <div className="summary-note">
        <span className="wordcount">
          <span className="plus">+{report.summary.words_added.toLocaleString()}</span>
          {" / "}
          <span className="minus">−{report.summary.words_removed.toLocaleString()}</span> words
        </span>
        <span>
          {report.is_cross_country ? (
            <>Cross-jurisdiction · clauses matched by meaning</>
          ) : (
            <>
              {report.summary.change_rate.toFixed(1)}% of clauses changed · matched by{" "}
              {report.alignment_method === "identifier" ? "clause number" : "meaning"}
            </>
          )}
        </span>
        <span className="mono" style={{ fontSize: 11, color: "var(--graphite-light)" }}>
          {report.model}
        </span>
      </div>
    </section>
  );
}

function LibraryResults({ hits, term }: { hits: SearchHit[] | null; term: string }) {
  if (term.trim().length < 2) {
    return (
      <div className="empty">
        <span className="empty-title">Search the whole library</span>
        <p>
          Every clause of every stored edition, across all jurisdictions. Type a
          term to find where it appears.
        </p>
      </div>
    );
  }

  if (hits === null) {
    return <div className="bar bar-indeterminate" style={{ marginTop: "1.5rem" }} />;
  }

  if (hits.length === 0) {
    return (
      <div className="empty">
        <span className="empty-title">No clause mentions “{term}”</span>
        <p>Check the spelling, or add the document that should contain it.</p>
      </div>
    );
  }

  return (
    <div className="records" style={{ paddingTop: "1rem" }}>
      {hits.map((hit) => (
        <article className="record" key={`${hit.version_id}-${hit.id}`}>
          <div className="record-gutter">
            <span className="sigil">{hit.country_code}</span>
            <span className="record-id">{hit.clause_number}</span>
          </div>
          <div>
            <div className="record-head">
              <span className="pane-label">
                {hit.document_name} · {hit.version_label}
              </span>
              {hit.section && <span className="record-section">{hit.section}</span>}
            </div>
            <p className="clause-text" style={{ margin: 0 }}>
              {hit.excerpt}
            </p>
          </div>
        </article>
      ))}
    </div>
  );
}

function StoredVersions({
  versions,
  onDeleted,
}: {
  versions: VersionRecord[];
  onDeleted: () => void;
}) {
  async function remove(version: VersionRecord) {
    const confirmed = window.confirm(
      `Remove “${version.document_name} — ${version.version_label}” and its ${version.clause_count} clauses?`,
    );
    if (!confirmed) return;
    await api.deleteVersion(version.id).catch(() => undefined);
    onDeleted();
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">Stored editions</span>
        <span className="mono" style={{ marginLeft: "auto", fontSize: 12, color: "var(--graphite)" }}>
          {versions.length}
        </span>
      </div>
      <div className="panel-body">
        <div className="checklist">
          {versions.map((version) => (
            <div className="check-row" key={version.id}>
              <span className="sigil">{version.country_code}</span>
              <span>
                <span className="check-title">{version.document_name}</span>
                <br />
                <span className="check-edition">
                  {version.version_label}
                  {version.parser_profile && ` · parsed as ${version.parser_profile}`}
                </span>
              </span>
              <span className="check-meta" style={{ textAlign: "right" }}>
                {version.clause_count.toLocaleString()} clauses
                <br />
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ padding: "0 0.2rem", fontSize: 11 }}
                  onClick={() => remove(version)}
                >
                  Remove
                </button>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Welcome({ hasVersions, onAdd }: { hasVersions: boolean; onAdd: () => void }) {
  return (
    <div className="empty">
      <span className="empty-title">
        {hasVersions ? "Pick two editions and compare" : "The library is empty"}
      </span>
      <p>
        {hasVersions
          ? "Any two editions can be compared — two versions of one instrument, or two countries' regulations against each other. Clauses are matched by number where the numbering is shared, and by meaning where it is not."
          : "Add a regulation PDF to get started, or run the corpus fetcher to download the published UK and Irish fire safety standards."}
      </p>
      {!hasVersions && (
        <button type="button" className="btn btn-primary" onClick={onAdd}>
          Add a document
        </button>
      )}
    </div>
  );
}
