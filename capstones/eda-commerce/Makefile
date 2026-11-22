# eda-commerce: one entry point for infrastructure and contracts.
# Run `make help` for the list. Every target works from the capstone root.

SHELL        := /usr/bin/env bash
COMPOSE      := docker compose -f infra/docker-compose.yml
PYTHON       ?= python3
RF           ?= 1
DURATION     ?= 30
SCRIPTS      := infra/scripts

.DEFAULT_GOAL := help
.PHONY: help up up-all down clean ps logs health topics schemas connectors seed bootstrap \
        contracts contracts-check chaos chaos-kafka chaos-connect chaos-postgres chaos-minio \
        chaos-registry chaos-psp-declines chaos-psp-timeouts chaos-psp-duplicates chaos-wms \
        chaos-carrier chaos-reset chaos-service k8s-render

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- lifecycle
up: ## Start the core infrastructure, wait for health checks, create buckets
	$(COMPOSE) up -d --wait --wait-timeout 240
	$(COMPOSE) run --rm minio-init

up-all: ## Core infrastructure plus Temporal and Keycloak profiles
	$(COMPOSE) --profile temporal --profile auth up -d --wait --wait-timeout 300
	$(COMPOSE) run --rm minio-init

down: ## Stop containers, keep volumes
	$(COMPOSE) --profile temporal --profile auth down

clean: ## Stop containers and delete all volumes (data loss: topics, databases, buckets)
	$(COMPOSE) --profile temporal --profile auth down -v

ps: ## Container status
	$(COMPOSE) ps

logs: ## Follow logs (SVC=connect to narrow)
	$(COMPOSE) logs -f $(SVC)

health: ## Probe every component from the host
	@$(SCRIPTS)/health.sh

# ---------------------------------------------------------------- bootstrap
topics: ## Create all topics from infra/topics.conf (RF=1 locally)
	RF=$(RF) $(SCRIPTS)/create-topics.sh

schemas: ## Register bundled Avro schemas (FULL_TRANSITIVE, compatibility-checked)
	$(PYTHON) $(SCRIPTS)/register-schemas.py

connectors: ## Create/update Debezium outbox connectors (SERVICES="order payment" to narrow)
	$(SCRIPTS)/register-connectors.sh $(SERVICES)

seed: ## Seed products, prices and stock through catalog-svc and inventory-svc
	$(SCRIPTS)/seed.sh

bootstrap: up topics schemas ## up + topics + schemas (run connectors after services migrate)

# ---------------------------------------------------------------- contracts
contracts: ## Regenerate bundled schemas, examples, AsyncAPI and topics.conf
	$(PYTHON) contracts/tools/contracts.py all

contracts-check: ## CI gate: lint contracts and fail if generated files are stale
	$(PYTHON) contracts/tools/contracts.py check

# ---------------------------------------------------------------- chaos drills
chaos: ## List chaos drills
	@$(SCRIPTS)/chaos.sh help

chaos-kafka: ## Pause the broker for DURATION seconds
	DURATION=$(DURATION) $(SCRIPTS)/chaos.sh kafka-pause

chaos-connect: ## Kill Kafka Connect (outbox relay) for DURATION seconds
	DURATION=$(DURATION) $(SCRIPTS)/chaos.sh connect-kill

chaos-postgres: ## Pause Postgres for DURATION seconds
	DURATION=$(DURATION) $(SCRIPTS)/chaos.sh postgres-pause

chaos-minio: ## Stop MinIO (claim-check store) for DURATION seconds
	DURATION=$(DURATION) $(SCRIPTS)/chaos.sh minio-stop

chaos-registry: ## Stop Schema Registry for DURATION seconds
	DURATION=$(DURATION) $(SCRIPTS)/chaos.sh schema-registry-stop

chaos-service: ## SIGKILL a service process (SVC=order-svc)
	SVC=$(SVC) $(SCRIPTS)/chaos.sh service-kill

chaos-psp-declines: ## Fake PSP declines 50%
	$(SCRIPTS)/chaos.sh psp-declines

chaos-psp-timeouts: ## Fake PSP times out 33%
	$(SCRIPTS)/chaos.sh psp-timeouts

chaos-psp-duplicates: ## Fake PSP duplicates every webhook
	$(SCRIPTS)/chaos.sh psp-duplicates

chaos-wms: ## Fake warehouse drops 50% of requests and slows down
	$(SCRIPTS)/chaos.sh wms-lossy

chaos-carrier: ## Fake carrier duplicates and reorders webhooks
	$(SCRIPTS)/chaos.sh carrier-chaos

chaos-reset: ## Restore default fake behaviour
	$(SCRIPTS)/chaos.sh reset

# ---------------------------------------------------------------- kubernetes
k8s-render: ## Render the example overlay (needs kubectl or kustomize)
	kubectl kustomize infra/k8s/overlays/local-example
