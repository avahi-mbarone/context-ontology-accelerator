// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type {
  CloudFormationCustomResourceEvent,
  CloudFormationCustomResourceResponse,
} from "aws-lambda";
import {
  DataZoneClient,
  CreateAssetTypeCommand,
  ConflictException,
  DeleteAssetTypeCommand,
} from "@aws-sdk/client-datazone";

const dz = new DataZoneClient({});

export const handler = async (
  event: CloudFormationCustomResourceEvent,
): Promise<CloudFormationCustomResourceResponse> => {
  console.log("Event:", JSON.stringify(event, null, 2));

  const props = event.ResourceProperties;
  const domainId = props.DomainId;
  const projectId = props.ProjectId;
  const name = props.Name;
  const description = props.Description;
  const formName = props.FormName;
  const formRevision = props.FormRevision;

  try {
    switch (event.RequestType) {
      case "Create":
      case "Update":
        return await handleCreateOrUpdate(event, {
          domainId,
          projectId,
          name,
          description,
          formName,
          formRevision,
        });
      case "Delete":
        return await handleDelete(event, { domainId, projectId, name });
      default:
        throw new Error(
          `Unsupported CloudFormation request type: ${(event as any).RequestType}`,
        );
    }
  } catch (error) {
    console.error("Error:", error);
    throw new Error(error instanceof Error ? error.message : String(error));
  }
};

async function handleCreateOrUpdate(
  event: CloudFormationCustomResourceEvent,
  params: {
    domainId: string;
    projectId: string;
    name: string;
    description: string;
    formName: string;
    formRevision: string;
  },
): Promise<CloudFormationCustomResourceResponse> {
  try {
    const resp = await dz.send(
      new CreateAssetTypeCommand({
        domainIdentifier: params.domainId,
        owningProjectIdentifier: params.projectId,
        name: params.name,
        description: params.description,
        formsInput: {
          [params.formName]: {
            typeIdentifier: params.formName,
            typeRevision: params.formRevision,
            required: false,
          },
        },
      }),
    );

    return {
      Status: "SUCCESS",
      PhysicalResourceId: `${params.domainId}/${params.name}`,
      StackId: event.StackId,
      RequestId: event.RequestId,
      LogicalResourceId: event.LogicalResourceId,
      Data: { Revision: resp.revision ?? "1" },
    };
  } catch (error) {
    if (error instanceof ConflictException) {
      return {
        Status: "SUCCESS",
        PhysicalResourceId: `${params.domainId}/${params.name}`,
        StackId: event.StackId,
        RequestId: event.RequestId,
        LogicalResourceId: event.LogicalResourceId,
        Data: { Revision: "existing" },
      };
    }
    throw error;
  }
}

async function handleDelete(
  event: CloudFormationCustomResourceEvent,
  params: { domainId: string; projectId: string; name: string },
): Promise<CloudFormationCustomResourceResponse> {
  try {
    await dz.send(
      new DeleteAssetTypeCommand({
        domainIdentifier: params.domainId,
        identifier: params.name,
      }),
    );
  } catch (error) {
    // Ignore not-found on delete — resource may already be gone
    console.log("Delete asset type (best-effort):", error);
  }

  return {
    Status: "SUCCESS",
    PhysicalResourceId:
      (event as any).PhysicalResourceId ?? `${params.domainId}/${params.name}`,
    StackId: event.StackId,
    RequestId: event.RequestId,
    LogicalResourceId: event.LogicalResourceId,
  };
}
