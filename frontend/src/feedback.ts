import { api, unwrap } from "./api/client";
import type { FeedbackKind } from "./api/types";

export function sendFeedback(postingId: string, kind: FeedbackKind): Promise<unknown> {
  return unwrap(
    api.POST("/api/v1/postings/{posting_id}/feedback", {
      params: { path: { posting_id: postingId } },
      body: { kind, surface: "feed" },
    }),
  );
}

export function undoFeedback(postingId: string, kind: "saved" | "dismissed"): Promise<unknown> {
  return unwrap(
    api.DELETE("/api/v1/postings/{posting_id}/feedback/{kind}", {
      params: { path: { posting_id: postingId, kind } },
    }),
  );
}
