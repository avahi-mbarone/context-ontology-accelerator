// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Parse an ECR image URI into its component parts.
 *
 * @param imageUri - Full ECR image URI, e.g.
 *   `123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo:latest`
 * @throws Error if the URI format is invalid.
 */
export function parseEcrImageUri(imageUri: string): {
  accountId: string;
  region: string;
  repositoryName: string;
  tag: string;
  repositoryArn: string;
} {
  const slashIndex = imageUri.indexOf("/");
  if (slashIndex === -1) {
    throw new Error(
      `Invalid ECR image URI: missing repository path. Got: ${imageUri}`,
    );
  }

  const host = imageUri.substring(0, slashIndex);
  const imageRef = imageUri.substring(slashIndex + 1);

  const hostParts = host.split(".");
  if (
    hostParts.length < 6 ||
    hostParts[1] !== "dkr" ||
    hostParts[2] !== "ecr"
  ) {
    throw new Error(
      `Invalid ECR image URI: host must be <account>.dkr.ecr.<region>.amazonaws.com. Got: ${host}`,
    );
  }

  const accountId = hostParts[0];
  const region = hostParts[3];

  const colonIndex = imageRef.lastIndexOf(":");
  const repositoryName =
    colonIndex !== -1 ? imageRef.substring(0, colonIndex) : imageRef;
  const tag = colonIndex !== -1 ? imageRef.substring(colonIndex + 1) : "latest";

  if (!repositoryName) {
    throw new Error(
      `Invalid ECR image URI: empty repository name. Got: ${imageUri}`,
    );
  }

  return {
    accountId,
    region,
    repositoryName,
    tag,
    repositoryArn: `arn:aws:ecr:${region}:${accountId}:repository/${repositoryName}`,
  };
}
