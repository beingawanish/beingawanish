// Gradle multi-project for the Java build of eda-commerce (implementation guide §2).
pluginManagement {
    includeBuild("build-logic")
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
    }
}

rootProject.name = "eda-commerce-java"

include(":libs:contracts-java")
include(":libs:edacommon")
include(":libs:kernel")

// Wave 1 services. Wave 2 adds fulfilment-svc, shipping-svc, notification-svc and returns-svc
// with the same layout (copy services/inventory-svc as the participant template, order-svc for an orchestrator).
include(":services:catalog-svc")
include(":services:checkout-svc")
include(":services:order-svc")
include(":services:inventory-svc")
include(":services:payment-svc")
