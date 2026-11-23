// edacommon: the shared library every service uses (implementation guide §4). It depends on no service.
plugins {
    id("eda.java-conventions")
    `java-test-fixtures`
}

dependencies {
    api(project(":libs:contracts-java"))
    api("org.springframework.boot:spring-boot-starter")
    api("org.springframework.boot:spring-boot-starter-web")
    api("org.springframework.boot:spring-boot-starter-validation")
    api("org.springframework.boot:spring-boot-starter-jdbc")
    api("org.springframework.boot:spring-boot-starter-security")
    api("org.springframework.boot:spring-boot-starter-oauth2-resource-server")
    api("org.springframework.kafka:spring-kafka")
    api(libs.otel.api)
    api(libs.otel.spring.boot.starter)
    api(libs.awssdk.s3)
    implementation(libs.uuid.creator)
    runtimeOnly(libs.logstash.logback.encoder)
    runtimeOnly("org.postgresql:postgresql")

    testFixturesApi(project(":libs:contracts-java"))
    testFixturesApi("org.springframework.boot:spring-boot-starter-test")
    testFixturesApi("org.springframework.boot:spring-boot-starter-jdbc")
    testFixturesApi("org.springframework.kafka:spring-kafka")
    testFixturesApi("org.testcontainers:junit-jupiter")
    testFixturesApi("org.testcontainers:postgresql")
    testFixturesApi("org.testcontainers:kafka")
    testFixturesApi(libs.archunit)
    testFixturesApi(libs.otel.sdk.testing)
    testFixturesApi(libs.swagger.request.validator.mockmvc)
    testFixturesImplementation("org.postgresql:postgresql")

    testImplementation(libs.jqwik)
    testImplementation(libs.wiremock)
    testImplementation(libs.logstash.logback.encoder)
    testImplementation("org.flywaydb:flyway-core")
    testImplementation("org.flywaydb:flyway-database-postgresql")
}
