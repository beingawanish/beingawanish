// returns-svc: return eligibility, RMA, and the returns-and-refunds saga (forward recovery,
// architecture §6) on the same saga kit as order-svc. Port 8109.
plugins {
    id("eda.spring-service")
}
