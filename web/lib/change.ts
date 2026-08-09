import type { ChangeType, ComparisonReport } from "./types";

/**
 * How each change type is coloured.
 *
 * Red and green are reserved for removal and addition, matching the redline
 * marks inside the clause text. The ochre scale in between is degree of edit,
 * so hue reads as one continuous idea across the whole interface.
 */
export const CHANGE_STYLE: Record<ChangeType, { color: string; wash: string }> = {
  Unchanged: { color: "var(--graphite-light)", wash: "var(--paper-sunken)" },
  "Minor Edit": { color: "var(--sand)", wash: "var(--sand-wash)" },
  "Significant Change": { color: "var(--burnt)", wash: "var(--burnt-wash)" },
  Added: { color: "var(--ins)", wash: "var(--ins-wash)" },
  Removed: { color: "var(--del)", wash: "var(--del-wash)" },
};

/** Display order: what an auditor acts on first. */
export const CHANGE_ORDER: ChangeType[] = [
  "Significant Change",
  "Added",
  "Removed",
  "Minor Edit",
  "Unchanged",
];

/**
 * Tallies for the summary strip.
 *
 * A cross-country comparison is not a diff of one text against its own later
 * self, so "unchanged" and "minor edit" are not meaningful readings there. It
 * is reported as what it is: how many clauses found a counterpart, and how
 * many exist on one side only.
 */
export function tallies(report: ComparisonReport) {
  const { summary } = report;

  if (report.is_cross_country) {
    const aligned =
      summary.unchanged + summary.minor_edits + summary.significant_changes;
    return [
      { key: "aligned", label: "Aligned", value: aligned, types: ["Unchanged", "Minor Edit", "Significant Change"] as ChangeType[], color: "var(--indigo)", wash: "var(--indigo-wash)" },
      { key: "close", label: "Close wording", value: summary.minor_edits, types: ["Minor Edit"] as ChangeType[], color: "var(--sand)", wash: "var(--sand-wash)" },
      { key: "diverging", label: "Diverging", value: summary.significant_changes, types: ["Significant Change"] as ChangeType[], color: "var(--burnt)", wash: "var(--burnt-wash)" },
      { key: "only2", label: `Only in ${report.v2.country_code}`, value: summary.added, types: ["Added"] as ChangeType[], color: "var(--ins)", wash: "var(--ins-wash)" },
      { key: "only1", label: `Only in ${report.v1.country_code}`, value: summary.removed, types: ["Removed"] as ChangeType[], color: "var(--del)", wash: "var(--del-wash)" },
    ];
  }

  return [
    { key: "total", label: "Clauses", value: summary.total_clauses, types: [] as ChangeType[], color: "var(--ink)", wash: "var(--paper-sunken)" },
    { key: "unchanged", label: "Unchanged", value: summary.unchanged, types: ["Unchanged"] as ChangeType[], color: "var(--graphite)", wash: "var(--paper-sunken)" },
    { key: "minor", label: "Minor edit", value: summary.minor_edits, types: ["Minor Edit"] as ChangeType[], color: "var(--sand)", wash: "var(--sand-wash)" },
    { key: "significant", label: "Significant", value: summary.significant_changes, types: ["Significant Change"] as ChangeType[], color: "var(--burnt)", wash: "var(--burnt-wash)" },
    { key: "added", label: "Added", value: summary.added, types: ["Added"] as ChangeType[], color: "var(--ins)", wash: "var(--ins-wash)" },
    { key: "removed", label: "Removed", value: summary.removed, types: ["Removed"] as ChangeType[], color: "var(--del)", wash: "var(--del-wash)" },
  ];
}

/** What the row's chip says, which differs across jurisdictions. */
export function chipLabel(
  changeType: ChangeType,
  report: ComparisonReport,
): string {
  if (!report.is_cross_country) return changeType;

  switch (changeType) {
    case "Added":
      return `only in ${report.v2.country_code}`;
    case "Removed":
      return `only in ${report.v1.country_code}`;
    case "Unchanged":
    case "Minor Edit":
      return "close wording";
    default:
      return "diverging";
  }
}
