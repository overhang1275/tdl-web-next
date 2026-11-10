import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { signIn } from "next-auth/react";
import { afterEach, expect, it, vi } from "vitest";
import { LoginForm } from "@/components/auth-forms";

vi.mock("next-auth/react", () => ({ signIn: vi.fn() }));

afterEach(() => { cleanup(); vi.mocked(signIn).mockReset(); });

it("restores the Authentik control and shows retry feedback when sign-in rejects", async () => {
  vi.mocked(signIn).mockRejectedValue(new Error("provider unavailable"));
  render(<LoginForm external />);
  const button = screen.getByRole("button", { name: "Continuar con Authentik" });
  fireEvent.click(button);
  await waitFor(() => expect(signIn).toHaveBeenCalledWith("authentik", { redirectTo: "/" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(/Authentik/);
  expect(alert).toHaveTextContent(/intenta de nuevo/i);
  expect(button).toBeEnabled();
  expect(button).toHaveTextContent("Continuar con Authentik");
});
