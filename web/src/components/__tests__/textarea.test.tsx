import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Textarea } from "@/components/ui/textarea";

describe("Textarea", () => {
  it("renders a textarea element", () => {
    render(<Textarea aria-label="comentario" />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("renders the placeholder", () => {
    render(<Textarea placeholder="Escribe aquí" />);
    expect(screen.getByPlaceholderText("Escribe aquí")).toBeInTheDocument();
  });

  it("accepts and displays a value", () => {
    render(<Textarea defaultValue="texto inicial" aria-label="t" />);
    expect(screen.getByRole("textbox")).toHaveValue("texto inicial");
  });

  it("fires onChange when typing", () => {
    let val = "";
    render(
      <Textarea aria-label="t" onChange={(e) => (val = e.target.value)} />,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hola" } });
    expect(val).toBe("hola");
  });

  it("can be disabled", () => {
    render(<Textarea aria-label="t" disabled />);
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("applies a custom className", () => {
    render(<Textarea aria-label="t" className="my-textarea" />);
    expect(screen.getByRole("textbox")).toHaveClass("my-textarea");
  });

  it("forwards ref to the textarea element", () => {
    const ref = { current: null as HTMLTextAreaElement | null };
    render(<Textarea ref={ref} aria-label="t" />);
    expect(ref.current?.tagName).toBe("TEXTAREA");
  });
});
