# Intent & SQL Tools

A powerful semantic parsing and intent recognition service designed for financial domain queries, built with FastAPI and LLM integration.

## Features

- **Intent Recognition**: accurately classifies user queries into predefined intents (e.g., stock screening, backtesting).
- **Slot Filling**: Extracts and validates parameters (slots) from natural language.
- **RAG Integration**: Multi-threaded retrieval of relevant documentation and terms to enhance LLM context.
- **Optimized Output**: Returns structured Markdown output with intent classification, condition breakdown, and retrieval plans.
- **Deployment Ready**: Includes scripts for packaging and deploying to FaaS environments with full dependency management.

## Project Structure

- `intent_tool/`: Core logic for intent recognition, training, and pipeline management.
- `common/`: Shared utilities and base classes.
- `entrypoints/`: Service entry points (API servers) and deployment configurations.
  - `deploy_pkg/`: Templates and requirements for deployment.
- `docs/`: Documentation and guides.

## Quick Start (Local Development)

1. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Service**:

   ```bash
   # Make sure you are in the project root
   sh intent_and_sql_tools/entrypoints/run.sh
   ```

   The service will start at `http://0.0.0.0:8000`.

3. **Access UI**:
   Open `http://localhost:8000` in your browser to test queries interactively.

## Deployment

For detailed instructions on how to package and deploy this service to a FaaS/Serverless environment (specifically handling Linux dependency compatibility), please refer to the [Deployment Guide](DEPLOY_GUIDE.md).

## Configuration

- **System Prompt**: Configurable in `intent_tool.py`.
- **Slot Catalog**: Defined in `slot_catalog.json` for validation rules.
- **Model Config**: Managed via `ark_client.py` and environment variables.
