"use client";

import * as React from "react";
import { Clock, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

interface SearchAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: (value: string) => void;
  suggestions?: string[];
  recentSearches?: string[];
  placeholder?: string;
  /** className for the outer container div */
  className?: string;
  /** className forwarded to the inner Input element */
  inputClassName?: string;
  "aria-label"?: string;
  id?: string;
  maxSuggestions?: number;
  leftIcon?: React.ReactNode;
  rightElement?: React.ReactNode;
  /** Marks this container as the global search input for keyboard shortcuts */
  "data-search-input"?: boolean | string;
}

export function SearchAutocomplete({
  value,
  onChange,
  onSubmit,
  suggestions = [],
  recentSearches = [],
  placeholder,
  className,
  inputClassName,
  "aria-label": ariaLabel,
  id,
  maxSuggestions = 8,
  leftIcon,
  rightElement,
  "data-search-input": dataSearchInput,
}: SearchAutocompleteProps) {
  const [open, setOpen] = React.useState(false);
  const [activeIndex, setActiveIndex] = React.useState(-1);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const listId = React.useId();

  const matchedSuggestions = React.useMemo(() => {
    if (!value) return [];
    const q = value.toLowerCase();
    return suggestions
      .filter((s) => s.toLowerCase().includes(q) && s.toLowerCase() !== q)
      .slice(0, maxSuggestions);
  }, [value, suggestions, maxSuggestions]);

  const recentFiltered = React.useMemo(() => {
    if (value) {
      const q = value.toLowerCase();
      return recentSearches
        .filter((s) => s.toLowerCase().includes(q) && s !== value)
        .slice(0, 4);
    }
    return recentSearches.slice(0, maxSuggestions);
  }, [value, recentSearches, maxSuggestions]);

  const items = React.useMemo(() => {
    const seen = new Set<string>();
    const result: { label: string; isRecent: boolean }[] = [];
    for (const s of recentFiltered) {
      if (!seen.has(s)) {
        seen.add(s);
        result.push({ label: s, isRecent: true });
      }
    }
    for (const s of matchedSuggestions) {
      if (!seen.has(s)) {
        seen.add(s);
        result.push({ label: s, isRecent: false });
      }
    }
    return result.slice(0, maxSuggestions);
  }, [recentFiltered, matchedSuggestions, maxSuggestions]);

  const shouldShow = open && items.length > 0;

  React.useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  function handleSelect(label: string) {
    onChange(label);
    onSubmit?.(label);
    setOpen(false);
    setActiveIndex(-1);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!shouldShow) {
      if (e.key === "Enter") onSubmit?.(value);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      if (activeIndex >= 0) {
        e.preventDefault();
        handleSelect(items[activeIndex].label);
      } else {
        onSubmit?.(value);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <div
      ref={containerRef}
      className={cn("relative", className)}
      {...(dataSearchInput != null ? { "data-search-input": "" } : {})}
    >
      {leftIcon && (
        <span className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground">
          {leftIcon}
        </span>
      )}
      <Input
        id={id}
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={shouldShow}
        aria-controls={shouldShow ? listId : undefined}
        aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        role="combobox"
        placeholder={placeholder}
        value={value}
        className={inputClassName}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActiveIndex(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {rightElement && (
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
          {rightElement}
        </span>
      )}
      {shouldShow && (
        <div
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-full z-50 mt-1 max-h-60 overflow-auto rounded-md border border-border bg-popover py-1 shadow-md"
        >
          {items.map((item, i) => (
            <div
              key={item.label}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === activeIndex}
              tabIndex={-1}
              className={cn(
                "flex cursor-pointer items-center gap-2 px-3 py-2 text-sm",
                i === activeIndex
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-accent hover:text-accent-foreground",
              )}
              onMouseDown={(e) => {
                e.preventDefault();
                handleSelect(item.label);
              }}
            >
              {item.isRecent ? (
                <Clock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              )}
              <span className="truncate">{item.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
