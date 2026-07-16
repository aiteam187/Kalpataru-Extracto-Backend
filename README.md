# Extracto Backend API

A lightweight, robust FastAPI backend for the Extracto application. It provides high-accuracy OCR + Vision LLM document extraction and dynamic image storage.

---

## Key Features

1. **OCR & LLM Data Extraction (`POST /extract`)**:
   - Mixed printed/handwritten text extraction using Azure Document Intelligence (`prebuilt-read` model).
   - High-accuracy structured data extraction using Groq Vision LLM (relying on both the high-quality OCR text and the raw image for vision capability).
   
2. **Dynamic File Storage**:
   - Automatically stores uploaded challans and vehicle images to a structured directory:
     ```
     kalpataru/
       └── {YYYY-MM-DD}/
             ├── inward/
             └── outward/
     ```
   - Automatically detects OS: defaults to the user's `Desktop` folder on Windows, and the `Home` directory (`~/kalpataru`) on Linux/Ubuntu.

3. **Multi-photo Upload (`POST /upload`)**:
   - Supports uploading up to 2 vehicle images (Front and Back) concurrently and storing them directly in the target date/direction folder.

4. **Cross-Platform Compatibility**:
   - Fully optimized for both Windows and Ubuntu Linux environments.
   - Scripts included for easy setup and launch on both operating systems.

5. **Network-Ready & CORS Enabled**:
   - Binds to `0.0.0.0` allowing anyone in the local network (WiFi/LAN) to connect.
   - Fully configured CORS middleware allowing all origins (`*`) to prevent any frontend CORS issues.

---

## Project Structure

```
document_extractor/
├── app.py                  # Server entry point & Swagger UI config
├── config.py               # Environment configuration & OS detection
├── models.py               # Pydantic request/response schemas
├── prompts.py              # Groq system & user prompts
├── requirements.txt        # Python package dependencies
├── setup.sh                # Ubuntu installation script
├── start.sh                # Ubuntu run script
├── routes/
│   ├── __init__.py
│   ├── extract.py          # Handler for POST /extract
│   └── upload.py           # Handler for POST /upload
└── services/
    ├── __init__.py
    ├── azure_ocr.py        # Connects to Azure Document Intelligence
    ├── groq_extraction.py  # Connects to Groq Vision LLM API
    └── storage.py          # Handles directory creation & file storage
```

---

## Getting Started

### 1. Configure Environment Variables
Create a file named `.env` in the root directory (you can copy `.env.example`) and fill in your API credentials:
```env
DOC_INTELLIGENCE_ENDPOINT="https://your-resource.cognitiveservices.azure.com/"
DOC_INTELLIGENCE_KEY="your-azure-key"
GROQ_API_KEY="your-groq-key"
GROQ_API_URL="https://api.groq.com/openai/v1/chat/completypes"
GROQ_MODEL="llama-3.1-70b-versatile"
GROQ_VISION_MODEL="meta-llama/llama-4-scout-17b-16e-instruct"
```

### 2. Setup & Run (Ubuntu / Linux)
We provide setup and launch scripts for easy deployment:

```bash
# Run setup (installs python3, venv, and upgrades pip packages)
bash setup.sh

# Start the server (runs in the virtual environment)
bash start.sh
```

### 3. Setup & Run (Windows)
Open a terminal (Command Prompt or PowerShell) in the root folder:

```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
```

---

## API Endpoints

### 1. `POST /extract`
Extracts structured information from a document image (e.g., Gate Pass or Challan).

- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `challan_image` (File): The document image.
  - `direction` (Form String): Direction of material movement (`inward` or `outward`, defaults to `inward`).
- **Response**:
  ```json
  {
    "success": true,
    "document_type": "SECURITY GATE PASS",
    "extracted_data": { ... },
    "ocr_text": "...",
    "stored_files": {
      "folder_path": "...",
      "direction": "inward",
      "saved_files": [ "..." ]
    }
  }
  ```

### 2. `POST /upload`
Saves vehicle photos directly to the server folder.

- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `vehicle_front_image` (File): Front photo of the vehicle.
  - `vehicle_back_image` (File): Back photo of the vehicle.
  - `direction` (Form String): Movement direction (`inward` or `outward`, defaults to `inward`).
- **Response**:
  ```json
  {
    "success": true,
    "direction": "outward",
    "folder_path": "...",
    "saved_files": [ "...", "..." ]
  }
  ```

### 3. `GET /docs`
Access the fully interactive Swagger API interface:
`http://localhost:8001/docs` (or replace `localhost` with the server's local IP address, e.g., `http://192.168.10.224:8001/docs`).
