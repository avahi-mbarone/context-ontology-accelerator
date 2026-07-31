// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ClassDetailCard } from "./ClassDetailCard";

const TURTLE = `
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://ex.org/Claim> a owl:Class ; rdfs:label "Claim" .
`;

describe("ClassDetailCard", () => {
  it("renders the class label", () => {
    render(
      <ClassDetailCard
        iri="http://ex.org/Claim"
        turtle={TURTLE}
        onSelectClass={vi.fn()}
      />,
    );
    expect(screen.getByText("Claim")).toBeTruthy();
  });

  it("shows a close button and calls onClose when clicked", () => {
    const onClose = vi.fn();
    render(
      <ClassDetailCard
        iri="http://ex.org/Claim"
        turtle={TURTLE}
        onSelectClass={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByLabelText("Close class details"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("omits the close button when onClose is not provided", () => {
    render(
      <ClassDetailCard
        iri="http://ex.org/Claim"
        turtle={TURTLE}
        onSelectClass={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Close class details")).toBeNull();
  });
});
