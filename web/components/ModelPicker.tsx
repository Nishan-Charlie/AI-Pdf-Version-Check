"use client";

import type { ModelInfo } from "@/lib/types";

/**
 * Which encoder to compare with.
 *
 * Models differ in how much of a clause they can read at once, which is the
 * property that matters here — regulation clauses are long, and a clause the
 * encoder cannot read whole is one whose later half it cannot judge. Each
 * option therefore leads with its window rather than its name.
 *
 * A model that is not yet on disk costs a large download on first use, so the
 * option says so instead of letting the first comparison appear to hang.
 */
export function ModelPicker({
  models,
  value,
  onChange,
  disabled,
}: {
  models: ModelInfo[];
  value: string;
  onChange: (key: string) => void;
  disabled?: boolean;
}) {
  const selected = models.find((m) => m.key === value);
  const needsDownload = selected && !selected.downloaded;

  return (
    <div className="field" style={{ minWidth: 190 }}>
      <label className="field-label" htmlFor="model">
        Comparison model
      </label>

      <select
        id="model"
        className="control"
        autoComplete="off"
        value={value}
        disabled={disabled || models.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        {models.map((model) => (
          <option key={model.key} value={model.key}>
            {model.key} — {model.window} tokens
            {model.downloaded ? "" : ` · ${formatSize(model.size_mb)} download`}
            {model.heavy_for_machine ? " · heavy" : ""}
          </option>
        ))}
      </select>

      {selected && (
        <span
          className="side-tag"
          style={{
            color: selected.heavy_for_machine
              ? "var(--burnt)"
              : needsDownload
                ? "var(--sand)"
                : "var(--graphite)",
          }}
        >
          {selected.heavy_for_machine ? (
            <>Needs ~{formatSize(selected.ram_mb)} RAM · heavy for this machine</>
          ) : needsDownload ? (
            <>Downloads {formatSize(selected.size_mb)} on first use</>
          ) : selected.loaded ? (
            <>Ready · {selected.dimensions}d</>
          ) : (
            <>On disk · {selected.dimensions}d</>
          )}
        </span>
      )}
    </div>
  );
}

function formatSize(megabytes: number): string {
  return megabytes >= 1024
    ? `${(megabytes / 1024).toFixed(1)} GB`
    : `${Math.round(megabytes)} MB`;
}
