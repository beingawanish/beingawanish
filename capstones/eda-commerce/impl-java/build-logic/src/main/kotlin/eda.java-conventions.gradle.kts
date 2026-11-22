// Shared conventions for every Java module: Java 21, pinned BOMs, Error Prone, Spotless, JUnit 5.
import net.ltgt.gradle.errorprone.errorprone

plugins {
    `java-library`
    id("net.ltgt.errorprone")
    id("com.diffplug.spotless")
}

val libs = extensions.getByType<VersionCatalogsExtension>().named("libs")
fun lib(alias: String) = libs.findLibrary(alias).get()

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(libs.findVersion("java").get().requiredVersion)) }
}

// BOMs are applied as Gradle platforms to every resolvable classpath of the module.
listOf("api", "implementation", "annotationProcessor", "testImplementation", "testRuntimeOnly").forEach { conf ->
    configurations.findByName(conf)?.let {
        dependencies {
            add(conf, platform(lib("spring-boot-bom")))
            add(conf, platform(lib("otel-instrumentation-bom")))
            add(conf, platform(lib("awssdk-bom")))
            add(conf, platform(lib("testcontainers-bom")))
        }
    }
}
plugins.withId("java-test-fixtures") {
    dependencies {
        add("testFixturesApi", platform(lib("spring-boot-bom")))
        add("testFixturesApi", platform(lib("otel-instrumentation-bom")))
        add("testFixturesApi", platform(lib("testcontainers-bom")))
    }
}

dependencies {
    "errorprone"(lib("errorprone-core"))
    // Gradle needs a launcher aligned with the BOM's JUnit Platform version.
    "testRuntimeOnly"("org.junit.platform:junit-platform-launcher")
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
    options.release.set(21)
    // -parameters: Spring binds constructor and request parameters by name.
    options.compilerArgs.addAll(listOf("-parameters", "-Xlint:deprecation"))
    options.errorprone {
        disableWarningsInGeneratedCode.set(true)
        excludedPaths.set(".*/build/generated.*")
        // Noise for this code base; everything else stays at Error Prone's defaults.
        disable("StringSplitter", "MissingSummary", "InlineMeSuggester", "JavaTimeDefaultTimeZone")
    }
}

spotless {
    java {
        target("src/**/*.java")
        googleJavaFormat(libs.findVersion("google-java-format").get().requiredVersion)
        removeUnusedImports()
    }
}

tasks.withType<Test>().configureEach {
    useJUnitPlatform()
    // Integration tests read these to find a database when Docker is not available (see edacommon testFixtures).
    listOf("EDA_TEST_JDBC_URL", "EDA_TEST_JDBC_USER", "EDA_TEST_JDBC_PASSWORD").forEach { name ->
        System.getenv(name)?.let { environment(name, it) }
    }
    systemProperty("eda.contracts.dir", rootProject.layout.projectDirectory.dir("../contracts").asFile.absolutePath)
    maxParallelForks = 1
    testLogging {
        events("failed", "skipped")
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
        showStandardStreams = false
    }
}
