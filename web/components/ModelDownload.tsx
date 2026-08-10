"use client";

import type { DownloadStatus, ModelInfo } from "@/lib/types";

/**
 * What the model is doing while you wait for it.
 *
 * A download of several hundred megabytes needs to look like progress rather
 * than a stall, so this reports the actual byte count the service is tracking.
 * The phases are named because they behave differently: bytes move during the
 * download, then stop for a while during the load, and a bar that sat at 100%
 * with no explanation would read as a hang.
 */

const PHASE_LABEL: Record<DownloadStatus["state"], string> = {
  idle: "Waiting",
  resolving: "Checking what needs downloading",
  downloading: "Downloading",
  loading: "Loading into memory",
  ready: "Ready",
  error: "Failed",
};

export function ModelDownload({
  status,
  model,
}: {
  status: DownloadStatus;
  model: ModelInfo | null;
}) {
  const failed = status.state === "error";
  const measured = status.total_bytes > 0 && status.state === "downloading";

  return (
    <section
      className="download"
      role="status"
      aria-live="polite"
      data-state={status.state}
    >
      <div className="download-head">
        <span className="download-spinner" aria-hidden="true" />
        <span className="download-title">
          {PHASE_LABEL[status.state]}
          {model ? ` · ${model.key}` : ""}
        </span>
        <span className="download-figure mono">
          {failed
            ? "error"
            : measured
              ? `${formatBytes(status.done_bytes)} / ${formatBytes(status.total_bytes)}`
              : status.state === "ready"
                ? "done"
                : "…"}
        </span>
      </div>

      <div
        className="download-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={measured ? Math.round(status.percent) : undefined}
        aria-label="Model download progress"
      >
        {measured ? (
          <div className="download-fill" style={{ width: `${status.percent}%` }} />
        ) : (
          <div className="download-fill download-fill-sweep" />
        )}
      </div>

      <p className="download-note">
        {failed ? (
          <span style={{ color: "var(--del)" }}>{status.error}</span>
        ) : status.state === "downloading" ? (
          <>
            {Math.round(status.percent)}% · this happens once, then the model
            stays on disk
          </>
        ) : (
          status.message
        )}
      </p>
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}
