// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  ColumnLayout,
  Container,
  ContentLayout,
  Grid,
  Header,
  SpaceBetween,
} from "@cloudscape-design/components";
import { useUser } from "@auth";
import { useToolsPanel } from "@components/ToolsPanelProvider";
import { HomeHelpPanel } from "./HomeHelpPanel";
import { ONBOARDING_ICON } from "@constants/drawer-icons";

/**
 * Decorative ontology-graph watermark rendered behind the hero. Purely visual
 * (aria-hidden) and self-contained — it draws a small fixed graph of example
 * domain classes so the landing hero echoes the product's semantic model.
 */
const OntologyWatermark: React.FC = () => {
  const nodes: Array<{
    id: string;
    label: string;
    x: number;
    y: number;
    r: number;
  }> = [
    { id: "policy", label: "Policy", x: 520, y: 180, r: 34 },
    { id: "coverage", label: "Coverage", x: 700, y: 110, r: 26 },
    { id: "party", label: "Party", x: 640, y: 290, r: 28 },
    { id: "claim", label: "Claim", x: 820, y: 230, r: 30 },
    { id: "payment", label: "Payment", x: 940, y: 130, r: 22 },
    { id: "agent", label: "Agent", x: 760, y: 360, r: 20 },
    { id: "endorsement", label: "Endorsement", x: 440, y: 80, r: 20 },
  ];
  const edges: Array<[string, string]> = [
    ["policy", "coverage"],
    ["policy", "party"],
    ["policy", "endorsement"],
    ["claim", "policy"],
    ["claim", "party"],
    ["payment", "claim"],
    ["agent", "party"],
    ["agent", "policy"],
  ];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        top: 0,
        bottom: "-20%",
        left: "calc(50% - 50vw)",
        right: "calc(50% - 50vw)",
        pointerEvents: "none",
        overflow: "hidden",
        opacity: 0.06,
        color: "currentColor",
      }}
    >
      <svg
        viewBox="0 0 1000 420"
        preserveAspectRatio="xMidYMid slice"
        style={{ width: "100%", height: "100%" }}
        fill="none"
        stroke="currentColor"
      >
        <g strokeWidth={1.5}>
          {edges.map(([a, b]) => {
            const na = byId.get(a);
            const nb = byId.get(b);
            if (!na || !nb) return null;
            return (
              <line key={`${a}-${b}`} x1={na.x} y1={na.y} x2={nb.x} y2={nb.y} />
            );
          })}
        </g>
        <g>
          {nodes.map((n) => (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r={n.r} strokeWidth={2} />
              <circle cx={n.x} cy={n.y} r={3} fill="currentColor" />
              <text
                x={n.x + n.r + 8}
                y={n.y + 5}
                fill="currentColor"
                stroke="none"
                fontSize={14}
                fontFamily="inherit"
              >
                {n.label}
              </text>
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
};

/**
 * Context Ontology Accelerator landing / home page. This is the post-login destination (the OIDC
 * authenticate callback redirects to `/`). It welcomes the signed-in user and
 * routes them into the core workflow: create a namespace, then connect a
 * source, model an ontology, and serve it.
 */
export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useUser();
  const { registerDrawer, unregisterDrawer } = useToolsPanel();
  const greetingName = user?.name || user?.email || "";

  useEffect(() => {
    registerDrawer({
      id: "onboarding",
      content: <HomeHelpPanel />,
      trigger: { iconSvg: ONBOARDING_ICON },
      ariaLabels: {
        drawerName: "Get started",
        closeButton: "Close Get started",
      },
    });
    return () => unregisterDrawer("onboarding");
  }, [registerDrawer, unregisterDrawer]);

  return (
    <ContentLayout
      headerVariant="high-contrast"
      maxContentWidth={1000}
      header={
        <div style={{ position: "relative", overflow: "hidden" }}>
          <OntologyWatermark />
          <Box padding={{ vertical: "xxxl" }}>
            <Grid
              gridDefinition={[
                { colspan: { default: 12, s: 7 } },
                { colspan: { default: 12, s: 1 } },
                { colspan: { default: 12, s: 4 } },
              ]}
            >
              <SpaceBetween size="xs">
                <Box color="inherit" fontSize="body-m">
                  AI Platform · Context Layer
                </Box>
                <Header variant="h1">
                  <Box
                    color="inherit"
                    fontSize="display-l"
                    fontWeight="heavy"
                    variant="span"
                  >
                    Context Ontology Accelerator
                  </Box>
                </Header>
                <Box fontWeight="light" fontSize="display-l" color="inherit">
                  The governed context layer for enterprise AI.
                </Box>
                <Box variant="p" color="inherit" fontSize="heading-s">
                  Connect to your Glue and SageMaker catalogs, induce a
                  W3C-standard semantic model, and serve it to analysts and AI
                  agents over MCP.
                </Box>
              </SpaceBetween>

              <div />

              <Container>
                <SpaceBetween size="l">
                  <Box variant="p">
                    {greetingName ? `Welcome, ${greetingName}. ` : ""}
                    Create a namespace and connect your first source in a few
                    guided steps.
                  </Box>
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button
                      variant="primary"
                      onClick={() => navigate("/namespaces/create")}
                    >
                      Get started
                    </Button>
                    <Button onClick={() => navigate("/namespaces")}>
                      View namespaces
                    </Button>
                  </SpaceBetween>
                </SpaceBetween>
              </Container>
            </Grid>
          </Box>
        </div>
      }
    >
      <Container header={<Header variant="h2">How it works</Header>}>
        <ColumnLayout columns={3} variant="text-grid">
          <SpaceBetween size="xs">
            <Header variant="h3">Scan</Header>
            <Box variant="p" color="text-body-secondary">
              Point Context Ontology Accelerator at your Glue and SageMaker
              catalogs. It inventories tables and columns, then previews
              AI-generated business context for your review.
            </Box>
          </SpaceBetween>
          <SpaceBetween size="xs">
            <Header variant="h3">Ontology</Header>
            <Box variant="p" color="text-body-secondary">
              Draft a W3C-standard ontology over scanned catalogs. Author
              validation rules, define governed metrics, and publish through a
              versioned workflow.
            </Box>
          </SpaceBetween>
          <SpaceBetween size="xs">
            <Header variant="h3">Serve</Header>
            <Box variant="p" color="text-body-secondary">
              Expose the governed surface to analysts and agents. Every request
              flows through policy enforcement, with every decision logged.
            </Box>
          </SpaceBetween>
        </ColumnLayout>
      </Container>
    </ContentLayout>
  );
};
