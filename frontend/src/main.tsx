import "./styles.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { ApiError } from "./api/problem";
import { AuthProvider } from "./auth/AuthProvider";
import { WakeGate } from "./components/WakeGate";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry a dropped connection, never an answer: a 404 or 409 will not change on retry.
      retry: (failures, error) => !(error instanceof ApiError) && failures < 2,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {/* The session restore below calls the API, so wait until the API is awake. */}
        <WakeGate>
          <AuthProvider>
            <App />
          </AuthProvider>
        </WakeGate>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
