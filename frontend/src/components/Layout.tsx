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
          <span className="led" aria-hidden="true" />
          Shortlist
        </Link>
        <nav aria-label="Main">
          {status === "signed-in" && user && (
            <div className="segments">
              <NavLink to="/feed">Feed</NavLink>
              <NavLink to="/saved">Saved</NavLink>
              <NavLink to="/profile">{user.full_name.split(" ")[0] || "Profile"}</NavLink>
              <button type="button" className="segment" onClick={handleLogOut}>
                Log out
              </button>
            </div>
          )}
          {status === "signed-out" && (
            <div className="segments">
              <NavLink to="/login">Log in</NavLink>
              <NavLink to="/register">Join with an invite</NavLink>
            </div>
          )}
        </nav>
      </header>
      <main id="main" className="page">
        {children}
      </main>
    </div>
  );
}
