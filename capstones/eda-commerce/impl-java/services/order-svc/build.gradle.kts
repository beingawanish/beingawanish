// order-svc: order aggregate, the order saga orchestrator, invoices, order status API, and the
// order-history projector (same codebase, Spring profile "projector"). Port 8103.
plugins {
    id("eda.spring-service")
}

dependencies {
    implementation(libs.openpdf)
}
