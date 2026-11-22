// Gradle multi-project for the Java build of eda-commerce (implementation guide §2).
pluginManagement {
    includeBuild("build-logic")
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    // Spotless resolves google-java-format from project repositories, so projects declare Maven Central too.
    repositoriesMode.set(RepositoriesMode.PREFER_PROJECT)
    repositories {
        mavenCentral()
    }
}

rootProject.name = "eda-commerce-java"

include(":libs:contracts-java")
include(":libs:edacommon")
include(":libs:kernel")

// Wave 1 services.
include(":services:catalog-svc")
include(":services:checkout-svc")
include(":services:order-svc")
include(":services:inventory-svc")
include(":services:payment-svc")

// Wave 2 services, same layout (inventory-svc is the participant template, order-svc the orchestrator).
include(":services:fulfilment-svc")
include(":services:shipping-svc")
include(":services:notification-svc")
include(":services:returns-svc")
