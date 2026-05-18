import mimetypes
import os
import re
import json
import shutil
import tempfile
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, parse_qs, urlparse

import fitz

from ai.ai import extrair_artigos_catalogo
from backend.organize_data import OrganizeData

ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "docs"
OUTPUT_DIR = ROOT_DIR / "web_results"
JOBS = {}
JOBS_LOCK = threading.Lock()


def safe_folder_name(value):
    if not isinstance(value, str):
        value = "lista_de_valores"
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "_", value.strip() or "lista_de_valores")
    return cleaned.strip(" .") or "extraction"


def safe_excel_filename(value):
    name = safe_folder_name(value)
    if not name.lower().endswith(".xlsx"):
        name = f"{name}.xlsx"
    return name


def parse_multipart(headers, body):
    content_type = headers.get("Content-Type", "")
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Pedido sem boundary multipart.")

    boundary = match.group("boundary").strip().strip('"').encode("utf-8")
    parts = {}

    for raw_part in body.split(b"--" + boundary):
        raw_part = raw_part.strip(b"\r\n")
        if not raw_part or raw_part == b"--":
            continue

        header_blob, separator, content = raw_part.partition(b"\r\n\r\n")
        if not separator:
            continue

        header_text = header_blob.decode("utf-8", errors="replace")

        disposition = ""
        for line in header_text.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break

        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue

        field_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)

        if filename_match:
            parts[field_name] = {
                "filename": filename_match.group(1),
                "content": content,
            }
        else:
            parts[field_name] = content.decode("utf-8", errors="replace")

    return parts


def add_job_log(job_id, message):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["logs"].append(str(message))


def extract_prices_to_excel(pdf_path, folder_name, api_token=None, model=None, job_id=None):
    def log(*parts):
        message = " ".join(str(p) for p in parts)
        print(message)
        if job_id:
            add_job_log(job_id, message)

    base_output_dir = OUTPUT_DIR / safe_folder_name(folder_name)
    imgs_dir = base_output_dir / "imgs"

    if base_output_dir.exists():
        shutil.rmtree(base_output_dir)

    imgs_dir.mkdir(parents=True, exist_ok=True)

    data_frame = OrganizeData()

    doc = fitz.open(str(pdf_path))
    try:
        for page_number in range(len(doc)):
            page = doc.load_page(page_number)
            pix = page.get_pixmap(dpi=200)

            image_path = imgs_dir / f"pagina_{page_number + 1}.jpg"
            pix.save(str(image_path))

            log("Guardado:", image_path)

            picture_to_analyse = extrair_artigos_catalogo(
                str(image_path),
                api_key=api_token or None,
                model=model or "claude-sonnet-4-20250514",
            )

            for item in picture_to_analyse["items"]:
                log(item["name"], item["price"])
                data_frame.add_lines(item)
                log("Artigo:", item["name"], "Preco:", item["price"])

    finally:
        doc.close()

    log("PDF processado com sucesso")
    data_frame.export_to_excel(str(base_output_dir))
    log("Excel criado")

    return base_output_dir / "resultados.xlsx"


def run_extraction_job(job_id, pdf_bytes, title, api_token, model):
    try:
        add_job_log(job_id, "INICIADO")

        with tempfile.TemporaryDirectory(prefix="extractor_") as tmp_dir:
            pdf_path = Path(tmp_dir) / "upload.pdf"
            pdf_path.write_bytes(pdf_bytes)

            excel_path = extract_prices_to_excel(
                pdf_path,
                title,
                api_token,
                model,
                job_id,
            )

        with JOBS_LOCK:
            job = JOBS[job_id]
            job["excel_path"] = str(excel_path)
            job["filename"] = safe_excel_filename(title)
            job["status"] = "done"

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        traceback.print_exc()
        with JOBS_LOCK:
            job = JOBS[job_id]
            job["status"] = "error"
            job["error"] = error_message
            job["logs"].append(f"Erro: {error_message}")


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/status":
            self._handle_status(parsed)
            return

        if parsed.path == "/download":
            self._handle_download(parsed)
            return

        path = unquote(parsed.path)

        if path == "/":
            path = "/index.html"

        file_path = (WEB_DIR / path.lstrip("/")).resolve()

        if not str(file_path).startswith(str(WEB_DIR.resolve())) or not file_path.is_file():
            self.send_error(404, "Nao encontrado")
            return

        content = file_path.read_bytes()
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != "/extract":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            fields = parse_multipart(self.headers, body)

            upload = fields.get("pdf")
            if not isinstance(upload, dict) or not upload.get("content"):
                self._send_text(400, "PDF obrigatorio")
                return

            title = fields.get("title", "extraction")
            api_token = fields.get("api_token", "")
            model = fields.get("model", "claude-sonnet-4-20250514")
            if not isinstance(api_token, str):
                api_token = ""
            if not isinstance(model, str):
                model = "claude-sonnet-4-20250514"

            api_token = api_token.strip()
            model = model.strip() or "claude-sonnet-4-20250514"
            if not api_token:
                self._send_text(400, "Token Anthropic obrigatorio")
                return

            job_id = uuid.uuid4().hex

            with JOBS_LOCK:
                JOBS[job_id] = {
                    "status": "running",
                    "logs": [],
                    "error": "",
                    "excel_path": "",
                    "filename": safe_excel_filename(title),
                }

            thread = threading.Thread(
                target=run_extraction_job,
                args=(job_id, upload["content"], title, api_token, model),
                daemon=True,
            )
            thread.start()

            self._send_json({"job_id": job_id})

        except Exception as exc:
            traceback.print_exc()
            self._send_text(500, str(exc))

    def _handle_status(self, parsed):
        job_id = parse_qs(parsed.query).get("job_id", [""])[0]

        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                self._send_text(404, "Job nao encontrado")
                return

        self._send_json(job)

    def _handle_download(self, parsed):
        job_id = parse_qs(parsed.query).get("job_id", [""])[0]

        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job or job["status"] != "done":
                self._send_text(400, "Ainda nao pronto")
                return

        file_path = Path(job["excel_path"])

        if not file_path.exists():
            self._send_text(404, "Ficheiro nao encontrado")
            return

        content = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{job["filename"]}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_text(self, code, msg):
        data = str(msg).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run():
    port = int(os.environ.get("PORT", 10000))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
