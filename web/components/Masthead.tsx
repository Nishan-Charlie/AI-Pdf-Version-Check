"use client";

import type { LibraryStats } from "@/lib/types";

export type Tab = "compare" | "library" | "collection";

const TABS: { id: Tab; label: string }[] = [
  { id: "compare", label: "Compare" },
  { id: "library", label: "Add documents" },
  { id: "collection", label: "Reference collection" },
];

/**
 * The app mark — the same drawing as app/icon.svg.
 *
 * Inlined rather than loaded, so it takes its colour from the theme. The
 * favicon keeps the charcoal tile because a browser tab can be any colour; on
 * the page the tile is redundant and the flame stands on its own.
 */
function Logo() {
  return (
    <svg
      className="wordmark-logo"
      viewBox="0 0 32 32"
      width="24"
      height="24"
      aria-hidden="true"
      focusable="false"
      fill="var(--accent)"
    >
      <path d="M16 5.2c4.6 4.2 7 8 7 11.4a7 7 0 0 1-14 0c0-2.4 1-4.4 2.7-6.1 0 2 .8 3.4 2.3 4.1.6-3.4-.6-6.3 2-9.4z" />
      <path d="M6 25.5h4.2l2.2-3.2H8.2zM13.4 25.5h4.2l2.2-3.2h-4.2zM20.8 25.5H25l2.2-3.2H23z" />
    </svg>
  );
}

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
          <Logo />
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
