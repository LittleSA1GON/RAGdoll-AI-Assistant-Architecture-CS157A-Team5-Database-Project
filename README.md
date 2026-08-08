# RAGdoll

RAGdoll is a local AI assistant built with Java/JSP, MySQL, and Python that enables users to interact with locally hosted language models. The application uses Retrieval-Augmented Generation (RAG) to incorporate relevant document context into queries, improving the accuracy and usefulness of model responses while keeping inference local.

## Contributors

- Ethan Vu (LittleSA1GON)
- Geo Lalu (gl91306)
- Naman Kumar (namank70)

## Requirements

Install the following before running RAGdoll:

- **MySQL Server** on `localhost:3306`
- **Apache Tomcat 9.0.x**
  - Tomcat 10/11 is not compatible with the current `javax.servlet` / Servlet 4.0 code.
- **JDK 25 or newer** for the compiled Java classes included in the repository
- **Python 3.12, 64-bit recommended**
- Enough disk space for a local GGUF language model and Sentence Transformer embedding model

MySQL Workbench is optional, but it can be useful for running `database/database.sql`.

Model files are not stored in the repository. The setup below uses:

- Embedding model: `BAAI/bge-base-en-v1.5`
- GGUF model: `gemma-3-1b-it-Q4_K_M.gguf`

## Python environment

Open a terminal in the repository root.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Keep the virtual environment named `.venv` in the repository root. RAGdoll checks `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS/Linux.

## Install `llama-cpp-python`

`llama-cpp-python` provides the local GGUF inference backend used by `src/rag_pipeline/model_worker.py`.

Install the build that matches your hardware **before** running `pip install -r requirements.txt`.

### CPU

The CPU wheel is the simplest option and works without CUDA or Metal:

```bash
python -m pip install --upgrade llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

### NVIDIA CUDA

Install the wheel that matches your CUDA version. For example, CUDA 12.4:

```bash
python -m pip install --upgrade llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

Common wheel tags include `cu118`, `cu121`, `cu122`, `cu123`, `cu124`, `cu125`, `cu130`, and `cu132`.

RAGdoll defaults `LLAMA_N_GPU_LAYERS` to `-1`, which requests GPU offload when the installed build supports it. Set `LLAMA_N_GPU_LAYERS=0` to force CPU inference.

### Apple Silicon / Metal

```bash
python -m pip install --upgrade llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal
```

### Build from source

The standard install command builds `llama.cpp` locally:

```bash
python -m pip install llama-cpp-python
```

A source build requires a native compiler toolchain:

- Windows: Visual Studio C++ Build Tools or MinGW
- Linux: GCC or Clang
- macOS: Xcode command-line tools

If installation fails with errors involving `CMAKE_C_COMPILER`, `nmake`, or a missing compiler, use one of the pre-built wheel commands above unless you specifically need a source build.

Verify the installation:

```bash
python -c "from llama_cpp import Llama, llama_cpp; print('llama-cpp-python OK'); print('GPU offload supported:', bool(getattr(llama_cpp, 'llama_supports_gpu_offload', lambda: False)()))"
```

Installation reference: https://github.com/abetlen/llama-cpp-python#installation

## Install Python dependencies

With `.venv` active:

```bash
python -m pip install -r requirements.txt
```

Verify the main imports:

```bash
python -c "import numpy, mysql.connector, pypdf, docx; from sentence_transformers import SentenceTransformer; from huggingface_hub import snapshot_download; from llama_cpp import Llama; print('Python requirements OK')"
```

## Model directories

The repository must use a directory named `models`, not `~models`.

Correct structure:

```text
models/
  embedding/
  models/
```

If your copy contains:

```text
~models/
```

remove the leading `~` so the directory is named:

```text
models/
```

RAGdoll does not use `~models` as a default path. Embeddings are loaded from `models/embedding/`, and GGUF files are discovered under `models/models/`.

### Rename `~models` on Windows

In File Explorer, rename `~models` to `models`, or run:

```powershell
Rename-Item -Path "~models" -NewName "models"
```

### Rename `~models` on macOS / Linux

```bash
mv '~models' models
```

If `models/` already exists, move any needed files from `~models/` into it instead of replacing the existing directory.

## Download the embedding model

The recommended embedding model is `BAAI/bge-base-en-v1.5`.

From the repository root with `.venv` active:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-base-en-v1.5', local_dir='models/embedding/bge-base-en-v1.5'); print('bge-base-en-v1.5 downloaded')"
```

The resulting structure should look like:

```text
models/
  embedding/
    bge-base-en-v1.5/
      config.json
      modules.json
      model.safetensors
      ...
```

RAGdoll loads embeddings from local files. Keep one Sentence Transformer model under `models/embedding/`, or set `RAGDOLL_EMBEDDING_MODEL_DIR` to the exact model directory.

For BGE retrieval, use this query prefix:

```text
Represent this sentence for searching relevant passages: 
```

Set it through `RAGDOLL_EMBEDDING_QUERY_PREFIX` as shown in the environment configuration below.

## Download the GGUF model

The recommended local chat model is:

```text
gemma-3-1b-it-Q4_K_M.gguf
```

Download it into `models/models/`:

```bash
python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='ggml-org/gemma-3-1b-it-GGUF', filename='gemma-3-1b-it-Q4_K_M.gguf', local_dir='models/models'))"
```

The file should end up here:

```text
models/
  models/
    gemma-3-1b-it-Q4_K_M.gguf
```

Hugging Face may require you to sign in and accept the Gemma terms before downloading. If needed, authenticate with the Hugging Face CLI or download the file from the model repository and place it in `models/models/` manually.

RAGdoll recursively scans `models/models/` for `.gguf` files. Newly discovered models are registered in the `Models` table and made available to the Free tier by the current application logic.

## Database setup

Start MySQL Server and run:

```text
database/database.sql
```

### MySQL Workbench

1. Connect to the local MySQL server.
2. Select **File -> Run SQL Script**.
3. Choose `database/database.sql`.
4. Run the script.

### Command line

```bash
mysql -u root -p < database/database.sql
```

`database.sql` starts with `DROP DATABASE IF EXISTS ragdoll_db;`. Running it again resets the database and reloads the seed data.

RAGdoll expects:

```text
Database: ragdoll_db
Host: localhost
Port: 3306
User: root
Password: supplied through DB_PASSWORD
```

## Environment variables

Tomcat must receive `DB_PASSWORD`. Setting `RAGDOLL_PROJECT_ROOT` is also recommended so the application can locate the Python worker, models, and upload directory.

### Windows: `setenv.bat`

Create or edit:

```text
<TOMCAT_HOME>\bin\setenv.bat
```

Add:

```bat
set "DB_PASSWORD=YOUR_MYSQL_ROOT_PASSWORD"
set "RAGDOLL_PROJECT_ROOT=C:\absolute\path\to\RAGdoll"
set "RAGDOLL_EMBEDDING_QUERY_PREFIX=Represent this sentence for searching relevant passages: "
```

Do not commit your database password.

### macOS / Linux: `setenv.sh`

Create or edit:

```text
<TOMCAT_HOME>/bin/setenv.sh
```

Add:

```bash
export DB_PASSWORD='YOUR_MYSQL_ROOT_PASSWORD'
export RAGDOLL_PROJECT_ROOT='/absolute/path/to/RAGdoll'
export RAGDOLL_EMBEDDING_QUERY_PREFIX='Represent this sentence for searching relevant passages: '
```

Make the file executable if needed:

```bash
chmod +x <TOMCAT_HOME>/bin/setenv.sh
```

If Tomcat is launched from an IDE, set the same environment variables in the Tomcat run configuration.

### Optional settings

```text
RAGDOLL_PYTHON                  Explicit Python executable path
RAGDOLL_MODEL_DIR               Override models/models
RAGDOLL_EMBEDDING_MODEL_DIR     Override the embedding-model directory
RAGDOLL_UPLOAD_DIR              Override data/uploads
RAGDOLL_EMBEDDING_DEVICE        cpu or cuda
RAGDOLL_EMBEDDING_QUERY_PREFIX  Embedding query prefix
LLAMA_N_GPU_LAYERS              -1 for supported GPU offload; 0 for CPU only
LLAMA_N_CTX                     Context size; default 2048
LLAMA_N_BATCH                   Batch size; default 256
LLAMA_N_UBATCH                  Micro-batch size; default 128
LLAMA_N_THREADS                 CPU thread count
RAGDOLL_RAG_ENABLED             true/false; default true
```

## Tomcat setup

RAGdoll is served at:

```text
http://localhost:8080/RAGdoll/
```

Use Apache Tomcat 9.0.x because the application uses `javax.servlet` / Servlet 4.0.

### 1. Confirm port 8080

Open:

```text
<TOMCAT_HOME>/conf/server.xml
```

The HTTP connector should use port `8080`, for example:

```xml
<Connector port="8080" protocol="HTTP/1.1"
           connectionTimeout="20000"
           redirectPort="8443" />
```

If another process is using port 8080, stop it or change the Tomcat configuration and URL accordingly.

### 2. Create the `/RAGdoll` context

Create this directory if it does not already exist:

```text
<TOMCAT_HOME>/conf/Catalina/localhost/
```

Create:

```text
RAGdoll.xml
```

Windows example:

```xml
<Context docBase="C:/absolute/path/to/RAGdoll/src/presentation"
         reloadable="true" />
```

macOS/Linux example:

```xml
<Context docBase="/absolute/path/to/RAGdoll/src/presentation"
         reloadable="true" />
```

The filename `RAGdoll.xml` creates the `/RAGdoll` context path. The application's `WEB-INF/web.xml` defines the home route used when opening `/RAGdoll/`.

### 3. Restart Tomcat

Restart Tomcat after changing the context file or environment variables.

Tomcat 9 documentation: https://tomcat.apache.org/tomcat-9.0-doc/

## Run RAGdoll

### Windows

```bat
<TOMCAT_HOME>\bin\startup.bat
```

### macOS / Linux

```bash
<TOMCAT_HOME>/bin/startup.sh
```

Open:

```text
http://localhost:8080/RAGdoll/
```

You can create a user account from the signup page or use one of the seeded admin accounts below.

## Admin accounts

All seeded administrator accounts use the password:

```text
password
```

Admin emails:

- `blake.admin@ragdoll.local`
- `casey.admin@ragdoll.local`
- `devon.admin@ragdoll.local`
- `emery.admin@ragdoll.local`
- `finn.admin@ragdoll.local`
- `gale.admin@ragdoll.local`
- `harper.admin@ragdoll.local`
- `iris.admin@ragdoll.local`
- `jane.fortnite@ragdoll.local`

Example:

```text
Email: blake.admin@ragdoll.local
Password: password
```

These accounts are intended for local development and testing. Do not reuse the shared password in a public or production deployment.

### Create another admin account

1. Start RAGdoll and sign up normally.
2. Find the account in MySQL:

```sql
USE ragdoll_db;
SELECT user_id, username, email FROM Users ORDER BY user_id DESC;
```

3. Add the user to `Admins`:

```sql
INSERT INTO Admins (user_id, company_id, admin_email)
VALUES (YOUR_USER_ID, 'LOCAL-ADMIN', 'YOUR_EMAIL');
```

4. Log out and sign in again.

Admin document uploads support `.pdf`, `.txt`, `.md`, and `.docx`. Uploaded files are chunked and embedded by the local Python worker.

## Health check

Open:

```text
http://localhost:8080/RAGdoll/health
```

Check these values:

- `status` is `ok`
- `database_connected` is `true`
- `llama_cpp_available` is `true`
- `embedding.model_files_present` is `true`
- `model_count` is at least `1`

You can also test the Python worker directly with `.venv` active.

### PowerShell

```powershell
'{"id":1,"action":"status"}' | python src/rag_pipeline/model_worker.py
```

### macOS / Linux

```bash
printf '%s\n' '{"id":1,"action":"status"}' | python src/rag_pipeline/model_worker.py
```

The response should include `"ok":true`.

## Troubleshooting

### `llama-cpp-python is not installed`

Activate `.venv` and test the import:

```bash
python -c "from llama_cpp import Llama; print('OK')"
```

If it fails, reinstall the CPU wheel:

```bash
python -m pip install --upgrade --force-reinstall llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

### Compiler errors while installing `llama-cpp-python`

Errors mentioning `CMAKE_C_COMPILER`, `nmake`, or a missing compiler usually mean `pip` is trying to build from source. Install a compiler toolchain or use the matching pre-built CPU, CUDA, or Metal wheel from the installation section.

### `http://localhost:8080/RAGdoll/` returns 404

Check that:

1. Tomcat 9 is running on port `8080`.
2. `<TOMCAT_HOME>/conf/Catalina/localhost/RAGdoll.xml` exists.
3. The file is named exactly `RAGdoll.xml`.
4. `docBase` points to the repository's `src/presentation` directory.
5. Tomcat was restarted after the context was created or changed.

If the page still returns 404, check the Tomcat logs for deployment errors.

### `~models` exists or models are not detected

Do not use `~models` as the model root. Move or rename it so the files are under:

```text
models/embedding/
models/models/
```

### No models appear in the dashboard

Check that:

1. The model filename ends in `.gguf`.
2. The file is under `models/models/` or the directory set by `RAGDOLL_MODEL_DIR`.
3. `/RAGdoll/health` reports a model count greater than zero.
4. Tomcat was restarted after environment-variable changes.

### RAG or document processing fails

Confirm that the embedding model exists at:

```text
models/embedding/bge-base-en-v1.5/
```

Then check `http://localhost:8080/RAGdoll/health` and confirm `embedding.model_files_present` is `true`.

### Database connection fails

Check that:

- MySQL is running on `localhost:3306`.
- `ragdoll_db` exists.
- Tomcat received the correct `DB_PASSWORD` for the MySQL `root` account.
- Tomcat was restarted after changing environment variables.

### `UnsupportedClassVersionError`

Run Tomcat with JDK 25+ or recompile the Java source for the JDK version you want to use.

### Tomcat 10/11 errors mentioning `javax.servlet`

Use Tomcat 9. The current application has not been migrated from `javax.servlet` to `jakarta.servlet`.

## Setup checklist

- [ ] MySQL Server is running.
- [ ] `database/database.sql` has been executed.
- [ ] `DB_PASSWORD` is available to Tomcat.
- [ ] Apache Tomcat 9.0.x is installed.
- [ ] Tomcat runs on JDK 25+.
- [ ] Python 3.12 `.venv` exists in the repository root.
- [ ] `llama-cpp-python` imports successfully.
- [ ] `python -m pip install -r requirements.txt` completed successfully.
- [ ] `models/embedding/bge-base-en-v1.5/` exists.
- [ ] `models/models/gemma-3-1b-it-Q4_K_M.gguf` exists, or another compatible GGUF model is present.
- [ ] Model files are under `models/`, not `~models/`.
- [ ] `RAGDOLL_PROJECT_ROOT` points to the repository root.
- [ ] `<TOMCAT_HOME>/conf/Catalina/localhost/RAGdoll.xml` points to `src/presentation`.
- [ ] `http://localhost:8080/RAGdoll/` opens successfully.
- [ ] `http://localhost:8080/RAGdoll/health` reports a connected database and available Python worker.
