import { useMutation } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { clearLoginNotice, useLoginNotice } from "../auth/loginNotice";
import {
  Field,
  FormError,
  Notice,
  SubmitButton,
  errorsByField,
  formValues,
} from "../components/Form";

interface LoginState {
  from?: string; // where a guard sent the student from, to return there afterwards
}

export function LoginPage() {
  const { logIn } = useAuth();
  const navigate = useNavigate();
  const state = (useLocation().state ?? {}) as LoginState;
  const notice = useLoginNotice();
  const login = useMutation({
    mutationFn: ({ email, password }: Record<string, string>) => logIn(email!, password!),
    onSuccess: () => {
      clearLoginNotice();
      navigate(state.from ?? "/feed", { replace: true });
    },
  });
  const errors = errorsByField(login.error);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate(formValues(event.currentTarget));
  }

  return (
    <section className="panel panel--narrow">
      <h1>Log in</h1>
      {notice && !login.error && <Notice>{notice}</Notice>}
      <form onSubmit={handleSubmit}>
        <FormError error={login.error} />
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
          error={errors.email}
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          error={errors.password}
        />
        <div className="actions">
          <SubmitButton pending={login.isPending}>Log in</SubmitButton>
        </div>
      </form>
      <p className="muted">
        Have an invite code? <Link to="/register">Create your account</Link>
      </p>
    </section>
  );
}
