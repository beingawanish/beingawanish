// shipping-svc: carrier bookings, shipping labels by claim check, tracking normalisation of signed,
// duplicated and reordered carrier webhooks; fake carrier included. Port 8107.
plugins {
    id("eda.spring-service")
}

dependencies {
    implementation(libs.openpdf)
}
