# Shelf-Sweeper (Worker)

Library Misplacement Detection System - AI Worker

## Overview
Shelf-Sweeper is a project developed for a competition and academic paper to automatically detect misplaced books in a library using AI.
This repository contains the Python-based AI worker that processes images of bookshelves, identifies book spines, and communicates with the web backend.

## Architecture
- **Language**: Python (3.10+)
- **AI Models**: YOLO / OpenAI API / Custom vision models
- **Communication**: REST API to the Web Backend

## Getting Started Locally
To run the worker locally, you will need Python.

1. **Setup virtual environment (recommended to use `uv`):**
   ```bash
   uv venv
   # or standard python: python -m venv .venv
   ```

2. **Install dependencies:**
   ```bash
   uv pip install -e .
   ```

3. **Run the worker:**
   Run the main python script to start the processing loop.
