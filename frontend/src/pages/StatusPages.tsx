import { Link, Navigate } from "react-router";
import { useAuth } from "../auth/AuthProvider";

export function HomeRedirect() {
  const { status } = useAuth();
  if (status === "signed-in") return <Navigate to="/feed" replace />;
  if (status === "signed-out") return <Navigate to="/login" replace />;
  return null;
}

export function ApiUnavailablePage() {
  return (
    <section className="panel panel--narrow">
      <h1>Can't reach Shortlist</h1>
      <div className="message message--error" role="alert">
        <p>The server didn't answer. It may still be waking up.</p>
      </div>
      <button type="button" className="button" onClick={() => window.location.reload()}>
        Try again
      </button>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <section className="panel panel--narrow">
      <h1>Not found</h1>
      <p>There's no page at this address.</p>
      <Link className="button" to="/">
        Go to the start
      </Link>
    </section>
  );
}
