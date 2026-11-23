// Shared kernel: value objects every domain uses (Money). Plain Java, no dependencies, so domain
// layers may depend on it without breaking the "standard library only" rule (guide §3).
plugins {
    id("eda.java-conventions")
}

dependencies {
    testImplementation("org.junit.jupiter:junit-jupiter")
    testImplementation("org.assertj:assertj-core")
    testImplementation(libs.jqwik)
}
