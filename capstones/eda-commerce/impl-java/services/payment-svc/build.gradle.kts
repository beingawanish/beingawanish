// payment-svc: authorise, capture, void, refund through the PSP port; fake PSP included. Port 8104.
plugins {
    id("eda.spring-service")
}

dependencies {
    testImplementation(libs.wiremock)
}
