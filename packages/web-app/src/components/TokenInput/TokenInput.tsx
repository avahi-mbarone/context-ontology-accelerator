// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TokenInput — a reusable "chip input" for editing a list of short string
 * values (tags/tokens).
 *
 * The user types a value and commits it with Enter or the add button; each
 * committed value is rendered as a dismissable chip via Cloudscape's
 * `TokenGroup`. Values are trimmed and de-duplicated. This replaces the
 * error-prone "type a comma-separated string" pattern with discrete,
 * individually-removable entries.
 */
import React, { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TokenGroup from "@cloudscape-design/components/token-group";

export interface TokenInputProps {
  /** Current committed values, rendered as chips. */
  value: string[];
  /** Called with the next value list whenever a chip is added or removed. */
  onChange: (value: string[]) => void;
  /** Placeholder shown in the text input. */
  placeholder?: string;
  /** Accessible label for the text input. */
  ariaLabel?: string;
  /** Disables the input and the add button. */
  disabled?: boolean;
  /**
   * Optional validator for a candidate value. Return an error string to reject
   * the value (it won't be added and the message is shown), or `null` to allow.
   */
  validate?: (candidate: string, existing: string[]) => string | null;
}

export const TokenInput: React.FC<TokenInputProps> = ({
  value,
  onChange,
  placeholder,
  ariaLabel,
  disabled = false,
  validate,
}) => {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const addToken = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Silently ignore duplicates — the value is already present as a chip.
    if (value.includes(trimmed)) {
      setText("");
      setError(null);
      return;
    }
    const validationError = validate?.(trimmed, value) ?? null;
    if (validationError) {
      setError(validationError);
      return;
    }
    onChange([...value, trimmed]);
    setText("");
    setError(null);
  };

  const removeToken = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <SpaceBetween size="xs">
      <SpaceBetween direction="horizontal" size="xs">
        <Input
          value={text}
          onChange={({ detail }) => {
            setText(detail.value);
            if (error) setError(null);
          }}
          onKeyDown={(event) => {
            if (event.detail.key === "Enter") {
              // Prevent the keypress from submitting an enclosing form.
              event.preventDefault();
              addToken();
            }
          }}
          placeholder={placeholder}
          ariaLabel={ariaLabel}
          disabled={disabled}
        />
        <Button
          iconName="add-plus"
          disabled={disabled || text.trim().length === 0}
          onClick={addToken}
          ariaLabel={ariaLabel ? `Add ${ariaLabel}` : "Add value"}
        >
          Add
        </Button>
      </SpaceBetween>
      {error && (
        <Box variant="small" color="text-status-error">
          {error}
        </Box>
      )}
      {value.length > 0 && (
        <TokenGroup
          items={value.map((v) => ({ label: v, dismissLabel: `Remove ${v}` }))}
          onDismiss={({ detail }) => removeToken(detail.itemIndex)}
        />
      )}
    </SpaceBetween>
  );
};
