"use client";

import type { LibraryStats } from "@/lib/types";

export type Tab = "compare" | "library" | "collection";

const TABS: { id: Tab; label: string }[] = [
  { id: "compare", label: "Compare" },
  { id: "library", label: "Add documents" },
  { id: "collection", label: "Reference collection" },
];

export function Masthead({
  stats,
  tab,
  onTab,
}: {
  stats: LibraryStats | null;
  tab: Tab;
  onTab: (tab: Tab) => void;
}) {
  return (
    <header className="masthead">
      <div className="shell masthead-inner">
        <div className="wordmark">
          <span className="wordmark-name">Regulation Diff</span>
          <span className="wordmark-rule" aria-hidden="true" />
          <span className="wordmark-sub">Fire safety standards</span>
        </div>

        <nav className="tabs" aria-label="Sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              className="tab"
              aria-selected={tab === item.id}
              onClick={() => onTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {stats && (
          <div className="masthead-stats">
            <span className="masthead-stat">
              <b>{stats.versions}</b> editions
            </span>
            <span className="masthead-stat">
              <b>{stats.clauses.toLocaleString()}</b> clauses
            </span>
            <span className="masthead-stat">
              <b>{Object.keys(stats.by_country).length}</b> jurisdictions
            </span>
          </div>
        )}
      </div>
    </header>
  );
}
