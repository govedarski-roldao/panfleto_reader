import base64
import io
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageOps

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_ANTHROPIC_IMAGE_BYTES = 5 * 1024 * 1024
TARGET_IMAGE_BYTES = 4_500_000


def _read_local_api_key() -> str:
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    if not env_path.is_file():
        return ""

    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "ANTHROPIC_API_KEY":
            return value.strip().strip('"').strip("'")

    return ""


def _compress_image_for_anthropic(path: Path) -> tuple[bytes, str]:
    with Image.open(path) as original_image:
        image = ImageOps.exif_transpose(original_image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    max_edge = 2200
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    for _ in range(12):
        for quality in (85, 75, 65, 55):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= TARGET_IMAGE_BYTES:
                return data, "image/jpeg"

        width, height = image.size
        image = image.resize(
            (max(1, int(width * 0.85)), max(1, int(height * 0.85))),
            Image.Resampling.LANCZOS,
        )

    raise ValueError(
        "Nao foi possivel comprimir a imagem abaixo do limite de 5 MB da Anthropic."
    )


def _read_image_as_base64(image_path: str) -> tuple[str, str]:
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Imagem nao encontrada: {image_path}")

    media_type, _ = mimetypes.guess_type(path.name)
    if media_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise ValueError(
            "Formato de imagem nao suportado. Usa JPG, PNG, WEBP ou GIF."
        )

    image_bytes = path.read_bytes()
    if len(image_bytes) > MAX_ANTHROPIC_IMAGE_BYTES:
        image_bytes, media_type = _compress_image_for_anthropic(path)

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return encoded, media_type


def _extract_json_from_text(text: str) -> dict[str, Any]:
    cleaned_text = text.strip()
    markdown_match = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        cleaned_text,
        flags=re.DOTALL,
    )
    if markdown_match:
        cleaned_text = markdown_match.group(1)

    try:
        parsed = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "A resposta da Anthropic nao veio em JSON valido."
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("A resposta da Anthropic tem um formato inesperado.")

    return parsed


def _normalize_items(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return []

    normalized_items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        price = str(item.get("price", "")).strip().replace(".", ",")
        if not name or not price:
            continue

        normalized_items.append({"name": name, "price": price})

    return normalized_items


def extrair_artigos_catalogo(
        image_path: str,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
) -> dict[str, Any]:
    """
    Envia uma imagem para a API da Anthropic, verifica se parece um catalogo de
    supermercado e extrai os nomes/precos dos artigos.
    """
    resolved_api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or _read_local_api_key()
    if not resolved_api_key:
        raise ValueError(
            "Define o api_key, a variavel de ambiente ANTHROPIC_API_KEY, "
            "ou ANTHROPIC_API_KEY no ficheiro local .env.local."
        )

    image_base64, media_type = _read_image_as_base64(image_path)

    prompt = (
        "Analisa esta imagem e responde apenas em JSON valido. "
        "Primeiro confirma se a imagem e um catalogo/folheto de supermercado. "
        "Se for, extrai todos os artigos visiveis e o respetivo preco. "
        'Usa exatamente este formato: {"is_supermarket_catalog": boolean, '
        '"supermarket_name": string, "items": [{"name": string, "price": string}], '
        '"notes": string}. '
        "Mantem os precos como texto no formato mais fiel ao que aparece na imagem. "
        "Se nao for um catalogo de supermercado, devolve items vazio e explica em notes."
    )

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    req = request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": resolved_api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"Falha na API da Anthropic ({exc.code}): {error_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Nao foi possivel ligar a API da Anthropic: {exc.reason}"
        ) from exc

    content = response_payload.get("content", [])
    if not content or not isinstance(content, list):
        raise ValueError("A resposta da Anthropic nao contem conteudo utilizavel.")

    text_blocks = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if not text_blocks:
        raise ValueError("A resposta da Anthropic nao contem texto.")

    parsed_payload = _extract_json_from_text("\n".join(text_blocks))
    normalized_items = _normalize_items(parsed_payload)

    return {
        "is_supermarket_catalog": bool(parsed_payload.get("is_supermarket_catalog")),
        "supermarket_name": str(parsed_payload.get("supermarket_name", "")).strip(),
        "items": normalized_items,
        "notes": str(parsed_payload.get("notes", "")).strip(),
    }


if __name__ == "__main__":
    sample_image = r"C:\Users\Utilizador\Desktop\Ideias para negocios\ler_panfletos\result\imgs\pagina_1.jpg"
    try:
        result = extrair_artigos_catalogo(sample_image)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"Erro: {exc}")
