import { Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthProvider";
import { GuestOnly, RequireSession } from "./components/Guards";
import { Layout } from "./components/Layout";
import { FeedPage } from "./pages/FeedPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";
import { SavedPage } from "./pages/SavedPage";
import { ApiUnavailablePage, HomeRedirect, NotFoundPage } from "./pages/StatusPages";
import { ThanksPage } from "./pages/ThanksPage";

const guest = (page: React.ReactNode) => <GuestOnly>{page}</GuestOnly>;
const member = (page: React.ReactNode) => <RequireSession>{page}</RequireSession>;

export function App() {
  const { status } = useAuth();

  return (
    <Layout>
      {status === "unavailable" ? (
        <ApiUnavailablePage />
      ) : (
        <Routes>
          <Route path="/" element={<HomeRedirect />} />
          <Route path="/login" element={guest(<LoginPage />)} />
          <Route path="/register" element={guest(<RegisterPage />)} />
          <Route path="/feed" element={member(<FeedPage />)} />
          <Route path="/saved" element={member(<SavedPage />)} />
          <Route path="/profile" element={member(<ProfilePage />)} />
          {/* Not behind a session: digest links land here from any browser. */}
          <Route path="/thanks" element={<ThanksPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      )}
    </Layout>
  );
}
