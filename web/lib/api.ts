import type {
  ComparisonReport,
  CorpusStatus,
  DownloadStatus,
  MachineInfo,
  Meta,
  ModelInfo,
  SearchHit,
  VersionRecord,
} from "./types";

/** Raised when the API answers with an error the user needs to see. */
export class ApiError extends Error {}

/**
 * Where the browser sends API calls.
 *
 * Empty by default, so requests go to the dashboard's own origin and Next
 * forwards them — one origin, no CORS preflight on uploads.
 *
 * Set NEXT_PUBLIC_API_ORIGIN to talk to the Python service directly instead.
 * That takes Next out of the data path, which matters on a machine short of
 * memory: the dev server no longer buffers every comparison response, and a
 * long comparison is no longer bounded by the proxy's request timeout, which
 * surfaces as `socket hang up` / ECONNRESET. The service already allows the
 * dashboard's origin, so no further configuration is needed.
 */
const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(API_ORIGIN + path, init);
  } catch {
    throw new ApiError(
      API_ORIGIN
        ? `Can't reach the comparison service at ${API_ORIGIN}. Start it with ` +
          "`uvicorn api.main:app --port 8000`."
        : "Can't reach the comparison service. Start it with `uvicorn api.main:app --port 8000`.",
    );
  }

  if (!response.ok) {
    // FastAPI puts the readable message in `detail`; fall back to the status.
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${response.status}).`,
    );
  }

  return response.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),

  corpus: () => request<CorpusStatus>("/api/corpus"),

  versions: (country?: string) =>
    request<{ versions: VersionRecord[] }>(
      country ? `/api/versions?country=${encodeURIComponent(country)}` : "/api/versions",
    ).then((r) => r.versions),

  models: () =>
    request<{ default: string; models: ModelInfo[]; machine: MachineInfo }>(
      "/api/models",
    ),

  /** Begin fetching a model. Returns straight away; poll modelStatus. */
  startModelDownload: (model: string) =>
    request<DownloadStatus>(
      `/api/models/download?model=${encodeURIComponent(model)}`,
      { method: "POST" },
    ),

  modelStatus: (model: string) =>
    request<DownloadStatus>(
      `/api/models/status?model=${encodeURIComponent(model)}`,
    ),

  /** Load a model and wait for it — the blocking counterpart to the above. */
  warmModel: (model: string) =>
    request<{ model: string; window: number; dimensions: number }>(
      `/api/models/warm?model=${encodeURIComponent(model)}`,
      { method: "POST" },
    ),

  compare: (
    versionV1: number,
    versionV2: number,
    strategy: string,
    model?: string,
  ) =>
    request<ComparisonReport>("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        version_v1: versionV1,
        version_v2: versionV2,
        strategy,
        model: model || null,
      }),
    }),

  search: (query: string, country?: string) => {
    const params = new URLSearchParams({ q: query });
    if (country) params.set("country", country);
    return request<{ results: SearchHit[] }>(`/api/search?${params}`).then(
      (r) => r.results,
    );
  },

  ingest: (form: FormData) =>
    request<{ parse: { clause_count: number; country_code: string; profile_label: string; confidence: number; page_count: number } }>(
      "/api/ingest",
      { method: "POST", body: form },
    ),

  deleteVersion: (id: number) =>
    request<{ deleted: number }>(`/api/versions/${id}`, { method: "DELETE" }),

  exportUrl: (
    versionV1: number,
    versionV2: number,
    strategy: string,
    model?: string,
  ) => {
    const params = new URLSearchParams({
      version_v1: String(versionV1),
      version_v2: String(versionV2),
      strategy,
    });
    if (model) params.set("model", model);
    return `${API_ORIGIN}/api/compare/export?${params}`;
  },
};
