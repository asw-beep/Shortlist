import { useMutation } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Field, FormError, SubmitButton, errorsByField, formValues } from "../components/Form";

export function RegisterPage() {
  const { logIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const register = useMutation({
    mutationFn: async (values: Record<string, string>) => {
      const body = {
        email: values.email!,
        full_name: values.full_name!,
        password: values.password!,
        invite_code: values.invite_code!.trim(),
      };
      await unwrap(api.POST("/api/v1/auth/register", { body }));
      return logIn(body.email, body.password);
    },
    onSuccess: () => navigate("/profile", { replace: true }),
  });
  const errors = errorsByField(register.error);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    register.mutate(formValues(event.currentTarget));
  }

  return (
    <section className="panel panel--narrow">
      <h1>Create your account</h1>
      <p className="muted">Shortlist is invite-only while it's small.</p>
      <form onSubmit={handleSubmit}>
        <FormError error={register.error} />
        <Field
          label="Invite code"
          name="invite_code"
          defaultValue={params.get("invite") ?? ""}
          autoComplete="off"
          required
          error={errors.invite_code}
        />
        <Field
          label="Full name"
          name="full_name"
          autoComplete="name"
          required
          error={errors.full_name}
        />
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
          autoComplete="new-password"
          minLength={12}
          hint="At least 12 characters. A few random words work well."
          required
          error={errors.password}
        />
        <div className="actions">
          <SubmitButton pending={register.isPending}>Create account</SubmitButton>
        </div>
      </form>
      <p className="muted">
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </section>
  );
}
