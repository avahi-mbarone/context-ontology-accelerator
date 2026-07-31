// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Template, Match } from "aws-cdk-lib/assertions";

import { JdbcConnectivity } from "../../lib/constructs/jdbc-connectivity";

/**
 * Build a stack with a VPC + two client SGs and a JdbcConnectivity construct.
 * Returns the synthesized Template for assertions.
 */
function buildTemplate(
  configure: (
    vpc: ec2.Vpc,
    clientSgs: ec2.ISecurityGroup[],
  ) => ConstructorParameters<typeof JdbcConnectivity>[2],
): Template {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, "TestStack", {
    env: { account: "123456789012", region: "us-east-1" },
  });
  const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2, natGateways: 1 });
  const sgA = new ec2.SecurityGroup(stack, "LambdaSg", { vpc });
  const sgB = new ec2.SecurityGroup(stack, "ConnectorSg", { vpc });
  new JdbcConnectivity(stack, "Conn", configure(vpc, [sgA, sgB]));
  return Template.fromStack(stack);
}

describe("JdbcConnectivity", () => {
  it("throws when no connectivity option is provided", () => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "S", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2 });
    expect(
      () =>
        new JdbcConnectivity(stack, "Conn", {
          vpc,
          clientSecurityGroups: [],
        }),
    ).toThrow(/at least one of/);
  });

  describe("VPC peering", () => {
    it("creates a peering connection and routes per private subnet x CIDR", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        peering: {
          peerVpcId: "vpc-0peer123",
          destinationCidrs: ["10.20.0.0/16", "10.21.0.0/16"],
        },
      }));

      template.resourceCountIs("AWS::EC2::VPCPeeringConnection", 1);
      template.hasResourceProperties("AWS::EC2::VPCPeeringConnection", {
        PeerVpcId: "vpc-0peer123",
      });
      // 2 private subnets (2 AZs) x 2 CIDRs = 4 peering routes.
      const routes = template.findResources("AWS::EC2::Route", {
        Properties: { VpcPeeringConnectionId: Match.anyValue() },
      });
      expect(Object.keys(routes).length).toBe(4);
    });

    it("passes peerOwnerId and peerRegion for cross-account/region peering", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        peering: {
          peerVpcId: "vpc-0peer123",
          destinationCidrs: ["10.20.0.0/16"],
          peerOwnerId: "999999999999",
          peerRegion: "us-west-2",
        },
      }));
      template.hasResourceProperties("AWS::EC2::VPCPeeringConnection", {
        PeerVpcId: "vpc-0peer123",
        PeerOwnerId: "999999999999",
        PeerRegion: "us-west-2",
      });
    });

    it("throws when destinationCidrs is empty", () => {
      expect(() =>
        buildTemplate((vpc, clientSgs) => ({
          vpc,
          clientSecurityGroups: clientSgs,
          peering: { peerVpcId: "vpc-0peer123", destinationCidrs: [] },
        })),
      ).toThrow(/destinationCidrs must not be empty/);
    });
  });

  describe("Transit Gateway", () => {
    it("creates an attachment and TGW routes per subnet x CIDR", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        transitGateway: {
          transitGatewayId: "tgw-0abc",
          destinationCidrs: ["10.30.0.0/16"],
        },
      }));

      template.resourceCountIs("AWS::EC2::TransitGatewayVpcAttachment", 1);
      template.hasResourceProperties("AWS::EC2::TransitGatewayVpcAttachment", {
        TransitGatewayId: "tgw-0abc",
      });
      const routes = template.findResources("AWS::EC2::Route", {
        Properties: { TransitGatewayId: "tgw-0abc" },
      });
      // 2 private subnets x 1 CIDR = 2 routes.
      expect(Object.keys(routes).length).toBe(2);
    });

    it("makes each TGW route depend on the attachment", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        transitGateway: {
          transitGatewayId: "tgw-0abc",
          destinationCidrs: ["10.30.0.0/16"],
        },
      }));
      const routes = template.findResources("AWS::EC2::Route", {
        Properties: { TransitGatewayId: "tgw-0abc" },
      });
      const attachmentId = Object.keys(
        template.findResources("AWS::EC2::TransitGatewayVpcAttachment"),
      )[0];
      for (const route of Object.values(routes)) {
        expect((route as any).DependsOn).toContain(attachmentId);
      }
    });

    it("throws when destinationCidrs is empty", () => {
      expect(() =>
        buildTemplate((vpc, clientSgs) => ({
          vpc,
          clientSecurityGroups: clientSgs,
          transitGateway: {
            transitGatewayId: "tgw-0abc",
            destinationCidrs: [],
          },
        })),
      ).toThrow(/destinationCidrs must not be empty/);
    });
  });

  describe("PrivateLink", () => {
    it("creates an interface endpoint with the service name and port", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        privateLink: {
          serviceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
          port: 5432,
        },
      }));

      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
        VpcEndpointType: "Interface",
      });
    });

    it("defaults private DNS to disabled and honours the override", () => {
      const off = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        privateLink: {
          serviceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
          port: 5432,
        },
      }));
      off.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        PrivateDnsEnabled: false,
      });

      const on = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        privateLink: {
          serviceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
          port: 5432,
          privateDnsEnabled: true,
        },
      }));
      on.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        PrivateDnsEnabled: true,
      });
    });

    it("scopes the endpoint SG ingress to the client SGs on the DB port", () => {
      const template = buildTemplate((vpc, clientSgs) => ({
        vpc,
        clientSecurityGroups: clientSgs,
        privateLink: {
          serviceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
          port: 1521,
        },
      }));
      // One ingress rule per client SG (2), on port 1521.
      const ingress = template.findResources("AWS::EC2::SecurityGroupIngress", {
        Properties: { FromPort: 1521, ToPort: 1521 },
      });
      expect(Object.keys(ingress).length).toBe(2);
    });
  });

  it("supports combining peering + TGW + PrivateLink at once", () => {
    const template = buildTemplate((vpc, clientSgs) => ({
      vpc,
      clientSecurityGroups: clientSgs,
      peering: { peerVpcId: "vpc-0peer", destinationCidrs: ["10.20.0.0/16"] },
      transitGateway: {
        transitGatewayId: "tgw-0abc",
        destinationCidrs: ["10.30.0.0/16"],
      },
      privateLink: {
        serviceName: "com.amazonaws.vpce.us-east-1.vpce-svc-0abc",
        port: 5432,
      },
    }));
    template.resourceCountIs("AWS::EC2::VPCPeeringConnection", 1);
    template.resourceCountIs("AWS::EC2::TransitGatewayVpcAttachment", 1);
    template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
      VpcEndpointType: "Interface",
    });
  });
});
