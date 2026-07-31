// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Documentation-coverage gate for the public API.
//
// EmitEachSelector emits a DANGER event for every operation matched by the
// selector; unsuppressed DANGER events make the model invalid and fail the
// Smithy build (`gradlew build` / `make generate`). This enforces that every
// public operation is documented and carries examples — satisfying ORR DOC-A-3
// at generation time, locally and in CI, with no custom script.
//
// `///` doc comments compile to the `smithy.api#documentation` trait, so the
// documentation selector matches operations that have no leading `///` comment.
//
// The structure gate covers hand-authored domain shapes (including error
// shapes) but deliberately excludes the input/output structures Smithy
// synthesizes from inline `input :=` / `output :=` blocks — those carry the
// `@input` / `@output` traits and are machine-generated, so requiring prose on
// them would add noise, not documentation.
//
// The member gate requires a description for every structure member that would
// otherwise render blank in the API reference — i.e. a member with no `///` of
// its own whose *target shape* is also undocumented. Members that target a
// documented type (e.g. `namespaceId: Uuid`, where `Uuid` carries a `///`)
// inherit that description in the generated OpenAPI and are correctly exempt.
//
// The enum gates require a description on every enum shape AND every enum value
// (member). Both are scoped to the `com.amazon.semanticcontext` namespace so
// that transitively-referenced AWS enums (aws.apigateway#*, aws.protocols#*),
// which we do not own and cannot annotate, are not gated.
$version: "2"

metadata validators = [
    {
        name: "EmitEachSelector"
        id: "OperationMissingDocumentation"
        message: "Every public operation must have documentation (a /// doc comment)."
        configuration: { selector: "operation :not([trait|documentation])" }
    }
    {
        name: "EmitEachSelector"
        id: "OperationMissingExamples"
        message: "Every public operation must have an @examples trait."
        configuration: { selector: "operation :not([trait|examples])" }
    }
    {
        name: "EmitEachSelector"
        id: "StructureMissingDocumentation"
        message: "Every domain structure must have documentation (a /// doc comment). Synthesized @input/@output wrappers are exempt."
        configuration: { selector: "structure :not([trait|documentation]) :not([trait|input]) :not([trait|output])" }
    }
    {
        name: "EmitEachSelector"
        id: "MemberMissingDocumentation"
        message: "Every structure member must have documentation (a /// doc comment) unless its target type is itself documented. Otherwise it renders blank in the API reference."
        configuration: {
            selector: "structure > member :not([trait|documentation]) :not(:test(> [trait|documentation]))"
        }
    }
    {
        name: "EmitEachSelector"
        id: "EnumMissingDocumentation"
        message: "Every enum must have documentation (a /// doc comment)."
        configuration: { selector: "[id|namespace^=com.amazon.semanticcontext] :is(enum) :not([trait|documentation])" }
    }
    {
        name: "EmitEachSelector"
        id: "EnumValueMissingDocumentation"
        message: "Every enum value must have documentation (a /// doc comment) so it is described in the API reference."
        configuration: {
            selector: "[id|namespace^=com.amazon.semanticcontext] :is(enum) > member :not([trait|documentation])"
        }
    }
]
