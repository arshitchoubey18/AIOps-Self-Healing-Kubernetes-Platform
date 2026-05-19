.PHONY: bootstrap observability argocd deploy lint helm-template demo clean-demo

bootstrap:
	./scripts/bootstrap-minikube.sh

observability:
	./scripts/install-observability.sh

argocd:
	./scripts/install-argocd.sh

deploy:
	./scripts/deploy-local.sh

lint:
	ruff check services

helm-template:
	helm template aio-self-healing charts/aio-self-healing

demo:
	kubectl apply -f examples/crashy-app.yaml

clean-demo:
	kubectl delete -f examples/crashy-app.yaml --ignore-not-found

