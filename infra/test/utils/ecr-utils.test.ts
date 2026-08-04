// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { parseEcrImageUri } from "../../lib/utils/ecr-utils";

describe("parseEcrImageUri", () => {
  it("parses a standard single-segment repo with tag", () => {
    const result = parseEcrImageUri(
      "123456789012.dkr.ecr.us-east-1.amazonaws.com/scl:context-manager-abc123",
    );
    expect(result.accountId).toBe("123456789012");
    expect(result.region).toBe("us-east-1");
    expect(result.repositoryName).toBe("scl");
    expect(result.tag).toBe("context-manager-abc123");
    expect(result.repositoryArn).toBe(
      "arn:aws:ecr:us-east-1:123456789012:repository/scl",
    );
  });

  it("parses a prefixed repo name with tag", () => {
    const result = parseEcrImageUri(
      "210987654321.dkr.ecr.us-west-2.amazonaws.com/coa-dev-context-manager:guardrail-v4",
    );
    expect(result.accountId).toBe("210987654321");
    expect(result.region).toBe("us-west-2");
    expect(result.repositoryName).toBe("coa-dev-context-manager");
    expect(result.tag).toBe("guardrail-v4");
    expect(result.repositoryArn).toBe(
      "arn:aws:ecr:us-west-2:210987654321:repository/coa-dev-context-manager",
    );
  });

  it("parses a nested repo path", () => {
    const result = parseEcrImageUri(
      "111222333444.dkr.ecr.eu-west-1.amazonaws.com/team/service:v1.2.3",
    );
    expect(result.accountId).toBe("111222333444");
    expect(result.region).toBe("eu-west-1");
    expect(result.repositoryName).toBe("team/service");
    expect(result.tag).toBe("v1.2.3");
    expect(result.repositoryArn).toBe(
      "arn:aws:ecr:eu-west-1:111222333444:repository/team/service",
    );
  });

  it("defaults tag to latest when not specified", () => {
    const result = parseEcrImageUri(
      "123456789012.dkr.ecr.us-east-1.amazonaws.com/scl",
    );
    expect(result.repositoryName).toBe("scl");
    expect(result.tag).toBe("latest");
  });

  it("throws on missing repository path", () => {
    expect(() => parseEcrImageUri("not-a-valid-uri")).toThrow(
      "missing repository path",
    );
  });

  it("throws on invalid host format", () => {
    expect(() => parseEcrImageUri("docker.io/library/nginx:latest")).toThrow(
      "host must be",
    );
  });

  it("throws on empty repository name", () => {
    expect(() =>
      parseEcrImageUri("123456789012.dkr.ecr.us-east-1.amazonaws.com/:tag"),
    ).toThrow("empty repository name");
  });
});
