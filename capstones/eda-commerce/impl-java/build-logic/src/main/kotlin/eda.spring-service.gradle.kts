// Conventions for a deployable Spring Boot service (one per bounded context).
plugins {
    id("eda.java-conventions")
    id("org.springframework.boot")
}

val libs = extensions.getByType<VersionCatalogsExtension>().named("libs")
fun lib(alias: String) = libs.findLibrary(alias).get()

dependencies {
    implementation(project(":libs:edacommon"))
    implementation(project(":libs:contracts-java"))
    implementation(project(":libs:kernel"))
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-validation")
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.flywaydb:flyway-core")
    implementation("org.flywaydb:flyway-database-postgresql")
    runtimeOnly("org.postgresql:postgresql")

    testImplementation(testFixtures(project(":libs:edacommon")))
    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation(lib("archunit"))
    testImplementation(lib("jqwik"))
    testImplementation(lib("swagger-request-validator-mockmvc"))
    testImplementation("org.testcontainers:junit-jupiter")
    testImplementation("org.testcontainers:postgresql")
    testImplementation("org.testcontainers:kafka")
}

tasks.named<org.springframework.boot.gradle.tasks.bundling.BootJar>("bootJar") {
    archiveFileName.set("${project.name}.jar")
}
tasks.named<Jar>("jar") { enabled = false }

// Migration 1 of every service is contracts/sql/common-tables.sql, copied at build time so it can
// never drift from the contract (guide §3.2: "copy of contracts/sql/common-tables.sql").
val commonTables = rootProject.layout.projectDirectory.file("../contracts/sql/common-tables.sql")
val copyCommonTables = tasks.register<Copy>("copyCommonTablesMigration") {
    from(commonTables)
    rename { "V1__common_tables.sql" }
    into(layout.buildDirectory.dir("generated/resources/migrations/db/migration"))
}
sourceSets["main"].resources.srcDir(layout.buildDirectory.dir("generated/resources/migrations"))
tasks.named("processResources") { dependsOn(copyCommonTables) }
