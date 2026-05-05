"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange"> {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  includeAllOption?: { label: string };
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    { className, value, onValueChange, options, placeholder, includeAllOption, ...props },
    ref,
  ) => (
    <select
      ref={ref}
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {placeholder ? (
        <option value="" disabled hidden>
          {placeholder}
        </option>
      ) : null}
      {includeAllOption ? <option value="">{includeAllOption.label}</option> : null}
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  ),
);
Select.displayName = "Select";
