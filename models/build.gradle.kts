plugins {
    java
    id("software.amazon.smithy.gradle.smithy-jar") version "1.3.0"
}

repositories {
    mavenCentral()
}

dependencies {
    // Smithy core
    implementation("software.amazon.smithy:smithy-model:1.69.0")
    implementation("software.amazon.smithy:smithy-aws-traits:1.69.0")

    // OpenAPI projection (for API Gateway integration + docs)
    implementation("software.amazon.smithy:smithy-openapi:1.69.0")
    implementation("software.amazon.smithy:smithy-aws-apigateway-openapi:1.69.0")

    // Native TypeScript client codegen (published on Maven Central)
    smithyBuild("software.amazon.smithy.typescript:smithy-aws-typescript-codegen:0.49.1")
}
