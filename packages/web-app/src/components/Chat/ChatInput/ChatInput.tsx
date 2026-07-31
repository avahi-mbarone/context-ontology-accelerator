// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { Button, Input } from "@cloudscape-design/components";

export interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  submitDisabled?: boolean;
  placeholder?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  disabled = false,
  submitDisabled = false,
  placeholder = "Ask a question against the governed surface...",
}) => {
  const handleKeyDown = (event: CustomEvent<{ key: string }>) => {
    if (event.detail.key === "Enter") {
      onSubmit();
    }
  };

  return (
    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
      <div style={{ flex: 1 }}>
        <Input
          value={value}
          onChange={({ detail }) => onChange(detail.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          ariaLabel="Query"
        />
      </div>
      <Button
        variant="icon"
        iconName="send"
        onClick={onSubmit}
        disabled={submitDisabled}
        ariaLabel="Run query"
      />
    </div>
  );
};
