.PHONY: install data test lint eval serve
install:
	pip install -e ".[dev]"
data:
	invoiceflow generate -n 300
test:
	pytest
lint:
	ruff check src tests azure_function
eval: data
	invoiceflow eval
serve:
	invoiceflow serve --port 8000
