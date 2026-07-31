// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from "@testing-library/react";
import { ChatAvatar } from "./ChatAvatar";

describe("ChatAvatar", () => {
  describe("user role", () => {
    it("renders user initials", () => {
      render(<ChatAvatar role="user" initials="MC" />);
      expect(screen.getByText("MC")).toBeInTheDocument();
    });

    it("renders default 'U' when no initials provided", () => {
      render(<ChatAvatar role="user" />);
      expect(screen.getByText("U")).toBeInTheDocument();
    });

    it("renders with ariaLabel 'User'", () => {
      render(<ChatAvatar role="user" initials="AB" />);
      expect(screen.getByLabelText("User")).toBeInTheDocument();
    });
  });

  describe("assistant role", () => {
    it("renders gen-ai icon (svg) for assistant role", () => {
      const { container } = render(<ChatAvatar role="assistant" />);
      expect(container.querySelector("svg")).toBeInTheDocument();
    });

    it("renders with ariaLabel 'Context Ontology Accelerator'", () => {
      render(<ChatAvatar role="assistant" />);
      expect(
        screen.getByLabelText("Context Ontology Accelerator"),
      ).toBeInTheDocument();
    });

    it("renders avatar when isLoading is true", () => {
      render(<ChatAvatar role="assistant" isLoading={true} />);
      expect(
        screen.getByLabelText("Context Ontology Accelerator"),
      ).toBeInTheDocument();
    });

    it("does not pass loading state when isLoading is false", () => {
      const { container } = render(
        <ChatAvatar role="assistant" isLoading={false} />,
      );
      expect(container.querySelector("svg")).toBeInTheDocument();
    });
  });
});
