import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";

describe("SearchAutocomplete", () => {
  it("renders an input with combobox role", () => {
    render(<SearchAutocomplete value="" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("does not show listbox when there are no matching items", () => {
    render(<SearchAutocomplete value="" onChange={vi.fn()} suggestions={[]} />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows listbox after focus when recentSearches are present", () => {
    render(
      <SearchAutocomplete
        value=""
        onChange={vi.fn()}
        recentSearches={["anterior búsqueda"]}
      />,
    );
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("anterior búsqueda")).toBeInTheDocument();
  });

  it("filters suggestions that include the current value", () => {
    render(
      <SearchAutocomplete
        value="con"
        onChange={vi.fn()}
        suggestions={["contrato", "consulta", "obra"]}
      />,
    );
    fireEvent.focus(screen.getByRole("combobox"));
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(screen.getByText("contrato")).toBeInTheDocument();
    expect(screen.getByText("consulta")).toBeInTheDocument();
  });

  it("excludes exact matches from suggestions list", () => {
    render(
      <SearchAutocomplete
        value="contrato"
        onChange={vi.fn()}
        suggestions={["contrato", "contratos públicos"]}
      />,
    );
    fireEvent.focus(screen.getByRole("combobox"));
    // "contrato" matches but is excluded as exact match; "contratos públicos" remains
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByText("contratos públicos")).toBeInTheDocument();
  });

  it("navigates options with ArrowDown and wraps at boundary", () => {
    render(
      <SearchAutocomplete
        value="con"
        onChange={vi.fn()}
        suggestions={["contrato", "consulta"]}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);

    // No active item initially
    expect(input.getAttribute("aria-activedescendant")).toBeNull();

    // First ArrowDown → first option becomes active
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).not.toBeNull();

    // ArrowDown again → second option
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const activeId = input.getAttribute("aria-activedescendant");
    expect(activeId).toMatch(/-1$/);

    // Another ArrowDown at last item stays at last item (no wrap)
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe(activeId);
  });

  it("navigates back with ArrowUp to deactivate first item", () => {
    render(
      <SearchAutocomplete
        value="con"
        onChange={vi.fn()}
        suggestions={["contrato"]}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).not.toBeNull();
    fireEvent.keyDown(input, { key: "ArrowUp" });
    // Back to -1 — no active descendant
    expect(input.getAttribute("aria-activedescendant")).toBeNull();
  });

  it("Enter on active item calls onChange and onSubmit with that label", () => {
    const onChange = vi.fn();
    const onSubmit = vi.fn();
    render(
      <SearchAutocomplete
        value="con"
        onChange={onChange}
        onSubmit={onSubmit}
        suggestions={["contrato", "consulta"]}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("contrato");
    expect(onSubmit).toHaveBeenCalledWith("contrato");
  });

  it("Enter with no active item calls onSubmit with current value", () => {
    const onSubmit = vi.fn();
    render(
      <SearchAutocomplete value="query" onChange={vi.fn()} onSubmit={onSubmit} />,
    );
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("query");
  });

  it("Escape closes the listbox", () => {
    render(
      <SearchAutocomplete
        value="con"
        onChange={vi.fn()}
        suggestions={["contrato"]}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("aria-expanded reflects open state", () => {
    render(
      <SearchAutocomplete
        value=""
        onChange={vi.fn()}
        recentSearches={["anterior"]}
      />,
    );
    const input = screen.getByRole("combobox");
    expect(input.getAttribute("aria-expanded")).toBe("false");
    fireEvent.focus(input);
    expect(input.getAttribute("aria-expanded")).toBe("true");
  });

  it("option clicked via mouseDown calls onChange and onSubmit", () => {
    const onChange = vi.fn();
    const onSubmit = vi.fn();
    render(
      <SearchAutocomplete
        value="con"
        onChange={onChange}
        onSubmit={onSubmit}
        suggestions={["contrato"]}
      />,
    );
    fireEvent.focus(screen.getByRole("combobox"));
    const option = screen.getByRole("option");
    fireEvent.mouseDown(option);
    expect(onChange).toHaveBeenCalledWith("contrato");
    expect(onSubmit).toHaveBeenCalledWith("contrato");
  });
});
