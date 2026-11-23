import { Link, useSearchParams } from "react-router";

const MESSAGES: Record<string, string> = {
  save: "Saved. It's waiting in your saved list.",
  dismiss: "Got it. You'll see fewer postings like that one.",
};

/** Where the one-click links in the digest email land. */
export function ThanksPage() {
  const [params] = useSearchParams();
  const message = MESSAGES[params.get("action") ?? ""] ?? "Thanks, noted.";
  return (
    <section className="panel panel--narrow">
      <h1>Thanks</h1>
      <p>{message}</p>
      <p>
        <Link className="button" to="/feed">
          See your feed
        </Link>
      </p>
    </section>
  );
}
