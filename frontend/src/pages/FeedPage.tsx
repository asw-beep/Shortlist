import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router";
import { api, unwrap } from "../api/client";
import { ApiError } from "../api/problem";
import type { Feed } from "../api/types";
import { FormError } from "../components/Form";
import { JobCard } from "../components/JobCard";
import { sendFeedback } from "../feedback";

export function FeedPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const key = ["feed", query] as const;
  const feed = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(api.GET("/api/v1/feed", { params: { query: { q: query || undefined, limit: 20 } } })),
  });

  const save = useMutation({
    mutationFn: (postingId: string) => sendFeedback(postingId, "saved"),
    onMutate: (postingId) => setSaved((current) => new Set(current).add(postingId)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["saved"] }),
  });
  const dismiss = useMutation({
    mutationFn: (postingId: string) => sendFeedback(postingId, "dismissed"),
    onMutate: (postingId) =>
      queryClient.setQueryData<Feed>(
        key,
        (current) =>
          current && {
            ...current,
            items: current.items.filter((job) => job.posting_id !== postingId),
          },
      ),
  });

  if (feed.error instanceof ApiError && feed.error.code === "profile-incomplete") {
    return (
      <Navigate to="/profile" replace state={{ notice: "Set up your profile to see your feed." }} />
    );
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(String(new FormData(event.currentTarget).get("q") ?? "").trim());
  }

  return (
    <section>
      <div className="feed-head">
        <h1>Your feed</h1>
        <form className="search" role="search" onSubmit={handleSearch}>
          <label className="visually-hidden" htmlFor="q">
            Search postings
          </label>
          <input
            id="q"
            name="q"
            type="search"
            placeholder="e.g. backend python, data intern"
            maxLength={200}
          />
          <button className="button button--quiet" type="submit">
            Search
          </button>
        </form>
      </div>
      {feed.data && <p className="cap ranked">Ranked for: {feed.data.query_used}</p>}
      <FormError error={feed.error ?? save.error ?? dismiss.error} />
      {feed.isPending && <p className="muted">Finding postings…</p>}
      {feed.data?.items.length === 0 && (
        <p className="empty">
          Nothing matches yet. Try widening your profile: more roles, relocation or remote work.
        </p>
      )}
      <div className="jobs">
        {feed.data?.items.map((job) => (
          <JobCard
            key={job.posting_id}
            job={job}
            saved={saved.has(job.posting_id)}
            onSave={() => save.mutate(job.posting_id)}
            onDismiss={() => dismiss.mutate(job.posting_id)}
            onOpen={() => void sendFeedback(job.posting_id, "clicked").catch(() => undefined)}
          />
        ))}
      </div>
    </section>
  );
}
