// Generated Avro SpecificRecord classes for every message in contracts/avro-bundled (ADR-0004).
// Nothing in this module is hand-written and nothing generated is committed: the classes are rebuilt
// from the bundled schemas on every build, so the Java types can never drift from the contract.
import com.github.davidmc24.gradle.plugin.avro.GenerateAvroJavaTask

buildscript {
    // The plugin ships an older avro-compiler; generate with the same Avro version we run with.
    dependencies { classpath("org.apache.avro:avro-compiler:1.12.1") }
}

plugins {
    id("eda.java-conventions")
    id("com.github.davidmc24.gradle.plugin.avro-base") version "1.9.1"
}

val bundledSchemas = rootProject.layout.projectDirectory.dir("../contracts/avro-bundled")

val generateContracts = tasks.register<GenerateAvroJavaTask>("generateContracts") {
    description = "Generates SpecificRecord classes from contracts/avro-bundled."
    source(bundledSchemas)
    include("*.avsc")
    setOutputDir(layout.buildDirectory.dir("generated/sources/avro").get().asFile)
    stringType.set("String")
    fieldVisibility.set("PRIVATE")
}

sourceSets["main"].java.srcDir(generateContracts)

// The bundled schemas are also published as resources, so code and tests can read the exact
// registered text (for subject lookups and golden-fixture tests) without a path to contracts/.
sourceSets["main"].resources.srcDir(bundledSchemas.asFile.parentFile)
tasks.named<ProcessResources>("processResources") {
    include("avro-bundled/*.avsc")
}

dependencies {
    api(libs.avro)
}

// Generated code is not ours to format or lint.
spotless { java { targetExclude("build/**") } }
