// Root project: no code. Conventions live in build-logic (eda.java-conventions, eda.spring-service).
tasks.register("testAll") {
    group = "verification"
    description = "Runs every test task in the build."
    dependsOn(subprojects.mapNotNull { it.tasks.findByName("test") })
}
