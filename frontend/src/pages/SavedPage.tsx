import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, unwrap } from "../api/client";
import { FormError } from "../components/Form";
import { undoFeedback } from "../feedback";

export function SavedPage() {
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["saved"], queryFn: () => unwrap(api.GET("/api/v1/saved")) });
  const remove = useMutation({
    mutationFn: (postingId: string) => undoFeedback(postingId, "saved"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["saved"] }),
  });

  return (
    <section>
      <h1>Saved</h1>
      <FormError error={saved.error ?? remove.error} />
      {saved.data?.items.length === 0 && (
        <p className="empty">
          Nothing saved yet. Save postings from your <Link to="/feed">feed</Link> to keep them here.
        </p>
      )}
      <ul className="saved">
        {saved.data?.items.map((item) => (
          <li key={item.posting_id} className="saved__item">
            <div className="saved__main">
              <strong>
                {item.title}
                {item.status === "closed" && (
                  <span className="badge">
                    <span className="led led--off" aria-hidden="true" />
                    Closed
                  </span>
                )}
              </strong>
              <span className="cap">
                {item.company} · saved {new Date(item.saved_at).toLocaleDateString()}
              </span>
            </div>
            <div className="saved__actions">
              <a className="key" href={item.url} target="_blank" rel="noopener noreferrer">
                Open
              </a>
              <button type="button" className="key" onClick={() => remove.mutate(item.posting_id)}>
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
