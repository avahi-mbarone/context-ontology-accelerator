// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from "@testing-library/react";
import { ChatMessage } from "./ChatMessage";

describe("ChatMessage", () => {
  const baseProps = {
    content: "Test message",
    timestamp: new Date("2026-01-01T12:00:00Z"),
  };

  describe("user messages", () => {
    it("renders user avatar with initials and message text", () => {
      render(
        <ChatMessage
          role="user"
          state="success"
          initials="JD"
          {...baseProps}
        />,
      );
      expect(screen.getByText("JD")).toBeInTheDocument();
      expect(screen.getByText("Test message")).toBeInTheDocument();
    });

    it("renders Cloudscape ChatBubble with type 'outgoing' for user", () => {
      render(
        <ChatMessage
          role="user"
          state="success"
          initials="AB"
          {...baseProps}
        />,
      );
      expect(screen.getByLabelText("user message")).toBeInTheDocument();
    });

    it("renders user avatar with row-reverse layout", () => {
      const { container } = render(
        <ChatMessage
          role="user"
          state="success"
          initials="AB"
          {...baseProps}
        />,
      );
      const wrapper = container.querySelector(".chat-message-user");
      expect(wrapper).toBeInTheDocument();
    });
  });

  describe("assistant messages", () => {
    it("renders assistant avatar with Context Ontology Accelerator label", () => {
      render(<ChatMessage role="assistant" state="loading" {...baseProps} />);
      expect(
        screen.getByLabelText("Context Ontology Accelerator"),
      ).toBeInTheDocument();
    });

    it("renders Cloudscape ChatBubble with type 'incoming' for assistant", () => {
      render(<ChatMessage role="assistant" state="success" {...baseProps} />);
      expect(screen.getByLabelText("assistant message")).toBeInTheDocument();
    });

    it("renders loading state with 'Resolving query'", () => {
      render(<ChatMessage role="assistant" state="loading" {...baseProps} />);
      expect(screen.getByText("Resolving query")).toBeInTheDocument();
    });

    it("renders loading with step labels when liveTraceSteps provided", () => {
      render(
        <ChatMessage
          role="assistant"
          state="loading"
          {...baseProps}
          liveTraceSteps={[
            { step: "t1.metric_match", status: "success", durationMs: 30 },
          ]}
        />,
      );
      expect(
        screen.getByText("Resolving query · Searching metric catalog"),
      ).toBeInTheDocument();
    });

    it("renders assistant response with answer text", () => {
      render(
        <ChatMessage
          role="assistant"
          state="success"
          content="The answer is 42"
          timestamp={baseProps.timestamp}
          response={{
            tier: 2,
            confidence: 0.85,
            synthesizedAnswer: "The answer is 42",
            latencyMs: 320,
          }}
        />,
      );
      expect(screen.getByText("The answer is 42")).toBeInTheDocument();
    });

    it("renders error state", () => {
      render(
        <ChatMessage
          role="assistant"
          state="error"
          {...baseProps}
          errorMessage="Something went wrong"
        />,
      );
      expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    });
  });
});
