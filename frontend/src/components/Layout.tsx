import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { setLoginNotice } from "../auth/loginNotice";

export function Layout({ children }: { children: ReactNode }) {
  const { status, user, logOut } = useAuth();
  const navigate = useNavigate();

  async function handleLogOut() {
    setLoginNotice("You're logged out.");
    await logOut().catch(() => undefined); // logged out in this tab either way
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="masthead">
        <Link to="/" className="wordmark" aria-label="Shortlist home">
          <svg viewBox="0 0 32 32" aria-hidden="true" className="wordmark__mark">
            <rect width="32" height="32" rx="7" fill="currentColor" />
            <path
              d="M9 11h14M9 16h10M9 21h6"
              stroke="var(--paper)"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
          </svg>
          Shortlist
        </Link>
        <nav aria-label="Main">
          {status === "signed-in" && user && (
            <>
              <NavLink to="/feed">Feed</NavLink>
              <NavLink to="/saved">Saved</NavLink>
              <NavLink to="/profile">{user.full_name.split(" ")[0] || "Profile"}</NavLink>
              <button type="button" className="link-button" onClick={handleLogOut}>
                Log out
              </button>
            </>
          )}
          {status === "signed-out" && (
            <>
              <NavLink to="/login">Log in</NavLink>
              <NavLink to="/register">Join with an invite</NavLink>
            </>
          )}
        </nav>
      </header>
      <main id="main" className="page">
        {children}
      </main>
    </div>
  );
}
