package com.edacommerce.edacommon.testing;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;
import static com.tngtech.archunit.library.Architectures.layeredArchitecture;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;

/**
 * The dependency rule of guide §3, as an ArchUnit check every service runs: adapters -> application
 * -> domain, never outwards; the domain imports nothing but the JDK and itself (no Spring, Avro,
 * JPA, Kafka, HTTP); application code never touches web, JPA or Kafka client types.
 */
public final class HexagonalArchitecture {
  private HexagonalArchitecture() {}

  public static void check(String basePackage) {
    JavaClasses classes =
        new ClassFileImporter()
            .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
            .importPackages(basePackage);

    layeredArchitecture()
        .consideringOnlyDependenciesInLayers()
        .layer("domain")
        .definedBy(basePackage + ".domain..")
        .layer("application")
        .definedBy(basePackage + ".application..")
        .layer("adapters")
        .definedBy(basePackage + ".adapters..")
        .layer("config")
        .definedBy(basePackage + ".config..")
        .whereLayer("adapters")
        .mayOnlyBeAccessedByLayers("config")
        .whereLayer("application")
        .mayOnlyBeAccessedByLayers("adapters", "config")
        .whereLayer("domain")
        .mayOnlyBeAccessedByLayers("application", "adapters", "config")
        .allowEmptyShould(true)
        .check(classes);

    noClasses()
        .that()
        .resideInAPackage(basePackage + ".domain..")
        .should()
        .dependOnClassesThat()
        .resideOutsideOfPackages(basePackage + ".domain..", "java..", "com.edacommerce.kernel..")
        .because("the domain is pure (JDK and the shared kernel only): no frameworks, Avro, SQL, Kafka, HTTP or clocks (guide §3)")
        .allowEmptyShould(true)
        .check(classes);

    noClasses()
        .that()
        .resideInAPackage(basePackage + ".application..")
        .should()
        .dependOnClassesThat()
        .resideInAnyPackage(
            "jakarta.persistence..",
            "org.springframework.web..",
            "org.springframework.data..",
            "org.apache.kafka..",
            "org.springframework.kafka..",
            "software.amazon..")
        .because("use cases know ports, not Spring MVC, JPA entities or Kafka clients (guide §3)")
        .allowEmptyShould(true)
        .check(classes);
  }
}
